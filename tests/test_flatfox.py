"""Tests for the Flatfox portal adapter (newest-scan + client-side filtering)."""
from unittest.mock import MagicMock, patch

from src.portals import resolve_portal
from src.portals.flatfox import FlatfoxPortal, API_LIST

# lat/lng inside the Rapperswil box used in tests below
SHARED_RAPPI = {"pk": 51159, "url": "/de/flat/8640-rapperswil/51159/", "object_category": "SHARED",
                "number_of_rooms": "1.0", "livingspace": 15, "city": "Rapperswil SG", "zipcode": 8640,
                "price_display": 850, "latitude": 47.22, "longitude": 8.82}
APARTMENT_RAPPI = {"pk": 51160, "url": "/de/flat/x/51160/", "object_category": "APARTMENT",
                   "city": "Rapperswil SG", "zipcode": 8640, "price_display": 2000,
                   "latitude": 47.22, "longitude": 8.82}
SHARED_ZURICH = {"pk": 51161, "url": "/de/flat/x/51161/", "object_category": "SHARED",
                 "city": "Zürich", "zipcode": 8001, "price_display": 900,
                 "latitude": 47.37, "longitude": 8.54}  # outside the box

BOX_URL = ("https://flatfox.ch/de/suche/?object_category=SHARED"
           "&north=47.235732&south=47.207887&east=8.883600&west=8.767098")


def _json(payload) -> MagicMock:
    r = MagicMock()
    r.json.return_value = payload
    return r


# ── resolution & pure filters ──────────────────────────────────────────────────

def test_resolve_portal_from_url():
    assert resolve_portal({"url": "https://flatfox.ch/de/suche/?object_category=SHARED"}).name == "flatfox"


def test_parse_filters_reads_box_and_category():
    bounds, category = FlatfoxPortal._parse_filters(BOX_URL)
    assert category == "SHARED"
    assert bounds == {"north": 47.235732, "south": 47.207887, "east": 8.883600, "west": 8.767098}


def test_parse_filters_defaults_without_geo():
    bounds, category = FlatfoxPortal._parse_filters("https://flatfox.ch/de/suche/")
    assert bounds is None
    assert category == "SHARED"


def test_in_bounds():
    box = {"north": 47.235732, "south": 47.207887, "east": 8.883600, "west": 8.767098}
    assert FlatfoxPortal._in_bounds(SHARED_RAPPI, box) is True
    assert FlatfoxPortal._in_bounds(SHARED_ZURICH, box) is False
    assert FlatfoxPortal._in_bounds({"latitude": None, "longitude": None}, box) is False
    assert FlatfoxPortal._in_bounds(SHARED_ZURICH, None) is True  # no box → pass


# ── fetch_listings ──────────────────────────────────────────────────────────────

@patch("src.portals.flatfox._get_with_retry")
def test_fetch_listings_filters_category_and_geo(mock_get):
    # first call = count, second = the tail page (oldest-first order in the page)
    mock_get.side_effect = [
        _json({"count": 3, "results": [{}]}),
        _json({"count": 3, "results": [SHARED_ZURICH, APARTMENT_RAPPI, SHARED_RAPPI]}),
    ]

    listings = FlatfoxPortal().fetch_listings({"url": BOX_URL})

    # only the SHARED listing inside the box survives
    assert len(listings) == 1
    l = listings[0]
    assert l.id == "51159"
    assert l.price == "CHF 850"
    assert l.location == "8640 Rapperswil SG"
    assert l.url == "https://flatfox.ch/de/flat/8640-rapperswil/51159/"


@patch("src.portals.flatfox._get_with_retry")
def test_fetch_listings_newest_first(mock_get):
    # no geo box, category SHARED → both shared kept, newest (page tail) first
    a = {**SHARED_ZURICH, "pk": 1}
    b = {**SHARED_ZURICH, "pk": 2}
    mock_get.side_effect = [
        _json({"count": 2, "results": [{}]}),
        _json({"count": 2, "results": [a, b]}),  # ascending → b is newest
    ]
    listings = FlatfoxPortal().fetch_listings({"url": "https://flatfox.ch/de/suche/?object_category=SHARED"})
    assert [l.id for l in listings] == ["2", "1"]


@patch("src.portals.flatfox._get_with_retry")
def test_fetch_listings_handles_count_failure(mock_get):
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
