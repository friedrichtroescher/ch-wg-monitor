"""Portal registry and resolution."""
from .base import Portal
from .flatfox import FlatfoxPortal
from .kleinanzeigen import KleinanzeigenPortal
from .wgzimmer import WgzimmerPortal

_PORTALS: dict[str, Portal] = {
    p.name: p for p in (FlatfoxPortal(), KleinanzeigenPortal(), WgzimmerPortal())
}


def get_portal(name: str) -> Portal:
    portal = _PORTALS.get(name)
    if portal is None:
        raise ValueError(f"Unknown portal {name!r}. Known portals: {', '.join(sorted(_PORTALS))}")
    return portal


def resolve_portal(search: dict) -> Portal:
    """Pick the portal for a search: explicit ``portal`` key wins, else infer from the URL host."""
    name = search.get("portal")
    if not name:
        url = search.get("url", "")
        if "flatfox" in url:
            name = "flatfox"
        elif "wgzimmer" in url:
            name = "wgzimmer"
        else:
            name = "kleinanzeigen"
    return get_portal(name)
