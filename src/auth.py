from __future__ import annotations


import hashlib
import hmac
import secrets


from dataclasses import dataclass, field
from typing import Iterable
from uuid import UUID


from src.storage import UserStore
from src.records import Account, Admin, Bank, User



class AuthenticationError(Exception):
    """Indicate failed authentication, an invalid session, or an
    incorrect login or account password.
    """



class AuthorizationError(PermissionError):
    """Indicate that a session lacks the required role or unlocked
    account access.
    """



class PasswordHasher:
    """Create and verify salted PBKDF2-HMAC-SHA256 password hashes.

    Encoded hashes contain the algorithm name, iteration count,
    hexadecimal salt, and hexadecimal digest separated by dollar signs.
    """

    ALGORITHM = "pbkdf2_sha256"
    ITERATIONS = 600_000
    SALT_BYTES = 16


    @classmethod
    def hash_password(cls, password: str) -> str:
        """Hash a UTF-8-encoded password using a new random salt.

        Returns:
            str: The algorithm, iteration count, salt, and digest in
                the format used by verify_password().

        Password-length and registration rules are checked by Auth,
        not by this method.
        """
        salt = secrets.token_bytes(cls.SALT_BYTES)


        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            cls.ITERATIONS,
        )


        return (
            f"{cls.ALGORITHM}"
            f"${cls.ITERATIONS}"
            f"${salt.hex()}"
            f"${digest.hex()}"
        )


    @classmethod
    def verify_password(
        cls,
        password: str,
        encoded_hash: str,
    ) -> bool:
        """Check a password against an encoded password hash.

        Validate the algorithm, iteration range, salt length, and
        digest length before calculating and comparing the digest.

        Returns:
            bool: True if the password matches; False if it does not
                match or the encoded hash fails the handled checks.
        """
        try:
            algorithm, iterations_text, salt_hex, digest_hex = (
                encoded_hash.split("$")
            )


            if algorithm != cls.ALGORITHM:
                return False


            iterations = int(iterations_text)


            if not 100_000 <= iterations <= 2_000_000:
                return False


            salt = bytes.fromhex(salt_hex)
            expected_digest = bytes.fromhex(digest_hex)


            if (
                len(salt) != cls.SALT_BYTES
                or len(expected_digest) != 32
            ):
                return False


            actual_digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                iterations,
            )


            return hmac.compare_digest(
                actual_digest,
                expected_digest,
            )


        except (ValueError, TypeError, AttributeError):
            return False



@dataclass
class _Session:
    """Store an authenticated individual's ID and the account IDs
    unlocked within that session.

    This internal record is associated with a session token and is
    not itself a public login credential.
    """


    user_id: UUID
    unlocked_accounts: set[UUID] = field(default_factory=set)



class Auth:
    """Manage individual registration, login sessions, password changes,
    account access, and administrator permissions.

    Normalize usernames for case-insensitive lookup, reserve Simon
    as the administrator identity, and save user changes through an
    optional UserStore. Adding new users requires configured storage.

    Bank and account operations modify the records layer; saving those
    changes is the responsibility of the calling application.
    """

    ADMIN_USERNAME = "Simon"


    MIN_PASSWORD_LENGTH = 8
    MAX_PASSWORD_LENGTH = 128
    MAX_USERNAME_LENGTH = 32


    def __init__(
        self,
        users: Iterable[User] = (),
        store: UserStore | None = None,
    ):
        """Load individuals from storage or accept initial user records.

        Build indexes by UUID and normalized username, validate duplicate
        identities and administrator-role assignments, and start with
        no active sessions.

        Args:
            users: Initial records to use when no store is supplied.
            store: User storage to load and use for subsequent saves.

        Raises:
            ValueError: If both initial users and storage are supplied,
                identities are invalid or duplicated, or administrator
                roles do not follow the reserved Simon identity rule.
        """
        self._store = store


        provided_users = list(users)


        if store is not None:
            if provided_users:
                raise ValueError(
                    "Provide either saved storage or initial users, not both."
                )


            users = store.load()
        else:
            users = provided_users


        self._users: dict[UUID, User] = {}
        self._username_index: dict[str, UUID] = {}
        self._sessions: dict[str, _Session] = {}


        for user in users:
            key = self.normalize_username(user.username)


            if (
                not key
                or key in self._username_index
                or user.id in self._users
            ):
                raise ValueError(
                    "Loaded users contain an invalid or duplicate identity."
                )


            if key == self.normalize_username(self.ADMIN_USERNAME):
                if not user.is_admin:
                    raise ValueError(
                        "The reserved Simon identity must be an administrator."
                    )


            if user.is_admin:
                if key != self.normalize_username(self.ADMIN_USERNAME):
                    raise ValueError(
                        "Only Simon may hold the administrator role."
                    )


            self._users[user.id] = user
            self._username_index[key] = user.id


        # Used to perform password-hashing work for unknown usernames too.
        self._dummy_hash = PasswordHasher.hash_password(
            secrets.token_urlsafe(32)
        )


    def leaderboard_names(self, token: str) -> dict[str, str]:
        """Return user IDs mapped to usernames for leaderboard display.

        Require a valid session and exclude password hashes from the
        returned mapping. User IDs are represented as strings.
        """
        self.current_user(token)


        return {
            str(user.id): user.username
            for user in self._users.values()
        }


    def _add_user(self, user: User) -> User:
        """Save a new individual before adding them to memory.

        Reject duplicate UUIDs or normalized usernames. If saving fails,
        do not add the individual to the in-memory indexes.

        Returns:
            User: The saved and indexed individual.

        Raises:
            ValueError: If the UUID or normalized username already exists.
            RuntimeError: If user storage is not configured.
        """
        key = self.normalize_username(user.username)


        if user.id in self._users:
            raise ValueError("This individual already exists.")


        if key in self._username_index:
            raise ValueError("This username is already taken.")


        if self._store is None:
            raise RuntimeError(
                "Authentication storage is not configured. "
                "Start Auth with Auth(store=store)."
            )


        updated_users = [
            *self._users.values(),
            user,
        ]


        # Save first. If this raises an error, registration stops.
        self._store.save(updated_users)


        self._users[user.id] = user
        self._username_index[key] = user.id


        return user


    @staticmethod
    def normalize_username(username: str) -> str:
        """Return a username with surrounding whitespace removed and
        case folded for lookup and duplicate detection.
        """
        return username.strip().casefold()


    def validate_username(self, username: str) -> str:
        """Trim and validate a proposed registration username.

        Require 1–32 characters and check its lowercase form against
        the allowed letters, digits, underscores, and hyphens.
        Reservation and uniqueness checks are performed separately.

        Returns:
            str: The trimmed username with its original case preserved.

        Raises:
            ValueError: If the length or character check fails.
        """
        username = username.strip()


        if not 1 <= len(username) <= self.MAX_USERNAME_LENGTH:
            raise ValueError(
                f"Username must contain 1–{self.MAX_USERNAME_LENGTH} characters."
            )


        # Restrict registration names to an unambiguous set.
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-"


        if any(character not in allowed for character in username.lower()):
            raise ValueError(
                "Use only letters A–Z, numbers, underscores, and hyphens."
            )


        return username


    def validate_password(self, password: str):
        """Require a password of 8–128 characters that is not entirely
        whitespace. Do not modify the password.

        Raises:
            ValueError: If the length is invalid or only whitespace
                is supplied.
        """
        if not (
            self.MIN_PASSWORD_LENGTH
            <= len(password)
            <= self.MAX_PASSWORD_LENGTH
        ):
            raise ValueError(
                f"Password must contain "
                f"{self.MIN_PASSWORD_LENGTH}–"
                f"{self.MAX_PASSWORD_LENGTH} characters."
            )


        if not password.strip():
            raise ValueError("Password cannot contain only spaces.")


    @property
    def needs_admin_setup(self) -> bool:
        """Return True when no loaded individual has administrator status."""
        return not any(user.is_admin for user in self._users.values())


    def setup_admin(self, password: str) -> User:
        """Create and save Simon's administrator identity during trusted
        first-launch setup, using a validated and hashed password.

        Returns:
            User: The newly saved administrator.

        Raises:
            AuthorizationError: If an administrator already exists.
            ValueError: If the password is invalid or the reserved
                administrator username is unavailable.
            RuntimeError: If user storage is not configured.
        """
        if not self.needs_admin_setup:
            raise AuthorizationError(
                "The administrator account already exists."
            )


        self.validate_password(password)


        key = self.normalize_username(self.ADMIN_USERNAME)


        if key in self._username_index:
            raise ValueError(
                "The reserved administrator name is unavailable."
            )


        user = User(
            username=self.ADMIN_USERNAME,
            password_hash=PasswordHasher.hash_password(password),
            is_admin=True,
        )


        return self._add_user(user)


    def register(self, username: str, password: str) -> User:
        """Validate, hash credentials for, and save a new customer identity.

        Public registration always creates a non-administrator and
        rejects the reserved Simon username and duplicate normalized
        usernames.

        Returns:
            User: The newly saved customer.

        Raises:
            AuthorizationError: If administrator setup is incomplete.
            ValueError: If credentials are invalid or the username is
                reserved or already taken.
            RuntimeError: If user storage is not configured.
        """
        if self.needs_admin_setup:
            raise AuthorizationError(
                "Complete administrator setup before registration."
            )


        username = self.validate_username(username)
        self.validate_password(password)


        key = self.normalize_username(username)


        if key == self.normalize_username(self.ADMIN_USERNAME):
            raise ValueError("This username is reserved.")


        if key in self._username_index:
            raise ValueError("This username is already taken.")


        user = User(
            username=username,
            password_hash=PasswordHasher.hash_password(password),
            is_admin=False,
        )


        return self._add_user(user)


    def login(self, username: str, password: str) -> str:
        """Verify credentials and create an in-memory login session.

        Look up the normalized username and verify its password hash.
        For an unknown username, verify against a dummy hash before
        returning the same generic authentication error.

        Returns:
            str: A randomly generated token identifying the new session.

        Raises:
            AuthenticationError: If the username or password is incorrect.
        """
        key = self.normalize_username(username)
        user_id = self._username_index.get(key)


        user = self._users.get(user_id) if user_id is not None else None
        password_hash = (
            user.password_hash if user is not None else self._dummy_hash
        )


        valid_password = PasswordHasher.verify_password(
            password,
            password_hash,
        )


        if user is None or not valid_password:
            raise AuthenticationError("Invalid username or password.")


        token = secrets.token_urlsafe(32)
        self._sessions[token] = _Session(user_id=user.id)
        return token


    def logout(self, token: str):
        """Remove a session and its unlocked-account access.

        Do nothing if the token is not associated with an active session.
        """
        self._sessions.pop(token, None)


    def _require_session(self, token: str) -> _Session:
        """Return an active session whose individual still exists.

        Remove a stale session if its individual is no longer present.

        Raises:
            AuthenticationError: If the token is unknown or the session's
                individual no longer exists.
        """
        session = self._sessions.get(token)


        if session is None:
            raise AuthenticationError("Please log in.")


        if session.user_id not in self._users:
            self._sessions.pop(token, None)
            raise AuthenticationError("This session is no longer valid.")


        return session


    def current_user(self, token: str) -> User:
        """Return the stored individual associated with a valid session.

        Raises:
            AuthenticationError: If the session is invalid.
        """
        session = self._require_session(token)
        return self._users[session.user_id]


    def require_admin(self, token: str) -> User:
        """Return the authenticated individual after checking their
        administrator role.

        Raises:
            AuthenticationError: If the session is invalid.
            AuthorizationError: If the individual is not an administrator.
        """
        user = self.current_user(token)


        if not user.is_admin:
            raise AuthorizationError(
                "Administrator permissions are required."
            )


        return user
    
    def change_password(
        self,
        token: str,
        current_password: str,
        new_password: str,
    ):
        """Verify the current password, validate and hash its replacement,
        and save the updated user records when storage is configured.

        Restore the previous hash if saving raises an exception.
        After a successful change, invalidate every session belonging
        to the individual, including the current session.

        Raises:
            AuthenticationError: If the session is invalid or the current
                password is incorrect.
            ValueError: If the new password fails validation.
        """
        user = self.current_user(token)


        if not PasswordHasher.verify_password(
            current_password,
            user.password_hash,
        ):
            raise AuthenticationError(
                "Current password is incorrect."
            )


        self.validate_password(new_password)


        previous_hash = user.password_hash
        user.password_hash = PasswordHasher.hash_password(
            new_password
        )


        try:
            if self._store is not None:
                self._store.save(self._users.values())


        except Exception:
            user.password_hash = previous_hash
            raise


        for session_token, session in list(self._sessions.items()):
            if session.user_id == user.id:
                del self._sessions[session_token]


    # Customer operations


    def get_banks(self, token: str) -> list[Bank]:
        """Return registered banks after verifying the login session."""
        self.current_user(token)
        return Admin.get_banks()


    def create_account(
        self,
        token: str,
        bank_id: UUID,
        acc_type: str,
        account_password: str,
    ) -> Account:
        """Create a bank account owned by the authenticated individual.

        Validate and hash the account password before passing it to the
        bank. The caller is responsible for saving the bank records.

        Returns:
            Account: The newly created bank account.

        Raises:
            AuthenticationError: If the session is invalid.
            ValueError: If the password, bank ID, or account type is invalid.
        """
        user = self.current_user(token)
        self.validate_password(account_password)


        bank = Admin.get_bank(bank_id)


        return bank.create_acc(
            user=user,
            acc_type=acc_type,
            password_hash=PasswordHasher.hash_password(
                account_password
            ),
        )


    def get_my_accounts(self, token: str) -> list[Account]:
        """Return the authenticated individual's accounts across all
        registered banks without unlocking those accounts.
        """
        user = self.current_user(token)


        return [
            account
            for bank in Admin.get_banks()
            for account in bank.get_user_accounts(user.id)
        ]


    def unlock_account(
        self,
        token: str,
        bank_id: UUID,
        account_id: UUID,
        account_password: str,
    ) -> Account:
        """Verify account ownership and its password, then mark the
        account as unlocked within the current session.

        Returns:
            Account: The verified account.

        Raises:
            AuthenticationError: If the session or account password is
                invalid.
            PermissionError: If the account belongs to another individual.
            ValueError: If the bank or account cannot be found.
        """
        session = self._require_session(token)


        account = Admin.get_bank(bank_id).get_owned_acc(
            session.user_id,
            account_id,
        )


        if not PasswordHasher.verify_password(
            account_password,
            account.password_hash,
        ):
            raise AuthenticationError("Incorrect account password.")


        session.unlocked_accounts.add(account.id)
        return account


    def require_account_access(
        self,
        token: str,
        bank_id: UUID,
        account_id: UUID,
    ) -> Account:
        """Return an account only if the current session owns it and
        has previously unlocked it.

        Raises:
            AuthenticationError: If the session is invalid.
            PermissionError: If the account belongs to another individual.
            AuthorizationError: If the account has not been unlocked.
            ValueError: If the bank or account cannot be found.
        """
        session = self._require_session(token)


        account = Admin.get_bank(bank_id).get_owned_acc(
            session.user_id,
            account_id,
        )


        if account.id not in session.unlocked_accounts:
            raise AuthorizationError("Unlock this account first.")


        return account


    def lock_account(self, token: str, account_id: UUID):
        """Remove an account's unlocked status from the current session.

        Do nothing if the account is already locked in that session.

        Raises:
            AuthenticationError: If the session is invalid.
        """
        session = self._require_session(token)
        session.unlocked_accounts.discard(account_id)


    # Administrator operations


    def create_bank(
        self,
        token: str,
        name: str,
        currency: str = "CAD",
        theme: str = "default",
    ) -> Bank:
        """Require administrator permissions and create a registered bank.

        Return the new bank. The caller is responsible for saving
        the updated bank records.
        """
        self.require_admin(token)
        return Admin.create_bank(name, currency, theme)


    def remove_bank(self, token: str, bank_id: UUID) -> Bank:
        """Require administrator permissions, unregister a bank, and
        remove its accounts' unlocked status from every active session.

        Return the removed bank object. This does not delete individual
        identities or separately stored trading data. The caller is
        responsible for saving the updated bank records.
        """
        self.require_admin(token)
        bank = Admin.remove_bank(bank_id)


        account_ids = set(bank.accounts)


        for session in self._sessions.values():
            session.unlocked_accounts.difference_update(account_ids)


        return bank


    def get_admin_info(self, token: str) -> dict[str, int]:
        """Require administrator permissions and return system counts.

        Include the bank registry's summary counts and the total number
        of loaded individuals.
        """
        self.require_admin(token)
        info = Admin.get_info()
        info["individual_count"] = len(self._users)
        return info


    def get_bank_info(
        self,
        token: str,
        bank_id: UUID,
    ) -> dict[str, str | UUID | int]:
        """Require administrator permissions and return a bank's summary.

        Raises:
            ValueError: If the bank cannot be found.
        """
        self.require_admin(token)
        return Admin.get_bank_info(bank_id)


    def remove_account(
        self,
        token: str,
        bank_id: UUID,
        account_id: UUID,
    ) -> Account:
        """Require administrator permissions and remove a bank account.

        Clear its unlocked status from every session and return the
        removed account. This does not check balances or remove separately
        stored trading data. The caller must save the bank records.
        """
        self.require_admin(token)
        account = Admin.remove_acc(bank_id, account_id)


        for session in self._sessions.values():
            session.unlocked_accounts.discard(account_id)


        return account


    def remove_customer_accounts(
        self,
        token: str,
        bank_id: UUID,
        user_id: UUID,
    ) -> list[Account]:
        """Require administrator permissions and remove an individual's
        accounts at one bank.

        Clear the removed accounts' unlocked status from every session.
        Preserve the individual's identity and accounts at other banks.
        The caller is responsible for saving the bank records.

        Returns:
            list[Account]: The accounts removed from the selected bank.
        """
        self.require_admin(token)


        accounts = Admin.remove_customer_accounts(
            bank_id,
            user_id,
        )


        removed_ids = {account.id for account in accounts}


        for session in self._sessions.values():
            session.unlocked_accounts.difference_update(removed_ids)


        return accounts