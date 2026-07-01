"""2Captcha (https://2captcha.com) solver — reCAPTCHA v3 support.

Flow (same as flathunter, extended for v3):
  1. POST in.php with method=userrecaptcha, version=v3, googlekey, pageurl, action, min_score
     → returns a captcha id.
  2. Poll res.php until the token is ready (or an error/timeout).
"""
import logging
import time

import requests

from .solver import (
    CaptchaSolver,
    CaptchaBalanceEmpty,
    CaptchaTimeout,
    CaptchaUnsolvableError,
    DEFAULT_MIN_SCORE,
)

log = logging.getLogger(__name__)

IN_URL = "https://2captcha.com/in.php"
RES_URL = "https://2captcha.com/res.php"


class TwoCaptchaSolver(CaptchaSolver):
    """reCAPTCHA v3 solver backed by 2Captcha."""

    def __init__(self, api_key: str, poll_interval: float = 5.0, timeout: float = 180.0):
        super().__init__(api_key)
        self.poll_interval = poll_interval
        self.timeout = timeout

    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str,
                           min_score: float = DEFAULT_MIN_SCORE) -> str:
        log.info("2Captcha: solving reCAPTCHA v3 for %s (action=%s)", page_url, action)
        captcha_id = self._submit({
            "key": self.api_key,
            "method": "userrecaptcha",
            "version": "v3",
            "googlekey": site_key,
            "pageurl": page_url,
            "action": action,
            "min_score": min_score,
            "json": 1,
        })
        return self._poll(captcha_id)

    def _submit(self, params: dict) -> str:
        resp = requests.post(IN_URL, data=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != 1:
            self._raise_for_error(body.get("request", ""))
        return body["request"]

    def _poll(self, captcha_id: str) -> str:
        deadline = time.monotonic() + self.timeout
        params = {"key": self.api_key, "action": "get", "id": captcha_id, "json": 1}
        while time.monotonic() < deadline:
            time.sleep(self.poll_interval)
            resp = requests.get(RES_URL, params=params, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") == 1:
                return body["request"]
            request = body.get("request", "")
            if request == "CAPCHA_NOT_READY":
                continue
            self._raise_for_error(request)
        raise CaptchaTimeout(f"2Captcha did not solve within {self.timeout:.0f}s")

    @staticmethod
    def _raise_for_error(code: str) -> None:
        if code == "ERROR_ZERO_BALANCE":
            raise CaptchaBalanceEmpty()
        if code == "ERROR_CAPTCHA_UNSOLVABLE":
            raise CaptchaUnsolvableError()
        raise CaptchaUnsolvableError(f"2Captcha error: {code}")
