"""Portal adapter interface.

Each supported site (Kleinanzeigen, Flatfox, wgzimmer, ...) implements this so the
monitor loop and evaluator stay portal-agnostic. Site-specific URL handling, request
methods (GET/POST/JSON API) and result parsing live entirely inside an adapter.
"""
from abc import ABC, abstractmethod

from ..models.listing import Listing
from ..models.listingDetail import ListingDetail


class Portal(ABC):
    name: str = ""

    @abstractmethod
    def fetch_listings(self, search: dict, retries: int = 2, search_name: str = "") -> list[Listing]:
        """Fetch the current listings for a single [[searches]] config block."""

    def fetch_details(self, listing: Listing, retries: int = 2, search_name: str = "") -> ListingDetail:
        """Fetch a listing's detail page (used by deep_eval).

        Default: no extra detail — the overview already carries everything. Portals whose
        overview lacks a description (e.g. wgzimmer) override this.
        """
        return ListingDetail()
