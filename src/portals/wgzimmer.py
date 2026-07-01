"""wgzimmer.ch adapter.

wgzimmer has no JSON API and a POST-only search form protected by reCAPTCHA v3. The search
results page yields only links to detail pages; title, rent and address live on the detail
page. So this portal keeps the overview cheap (one solved POST → list of detail URLs) and
relies on deep_eval to fetch each new listing's detail page.

Config ([[searches]] block):
    portal    = "wgzimmer"
    state     = "zurich"     # canton/region slug (form field wgState)
    max_price = 1200         # → priceMax
    permanent = true         # unbefristet only (default true)
    deep_eval = true         # REQUIRED — the overview has no description/rent

LIVE-VERIFIED (2026-07) — reCAPTCHA v3, results DON'T render for solved tokens:
  The search POST is gated by reCAPTCHA v3 (site key + action below). With a 2Captcha-solved
  token the POST is ACCEPTED (HTTP 200, our criteria are echoed back in the form) — but the
  results list stays EMPTY, even requesting min_score=0.9 and sending the full form (query,
  permanent, student, typeofwg, priceMin/priceMax as <select> values, wgState=<canton slug>).
  submitForm() does a plain form .submit() (no AJAX endpoint found), so results should render
  server-side; they don't → wgzimmer almost certainly gates rendering on the v3 SCORE, which
  datacenter solving services can't reliably reach. Getting results needs a real headless
  browser (Playwright) to earn a passing v3 score — out of scope for this requests-based cron.
  ⇒ This adapter + the captcha package are correct and reusable, but wgzimmer returns nothing
  in production for now. Prefer Flatfox (works, no captcha). Detail selectors below are
  unverified (search never yielded results). The canton slug for Rapperswil is "rapperswil-jona".
"""
import logging
import re

import requests
from bs4 import BeautifulSoup

from .base import Portal
from ..captcha import build_solver_from_env, CaptchaError
from ..fetcher import BROWSER_HEADERS, _get_with_retry
from ..models.listing import Listing
from ..models.listingDetail import ListingDetail
from ..telemetry import scrape_rejections

log = logging.getLogger(__name__)

SITE = "https://www.wgzimmer.ch"
SEARCH_URL = f"{SITE}/wgzimmer/search/mate.html"

# Fallbacks if extraction from the live form fails (verified 2026-07).
SITEKEY_FALLBACK = "6LfkCbEUAAAAAHBeOgdzn-MpmM6MRzBFlj5sPzxu"
ACTION_FALLBACK = "//form///wgzimmer/search/mate/submitForm"


class WgzimmerPortal(Portal):
    name = "wgzimmer"

    def fetch_listings(self, search: dict, retries: int = 2, search_name: str = "") -> list[Listing]:
        solver = build_solver_from_env()
        if solver is None:
            log.warning("wgzimmer requires a captcha solver (set CAPTCHA_API_KEY) — skipping %r", search_name)
            return []

        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)

        # 1. Load the form (sets the session cookie, carries the current site key + action).
        try:
            form_resp = session.get(SEARCH_URL, timeout=15)
            form_resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("wgzimmer: failed to load search form: %s", e)
            return []
        site_key, action = self._extract_recaptcha(form_resp.text)

        # 2. Solve reCAPTCHA v3.
        try:
            token = solver.solve_recaptcha_v3(site_key, SEARCH_URL, action)
        except CaptchaError as e:
            log.warning("wgzimmer: captcha solving failed: %s", e)
            return []

        # 3. POST the search with the token.
        data = self._form(search)
        data["g-recaptcha-response"] = token
        try:
            resp = session.post(SEARCH_URL, data=data,
                                headers={"Referer": SEARCH_URL, "Origin": SITE}, timeout=15)
            if resp.status_code in (403, 429):
                scrape_rejections.add(1, {"http.status_code": resp.status_code, "search.name": search_name})
                log.warning("wgzimmer: search POST rejected (%d) — captcha score too low?", resp.status_code)
                return []
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("wgzimmer: search POST failed: %s", e)
            return []

        return self._parse_results(resp.text)

    def fetch_details(self, listing: Listing, retries: int = 2, search_name: str = "") -> ListingDetail:
        resp = _get_with_retry(listing.url, retries, search_name=search_name)
        if resp is None:
            return ListingDetail()
        try:
            soup = BeautifulSoup(resp.text, "lxml")
            description = "\n\n".join(
                self._text(soup, sel) for sel in (".room-content", ".mate-content", ".person-content")
                if self._text(soup, sel)
            )
            attributes: dict[str, str] = {}
            cost = self._text(soup, ".date-cost")
            if cost:
                attributes["Kosten / Dauer"] = cost
            address = self._text(soup, ".adress-region")
            if address:
                attributes["Adresse / Region"] = address
            return ListingDetail(description=description, attributes=attributes)
        except Exception as e:
            log.warning("Error parsing wgzimmer detail %s: %s", listing.url, e)
            return ListingDetail()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _parse_results(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        listings = []
        seen_urls = set()
        for li in soup.select("#content ul li"):
            anchors = li.select("a[href]")
            if not anchors:
                continue
            href = anchors[-1]["href"]  # the text link (a[2]); last anchor on a result item
            url = SITE + href if href.startswith("/") else href
            if url in seen_urls or SEARCH_URL in url:
                continue
            seen_urls.add(url)
            title = " ".join(li.get_text(" ", strip=True).split()) or "WG-Zimmer"
            listings.append(Listing(
                id=self._id_from_url(url),
                title=title[:120],
                price="Price unknown",  # only on the detail page → filled via deep_eval
                location="",
                url=url,
            ))
        return listings

    @staticmethod
    def _extract_recaptcha(html: str) -> tuple[str, str]:
        key_m = re.search(r"recaptcha/api\.js\?render=([\w-]+)", html)
        act_m = re.search(r"grecaptcha\.execute\([^,]+,\s*\{action:\s*'([^']+)'", html)
        return (key_m.group(1) if key_m else SITEKEY_FALLBACK,
                act_m.group(1) if act_m else ACTION_FALLBACK)

    @staticmethod
    def _form(search: dict) -> dict:
        # Field names live-verified against the real searchMateForm.
        max_price = search.get("max_price")
        return {
            "query": search.get("query", ""),
            "priceMin": str(search.get("min_price", "")),
            "priceMax": str(max_price) if max_price is not None else "",
            "wgState": search.get("state", search.get("canton", "")),  # canton/region slug
            "permanent": "true" if search.get("permanent", True) else "false",
            "bypass-csrf": "true",
            "startSearch": "true",
            "orderBy": "MetaData/@mgnl:lastmodified",  # newest first
        }

    @staticmethod
    def _id_from_url(url: str) -> str:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return slug[:-5] if slug.endswith(".html") else slug

    @staticmethod
    def _text(soup: BeautifulSoup, selector: str) -> str:
        el = soup.select_one(selector)
        return el.get_text(" ", strip=True) if el else ""
