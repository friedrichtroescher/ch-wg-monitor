"""Captcha solving: pluggable solvers built from environment configuration."""
import logging
import os
from typing import Optional

from .solver import (
    CaptchaSolver,
    CaptchaError,
    CaptchaUnsolvableError,
    CaptchaBalanceEmpty,
    CaptchaTimeout,
)
from .twocaptcha import TwoCaptchaSolver

log = logging.getLogger(__name__)

_SOLVERS = {
    "2captcha": TwoCaptchaSolver,
}


def build_solver_from_env() -> Optional[CaptchaSolver]:
    """Build a captcha solver from CAPTCHA_API_KEY / CAPTCHA_PROVIDER, or None if unconfigured."""
    api_key = os.environ.get("CAPTCHA_API_KEY", "").strip()
    if not api_key:
        return None
    provider = os.environ.get("CAPTCHA_PROVIDER", "2captcha").strip().lower()
    solver_cls = _SOLVERS.get(provider)
    if solver_cls is None:
        log.warning("Unknown CAPTCHA_PROVIDER %r — known: %s", provider, ", ".join(_SOLVERS))
        return None
    return solver_cls(api_key)


__all__ = [
    "CaptchaSolver", "CaptchaError", "CaptchaUnsolvableError", "CaptchaBalanceEmpty",
    "CaptchaTimeout", "TwoCaptchaSolver", "build_solver_from_env",
]
