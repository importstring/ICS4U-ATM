from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar, Mapping
from uuid import UUID, uuid4



def utc_now() -> datetime:
    """Return the current date and time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)



@dataclass
class User:
    """Represent an individual independently of any bank.

    Store the individual's login username, password hash, administrator
    status, UUID, and creation timestamp. Bank-account ownership is
    recorded separately through Account.user_id.

    Exclude the password hash from the generated representation.
    """


    username: str
    password_hash: str = field(repr=False)
    is_admin: bool = False


    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)



@dataclass
class Account:
    """Represent a bank account owned by one individual at one bank.

    Reference the owner and bank by UUID, and store the account type,
    account-password hash, account UUID, and creation timestamp.

    Exclude the password hash from the generated representation.
    Trading balances and holdings are stored separately.
    """


    user_id: UUID
    bank_id: UUID
    acc_type: str
    password_hash: str = field(repr=False)


    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)


    def belongs_to(self, user_id: UUID) -> bool:
        """Return whether the supplied individual ID matches the owner.

        This compares IDs only; it does not authenticate the individual
        or verify the account password.
        """
        return self.user_id == user_id



@dataclass(frozen=True)
class CustomerInfo:
    """Provide an immutable customer summary for a bank relationship.

    Include the individual's UUID, username, and account IDs at the
    bank without exposing login or account-password hashes.
    """


    user_id: UUID
    username: str
    account_ids: tuple[UUID, ...]



@dataclass
class Bank:
    """Store a bank's identity, currency, display theme, and accounts.

    Derive customer membership from account ownership rather than
    creating separate individual identities for each bank.

    These record operations do not authenticate callers or save changes.
    Authentication and persistence belong to the surrounding services.
    """

    name: str
    currency: str = "CAD"
    theme: str = "default"


    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    accounts: dict[UUID, Account] = field(default_factory=dict)


    ACCOUNT_TYPES: ClassVar[tuple[str, ...]] = (
        "Savings",
        "Chequing",
    )


    @property
    def customer_ids(self) -> set[UUID]:
        """Return the distinct IDs of individuals who currently own
        at least one account at this bank.
        """
        return {
            account.user_id
            for account in self.accounts.values()
        }


    def create_acc(
        self,
        user: User,
        acc_type: str,
        password_hash: str,
    ) -> Account:
        """Create and register an account for an existing individual.

        Validate the account type and require a nonempty password hash.
        The calling service must authenticate the individual, hash the
        account password, and save the updated bank records.

        Returns:
            Account: The newly created account linked to this bank
                and the supplied individual's ID.

        Raises:
            ValueError: If the account type is unsupported or the
                password hash is empty.
        """
        if acc_type not in self.ACCOUNT_TYPES:
            raise ValueError(
                f"Account type must be one of: "
                f"{', '.join(self.ACCOUNT_TYPES)}."
            )


        if not password_hash:
            raise ValueError("An account password hash is required.")


        account = Account(
            user_id=user.id,
            bank_id=self.id,
            acc_type=acc_type,
            password_hash=password_hash,
        )


        self.accounts[account.id] = account
        return account


    def get_acc(self, account_id: UUID) -> Account:
        """Return an account registered at this bank by its UUID.

        This lookup does not check ownership or verify a password.

        Raises:
            ValueError: If the account is not registered at this bank.
        """
        try:
            return self.accounts[account_id]
        except KeyError:
            raise ValueError(
                "Account not found at this bank."
            ) from None


    def get_user_accounts(self, user_id: UUID) -> list[Account]:
        """Return this bank's accounts owned by the supplied individual.

        Return an empty list if no accounts match. This filters by
        owner ID without authenticating the caller.
        """
        return [
            account
            for account in self.accounts.values()
            if account.user_id == user_id
        ]


    def get_owned_acc(
        self,
        user_id: UUID,
        account_id: UUID,
    ) -> Account:
        """Return an account after checking its owner ID.

        This does not authenticate the individual, verify the account
        password, or check whether the account is unlocked.

        Raises:
            ValueError: If the account is not registered at this bank.
            PermissionError: If the supplied individual does not own it.
        """
        account = self.get_acc(account_id)


        if not account.belongs_to(user_id):
            raise PermissionError(
                "This account does not belong to this individual."
            )


        return account


    def get_customer_info(self, user: User) -> CustomerInfo:
        """Build a password-free summary of an individual's relationship
        with this bank.

        Returns:
            CustomerInfo: The individual's ID, username, and IDs of
                their accounts at this bank.

        Raises:
            ValueError: If the individual has no accounts at this bank.
        """
        accounts = self.get_user_accounts(user.id)


        if not accounts:
            raise ValueError(
                "This individual is not a customer of this bank."
            )


        return CustomerInfo(
            user_id=user.id,
            username=user.username,
            account_ids=tuple(account.id for account in accounts),
        )


    def get_customers(
        self,
        users: Mapping[UUID, User],
    ) -> list[CustomerInfo]:
        """Build summaries for all current customers using a supplied
        global mapping of individual IDs to User records.

        Returns:
            list[CustomerInfo]: One password-free summary per customer.

        Raises:
            KeyError: If an account owner is missing from the mapping.
        """
        return [
            self.get_customer_info(users[user_id])
            for user_id in self.customer_ids
        ]


    def get_info(self) -> dict[str, str | UUID | int]:
        """Return bank identification, display settings, and counts.

        Count each customer once, even if they own multiple accounts
        at this bank. Do not include passwords or individual details.
        """
        return {
            "id": self.id,
            "name": self.name,
            "currency": self.currency,
            "theme": self.theme,
            "customer_count": len(self.customer_ids),
            "account_count": len(self.accounts),
        }


    def remove_acc(self, account_id: UUID) -> Account:
        """Remove and return an account registered at this bank.

        Do not check balances, delete the owner's identity, or modify
        separately stored trading data. The caller must authorize the
        operation and save the updated bank records.

        Raises:
            ValueError: If the account is not registered at this bank.
        """
        account = self.get_acc(account_id)
        del self.accounts[account_id]
        return account


    def remove_customer_accounts(
        self,
        user_id: UUID,
    ) -> list[Account]:
        """Remove all accounts owned by an individual at this bank.

        Preserve the individual's global identity and accounts at other
        banks. Do not check balances or modify separate trading data.

        Returns:
            list[Account]: The removed accounts, or an empty list if
                the individual had no accounts at this bank.
        """
        accounts = self.get_user_accounts(user_id)


        for account in accounts:
            del self.accounts[account.id]


        return accounts



class Admin:
    """Manage registered banks through a shared class-level registry.

    This class is a bank-management interface, not a login identity.
    A surrounding service must authenticate callers, enforce
    administrator permissions, and save record changes.
    """


    banks: ClassVar[dict[UUID, Bank]] = {}


    @classmethod
    def create_bank(
        cls,
        name: str,
        currency: str = "CAD",
        theme: str = "default",
    ) -> Bank:
        """Create a bank and add it to the shared registry.

        Trim the name and currency, uppercase the currency, and reject
        empty values or an existing case-insensitive bank name.
        Currency support and theme validity are not checked here.

        Returns:
            Bank: The newly created and registered bank.

        Raises:
            ValueError: If the name or currency is empty, or the name
                matches an existing registered bank.
        """
        name = name.strip()
        currency = currency.strip().upper()


        if not name:
            raise ValueError("Bank name cannot be empty.")


        if not currency:
            raise ValueError("Currency cannot be empty.")


        if any(
            bank.name.casefold() == name.casefold()
            for bank in cls.banks.values()
        ):
            raise ValueError("A bank with this name already exists.")


        bank = Bank(
            name=name,
            currency=currency,
            theme=theme,
        )


        cls.banks[bank.id] = bank
        return bank


    @classmethod
    def get_bank(cls, bank_id: UUID) -> Bank:
        """Return a registered bank by its UUID.

        Raises:
            ValueError: If the bank is not in the shared registry.
        """
        try:
            return cls.banks[bank_id]
        except KeyError:
            raise ValueError("Bank not found.") from None


    @classmethod
    def get_banks(cls) -> list[Bank]:
        """Return a new list containing the registered Bank objects."""
        return list(cls.banks.values())


    @classmethod
    def get_bank_info(
        cls,
        bank_id: UUID,
    ) -> dict[str, str | UUID | int]:
        """Return the identification, settings, and counts for one bank.

        Raises:
            ValueError: If the bank is not registered.
        """
        return cls.get_bank(bank_id).get_info()


    @classmethod
    def get_info(cls) -> dict[str, int]:
        """Return total registered banks, distinct customers, and accounts.

        Count an individual once across all registered banks, even if
        they own multiple accounts. Individuals without bank accounts
        are not included in the customer count.
        """
        customer_ids: set[UUID] = set()


        for bank in cls.banks.values():
            customer_ids.update(bank.customer_ids)


        return {
            "bank_count": len(cls.banks),
            "customer_count": len(customer_ids),
            "account_count": sum(
                len(bank.accounts)
                for bank in cls.banks.values()
            ),
        }


    @classmethod
    def remove_bank(cls, bank_id: UUID) -> Bank:
        """Unregister and return a bank without deleting global individuals.

        The returned bank object retains its account records. This
        method does not modify separate trading data or save changes.

        Raises:
            ValueError: If the bank is not registered.
        """
        bank = cls.get_bank(bank_id)
        del cls.banks[bank_id]
        return bank


    @classmethod
    def remove_acc(
        cls,
        bank_id: UUID,
        account_id: UUID,
    ) -> Account:
        """Remove and return an account from a registered bank.

        Delegate removal to the bank without checking financial balances
        or modifying separate trading data.

        Raises:
            ValueError: If the bank or account cannot be found.
        """
        return cls.get_bank(bank_id).remove_acc(account_id)


    @classmethod
    def remove_customer_accounts(
        cls,
        bank_id: UUID,
        user_id: UUID,
    ) -> list[Account]:
        """Remove an individual's accounts from one registered bank.

        Return the removed accounts while preserving the individual's
        identity and accounts at other banks.

        Raises:
            ValueError: If the bank is not registered.
        """
        return cls.get_bank(bank_id).remove_customer_accounts(user_id)