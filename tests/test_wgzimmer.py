"""Tests for the wgzimmer portal adapter (captcha-gated POST search)."""
from unittest.mock import MagicMock, patch

from src.models.listing import Listing
from src.portals import resolve_portal
from src.portals.wgzimmer import WgzimmerPortal, SITE, SITEKEY_FALLBACK, ACTION_FALLBACK

FORM_HTML = """
<html><head>
<script src="https://www.google.com/recaptcha/api.js?render=TESTKEY123"></script>
<script>grecaptcha.execute(siteKey, {action: '//form///wgzimmer/search/mate/submitForm'});</script>
</head><body><form id="searchMateForm"></form></body></html>
"""

SEARCH_HTML = """
<html><body><div id="content"><ul>
  <li><a href="/de/objekt/aaa-111.html"><img></a><a href="/de/objekt/aaa-111.html">Schönes Zimmer Zürich CHF 900</a></li>
  <li><a href="/de/objekt/bbb-222.html">Zimmer Oerlikon</a></li>
</ul></div></body></html>
"""

DETAIL_HTML = """
<html><body>
  <div class="room-content"><p>Grosses helles Zimmer, 18 m².</p></div>
  <div class="mate-content"><p>2er WG, ruhig.</p></div>
  <div class="date-cost"><p>ab 1.8.</p><p>unbefristet</p><p>CHF 900 inkl.</p></div>
  <div class="adress-region"><p>8050 Zürich</p></div>
</body></html>
"""


def _resp(text: str, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.text = text
    r.status_code = status
    r.raise_for_status.return_value = None
    return r


# ── resolution / pure helpers ─────────────────────────────────────────────────

def test_resolve_portal_wgzimmer_from_url():
    assert resolve_portal({"url": "https://www.wgzimmer.ch/wgzimmer/search/mate.html"}).name == "wgzimmer"


def test_form_maps_config():
    form = WgzimmerPortal._form({"state": "zurich", "max_price": 1200, "permanent": False})
    assert form["wgState"] == "zurich"
    assert form["priceMax"] == "1200"
    assert form["permanent"] == "false"
    assert form["bypass-csrf"] == "true"


def test_id_from_url():
    assert WgzimmerPortal._id_from_url(f"{SITE}/de/objekt/aaa-111.html") == "aaa-111"


def test_extract_recaptcha_from_form():
    key, action = WgzimmerPortal._extract_recaptcha(FORM_HTML)
    assert key == "TESTKEY123"
    assert action == "//form///wgzimmer/search/mate/submitForm"


def test_extract_recaptcha_falls_back():
    key, action = WgzimmerPortal._extract_recaptcha("<html>no captcha here</html>")
    assert key == SITEKEY_FALLBACK
    assert action == ACTION_FALLBACK


def test_parse_results_extracts_links():
    listings = WgzimmerPortal()._parse_results(SEARCH_HTML)
    assert [l.id for l in listings] == ["aaa-111", "bbb-222"]
    assert all(l.url.startswith(SITE) for l in listings)
    assert "Zürich" in listings[0].title


# ── fetch_listings: captcha flow ──────────────────────────────────────────────

@patch("src.portals.wgzimmer.build_solver_from_env", return_value=None)
def test_no_solver_skips(_mock_build):
    assert WgzimmerPortal().fetch_listings({"state": "zurich"}) == []


@patch("src.portals.wgzimmer.requests.Session")
@patch("src.portals.wgzimmer.build_solver_from_env")
def test_fetch_listings_solves_and_posts(mock_build, mock_session_cls):
    solver = MagicMock()
    solver.solve_recaptcha_v3.return_value = "TOKEN"
    mock_build.return_value = solver

    session = MagicMock()
    session.get.return_value = _resp(FORM_HTML)
    session.post.return_value = _resp(SEARCH_HTML)
    mock_session_cls.return_value = session

    listings = WgzimmerPortal().fetch_listings({"state": "zurich", "max_price": 1200})

    assert [l.id for l in listings] == ["aaa-111", "bbb-222"]
    # solver called with the site key + action extracted from the form
    site_key, _page_url, action = solver.solve_recaptcha_v3.call_args.args
    assert site_key == "TESTKEY123"
    assert action == "//form///wgzimmer/search/mate/submitForm"
    # token injected into the POST body
    posted = session.post.call_args.kwargs["data"]
    assert posted["g-recaptcha-response"] == "TOKEN"
    assert posted["wgState"] == "zurich"


@patch("src.portals.wgzimmer.requests.Session")
@patch("src.portals.wgzimmer.build_solver_from_env")
def test_fetch_listings_handles_403(mock_build, mock_session_cls):
    solver = MagicMock()
    solver.solve_recaptcha_v3.return_value = "TOKEN"
    mock_build.return_value = solver
    session = MagicMock()
    session.get.return_value = _resp(FORM_HTML)
    session.post.return_value = _resp("<html>403</html>", status=403)
    mock_session_cls.return_value = session

    assert WgzimmerPortal().fetch_listings({"state": "zurich"}) == []


# ── fetch_details ─────────────────────────────────────────────────────────────

@patch("src.portals.wgzimmer._get_with_retry")
def test_fetch_details_parses_content(mock_get):
    mock_get.return_value = _resp(DETAIL_HTML)
    detail = WgzimmerPortal().fetch_details(Listing(id="aaa-111", title="", price="", location="",
                                                    url=f"{SITE}/de/objekt/aaa-111.html"))
    assert "18 m²" in detail.description
    assert "2er WG" in detail.description
    assert "CHF 900" in detail.attributes["Kosten / Dauer"]
    assert "8050 Zürich" in detail.attributes["Adresse / Region"]
