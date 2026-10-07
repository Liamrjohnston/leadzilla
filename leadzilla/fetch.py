"""Polite fetching on top of Scrapling (github.com/D4Vinci/Scrapling, BSD-3).

Defaults: obey robots.txt, one request per domain per `delay` seconds, no fake
search-engine referer, no anti-bot bypass. A site that blocks us is skipped,
not attacked. `browser=True` retries JavaScript-only pages in a real browser.
"""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from urllib.parse import urlparse

from scrapling.fetchers import Fetcher

UA_NOTE = "LEADZILLA (+https://github.com/Liamrjohnston/leadzilla)"


class Politeness:
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def wait(self, host: str):
        with self._lock:
            now = time.time()
            nxt = max(now, self._last.get(host, 0) + self.delay)
            self._last[host] = nxt
        if nxt > now:
            time.sleep(nxt - now)

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        host = p.netloc
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = Fetcher.get(f"{p.scheme}://{host}/robots.txt", impersonate="chrome",
                                stealthy_headers=False, timeout=10)
                if r.status in (401, 403):
                    rp.disallow_all = True
                elif r.status >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(r.body.decode("utf-8", "ignore").splitlines() if isinstance(r.body, bytes)
                             else str(r.body).splitlines())
            except Exception:
                rp = None  # robots unreachable: treat the site as unreachable
            self._robots[host] = rp
        rp = self._robots[host]
        return bool(rp) and rp.can_fetch("*", url)


def _text(resp) -> str:
    try:
        return resp.html_content
    except Exception:
        b = resp.body
        return b.decode("utf-8", "ignore") if isinstance(b, bytes) else str(b)


def get(url: str, polite: Politeness, browser: bool = False, timeout: int = 15) -> dict:
    """Fetch one URL. Returns {ok, status, html, reason, seconds, via}."""
    t0 = time.time()
    if not polite.allowed(url):
        return {"ok": False, "status": None, "html": "", "reason": "robots.txt disallows or unreachable",
                "seconds": 0.0, "via": None}
    polite.wait(urlparse(url).netloc)
    try:
        r = Fetcher.get(url, impersonate="chrome", stealthy_headers=False, timeout=timeout,
                        follow_redirects=True)
        html, status, via = _text(r), r.status, "http"
        final = str(getattr(r, "url", "") or url)
    except Exception as e:
        return {"ok": False, "status": None, "html": "", "reason": f"fetch error: {type(e).__name__}",
                "seconds": time.time() - t0, "via": "http"}
    if browser and status == 200 and len(" ".join(html.split())) < 1500:
        try:
            from scrapling.fetchers import DynamicFetcher
            r = DynamicFetcher.fetch(url, headless=True, network_idle=True, timeout=timeout * 1000)
            html, status, via = _text(r), r.status, "browser"
        except Exception:
            pass
    ok = status == 200 and bool(html)
    return {"ok": ok, "status": status, "html": html if ok else "", "final_url": final,
            "reason": "" if ok else f"HTTP {status}", "seconds": time.time() - t0, "via": via}
