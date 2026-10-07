"""Free discovery: DuckDuckGo results via the `ddgs` package, no API key."""
from __future__ import annotations

import time

from ddgs import DDGS

from .extract import domain_of

# Sites that are never one small business's own website.
SKIP = ("google.", "bing.com", "yahoo.", "yandex.", "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "tiktok.com", "x.com",
        "twitter.com", "yelp.", "yellowpages.", "wikipedia.org", "reddit.com", "tripadvisor.", "bbb.org",
        "indeed.", "glassdoor.", "zillow.com", "realtor.ca", "realtor.com", "rew.ca", "zolo.ca",
        "craigslist.", "kijiji.", "amazon.", "apple.com", "bing.com", "duckduckgo.com", "mapquest.com",
        "pinterest.", "quora.com", "medium.com")

BACKENDS = ("bing", "yahoo", "yandex", "auto")

TEMPLATES = ("{niche} {place}", "best {niche} in {place}", "{niche} {place} contact us",
             "independent {niche} {place}", "{niche} {place} our team", "top {niche} {place} list",
             "boutique {niche} {place}", "{niche} near {place} email")


def skippable(domain: str) -> bool:
    return any(s in domain for s in SKIP)


def search(niche: str, place: str, per_query: int = 25, pause: float = 2.0,
           extra_queries: list[str] | None = None) -> list[dict]:
    queries = [t.format(niche=niche, place=place) for t in TEMPLATES] + list(extra_queries or [])
    seen, out = set(), []
    with DDGS() as d:
        for q in queries:
            rows = []
            for backend in BACKENDS:
                try:
                    rows = d.text(q, max_results=per_query, backend=backend) or []
                except Exception:
                    rows = []
                if rows:
                    break
            for r in rows:
                url = r.get("href") or r.get("url") or ""
                dom = domain_of(url)
                if not dom or url in seen:
                    continue
                seen.add(url)
                out.append({"url": url, "domain": dom, "title": r.get("title", ""), "snippet": r.get("body", ""),
                            "query": q, "skip": skippable(dom)})
            time.sleep(pause)
    return out


def lookup(name: str, place: str, n: int = 6) -> list[dict]:
    """Results for one business name, for finding its website. Tries several free engines."""
    q = f"{name} {place.split(',')[0]}"
    with DDGS() as d:
        for backend in BACKENDS:
            try:
                rows = d.text(q, max_results=10, backend=backend) or []
            except Exception:
                rows = []
            out, seen = [], set()
            for r in rows:
                url = r.get("href") or ""
                dom = domain_of(url)
                if dom and not skippable(dom) and dom not in seen:
                    seen.add(dom)
                    out.append({"url": url, "domain": dom, "title": r.get("title", ""), "snippet": r.get("body", "")})
            if out:
                return out[:n]
    return []


def linkedin_pages(company: str, place: str) -> list[dict]:
    """Public search results for the company's LinkedIn page. LinkedIn itself is never fetched."""
    q = f"{company} {place.split(',')[0]} site:linkedin.com/company"
    with DDGS() as d:
        for backend in BACKENDS:
            try:
                rows = d.text(q, max_results=8, backend=backend) or []
            except Exception:
                rows = []
            hits = [{"url": (r.get("href") or "").split("?")[0], "title": r.get("title", ""),
                     "snippet": r.get("body", "")} for r in rows
                    if "linkedin.com/company/" in (r.get("href") or "")]
            if hits:
                return hits[:4]
    return []
