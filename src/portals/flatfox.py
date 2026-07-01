"""Flatfox (flatfox.ch) adapter.

The public-listing LIST endpoint ignores category/geo query params, but the map-pin endpoint
`/api/v1/pin/` IS server-side filtered by bounding box + object_category and returns the
matching listing pks. So we do what the website does:

  1. GET /api/v1/pin/?<box>&object_category=SHARED&max_count=N  → pins (pk + coords + price)
  2. GET /api/v1/public-listing/?pk=..&pk=..&limit=0             → full listing objects (batched)

LIVE-VERIFIED (2026-07): exact box results, no pagination/scanning, no captcha, no key.

Config: a [[searches]] block's ``url`` is the Flatfox frontend search URL
(``https://flatfox.ch/de/suche/?object_category=SHARED&north=..&south=..&east=..&west=..``);
its object_category + north/south/east/west bounds are used. Optional ``max_count`` (default
400) caps the number of pins returned per box.
"""
import logging
from typing import Optional
from urllib.parse import urlsplit, parse_qsl, urlencode

from .base import Portal
from ..fetcher import _get_with_retry
from ..models.listing import Listing
from ..models.listingDetail import ListingDetail

log = logging.getLogger(__name__)

SITE = "https://flatfox.ch"
API_PIN = f"{SITE}/api/v1/pin/"
API_LIST = f"{SITE}/api/v1/public-listing/"
DEFAULT_CATEGORY = "SHARED"
DEFAULT_MAX_COUNT = 400
PK_CHUNK = 50  # pks per detail request (keeps the URL a sane length)

# Fallback box (roughly Switzerland) when the search URL carries no bounds.
CH_BOX = {"north": 47.9, "south": 45.8, "east": 10.6, "west": 5.9}

DETAIL_ATTRS = ("object_type", "number_of_rooms", "livingspace", "floor", "is_furnished",
                "year_built", "available_from")


class FlatfoxPortal(Portal):
    name = "flatfox"

    def fetch_listings(self, search: dict, retries: int = 2, search_name: str = "") -> list[Listing]:
        bounds, category = self._parse_filters(search.get("url", ""))
        max_count = int(search.get("max_count", DEFAULT_MAX_COUNT))

        pins = self._get_pins(bounds or CH_BOX, category, max_count, retries, search_name)
        pks = [p["pk"] for p in pins if isinstance(p, dict) and p.get("pk") is not None]
        if not pks:
            return []

        items = []
        for i in range(0, len(pks), PK_CHUNK):
            items.extend(self._get_by_pks(pks[i:i + PK_CHUNK], retries, search_name))

        listings = [l for l in (self._to_listing(it) for it in items) if l]
        listings.sort(key=lambda l: int(l.id) if l.id.isdigit() else 0, reverse=True)  # newest first
        return listings

    def fetch_details(self, listing: Listing, retries: int = 2, search_name: str = "") -> ListingDetail:
        resp = _get_with_retry(f"{API_LIST}{listing.id}/", retries, search_name=search_name)
        if resp is None:
            return ListingDetail()
        try:
            item = resp.json()
        except ValueError as e:
            log.warning("Flatfox: invalid detail JSON for %s: %s", listing.id, e)
            return ListingDetail()
        description = (item.get("description") or "").strip()
        attributes = {k: str(item[k]) for k in DETAIL_ATTRS if item.get(k) not in (None, "")}
        return ListingDetail(description=description, attributes=attributes)

    # ── fetching ──────────────────────────────────────────────────────────────

    def _get_pins(self, bounds: dict, category: str, max_count: int, retries: int, search_name: str) -> list[dict]:
        query = urlencode({**{k: bounds[k] for k in ("north", "south", "east", "west")},
                           "object_category": category, "max_count": max_count})
        return self._get_json_list(f"{API_PIN}?{query}", retries, search_name)

    def _get_by_pks(self, pks: list, retries: int, search_name: str) -> list[dict]:
        query = "&".join(f"pk={pk}" for pk in pks) + "&limit=0"
        return self._get_json_list(f"{API_LIST}?{query}", retries, search_name)

    @staticmethod
    def _get_json_list(url: str, retries: int, search_name: str) -> list[dict]:
        resp = _get_with_retry(url, retries, search_name=search_name)
        if resp is None:
            return []
        try:
            data = resp.json()
        except ValueError as e:
            log.warning("Flatfox: invalid JSON from %s: %s", url, e)
            return []
        return data if isinstance(data, list) else (data.get("results") or [])

    # ── parsing / mapping ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_filters(url: str) -> tuple[Optional[dict], str]:
        params = dict(parse_qsl(urlsplit(url).query))
        category = params.get("object_category", DEFAULT_CATEGORY)
        try:
            bounds = {k: float(params[k]) for k in ("north", "south", "east", "west")}
        except (KeyError, ValueError):
            bounds = None
        return bounds, category

    def _to_listing(self, item: dict) -> Optional[Listing]:
        pk = item.get("pk") or item.get("id")
        if pk is None:
            return None
        url = item.get("url") or item.get("short_url") or ""
        if url.startswith("/"):
            url = SITE + url
        city = item.get("city") or ""
        zipcode = item.get("zipcode")
        location = " ".join(str(p) for p in (zipcode, city) if p) or "Location unknown"
        title = (item.get("public_title") or item.get("title")
                 or self._compose_title(item.get("number_of_rooms"), item.get("livingspace"), city))
        return Listing(id=str(pk), title=title, price=self._format_price(item), location=location, url=url)

    @staticmethod
    def _compose_title(rooms, livingspace, city: str) -> str:
        parts = ["WG-Zimmer"]
        if rooms:
            parts.append(f"{rooms} Zi.")
        if livingspace:
            parts.append(f"{livingspace} m²")
        title = ", ".join(parts)
        return f"{title} in {city}" if city else title

    @staticmethod
    def _format_price(item: dict) -> str:
        for key in ("price_display", "rent_gross", "rent_net"):
            value = item.get(key)
            if value not in (None, ""):
                return f"CHF {value}"
        return "Price unknown"
