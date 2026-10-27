from __future__ import annotations


import json
import os
import tempfile


from datetime import datetime
from pathlib import Path
from typing import Iterable
from uuid import UUID


from src.records import User, Account, Bank



class StorageError(Exception):
    """Indicate that saved data could not be read, validated, or written."""



class UserStore:
    """Load and save individual identities in a versioned JSON file.

    Store UUIDs and creation timestamps as strings and reconstruct
    them when loading. Password hashes are stored as supplied;
    password verification and identity rules belong to Auth.
    """

    VERSION = 1


    def __init__(self, path: str | Path):
        """Set the user-data file path without reading or creating it.

        Args:
            path: Location of the JSON file containing user records.
        """
        self.path = Path(path)


    def load(self) -> list[User]:
        """Read user records from JSON and reconstruct User objects.

        Check the document version, record structure, username type,
        nonempty password hash, administrator flag, UUID, and creation
        timestamp. Username uniqueness and administrator identity rules
        are checked separately by Auth.

        Returns:
            list[User]: Loaded individuals, or an empty list if the
                file does not exist.

        Raises:
            StorageError: If reading, parsing, or validation fails
                with one of the handled exceptions.
        """
        if not self.path.exists():
            return []


        try:
            with self.path.open("r", encoding="utf-8") as file:
                document = json.load(file)


            if not isinstance(document, dict):
                raise ValueError("Expected a JSON object.")


            if document.get("version") != self.VERSION:
                raise ValueError("Unsupported saved-data version.")


            rows = document["users"]


            if not isinstance(rows, list):
                raise ValueError("Expected a users list.")


            users = []


            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid user entry.")


                if not isinstance(row["username"], str):
                    raise ValueError("Invalid username.")


                if not isinstance(row["password_hash"], str):
                    raise ValueError("Invalid password hash.")


                if not row["password_hash"]:
                    raise ValueError("Missing password hash.")


                if type(row["is_admin"]) is not bool:
                    raise ValueError("Invalid administrator role.")


                users.append(
                    User(
                        id=UUID(row["id"]),
                        username=row["username"],
                        password_hash=row["password_hash"],
                        is_admin=row["is_admin"],
                        created_at=datetime.fromisoformat(
                            row["created_at"]
                        ),
                    )
                )


            return users


        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as error:
            raise StorageError(
                f"Could not load {self.path.name}: {error}"
            ) from error


    def save(self, users: Iterable[User]):
        """Replace the saved user collection with the supplied records.

        Convert UUIDs and timestamps to strings, create parent
        directories if needed, and write a complete temporary JSON file.
        Flush the temporary file to disk before replacing the destination,
        then remove any remaining temporary file during cleanup.

        This saves the entire supplied collection; it does not append
        a single user or merge records with the existing file.

        Args:
            users: Individuals to include in the replacement file.

        Raises:
            StorageError: If file writing, JSON serialization, or
                replacement fails with a handled exception.
        """
        document = {
            "version": self.VERSION,
            "users": [
                {
                    "id": str(user.id),
                    "username": user.username,
                    "password_hash": user.password_hash,
                    "is_admin": user.is_admin,
                    "created_at": user.created_at.isoformat(),
                }
                for user in users
            ],
        }


        temporary_path = None


        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)


            # Write a complete replacement before replacing the saved file.
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)


                json.dump(document, file, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())


            os.replace(temporary_path, self.path)


        except (OSError, ValueError, TypeError) as error:
            raise StorageError(
                f"Could not save {self.path.name}: {error}"
            ) from error


        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)



class BankStore:
    """Load and save banks and their accounts in a versioned JSON file.

    Account records reference individuals by UUID. User identities and
    trading balances are stored separately, and loading this file does
    not update the Admin registry automatically.
    """

    VERSION = 1


    def __init__(self, path: str | Path):
        """Set the bank-data file path without reading or creating it.

        Args:
            path: Location of the JSON file containing banks and accounts.
        """
        self.path = Path(path)


    def load(self) -> list[Bank]:
        """Read banks from JSON and reconstruct their Account objects.

        Validate the document format, bank details, UUIDs, timestamps,
        account types, and nonempty account password hashes. Reject
        duplicate bank IDs, normalized bank names, and account IDs.

        Assign each reconstructed account to its containing bank.
        This method does not verify that account owners exist in the
        separately stored user records.

        Returns:
            list[Bank]: Banks containing their loaded accounts, or an
                empty list if the file does not exist.

        Raises:
            StorageError: If reading, parsing, or validation fails
                with one of the handled exceptions.
        """
        if not self.path.exists():
            return []


        try:
            with self.path.open("r", encoding="utf-8") as file:
                document = json.load(file)


            if (
                not isinstance(document, dict)
                or document.get("version") != self.VERSION
                or not isinstance(document.get("banks"), list)
            ):
                raise ValueError("Invalid bank storage format.")


            banks = []
            bank_ids = set()
            account_ids = set()
            bank_names = set()


            for row in document["banks"]:
                bank = Bank(
                    id=UUID(row["id"]),
                    name=row["name"],
                    currency=row["currency"],
                    theme=row["theme"],
                    created_at=datetime.fromisoformat(
                        row["created_at"]
                    ),
                )


                if not all(
                    isinstance(value, str) and value.strip()
                    for value in (
                        bank.name,
                        bank.currency,
                        bank.theme,
                    )
                ):
                    raise ValueError("Invalid bank details.")


                normalized_name = bank.name.strip().casefold()


                if (
                    bank.id in bank_ids
                    or normalized_name in bank_names
                ):
                    raise ValueError("Duplicate bank.")


                bank_ids.add(bank.id)
                bank_names.add(normalized_name)


                if not isinstance(row["accounts"], list):
                    raise ValueError("Invalid account list.")


                for item in row["accounts"]:
                    account = Account(
                        id=UUID(item["id"]),
                        user_id=UUID(item["user_id"]),
                        bank_id=bank.id,
                        acc_type=item["acc_type"],
                        password_hash=item["password_hash"],
                        created_at=datetime.fromisoformat(
                            item["created_at"]
                        ),
                    )


                    if account.id in account_ids:
                        raise ValueError("Duplicate account ID.")


                    if account.acc_type not in bank.ACCOUNT_TYPES:
                        raise ValueError("Invalid account type.")


                    if (
                        not isinstance(account.password_hash, str)
                        or not account.password_hash
                    ):
                        raise ValueError("Missing account password hash.")


                    account_ids.add(account.id)
                    bank.accounts[account.id] = account


                banks.append(bank)


            return banks


        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as error:
            raise StorageError(
                f"Could not load {self.path.name}: {error}"
            ) from error


    def save(self, banks: Iterable[Bank]):
        """Replace the saved bank collection and its nested accounts.

        Serialize bank details, account ownership references, password
        hashes, UUIDs, and creation timestamps. Account bank IDs are
        represented by nesting each account within its bank record.

        Create parent directories if needed, write and flush a complete
        temporary JSON file, and replace the destination. Remove any
        remaining temporary file during cleanup.

        This saves the entire supplied collection, not an incremental
        change. It does not save individual identities or trading data.

        Args:
            banks: Banks and their current accounts to include in the
                replacement file.

        Raises:
            StorageError: If file writing, JSON serialization, or
                replacement fails with a handled exception.
        """
        document = {
            "version": self.VERSION,
            "banks": [
                {
                    "id": str(bank.id),
                    "name": bank.name,
                    "currency": bank.currency,
                    "theme": bank.theme,
                    "created_at": bank.created_at.isoformat(),
                    "accounts": [
                        {
                            "id": str(account.id),
                            "user_id": str(account.user_id),
                            "acc_type": account.acc_type,
                            "password_hash": account.password_hash,
                            "created_at": account.created_at.isoformat(),
                        }
                        for account in bank.accounts.values()
                    ],
                }
                for bank in banks
            ],
        }


        temporary_path = None


        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)


            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)


                json.dump(document, file, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())


            os.replace(temporary_path, self.path)


        except (OSError, ValueError, TypeError) as error:
            raise StorageError(
                f"Could not save {self.path.name}: {error}"
            ) from error


        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)