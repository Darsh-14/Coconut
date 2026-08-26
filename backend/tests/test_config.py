"""Guards for CLAUDE.md Section 2's hard constraints.

Constraint 1 (test mode only) is the one that can cause real-world harm if it regresses, so
it gets a permanent test rather than a one-off manual check.
"""

from __future__ import annotations

import pytest

from app.config import TEST_MODE_KEY_PREFIX, ConfigError, Settings


def _set_env(monkeypatch, **overrides: str | None) -> None:
    base = {
        "RAZORPAY_KEY_ID": "rzp_test_abc123",
        "RAZORPAY_KEY_SECRET": "secret",
        "ANTHROPIC_API_KEY": "",
        "DATABASE_URL": "sqlite:///./test.db",
        "ASSUMED_REPRESENTMENT_COST_INR": "1500",
    }
    base.update(overrides)
    for key, value in base.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def test_test_mode_key_is_accepted(monkeypatch):
    _set_env(monkeypatch)
    settings = Settings(load_env_file=False)
    assert settings.razorpay_key_id.startswith(TEST_MODE_KEY_PREFIX)
    assert settings.assumed_representment_cost_inr == 1500.0


def test_surrounding_whitespace_is_stripped_not_rejected(monkeypatch):
    """A padded but genuine test key is valid; it must not be mistaken for a live key."""
    _set_env(monkeypatch, RAZORPAY_KEY_ID="  rzp_test_abc123  ")
    assert Settings(load_env_file=False).razorpay_key_id == "rzp_test_abc123"


@pytest.mark.parametrize(
    "bad_key",
    [
        "rzp_live_abc123",  # the dangerous one
        "rzp_abc123",
        "sk_test_abc123",
        "RZP_TEST_abc123",  # prefix check is case-sensitive on purpose
        "xrzp_test_abc123",  # prefix must be at position 0, not merely present
    ],
)
def test_non_test_mode_key_refuses_to_start(monkeypatch, bad_key):
    _set_env(monkeypatch, RAZORPAY_KEY_ID=bad_key)
    with pytest.raises(ConfigError, match="REFUSING TO START"):
        Settings(load_env_file=False)


def test_missing_key_id_refuses_to_start(monkeypatch):
    _set_env(monkeypatch, RAZORPAY_KEY_ID=None)
    with pytest.raises(ConfigError, match="RAZORPAY_KEY_ID"):
        Settings(load_env_file=False)


def test_missing_key_secret_refuses_to_start(monkeypatch):
    _set_env(monkeypatch, RAZORPAY_KEY_SECRET=None)
    with pytest.raises(ConfigError, match="RAZORPAY_KEY_SECRET"):
        Settings(load_env_file=False)


def test_non_numeric_representment_cost_is_rejected(monkeypatch):
    _set_env(monkeypatch, ASSUMED_REPRESENTMENT_COST_INR="not-a-number")
    with pytest.raises(ConfigError, match="is not a number"):
        Settings(load_env_file=False)


def test_anthropic_key_is_optional_at_boot(monkeypatch):
    """The API must serve without an Anthropic key; it is only needed offline."""
    _set_env(monkeypatch, ANTHROPIC_API_KEY="")
    settings = Settings(load_env_file=False)
    assert settings.anthropic_configured is False
