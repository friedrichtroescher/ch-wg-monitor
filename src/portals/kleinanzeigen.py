"""Kleinanzeigen adapter — wraps the original HTML fetcher (kept as a reference portal)."""
from .base import Portal
from ..fetcher import fetch_listings, fetch_listing_details
from ..models.listing import Listing
from ..models.listingDetail import ListingDetail


class KleinanzeigenPortal(Portal):
    name = "kleinanzeigen"

    def fetch_listings(self, search: dict, retries: int = 2, search_name: str = "") -> list[Listing]:
        return fetch_listings(search["url"], retries=retries, search_name=search_name)

    def fetch_details(self, listing: Listing, retries: int = 2, search_name: str = "") -> ListingDetail:
        return fetch_listing_details(listing.url, retries=retries, search_name=search_name)
