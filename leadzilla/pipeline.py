"""The LEADZILLA run: search -> triage -> crawl -> extract -> judge -> verify -> keep.

Only judgements go to Jev. Fetching, parsing, deduping, counting and the email
check are plain code. The run stops once it has `target` new leads, and a
re-run of the same campaign continues where the last one stopped.
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import time

from . import fetch as F
from . import osm
from . import qualify as Q
from .extract import contact_links, domain_of, external_sites, extract, phone_from_any
from .jev import Jev
from .search import linkedin_pages, lookup, search, skippable
from .store import Store
from .verify import check

# For the cost comparison only: what reading every fetched page with a big model
# would cost, the way per-page LLM scrapers work (whole page text in, JSON out).
# Anthropic list prices per million tokens; update if they change.
CLAUDE_PRICES = {"sonnet": (2.00, 10.00), "haiku": (1.00, 5.00), "opus": (5.00, 25.00)}
PROMPT_TOKENS, OUTPUT_TOKENS, CHARS_PER_TOKEN = 300, 250, 4


def _company(page: dict) -> str:
    for j in page.get("jsonld", []):
        if j.get("name") and isinstance(j["name"], str):
            return j["name"].strip()
    t = re.split(r"\s[|\-–—:]\s", page.get("title", ""))
    return (t[0] if t else page.get("domain", "")).strip()[:120]


def _brand(url: str) -> str:
    """The name part of a domain: suttoncentrerealty.com and .ca are the same business."""
    parts = domain_of(url).split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net") and len(parts[-1]) == 2:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else domain_of(url)


def _names_from_email(email: str | None) -> tuple[str, str]:
    if not email:
        return "", ""
    local = email.split("@")[0]
    parts = re.split(r"[._-]", local)
    if len(parts) == 2 and all(p.isalpha() and len(p) > 1 for p in parts):
        return parts[0].title(), parts[1].title()
    return "", ""


class Run:
    def __init__(self, niche: str, place: str, offer: str, target: int, db: str, jev: Jev,
                 delay: float = 1.0, browser: bool = False, workers: int = 8, log=print,
                 use_search: bool = True, radius_km: float = 15.0):
        self.niche, self.place, self.offer, self.target = niche, place, offer, target
        self.store, self.jev, self.log = Store(db), jev, log
        self.cid = self.store.campaign(niche, place, offer)
        self.polite = F.Politeness(delay)
        self.browser, self.workers = browser, workers
        self.use_search, self.radius_km = use_search, radius_km
        self.stats = {"search_results": 0, "candidates": 0, "sites_checked": 0, "pages_fetched": 0,
                      "page_chars": 0, "kept": 0, "rejected": {}, "emails_found": 0}

    # -- helpers -------------------------------------------------------------
    def _fetch(self, url: str) -> dict | None:
        r = F.get(url, self.polite, browser=self.browser)
        if not r["ok"]:
            return None
        if _brand(r["final_url"]) != _brand(url):
            return {"redirected": domain_of(r["final_url"])}
        page = extract(r["html"], url)
        page["domain"] = domain_of(url)
        self.stats["pages_fetched"] += 1
        self.stats["page_chars"] += len(page["text"])
        return page

    def _reject(self, domain: str, why: str, source: str = ""):
        self.store.mark(self.cid, domain, "rejected", why, source)
        key = why.split(" (")[0]
        self.stats["rejected"][key] = self.stats["rejected"].get(key, 0) + 1

    # -- stages ----------------------------------------------------------------
    def discover_map(self) -> dict:
        tags = osm.pick_tags(self.jev, self.niche)
        self.stats["map_tags"] = tags
        if not tags:
            self.log("  OpenStreetMap: no matching business type for this niche")
            return {}
        box = osm.widen(osm.bbox(self.place), self.radius_km)
        found = osm.businesses(tags, box)
        sites = {}
        for b in found:
            if not b["website"]:
                continue
            url = b["website"] if b["website"].startswith("http") else "https://" + b["website"]
            d = domain_of(url)
            if d and not skippable(d) and d not in sites:
                sites[d] = {"domain": d, "url": url, "source": f"openstreetmap: {b['osm']}",
                            "map": {k: b[k] for k in ("name", "email", "phone", "address")}}
        self.stats["map_businesses"] = len(found)
        self.stats["map_with_website"] = len(sites)
        self.log(f"  OpenStreetMap ({', '.join(tags)}): {len(found)} businesses, {len(sites)} with a website")
        if self.use_search and len(sites) < self.target * 2:  # only hunt for websites when the map is short
            missing = [b for b in found if not b["website"]]
            names = {}
            for b in missing:
                names.setdefault(b["name"].strip().lower(), b)
            items = []
            with cf.ThreadPoolExecutor(2) as ex:
                for b, res in zip(names.values(), ex.map(lambda b: lookup(b["name"], self.place), names.values())):
                    items.append({**b, "results": res})
            matched = Q.match_websites(self.jev, items)
            added = 0
            for it in items:
                r = matched.get(it["name"])
                if r and r["domain"] not in sites:
                    url = f"https://{r['domain']}/"
                    sites[r["domain"]] = {"domain": r["domain"], "url": url,
                                          "source": f"openstreetmap + website match: {it['osm']}",
                                          "map": {k: it[k] for k in ("name", "email", "phone", "address")}}
                    added += 1
            self.stats["map_websites_matched"] = added
            self.log(f"  Jev matched websites for {added} of {len(items)} map businesses that had none listed")
        return sites

    def discover(self) -> list[dict]:
        self.log(f"Looking for {self.niche} in {self.place}...")
        sites = self.discover_map()
        if not self.use_search or len(sites) >= self.target * 2:
            cands = [s for s in sites.values() if not self.store.seen(self.cid, s["domain"])]
            self.stats["candidates"] = len(cands)
            return cands
        results = search(self.niche, self.place)
        self.stats["search_results"] = len(results)
        fresh = [r for r in results if not r["skip"]]
        kinds = Q.triage_results(self.jev, fresh, self.niche, self.place) if fresh else {}
        directories = []
        for r in fresh:
            kind, conf = kinds.get(r["url"], ("other", 0))
            if kind == "own_site" and r["domain"] not in sites:
                sites[r["domain"]] = {"domain": r["domain"], "url": f"https://{r['domain']}/", "source": "search"}
            elif kind == "directory":
                directories.append(r["url"])
        self.log(f"  {len(results)} results -> {len(sites)} business sites, {len(directories)} directories")
        with cf.ThreadPoolExecutor(self.workers) as ex:
            pages = [p for p in ex.map(self._fetch, directories[:15]) if p and "redirected" not in p]
        outbound = []
        for p in pages:
            for l in external_sites(p):
                if not skippable(l["domain"]) and l["domain"] not in sites:
                    l["source"] = f"directory: {p['url']}"
                    outbound.append(l)
        dedup = {l["domain"]: l for l in outbound}
        if dedup:
            probs = Q.triage_outbound(self.jev, list(dedup.values()), self.niche, self.place)
            for d, p in probs.items():
                if p >= 0.5 and d not in sites:
                    sites[d] = {"domain": d, "url": f"https://{d}/", "source": dedup[d]["source"]}
        self.log(f"  {len(sites)} sites in total after search and directories")
        cands = [s for s in sites.values() if not self.store.seen(self.cid, s["domain"])]
        self.stats["candidates"] = len(cands)
        return cands

    def crawl(self, batch: list[dict]) -> list[dict]:
        with cf.ThreadPoolExecutor(self.workers) as ex:
            homes = list(ex.map(lambda s: (s, self._fetch(s["url"])), batch))
        live = []
        for s, page in homes:
            self.stats["sites_checked"] += 1
            if page is None:
                self._reject(s["domain"], "site unreachable or robots.txt says no", s["source"])
            elif "redirected" in page:
                self._reject(s["domain"], f"redirects to another site ({page['redirected']})", s["source"])
            else:
                live.append((s, page))
        picks = Q.pick_contact_pages(self.jev, {s["domain"]: contact_links(p) for s, p in live})
        extra_urls = [(s["domain"], u) for s, _ in live for u in picks.get(s["domain"], [])]
        with cf.ThreadPoolExecutor(self.workers) as ex:
            extras = list(ex.map(lambda du: (du[0], self._fetch(du[1])), extra_urls))
        by_domain: dict[str, list[dict]] = {}
        for d, p in extras:
            if p and "redirected" not in p:
                by_domain.setdefault(d, []).append(p)
        # No email anywhere yet: try the usual contact paths once (robots.txt still applies).
        tried = {u for _, u in extra_urls}
        fallback = []
        for s, home in live:
            have = home["emails"] or any(p["emails"] for p in by_domain.get(s["domain"], []))
            if not have and not s.get("map", {}).get("email"):
                base = s["url"].split("/")[0] + "//" + s["url"].split("/")[2]
                fallback += [(s["domain"], base + path) for path in ("/contact", "/contact-us")
                             if base + path not in tried]
        with cf.ThreadPoolExecutor(self.workers) as ex:
            for d, p in ex.map(lambda du: (du[0], self._fetch(du[1])), fallback):
                if p and "redirected" not in p and p["emails"]:
                    by_domain.setdefault(d, []).append(p)
        leads = []
        for s, home in live:
            pages = [home] + by_domain.get(s["domain"], [])
            emails, phones, jsonld, socials, addr = [], [], [], {}, ""
            for p in pages:
                emails += p["emails"]; phones += p["phones"]; jsonld += p["jsonld"]
                socials = {**p["socials"], **socials}
            m = s.get("map", {})
            if m.get("email"):
                emails.insert(0, m["email"].lower())
            if m.get("phone") and phone_from_any(m["phone"]):
                phones.append(phone_from_any(m["phone"]))
            addr = m.get("address", "")
            for j in jsonld:
                addr = addr or j.get("address", "")
            emails = list(dict.fromkeys(emails))
            self.stats["emails_found"] += len(emails)
            excerpt = home["text"][:1200]
            for p in pages[1:]:
                excerpt += " ... " + p["text"][:500]
            leads.append({"domain": s["domain"], "website": s["url"], "source": s["source"], "on_map": bool(m),
                          "company": m.get("name") or _company(home), "page_title": home["title"],
                          "description": home["description"], "jsonld": jsonld[:3], "address": addr,
                          "emails": emails, "phones": list(dict.fromkeys(phones)), "socials": socials,
                          "excerpt": excerpt, "pages": [p["url"] for p in pages]})
        return leads

    def judge(self, leads: list[dict]) -> int:
        if not leads:
            return 0
        Q.judge_leads(self.jev, leads, self.niche, self.place, self.offer)
        kept = 0
        good = []
        for L in leads:
            L["niche_label"] = self.niche
            status, why = Q.keep(L)
            if status == "rejected":
                self._reject(L["domain"], why, L["source"])
                continue
            L["status"], L["status_note"] = status, why
            good.append(L)
        need = [L for L in good if not L["socials"].get("linkedin")]
        if need and self.use_search:
            with cf.ThreadPoolExecutor(4) as ex:
                res = list(ex.map(lambda L: linkedin_pages(L["company"], self.place), need))
            found = Q.match_linkedin(self.jev, [{"domain": L["domain"], "company": L["company"], "results": r}
                                                for L, r in zip(need, res)])
            for L in need:
                if L["domain"] in found:
                    L["socials"]["linkedin"] = found[L["domain"]]
                    self.stats["linkedin_matched"] = self.stats.get("linkedin_matched", 0) + 1
        for L in good:
            if L.get("email"):
                c = check(L["email"])
                L["email_status"], L["email_role"] = c["status"], c["role"]
                if c["status"] in ("invalid", "do_not_use", "domain_has_no_mail"):
                    L["email"] = None
            L["phone"] = L["phones"][0] if L["phones"] else None
            L["reason"] = Q.reason(L)
            L["data"] = {"pages": L["pages"], "is_business": L["is_business"], "all_emails": L["emails"],
                         "status": L["status"], "status_note": L["status_note"]}
            self.store.add_lead(self.cid, L)
            self.store.mark(self.cid, L["domain"], L["status"], L["status_note"], L["source"])
            kept += 1
            if L["status"] == "review":
                self.stats["review"] = self.stats.get("review", 0) + 1
        self.stats["kept"] += kept
        return kept

    # -- whole run -------------------------------------------------------------
    def go(self, wave: int = 12) -> dict:
        t0 = time.time()
        cands = self.discover()
        for i in range(0, len(cands), wave):
            if self.stats["kept"] >= self.target:
                break
            batch = cands[i:i + wave]
            kept = self.judge(self.crawl(batch))
            self.log(f"  checked {self.stats['sites_checked']} sites, kept {self.stats['kept']} "
                     f"(+{kept}), Jev so far ${self.jev.meter.cost_usd:.4f}")
        self.stats["seconds"] = round(time.time() - t0, 1)
        self.stats["jev"] = {"calls": self.jev.meter.calls, "input_tokens": self.jev.meter.input_tokens,
                             "cost_usd": round(self.jev.meter.cost_usd, 5)}
        pages = self.stats["pages_fetched"]
        page_tokens = self.stats["page_chars"] / CHARS_PER_TOKEN
        self.stats["claude_estimate"] = {
            name: round(((page_tokens + pages * PROMPT_TOKENS) * i + pages * OUTPUT_TOKENS * o) / 1e6, 4)
            for name, (i, o) in CLAUDE_PRICES.items()}
        self.stats["claude_estimate_basis"] = (
            f"{pages} pages x (page text at ~{CHARS_PER_TOKEN} chars/token + {PROMPT_TOKENS} prompt tokens) in, "
            f"{OUTPUT_TOKENS} tokens out per page, at list price per million tokens {CLAUDE_PRICES}")
        self.store.log_run(self.cid, t0, self.stats)
        return self.stats
