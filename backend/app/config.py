"""Environment configuration and startup validation.

Hard constraint (CLAUDE.md Section 2.1): every Razorpay call in this system must use
test-mode credentials. We enforce that here, at import time, by refusing to construct a
Settings object whose RAZORPAY_KEY_ID does not carry the ``rzp_test_`` prefix. There is no
override flag and no way to opt out -- that is deliberate.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Repo root is three levels up from this file: backend/app/config.py -> backend/app -> backend -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]

TEST_MODE_KEY_PREFIX = "rzp_test_"


class ConfigError(RuntimeError):
    """Raised when the environment is missing or misconfigured.

    Deliberately fatal: we would rather refuse to boot than start a process that could
    reach Razorpay's live API.
    """


def _load_dotenv_once() -> None:
    """Load ``.env`` from the repo root, then from backend/, without clobbering real env vars."""
    for candidate in (REPO_ROOT / ".env", BACKEND_ROOT / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)


class Settings:
    """Validated application settings.

    Attributes are plain values rather than a Pydantic model so that the failure mode for a
    missing variable is a single readable ConfigError instead of a Pydantic traceback.
    """

    def __init__(self, *, load_env_file: bool = True) -> None:
        # Tests pass load_env_file=False so that a developer's real .env cannot silently
        # satisfy a variable the test is deliberately removing.
        if load_env_file:
            _load_dotenv_once()

        self.razorpay_key_id: str = self._require("RAZORPAY_KEY_ID")
        self.razorpay_key_secret: str = self._require("RAZORPAY_KEY_SECRET")
        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///./recourse.db").strip()
        self.assumed_representment_cost_inr: float = self._float_env(
            "ASSUMED_REPRESENTMENT_COST_INR", default=1500.0
        )

        # --- LLM drafting (optional; only ever used AFTER a decision is made) ---
        # Every one of these may be absent: the packet generator falls back to a
        # deterministic template, so the API serves fully without any LLM credentials.
        self.anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.gemini_api_key: str = (
            os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
        )
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "").strip()
        self.anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5").strip()
        self.llm_provider: str = (os.getenv("LLM_PROVIDER", "auto").strip().lower() or "auto")
        # Hard ceiling on a drafting attempt. Without one, an SDK's internal backoff can
        # retry a 503 for minutes and hang the request that triggered it (measured: 296s).
        self.llm_timeout_seconds: float = self._float_env("LLM_TIMEOUT_SECONDS", default=15.0)
        self.llm_retry_attempts: int = int(
            self._float_env("LLM_RETRY_ATTEMPTS", default=2.0)
        )

        if self.llm_provider not in {"auto", "gemini", "anthropic", "none"}:
            raise ConfigError(
                f"LLM_PROVIDER={self.llm_provider!r} is not one of: auto, gemini, anthropic, none."
            )

        self._enforce_test_mode()

    # -- validation helpers -------------------------------------------------

    @staticmethod
    def _require(name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise ConfigError(
                f"Required environment variable {name} is not set. "
                f"Copy .env.example to .env and fill it in (see README, Setup)."
            )
        return value

    @staticmethod
    def _float_env(name: str, *, default: float) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise ConfigError(f"Environment variable {name}={raw!r} is not a number.") from exc

    def _enforce_test_mode(self) -> None:
        """Hard-fail if the Razorpay key is not a test-mode key. No exceptions, no override."""
        if not self.razorpay_key_id.startswith(TEST_MODE_KEY_PREFIX):
            raise ConfigError(
                "REFUSING TO START: RAZORPAY_KEY_ID must be a test-mode key beginning with "
                f"{TEST_MODE_KEY_PREFIX!r}, but it begins with "
                f"{self.razorpay_key_id[:8]!r}. Recourse is a test-mode-only system "
                "(see CLAUDE.md Section 2, hard constraint 1); it never talks to Razorpay live."
            )

    # -- convenience --------------------------------------------------------

    @property
    def anthropic_configured(self) -> bool:
        """True when an Anthropic key is present.

        The key is optional at boot: it is needed only for offline synthetic-data
        generation (Phase 1) and representment drafting (Phase 6), not to serve the API.
        """
        return bool(self.anthropic_api_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    def resolve_llm_provider(self) -> str:
        """Which drafting provider to actually use: 'gemini', 'anthropic' or 'none'.

        'auto' prefers Gemini because its free tier means a person cloning this repo can
        exercise the LLM path without paying for credits. 'none' is a first-class outcome,
        not an error: the deterministic template is a supported path, not a degraded one.
        """
        if self.llm_provider == "none":
            return "none"
        if self.llm_provider == "gemini":
            return "gemini" if self.gemini_configured else "none"
        if self.llm_provider == "anthropic":
            return "anthropic" if self.anthropic_configured else "none"
        # auto
        if self.gemini_configured:
            return "gemini"
        if self.anthropic_configured:
            return "anthropic"
        return "none"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Settings(razorpay_key_id={self.razorpay_key_id[:14]}..., "
            f"database_url={self.database_url!r}, "
            f"anthropic_configured={self.anthropic_configured})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton, constructing (and validating) it once."""
    return Settings()
