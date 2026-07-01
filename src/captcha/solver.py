"""Captcha solver interface + data types.

Modelled on flathunter's captcha package: a small abstract base that concrete solving
services (2Captcha, CapMonster, ...) subclass. Solvers talk to a paid third-party service
that returns a token; the caller injects that token into the site's form submission.

Only reCAPTCHA v3 is needed so far (wgzimmer.ch). v3 is score-based and requires the
`action` string in addition to the site key.
"""
from abc import ABC, abstractmethod

DEFAULT_MIN_SCORE = 0.3


class CaptchaSolver(ABC):
    """Interface for captcha solving services."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    @abstractmethod
    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str,
                           min_score: float = DEFAULT_MIN_SCORE) -> str:
        """Return a valid ``g-recaptcha-response`` token for a reCAPTCHA v3 challenge."""
        raise NotImplementedError


class CaptchaError(Exception):
    """Base class for captcha solving failures."""


class CaptchaUnsolvableError(CaptchaError):
    """The service could not solve the captcha."""


class CaptchaBalanceEmpty(CaptchaError):
    """The solving-service account is out of credit."""


class CaptchaTimeout(CaptchaError):
    """The captcha was not solved within the allotted time."""
