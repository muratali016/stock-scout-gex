"""Local, git-safe credential storage for optional Alpaca features."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv, set_key


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"

_NAMES = {
    "paper": ("ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"),
    "live": ("ALPACA_LIVE_API_KEY", "ALPACA_LIVE_SECRET_KEY"),
}


def _normalize_environment(environment: str | None) -> str:
    return "live" if str(environment).lower() == "live" else "paper"


def get_alpaca_credentials(environment: str = "paper") -> tuple[str, str]:
    """Read credentials at call time so keys entered in the UI work immediately."""
    load_dotenv(ENV_FILE, override=False)
    key_name, secret_name = _NAMES[_normalize_environment(environment)]
    return (os.getenv(key_name, "").strip(),
            os.getenv(secret_name, "").strip())


def alpaca_credentials_configured(environment: str | None = None) -> bool:
    """Return whether one complete pair, or a requested pair, is configured."""
    if environment:
        return all(get_alpaca_credentials(environment))
    return (all(get_alpaca_credentials("paper"))
            or all(get_alpaca_credentials("live")))


def validate_and_store_alpaca_credentials(
    environment: str,
    api_key: str,
    secret_key: str,
) -> tuple[bool, str]:
    """Validate a key pair with a read-only account request, then save locally."""
    environment = _normalize_environment(environment)
    api_key = (api_key or "").strip()
    secret_key = (secret_key or "").strip()
    if not api_key or not secret_key:
        return False, "Enter both the Alpaca API key and secret key."
    if len(api_key) < 8 or len(secret_key) < 16:
        return False, "That key pair is too short to be a valid Alpaca credential."

    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key, secret_key, paper=(environment == "paper"))
        account = client.get_account()  # read-only authentication check
        account_status = str(getattr(account, "status", "authenticated"))
    except Exception as exc:
        return False, f"Alpaca rejected the credentials: {type(exc).__name__}: {exc}"

    ENV_FILE.touch(exist_ok=True)
    key_name, secret_name = _NAMES[environment]
    set_key(str(ENV_FILE), key_name, api_key, quote_mode="always")
    set_key(str(ENV_FILE), secret_name, secret_key, quote_mode="always")
    os.environ[key_name] = api_key
    os.environ[secret_name] = secret_key
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    return True, (f"Alpaca {environment} access activated locally "
                  f"(account status: {account_status}).")
