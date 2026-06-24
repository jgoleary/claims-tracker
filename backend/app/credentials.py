"""Read/write Anthem credentials in the macOS Keychain via `keyring`."""
import keyring
from keyring.errors import KeyringError

SERVICE = "claims-tracker-anthem"
_USERNAME_KEY = "username"
_PASSWORD_KEY = "password"


def store_credentials(username: str, password: str) -> None:
    keyring.set_password(SERVICE, _USERNAME_KEY, username)
    keyring.set_password(SERVICE, _PASSWORD_KEY, password)


def get_credentials() -> tuple[str, str] | None:
    # A locked or access-denied Keychain (e.g. the user clicked Deny) is treated
    # the same as "no credentials stored" rather than crashing the caller.
    try:
        username = keyring.get_password(SERVICE, _USERNAME_KEY)
        password = keyring.get_password(SERVICE, _PASSWORD_KEY)
    except KeyringError:
        return None
    if not username or not password:
        return None
    return username, password


ANTHROPIC_SERVICE = "claims-tracker-anthropic"
_ANTHROPIC_KEY = "api_key"


def store_anthropic_key(key: str) -> None:
    keyring.set_password(ANTHROPIC_SERVICE, _ANTHROPIC_KEY, key)


def get_anthropic_key() -> str | None:
    try:
        key = keyring.get_password(ANTHROPIC_SERVICE, _ANTHROPIC_KEY)
    except KeyringError:
        return None
    return key or None
