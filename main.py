"""
ATM & Live Trading App

Key:
    [X] completely address  [E] eliminated [-] Not completed
                      [=] somewhat completely

** deposit and withdraw non-tradable money --> done after TUI is exited
** allow users to delete their account --> resolved in person. Since admin can, no need. 
** display the average balence --> done after the TUI is exited

Criteria:  
    [X] Save user records --> done in classes in `src/records`
    [E] Add two or more attributes of your choice: stock holdings
    [X] Require unique password and username --> `auth.py`
    [X] Add built in accounts
        - Admin: Simon pass: 12345678
        - Other player accounts from family members
        - 3+ for sure
    [E] Include an algorithm that calculates the average
        - I thought a leaderboard would be better. 
Challenges:
    [E] Build an interest rate projector 
        - Live stock trading
    [X] Build three searching algorithms
        - Built insertion sort
        - Wide range of array manipulation
    [E] Keep a record of transactions with time stamps
        - Detailed stock logs and trading logs
    [X] Allow the user to transfer funds from one account to another
    [X] Include a currency converter

    ________
    |  ATM   |
    |        |   Menu
    |        |  1
    |        |  2
    |        |  3
    ________

    ^ Design inspo

Live trading is done with ascii characters

|      ._._./
|    ./
|___./_______
b for buy, s for sell, up and down adjust buy increments, side arrows shift through graphs.

Storage is done in `data/` and the code for it is done in `src/storage.py`

The admin (Simon) can create & delete banks. The UI is done in `src/ui.py`

ATM ascii art was found here: https://patorjk.com/software/taag/#p=display&f=File+Blue&t=Hello+User&x=none&v=4&h=4&w=80&we=false&ft=thedraw
Some code for graphs and for curses menu was taken off of the internet.

Used the python built in library `uuid` to generate unique IDs that are more secure.
Also used the ClassVar and Mapping library from typing to allow me to create this class that allows me to have the class `Admin` almost function as an instance. I liked how this looked:
```python
admin.remove_bank("Bank of Canada")
```

As for records, I probably rewrote this file 10 or 20 times. I decided to go with using a lot of dataclasses.

Then for `src/simulator.py`, I created some new classes like an `Asset` dataclass and one for BankTerms. I decided to put this in simulator instead of records because I thought they were more related to trading.

On line 220 you can find an insertion sort implementation that's used for the trading leaderboard.
"""

__author__ = "Simon Bergeron"
__date__ = "Friday Oct 23rd 2026"
__course__ = "ICS3U"
__teacher__ = "Mr. G"

# ~~~~~ Imports ~~~~~~~ 
import curses

from pathlib import Path

from src.auth import Auth
from src.records import Admin
from src.simulator import Simulator
from src.storage import BankStore, StorageError, UserStore
from src.ui import SimulatorApp, TUI


# ~~~~ Initalization ~~~~~
ROOT = Path(__file__).resolve().parent

INITIAL_BANKS = (
    ("Bank of Canada", "CAD", "canada"),
    ("United States Bank", "USD", "default"),
    ("Bank of England", "GBP", "england"),
    ("Tokyo Bank", "JPY", "japan"),
    ("Europa Bank", "EUR", "europe"),
    ("Southern Cross Bank", "AUD", "australia"),
)

# ~~~~ Functions ~~~~~~
def run(screen, auth, bank_store, simulator):
    """
    Try to hide the cursor and then run the simulation and nav
    """
    try:
        curses.curs_set(0)
    except curses.error:
        pass

    SimulatorApp(
        TUI(screen), simulator, auth, bank_store
    ).run()


def main():
    """
    Initialize instances of objects and pass them to run
    """
    auth = Auth(store=UserStore(ROOT / "data" / "users.json"))
    bank_store = BankStore(ROOT / "data" / "banks.json")

    Admin.banks.clear()

    if bank_store.path.exists():
        banks = bank_store.load()
        Admin.banks.update({bank.id: bank for bank in banks})
    else:
        for name, currency, theme in INITIAL_BANKS:
            Admin.create_bank(name, currency, theme)
        bank_store.save(Admin.get_banks())

    simulator = Simulator(
        auth=auth,
        path=ROOT / "data" / "trading.json",
    )

    curses.wrapper(run, auth, bank_store, simulator)
    print_average_balance(simulator)
    simulated_deposit_and_withdrawal(simulator)

from decimal import Decimal, ROUND_HALF_UP
def print_average_balance(simulator):
    """
    Demonstration function for knowledge criteria
    --> input is a instance of the Simulator class
    --> prints average
    """
    total = Decimal("0")
    account_count = 0

    for bank in Admin.get_banks():
        for account in bank.accounts.values():
            entry = simulator.state["accounts"].get(str(account.id))

            balance = (
                Decimal(entry["cash"])
                if entry is not None
                else Decimal("0")
            )

            total += balance * simulator.rate(bank.currency, "CAD")
            account_count += 1

    if account_count == 0:
        print("\nAverage account balance: N/A — no bank accounts.")
        return

    average = (total / account_count).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    print(
        f"\nAverage account balance: CAD {average:,.2f}"
        f"\nAcross {account_count} active bank account(s)."
    )

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from decimal import InvalidOperation
def simulated_deposit_and_withdrawal(simulator):
    """
    Interactive deposit/withdrawal demonstration.

    Uses a copy of an existing account.
    Does not change trading funds, stocks, or saved files.
    """
    selected = None

    for bank in Admin.get_banks():
        for account in bank.accounts.values():
            entry = simulator.state["accounts"].get(str(account.id))

            if entry is not None:
                selected = (bank, account, entry)
                break

        if selected is not None:
            break

    if selected is None:
        print(
            "\nDeposit/withdrawal demonstration unavailable:"
            "\nOpen and unlock a bank account first."
        )
        return

    bank, account, entry = selected

    simulated_account = deepcopy(entry)
    simulated_account["bank_balance"] = "0.00"
    transactions = []

    print("\n--- Deposit and withdrawal demonstration ---")
    print(f"Bank: {bank.name}")
    print(f"Currency: {bank.currency}")
    print("Using a temporary account copy; nothing will be saved.")

    while True:
        balance = Decimal(simulated_account["bank_balance"])

        print(f"\nBank balance: {balance:,.2f} {bank.currency}")
        print("1. Deposit")
        print("2. Withdraw")
        print("3. View transactions")
        print("4. Finish")

        try:
            choice = input("Choose an option: ").strip()
        except EOFError:
            print("\nInput ended.")
            break

        if choice == "4":
            break

        if choice == "3":
            if not transactions:
                print("No transactions yet.")
            else:
                for transaction in transactions:
                    print(
                        f"{transaction['timestamp']} | "
                        f"{transaction['operation']} | "
                        f"{transaction['amount']} {bank.currency} | "
                        f"Balance: {transaction['balance_after']}"
                    )
            continue

        if choice not in ("1", "2"):
            print("Invalid option. Enter 1, 2, 3, or 4.")
            continue

        operation = "DEPOSIT" if choice == "1" else "WITHDRAWAL"

        try:
            raw_amount = input(
                f"Amount to {operation.lower()} "
                f"(or 'cancel'): "
            ).strip()
        except EOFError:
            print("\nInput ended.")
            break

        if raw_amount.casefold() == "cancel":
            print("Transaction cancelled.")
            continue

        # Validate everything before changing the balance.
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            print("Invalid amount. Enter a number, such as 25.50.")
            continue

        if not amount.is_finite():
            print("Invalid amount. NaN and infinity are not allowed.")
            continue

        if amount <= 0:
            print("Amount must be greater than zero.")
            continue

        if amount > Decimal("1000000"):
            print("Maximum amount per transaction is 1,000,000.")
            continue

        rounded = amount.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        if amount != rounded:
            print("Use no more than two decimal places.")
            continue

        amount = rounded

        if operation == "WITHDRAWAL":
            if amount > balance:
                print(
                    "Insufficient funds. "
                    f"You can withdraw up to "
                    f"{balance:,.2f} {bank.currency}."
                )
                continue

            balance -= amount
        else:
            balance += amount

        simulated_account["bank_balance"] = str(balance)

        transactions.append({
            "account_id": str(account.id),
            "operation": operation,
            "amount": str(amount),
            "balance_after": str(balance),
            "currency": bank.currency,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        print(
            f"{operation} successful: {amount:,.2f} {bank.currency}"
            f"\nNew balance: {balance:,.2f} {bank.currency}"
        )

    print("\n--- Demonstration finished ---")
    print(
        f"Final bank balance: "
        f"{Decimal(simulated_account['bank_balance']):,.2f} "
        f"{bank.currency}"
    )
    print(f"Successful transactions: {len(transactions)}")
    print(
        "Trading cash unchanged:",
        simulated_account["cash"] == entry["cash"],
    )
    print(
        "Stock holdings unchanged:",
        simulated_account["holdings"] == entry["holdings"],
    )
    print("Original account and saved files unchanged.")

if __name__ == "__main__":
    try:
        main()
    except StorageError as error:
        print(f"Storage error: {error}")
    except KeyboardInterrupt:
        print("Closed. Completed trades and transfers were already saved.")
    
    