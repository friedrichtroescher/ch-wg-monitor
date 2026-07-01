"""Flatfox (flatfox.ch) adapter.

Flatfox exposes a public JSON API. Its list endpoint /api/v1/public-listing/ does NOT accept
the frontend's category/geo/ordering filters as query params (they are silently ignored;
only offset/limit work, and results come back ordered by pk ASCENDING = oldest first).

So instead of server-side filtering we scan the NEWEST listings and filter client-side:
  1. GET ?limit=1  → read total `count`.
  2. Page the tail: GET ?offset=count-SCAN&limit=100 (…) → the newest SCAN listings.
  3. Keep only those matching object_category and the configured lat/lng bounding box.

This needs no secret params and no captcha. LIVE-VERIFIED (2026-07): high offset returns the
freshest listings (pk ~86M, today's `published`), each carrying latitude/longitude/
object_category, so client-side geo+category filtering is exact.

Config: a [[searches]] block's ``url`` is the Flatfox frontend search URL
(``https://flatfox.ch/de/suche/?object_category=SHARED&north=..&south=..&east=..&west=..``);
its object_category + north/south/east/west params are read as the filter. Optional
``scan_newest`` (default 300) bounds how many of the newest listings are scanned per run.
"""
import logging
from typing import Optional
from urllib.parse import urlsplit, parse_qsl

from .base import Portal
from ..fetcher import _get_with_retry
from ..models.listing import Listing
from ..models.listingDetail import ListingDetail

log = logging.getLogger(__name__)

SITE = "https://flatfox.ch"
API_LIST = f"{SITE}/api/v1/public-listing/"
PAGE_SIZE = 100          # server caps a page at ~100
DEFAULT_SCAN = 300       # newest listings scanned per run (dedup handles the rest)
DEFAULT_CATEGORY = "SHARED"

DETAIL_ATTRS = ("object_type", "number_of_rooms", "livingspace", "floor", "is_furnished",
                "year_built", "available_from")


class FlatfoxPortal(Portal):
    name = "flatfox"

    def fetch_listings(self, search: dict, retries: int = 2, search_name: str = "") -> list[Listing]:
        bounds, category = self._parse_filters(search.get("url", ""))
        scan = int(search.get("scan_newest", DEFAULT_SCAN))

        count = self._get_count(retries, search_name)
        if count is None:
            return []

        raw = []
        offset = max(0, count - scan)
        while offset < count:
            page = self._get_page(offset, retries, search_name)
            if not page:
                break
            raw.extend(page)
            offset += PAGE_SIZE

        listings = []
        for item in reversed(raw):  # tail is oldest-first → reverse to newest-first
            if category and item.get("object_category") != category:
                continue
            if not self._in_bounds(item, bounds):
                continue
            listing = self._to_listing(item)
            if listing:
                listings.append(listing)
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

    def _get_count(self, retries: int, search_name: str) -> Optional[int]:
        resp = _get_with_retry(f"{API_LIST}?limit=1", retries, search_name=search_name)
        if resp is None:
            return None
        try:
            return resp.json().get("count")
        except ValueError as e:
            log.warning("Flatfox: invalid count JSON: %s", e)
            return None

    def _get_page(self, offset: int, retries: int, search_name: str) -> list[dict]:
        resp = _get_with_retry(f"{API_LIST}?limit={PAGE_SIZE}&offset={offset}", retries, search_name=search_name)
        if resp is None:
            return []
        try:
            return resp.json().get("results") or []
        except ValueError as e:
            log.warning("Flatfox: invalid page JSON at offset %d: %s", offset, e)
            return []

    # ── filtering ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_filters(url: str) -> tuple[Optional[dict], str]:
        params = dict(parse_qsl(urlsplit(url).query))
        category = params.get("object_category", DEFAULT_CATEGORY)
        try:
            bounds = {k: float(params[k]) for k in ("north", "south", "east", "west")}
        except (KeyError, ValueError):
            bounds = None  # no/invalid geo box → no geo filter
        return bounds, category

    @staticmethod
    def _in_bounds(item: dict, bounds: Optional[dict]) -> bool:
        if bounds is None:
            return True
        lat, lng = item.get("latitude"), item.get("longitude")
        if lat is None or lng is None:
            return False
        return (bounds["south"] <= lat <= bounds["north"]
                and bounds["west"] <= lng <= bounds["east"])

    # ── mapping ───────────────────────────────────────────────────────────────

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
