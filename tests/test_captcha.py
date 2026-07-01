"""Tests for the captcha solver package."""
from unittest.mock import MagicMock, patch

import pytest

from src.captcha import build_solver_from_env, TwoCaptchaSolver
from src.captcha.solver import CaptchaBalanceEmpty, CaptchaTimeout, CaptchaUnsolvableError


def _json(payload) -> MagicMock:
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


# ── factory ───────────────────────────────────────────────────────────────────

def test_build_solver_none_without_key(monkeypatch):
    monkeypatch.delenv("CAPTCHA_API_KEY", raising=False)
    assert build_solver_from_env() is None


def test_build_solver_twocaptcha(monkeypatch):
    monkeypatch.setenv("CAPTCHA_API_KEY", "k")
    monkeypatch.delenv("CAPTCHA_PROVIDER", raising=False)
    solver = build_solver_from_env()
    assert isinstance(solver, TwoCaptchaSolver)
    assert solver.api_key == "k"


def test_build_solver_unknown_provider(monkeypatch):
    monkeypatch.setenv("CAPTCHA_API_KEY", "k")
    monkeypatch.setenv("CAPTCHA_PROVIDER", "nope")
    assert build_solver_from_env() is None


# ── TwoCaptchaSolver.solve_recaptcha_v3 ────────────────────────────────────────

@patch("src.captcha.twocaptcha.requests.get")
@patch("src.captcha.twocaptcha.requests.post")
def test_solve_recaptcha_v3_success(mock_post, mock_get):
    mock_post.return_value = _json({"status": 1, "request": "CAP_ID"})
    mock_get.side_effect = [
        _json({"status": 0, "request": "CAPCHA_NOT_READY"}),
        _json({"status": 1, "request": "THE_TOKEN"}),
    ]
    solver = TwoCaptchaSolver("key", poll_interval=0)

    token = solver.solve_recaptcha_v3("SITEKEY", "https://x/y", "act")

    assert token == "THE_TOKEN"
    # v3 params were submitted
    params = mock_post.call_args.kwargs["data"]
    assert params["version"] == "v3"
    assert params["googlekey"] == "SITEKEY"
    assert params["action"] == "act"


@patch("src.captcha.twocaptcha.requests.post")
def test_solve_zero_balance(mock_post):
    mock_post.return_value = _json({"status": 0, "request": "ERROR_ZERO_BALANCE"})
    with pytest.raises(CaptchaBalanceEmpty):
        TwoCaptchaSolver("key", poll_interval=0).solve_recaptcha_v3("s", "u", "a")


@patch("src.captcha.twocaptcha.requests.get")
@patch("src.captcha.twocaptcha.requests.post")
def test_solve_unsolvable(mock_post, mock_get):
    mock_post.return_value = _json({"status": 1, "request": "CAP_ID"})
    mock_get.return_value = _json({"status": 0, "request": "ERROR_CAPTCHA_UNSOLVABLE"})
    with pytest.raises(CaptchaUnsolvableError):
        TwoCaptchaSolver("key", poll_interval=0).solve_recaptcha_v3("s", "u", "a")


@patch("src.captcha.twocaptcha.requests.get")
@patch("src.captcha.twocaptcha.requests.post")
def test_solve_timeout(mock_post, mock_get):
    mock_post.return_value = _json({"status": 1, "request": "CAP_ID"})
    mock_get.return_value = _json({"status": 0, "request": "CAPCHA_NOT_READY"})
    with pytest.raises(CaptchaTimeout):
        TwoCaptchaSolver("key", poll_interval=0, timeout=0).solve_recaptcha_v3("s", "u", "a")
