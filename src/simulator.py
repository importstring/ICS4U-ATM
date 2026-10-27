from __future__ import annotations


import copy
import json
import os
import tempfile


from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from random import Random
from uuid import UUID


from src.auth import Auth
from src.storage import StorageError



CENT = Decimal("0.01")



def money(value: Decimal) -> Decimal:
    """Return a Decimal rounded to two places, with halfway values
    rounded away from zero.
    """
    return value.quantize(CENT, rounding=ROUND_HALF_UP)



def timestamp() -> str:
    """Return the current UTC date and time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()



@dataclass(frozen=True)
class Asset:
    """Store an asset's symbol, name, currency, and price history."""

    symbol: str
    name: str
    currency: str
    history: tuple[Decimal, ...]


    @property
    def price(self) -> Decimal:
        """Return the most recent price in the asset's listing currency."""
        return self.history[-1]



@dataclass(frozen=True)
class BankTerms:
    """Store a bank's trading fees, currency-transfer fees, and
    preferred-currency discount multiplier.

    Rates are decimal fractions, such as 0.001 for a 0.1% fee.
    """

    name: str
    trade_rate: Decimal
    fx_rate: Decimal
    preferred_currency: str | None = None
    preferred_multiplier: Decimal = Decimal("1")


    def rate_for(self, asset_currency: str) -> Decimal:
        """Return the trading fee rate for an asset's currency.

        Apply the preferred multiplier when the asset uses the bank's
        preferred currency; otherwise, return the base trading rate.
        """
        if asset_currency == self.preferred_currency:
            return self.trade_rate * self.preferred_multiplier
        return self.trade_rate



class Simulator:
    """Manage persistent market prices, account trading balances,
    stock holdings, transfers, transaction events, and leaderboard data.

    Account operations use Auth to verify ownership and unlocked access.
    Monetary values are stored as strings in the saved JSON state.
    """

    HISTORY_LENGTH = 60


    ASSETS = (
        ("NOVA", "Nova Technology", "USD", "120.00", 180),
        ("MAPL", "Maple Industries", "CAD", "75.00", 110),
        ("GRID", "Grid Energy", "GBP", "48.00", 160),
        ("TOKY", "Tokyo Robotics", "JPY", "7500.00", 200),
        ("EURO", "Europa Industries", "EUR", "90.00", 100),
        ("AUST", "Southern Resources", "AUD", "65.00", 140),
    )


    BASE_RATES = {
        "CAD": "1",
        "USD": "1.38",
        "GBP": "1.82",
        "EUR": "1.51",
        "JPY": "0.0092",
        "AUD": "0.91",
    }


    # Terms are game rules selected by the bank's native currency.
    TERMS = {
        "CAD": BankTerms(
            "Low trading fees",
            Decimal("0.001"),
            Decimal("0.004"),
        ),
        "USD": BankTerms(
            "75% lower fees on USD stocks",
            Decimal("0.004"),
            Decimal("0.004"),
            "USD",
            Decimal("0.25"),
        ),
        "GBP": BankTerms(
            "Low currency-transfer fees",
            Decimal("0.003"),
            Decimal("0.001"),
        ),
        "JPY": BankTerms(
            "80% lower fees on JPY stocks",
            Decimal("0.004"),
            Decimal("0.003"),
            "JPY",
            Decimal("0.20"),
        ),
        "EUR": BankTerms(
            "75% lower fees on EUR stocks",
            Decimal("0.004"),
            Decimal("0.003"),
            "EUR",
            Decimal("0.25"),
        ),
        "AUD": BankTerms(
            "Balanced trading and transfer fees",
            Decimal("0.002"),
            Decimal("0.002"),
        ),
    }


    def __init__(self, auth: Auth, path: str | Path, seed: int = 42):
        """Load existing trading state or generate and save a new state.

        New states use the supplied random seed and generate 29 market
        steps after the initial prices. Existing states retain their
        saved prices and use a newly initialized random generator.

        Args:
            auth: Authentication service used for account access checks.
            path: Location of the trading JSON file.
            seed: Random seed used only when creating a new state.
        """
        self.auth = auth
        self.path = Path(path)


        if self.path.exists():
            self.state = self._load()
            self.rng = Random()
        else:
            self.rng = Random(seed)
            self.state = {
                "version": 1,
                "step": 0,
                "assets": {
                    symbol: [price]
                    for symbol, _, _, price, _ in self.ASSETS
                },
                "rates": {
                    currency: [rate]
                    for currency, rate in self.BASE_RATES.items()
                },
                "accounts": {},
                "funded_users": [],
                "events": [],
            }


            for _ in range(29):
                self._advance_state(self.state)


            self._save(self.state)


    def leaderboard(self, token: str) -> list[dict]:
        """Calculate and rank funded individuals by total equity in CAD.

        Combine each individual's saved cash and current stock values
        across accounts, including saved entries for removed accounts.
        Calculate profit and percentage return against CAD 10,000.

        Use insertion sort to order rows by descending rounded equity,
        then by case-insensitive username. Equal rounded equity receives
        the same rank, with subsequent ranks reflecting row positions.

        Args:
            token: A valid authenticated session token.

        Returns:
            list[dict]: Ranked user summaries containing cash, stocks,
                equity, profit, percentage return, and rank.
        """
        names = self.auth.leaderboard_names(token)


        banks = {
            str(bank.id): bank
            for bank in self.auth.get_banks(token)
        }


        starting_credit = Decimal("10000")
        totals = {}


        for entry in self.state["accounts"].values():
            user_id = entry["user_id"]


            if user_id not in names:
                continue


            # Keep saved balances in the score even if their bank
            # was removed. Deleting an account must not erase losses.
            currency = entry["currency"]
            cash_cad = (
                Decimal(entry["cash"])
                * self.rate(currency, "CAD")
            )


            stocks_cad = sum(
                (
                    self.get_asset(symbol).price
                    * quantity
                    * self.rate(
                        self.get_asset(symbol).currency,
                        "CAD",
                    )
                    for symbol, quantity
                    in entry["holdings"].items()
                ),
                Decimal("0"),
            )


            if user_id not in totals:
                totals[user_id] = {
                    "user_id": user_id,
                    "username": names[user_id],
                    "cash": Decimal("0"),
                    "stocks": Decimal("0"),
                }


            totals[user_id]["cash"] += cash_cad
            totals[user_id]["stocks"] += stocks_cad


        rows = []


        for user_id, total in totals.items():
            if user_id not in self.state["funded_users"]:
                continue


            equity = total["cash"] + total["stocks"]
            profit = equity - starting_credit


            rows.append({
                **total,
                "cash": money(total["cash"]),
                "stocks": money(total["stocks"]),
                "equity": money(equity),
                "profit": money(profit),
                "return_percent": (
                    profit / starting_credit * Decimal("100")
                ),
            })


        for i in range(1, len(rows)): # insertion sort
            current = rows[i]
            current_key = (
                -current["equity"],
                current["username"].casefold(),
            )


            j = i - 1


            while j >= 0:
                previous_key = (
                    -rows[j]["equity"],
                    rows[j]["username"].casefold(),
                )


                if previous_key <= current_key:
                    break


                rows[j + 1] = rows[j]
                j -= 1


            rows[j + 1] = current


        # Equal displayed equity receives the same rank.
        previous_equity = None
        rank = 0


        for position, row in enumerate(rows, start=1):
            if row["equity"] != previous_equity:
                rank = position


            row["rank"] = rank
            previous_equity = row["equity"]


        return rows


    def _load(self):
        """
        Load and validate saved trading data from the JSON file.


        Check the data version, market step, required containers,
        price histories, account UUIDs, currencies, cash balances,
        and stock holdings.


        Returns:
            dict: The loaded trading state after validation.


        Raises:
            StorageError: If the file cannot be read or the saved
                data fails validation.
        """
        try:
            with self.path.open("r", encoding="utf-8") as file:
                state = json.load(file)


            if state["version"] != 1:
                raise ValueError("Unsupported trading data version.")


            if type(state["step"]) is not int or state["step"] < 0:
                raise ValueError("Invalid market step.")


            for key in ("assets", "rates", "accounts"):
                if not isinstance(state[key], dict):
                    raise ValueError(f"Invalid {key} data.")


            for key in ("funded_users", "events"):
                if not isinstance(state[key], list):
                    raise ValueError(f"Invalid {key} data.")


            for symbol, *_ in self.ASSETS:
                self._validate_history(state["assets"][symbol])


            for currency in self.BASE_RATES:
                self._validate_history(state["rates"][currency])


            for entry in state["accounts"].values():
                UUID(entry["user_id"])
                UUID(entry["bank_id"])


                if entry["currency"] not in self.BASE_RATES:
                    raise ValueError("Unknown account currency.")


                cash = Decimal(entry["cash"])
                if not cash.is_finite() or cash < 0:
                    raise ValueError("Invalid account cash.")


                for symbol, quantity in entry["holdings"].items():
                    if symbol not in state["assets"]:
                        raise ValueError("Unknown holding.")
                    if type(quantity) is not int or quantity <= 0:
                        raise ValueError("Invalid holding quantity.")


            return state


        except (
            OSError, ValueError, KeyError, TypeError, ArithmeticError
        ) as error:
            raise StorageError(
                f"Could not load trading data: {error}"
            ) from error


    @staticmethod
    def _validate_history(values):
        """Validate that a price history is a nonempty list whose entries
        convert to finite, positive Decimal values.

        Raises:
            ValueError: If the history is missing, has the wrong
                container type, or contains a nonpositive or nonfinite
                value.
            ArithmeticError: If an entry cannot be converted to Decimal
                because of an invalid numeric representation.
            TypeError: If an entry has an unsupported type.
        """
        if not isinstance(values, list) or not values:
            raise ValueError("Missing market history.")


        for raw in values:
            value = Decimal(raw)
            if not value.is_finite() or value <= 0:
                raise ValueError("Invalid market price.")


    def _save(self, state):
        """Write the supplied state to a temporary JSON file, flush it
        to disk, and replace the saved trading file.

        Create parent directories when needed and remove any remaining
        temporary file during cleanup.

        Args:
            state: JSON-serializable trading state to save.

        Raises:
            StorageError: If writing, serialization, or replacement
                fails with a handled storage or serialization error.
        """
        temporary = None


        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)


            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".trading-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(state, file, indent=2)
                file.flush()
                os.fsync(file.fileno())


            os.replace(temporary, self.path)


        except (OSError, ValueError, TypeError) as error:
            raise StorageError(
                f"Could not save trading data: {error}"
            ) from error


        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


    def _commit(self, updated):
        """Save the updated state before replacing the in-memory state.

        If saving raises an exception, the in-memory state reference
        is not replaced.
        """
        self._save(updated)
        self.state = updated


    @property
    def step(self):
        """Return the current saved market-step number."""
        return self.state["step"]


    @property
    def currencies(self):
        """Return a new list of supported currency codes."""
        return list(self.BASE_RATES)


    def assets(self) -> list[Asset]:
        """Build and return asset records using the current saved
        histories, converting price strings to Decimal values.
        """
        return [
            Asset(
                symbol,
                name,
                currency,
                tuple(Decimal(p) for p in self.state["assets"][symbol]),
            )
            for symbol, name, currency, _, _ in self.ASSETS
        ]


    def get_asset(self, symbol: str) -> Asset:
        """Find an asset by its exact symbol using a linear search.

        Returns:
            Asset: The matching asset with its current price history.

        Raises:
            ValueError: If no asset has the supplied symbol.
        """
        for asset in self.assets():
            if asset.symbol == symbol:
                return asset
        raise ValueError("Unknown asset.")


    def terms(self, bank_currency: str) -> BankTerms:
        """Return the fee rules associated with a bank's currency.

        Raises:
            ValueError: If the bank currency is unsupported.
        """
        try:
            return self.TERMS[bank_currency]
        except KeyError:
            raise ValueError("Unsupported bank currency.") from None


    def rate(self, source: str, target: str) -> Decimal:
        """Return the number of target-currency units per source unit.

        Derive the cross-currency rate from the latest saved rates,
        which are expressed as CAD per currency unit.

        Raises:
            ValueError: If either currency code is unsupported.
        """
        if source not in self.BASE_RATES or target not in self.BASE_RATES:
            raise ValueError("Unsupported currency.")


        return (
            Decimal(self.state["rates"][source][-1])
            / Decimal(self.state["rates"][target][-1])
        )


    def _advance_state(self, state):
        """Modify a supplied state by generating one market step.

        Apply random price changes within each asset's configured
        volatility, round asset prices to cents, and keep them positive.
        Update exchange rates while keeping CAD fixed at one.

        Trim histories to HISTORY_LENGTH and increment the market step.
        This method does not save the state.
        """
        for symbol, _, _, _, volatility in self.ASSETS:
            history = state["assets"][symbol]
            change = Decimal(
                self.rng.randint(-volatility, volatility)
            ) / Decimal("10000")


            price = money(
                Decimal(history[-1]) * (Decimal("1") + change)
            )


            history.append(str(max(CENT, price)))
            del history[:-self.HISTORY_LENGTH]


        for currency, history in state["rates"].items():
            change = Decimal(self.rng.randint(-10, 10)) / Decimal("10000")
            price = (
                Decimal("1")
                if currency == "CAD"
                else Decimal(history[-1]) * (Decimal("1") + change)
            )
            history.append(str(price))
            del history[:-self.HISTORY_LENGTH]


        state["step"] += 1


    def advance(self):
        """Generate one market step on a copy of the current state,
        then save and adopt the updated state.
        """
        updated = copy.deepcopy(self.state)
        self._advance_state(updated)
        self._commit(updated)


    def _access(self, token, bank, account):
        """Verify authenticated access to an unlocked account and
        resolve its bank from the registered banks.

        Returns:
            Bank: The registered bank matching the supplied bank ID.

        Raises:
            ValueError: If the bank cannot be found.
            AuthenticationError: If the session is invalid.
            PermissionError: If ownership or unlocked access checks fail.
        """
        self.auth.require_account_access(token, bank.id, account.id)


        # Resolve the actual bank from the authenticated registry.
        actual_bank = next(
            (b for b in self.auth.get_banks(token) if b.id == bank.id),
            None,
        )
        if actual_bank is None:
            raise ValueError("Bank not found.")


        return actual_bank


    def ensure_account(self, token, bank, account):
        """Initialize and save trading data for an accessible account
        if no trading entry exists yet.

        Credit the individual's first initialized trading account with
        the current bank-currency equivalent of CAD 10,000 and record
        the starting-credit event. Later accounts start with zero cash.

        If an entry already exists, validate it without adding funds.
        """
        bank = self._access(token, bank, account)
        self.terms(bank.currency)


        key = str(account.id)


        if key in self.state["accounts"]:
            self.account(token, bank, account)
            return


        updated = copy.deepcopy(self.state)
        user_id = str(self.auth.current_user(token).id)


        first_account = user_id not in updated["funded_users"]
        cash = (
            money(Decimal("10000") * self.rate("CAD", bank.currency))
            if first_account else Decimal("0")
        )


        updated["accounts"][key] = {
            "user_id": user_id,
            "bank_id": str(bank.id),
            "currency": bank.currency,
            "cash": str(cash),
            "holdings": {},
        }


        if first_account:
            updated["funded_users"].append(user_id)
            updated["events"].append({
                "type": "STARTING_CREDIT",
                "account_id": key,
                "amount": str(cash),
                "currency": bank.currency,
                "timestamp": timestamp(),
            })


        self._commit(updated)


    def account(self, token, bank, account):
        """Return an independent copy of an accessible trading entry.

        Verify unlocked account access and confirm that the saved owner,
        bank ID, and currency match the authenticated individual and bank.

        Raises:
            ValueError: If the trading entry is missing or inconsistent.
        """
        bank = self._access(token, bank, account)
        entry = self.state["accounts"].get(str(account.id))


        if entry is None:
            raise ValueError("Trading account has not been initialized.")


        if (
            entry["user_id"] != str(self.auth.current_user(token).id)
            or entry["bank_id"] != str(bank.id)
            or entry["currency"] != bank.currency
        ):
            raise ValueError("Account data does not match its owner or bank.")


        return copy.deepcopy(entry)


    def equity(self, token, bank, account) -> Decimal:
        """Return cash plus current stock value in the account's currency.

        Convert each holding from its listing currency using the current
        exchange rate and round the final equity to two decimal places.
        Hypothetical selling fees are not deducted.
        """
        entry = self.account(token, bank, account)


        holdings = sum(
            (
                self.get_asset(symbol).price
                * quantity
                * self.rate(self.get_asset(symbol).currency, entry["currency"])
                for symbol, quantity in entry["holdings"].items()
            ),
            Decimal("0"),
        )


        return money(Decimal(entry["cash"]) + holdings)


    def trade(self, token, bank, account, side, symbol, quantity):
        """Execute and save a whole-share purchase or sale.

        Require authenticated, unlocked account access. Convert the
        order value to the account's currency and apply the bank's
        trading fee, including any preferred-currency discount.

        Update cash and holdings on a copied state, append a timestamped
        trade event, and commit the result before returning.

        Args:
            token: The owner's authenticated session token.
            bank: Bank associated with the account.
            account: Unlocked account used to settle the order.
            side: Either "BUY" or "SELL".
            symbol: Exact symbol of the asset to trade.
            quantity: Positive integer number of shares.

        Returns:
            dict: The saved trade event.

        Raises:
            ValueError: If the order is invalid, cash or shares are
                insufficient, or sale proceeds cannot cover the fee.
            StorageError: If the updated state cannot be saved.
        """
        entry = self.account(token, bank, account)
        asset = self.get_asset(symbol)


        if side not in ("BUY", "SELL"):
            raise ValueError("Invalid order side.")
        if type(quantity) is not int or quantity <= 0:
            raise ValueError("Choose a positive whole-share quantity.")


        gross = money(
            asset.price * quantity
            * self.rate(asset.currency, entry["currency"])
        )
        fee = money(
            gross * self.terms(entry["currency"]).rate_for(asset.currency)
        )


        cash = Decimal(entry["cash"])
        owned = entry["holdings"].get(symbol, 0)


        if side == "BUY":
            if gross + fee > cash:
                raise ValueError("Not enough cash, including the trading fee.")
            cash -= gross + fee
            owned += quantity
        else:
            if quantity > owned:
                raise ValueError("Not enough shares.")
            if gross < fee:
                raise ValueError("Sale proceeds cannot cover the fee.")
            cash += gross - fee
            owned -= quantity


        updated = copy.deepcopy(self.state)
        target = updated["accounts"][str(account.id)]
        target["cash"] = str(cash)


        if owned:
            target["holdings"][symbol] = owned
        else:
            target["holdings"].pop(symbol, None)


        event = {
            "type": side,
            "account_id": str(account.id),
            "symbol": symbol,
            "quantity": quantity,
            "price": str(asset.price),
            "price_currency": asset.currency,
            "gross": str(gross),
            "fee": str(fee),
            "currency": entry["currency"],
            "step": self.step,
            "timestamp": timestamp(),
        }


        updated["events"].append(event)
        self._commit(updated)
        return event


    def transfer(self, token, source_bank, source, target_bank, target, amount):
        """Transfer and save cash between two unlocked accounts owned
        by the authenticated individual.

        Round the amount to cents. Debit the source by the amount plus
        any cross-currency fee, and credit the destination using the
        current exchange rate. Same-currency transfers have no fee.

        Update both balances and append a timestamped transfer event
        in one copied state before committing it.

        Args:
            token: The owner's authenticated session token.
            source_bank: Bank holding the source account.
            source: Unlocked account to debit.
            target_bank: Bank holding the destination account.
            target: Unlocked account to credit.
            amount: Positive, finite Decimal in the source currency.

        Returns:
            tuple[Decimal, Decimal]: The credited amount in destination
                currency and the fee in source currency.

        Raises:
            ValueError: If the accounts are identical, the amount is
                invalid or too small, or available cash is insufficient.
            StorageError: If the updated state cannot be saved.
        """
        if source.id == target.id:
            raise ValueError("Choose a different destination account.")


        # Both accounts must belong to the session and be unlocked.
        source_entry = self.account(token, source_bank, source)
        target_entry = self.account(token, target_bank, target)


        if not amount.is_finite() or amount <= 0:
            raise ValueError("Enter a positive amount.")


        amount = money(amount)
        if amount <= 0:
            raise ValueError("Amount is too small.")


        source_currency = source_entry["currency"]
        target_currency = target_entry["currency"]


        fee = (
            money(amount * self.terms(source_currency).fx_rate)
            if source_currency != target_currency
            else Decimal("0")
        )


        if amount + fee > Decimal(source_entry["cash"]):
            raise ValueError("Not enough cash, including the transfer fee.")


        credited = money(amount * self.rate(source_currency, target_currency))
        if credited <= 0:
            raise ValueError("Converted amount is too small.")


        updated = copy.deepcopy(self.state)
        updated["accounts"][str(source.id)]["cash"] = str(
            Decimal(source_entry["cash"]) - amount - fee
        )
        updated["accounts"][str(target.id)]["cash"] = str(
            Decimal(target_entry["cash"]) + credited
        )
        updated["events"].append({
            "type": "TRANSFER",
            "source": str(source.id),
            "target": str(target.id),
            "amount": str(amount),
            "source_currency": source_currency,
            "fee": str(fee),
            "credited": str(credited),
            "target_currency": target_currency,
            "timestamp": timestamp(),
        })


        self._commit(updated)
        return credited, fee