"""Read/write Anthem credentials in the macOS Keychain via `keyring`."""
import keyring

SERVICE = "claims-tracker-anthem"
_USERNAME_KEY = "username"
_PASSWORD_KEY = "password"


def store_credentials(username: str, password: str) -> None:
    keyring.set_password(SERVICE, _USERNAME_KEY, username)
    keyring.set_password(SERVICE, _PASSWORD_KEY, password)


def get_credentials() -> tuple[str, str] | None:
    username = keyring.get_password(SERVICE, _USERNAME_KEY)
    password = keyring.get_password(SERVICE, _PASSWORD_KEY)
    if not username or not password:
        return None
    return username, password
