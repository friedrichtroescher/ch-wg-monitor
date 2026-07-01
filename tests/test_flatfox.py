"""Tests for the Flatfox portal adapter (pin search + batch detail fetch)."""
from unittest.mock import MagicMock, patch

from src.portals import resolve_portal
from src.portals.flatfox import FlatfoxPortal

BOX_URL = ("https://flatfox.ch/de/suche/?object_category=SHARED"
           "&north=47.32&south=47.13&east=8.95&west=8.68")

PINS = [{"pk": 86149701, "latitude": 47.23, "longitude": 8.83, "price_display": 990},
        {"pk": 86149697, "latitude": 47.23, "longitude": 8.83, "price_display": 1190}]

DETAILS = [
    {"pk": 86149701, "url": "/de/flat/8645-jona/86149701/", "city": "Jona", "zipcode": 8645,
     "price_display": 990, "public_title": "8645 Jona - CHF 990"},
    {"pk": 86149697, "url": "/de/flat/8645-jona/86149697/", "city": "Jona", "zipcode": 8645,
     "price_display": 1190, "public_title": "8645 Jona - CHF 1190"},
]


def _json(payload) -> MagicMock:
    r = MagicMock()
    r.json.return_value = payload
    return r


# ── resolution & parsing ───────────────────────────────────────────────────────

def test_resolve_portal_from_url():
    assert resolve_portal({"url": "https://flatfox.ch/de/suche/?object_category=SHARED"}).name == "flatfox"


def test_parse_filters_reads_box_and_category():
    bounds, category = FlatfoxPortal._parse_filters(BOX_URL)
    assert category == "SHARED"
    assert bounds == {"north": 47.32, "south": 47.13, "east": 8.95, "west": 8.68}


def test_parse_filters_defaults_without_geo():
    bounds, category = FlatfoxPortal._parse_filters("https://flatfox.ch/de/suche/")
    assert bounds is None
    assert category == "SHARED"


# ── fetch_listings: pin → by-pk ─────────────────────────────────────────────────

@patch("src.portals.flatfox._get_with_retry")
def test_fetch_listings_pin_then_details(mock_get):
    # 1st call = pin endpoint, 2nd = public-listing?pk=..
    mock_get.side_effect = [_json(PINS), _json(DETAILS)]

    listings = FlatfoxPortal().fetch_listings({"url": BOX_URL})

    # pin endpoint was queried with the box + category
    pin_url = mock_get.call_args_list[0].args[0]
    assert pin_url.startswith("https://flatfox.ch/api/v1/pin/?")
    assert "object_category=SHARED" in pin_url and "north=47.32" in pin_url
    # detail endpoint fetched by the pins' pks
    detail_url = mock_get.call_args_list[1].args[0]
    assert "pk=86149701" in detail_url and "pk=86149697" in detail_url

    # mapped + sorted newest (highest pk) first
    assert [l.id for l in listings] == ["86149701", "86149697"]
    assert listings[0].price == "CHF 990"
    assert listings[0].location == "8645 Jona"
    assert listings[0].url == "https://flatfox.ch/de/flat/8645-jona/86149701/"


@patch("src.portals.flatfox._get_with_retry")
def test_fetch_listings_empty_pins(mock_get):
    mock_get.return_value = _json([])
    assert FlatfoxPortal().fetch_listings({"url": BOX_URL}) == []


@patch("src.portals.flatfox._get_with_retry")
def test_fetch_listings_pin_fetch_fails(mock_get):
    mock_get.return_value = None
    assert FlatfoxPortal().fetch_listings({"url": BOX_URL}) == []


# ── fetch_details ─────────────────────────────────────────────────────────────

@patch("src.portals.flatfox._get_with_retry")
def test_fetch_details_extracts_description_and_attrs(mock_get):
    from src.models.listing import Listing
    mock_get.return_value = _json({
        "description": "Schönes Zimmer in netter WG.",
        "number_of_rooms": "1.0", "livingspace": 15, "is_furnished": True,
    })
    detail = FlatfoxPortal().fetch_details(Listing(id="51159", title="", price="", location="", url=""))
    assert detail.description == "Schönes Zimmer in netter WG."
    assert detail.attributes["livingspace"] == "15"
    assert detail.attributes["is_furnished"] == "True"
