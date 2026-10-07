"""Every judgement LEADZILLA makes, asked of Jev in batches.

Jev answers; code decides. Thresholds live here, in plain numbers, so you can
change them without re-running anything (judgements are stored with the lead).
"""
from __future__ import annotations

from .jev import Jev, choice, noul, score

KEEP_BUSINESS = 0.6   # probability the site is one business in the niche
KEEP_AREA = 0.5       # probability it serves the place you asked for
KEEP_FIT = 2.0        # 0-4 fit score: 2 = "possible buyer"

FIT_LEVELS = [
    "Clearly not a buyer for `offer`: the wrong kind of business, or no way it could use it.",
    "Unlikely buyer: a related business, but little sign it needs `offer`.",
    "Possible buyer: the right kind of business, nothing specific either way.",
    "Good fit: the right kind of business, with signs it would benefit from `offer`, such as an active team, several agents or offices, or visible marketing.",
    "Strong fit: exactly the customer `offer` is built for, with clear signs of need and the size to pay for it.",
]
SIZE = {
    "solo": "One person working alone.",
    "small": "A small team, roughly 2 to 20 people or agents.",
    "mid": "A mid-sized firm, roughly 21 to 200 people, or several offices.",
    "large": "A large company or national brand with more than 200 people.",
    "unclear": "The page does not show how big the business is.",
}


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def triage_results(jev: Jev, results: list[dict], niche: str, place: str, batch: int = 15) -> dict:
    """Search results -> 'own_site' | 'directory' | 'other' with confidence, from title+snippet only."""
    opts = {
        "own_site": f"The website of one {niche} business itself (its own domain).",
        "directory": f"A page that lists many different {niche} businesses, like a directory, ranking or 'best of' list, with links out to them.",
        "other": "Anything else: news, a job board, a social network, a listings portal for properties, a government or association page, or a business outside the niche.",
    }
    out = {}
    for chunk in _chunks(results, batch):
        state = {"looking_for": f"{niche} in {place}",
                 "results": {f"r{i}": {"domain": r["domain"], "title": r["title"], "snippet": r["snippet"]}
                             for i, r in enumerate(chunk)}}
        qs = {f"r{i}": choice(f"Looking only at `results.r{i}`: what kind of page is it?", opts)
              for i in range(len(chunk))}
        ans = jev.ask(state, qs)
        for i, r in enumerate(chunk):
            a = ans[f"r{i}"]
            out[r["url"]] = (a.value, a.confidence or 0.0)
    return out


def triage_outbound(jev: Jev, links: list[dict], niche: str, place: str, batch: int = 20) -> dict:
    """Links found on a directory page -> probability each is a niche business's own website."""
    out = {}
    for chunk in _chunks(links, batch):
        state = {"looking_for": f"{niche} in {place}",
                 "links": {f"l{i}": {"domain": l["domain"], "anchor_text": l["text"]} for i, l in enumerate(chunk)}}
        qs = {f"l{i}": noul(f"Is `links.l{i}` most likely the website of one {niche} business?")
              for i in range(len(chunk))}
        ans = jev.ask(state, qs)
        for i, l in enumerate(chunk):
            out[l["domain"]] = ans[f"l{i}"].value
    return out


def pick_contact_pages(jev: Jev, sites: dict[str, list[dict]], batch: int = 6) -> dict:
    """{domain: [candidate links]} -> {domain: [url, url]} the two links most likely to show contacts."""
    out = {}
    items = [(d, ls) for d, ls in sites.items() if ls]
    for chunk in _chunks(items, batch):
        state, qs = {"sites": {}}, {}
        for j, (d, ls) in enumerate(chunk):
            state["sites"][f"s{j}"] = {f"L{k}": f"{l['text']} — {l['url']}" for k, l in enumerate(ls)}
            opts = {f"L{k}": f"The link `sites.s{j}.L{k}`" for k in range(len(ls))}
            opts["none"] = "None of these links is likely to show an email address, contact form or team list."
            qs[f"s{j}"] = choice(f"Which link in `sites.s{j}` most likely shows this business's email address or its people?", opts)
        ans = jev.ask(state, qs)
        for j, (d, ls) in enumerate(chunk):
            probs = ans[f"s{j}"].probabilities or {}
            ranked = sorted((p, k) for k, p in probs.items() if k != "none")[::-1]
            out[d] = [ls[int(k[1:])]["url"] for p, k in ranked[:2] if p >= 0.15]
    return out


def judge_leads(jev: Jev, leads: list[dict], niche: str, place: str, offer: str, batch: int = 5) -> None:
    """Adds is_business, in_area, fit (0-4), confidence, size and best email to each lead, in place."""
    for chunk in _chunks(leads, batch):
        state = {"niche": niche, "place": place, "offer": offer, "leads": {}}
        qs = {}
        for j, L in enumerate(chunk):
            k = f"x{j}"
            state["leads"][k] = {"domain": L["domain"], "name": L.get("company"), "title": L["page_title"],
                                 "description": L["description"], "structured_data": L.get("jsonld"),
                                 "address": L.get("address"), "page_text": L["excerpt"]}
            qs[f"{k}_biz"] = noul(f"Is `leads.{k}` the website of one {niche} business (a single company or office)?",
                                  true=f"Its own site, and it is a {niche} business.",
                                  false="A directory, portal, listings aggregator, media site, association, job board, or a different kind of business.")
            if not L.get("on_map"):
                qs[f"{k}_area"] = noul(f"Does `leads.{k}` operate in or serve {place}?")
            qs[f"{k}_fit"] = score(f"How good a customer is `leads.{k}` for `offer`?", FIT_LEVELS)
            qs[f"{k}_size"] = choice(f"How big is the business in `leads.{k}`?", SIZE)
            if len(L["emails"]) > 1:
                state["leads"][k]["emails"] = {f"e{i}": e for i, e in enumerate(L["emails"][:12])}
                opts = {f"e{i}": f"`leads.{k}.emails.e{i}`" for i in range(len(L["emails"][:12]))}
                opts["none"] = "None of them belongs to this business."
                qs[f"{k}_email"] = choice(
                    f"Which address in `leads.{k}.emails` is the best way to reach the owner, a decision-maker, "
                    f"or the business's main inbox? Prefer a named leader, then a general business inbox. "
                    f"An address at a different company's domain is not this business's.", opts)
        ans = jev.ask(state, qs)
        for j, L in enumerate(chunk):
            k = f"x{j}"
            L["is_business"] = round(ans[f"{k}_biz"].value, 3)
            L["in_area"] = 1.0 if L.get("on_map") else round(ans[f"{k}_area"].value, 3)
            L["fit"] = round(float(ans[f"{k}_fit"].value), 2)
            L["confidence"] = round(ans[f"{k}_fit"].confidence or 0.0, 2)
            L["size"] = ans[f"{k}_size"].value
            if f"{k}_email" in ans:
                v = ans[f"{k}_email"].value
                L["email"] = None if v == "none" else L["emails"][int(v[1:])]
            else:
                L["email"] = L["emails"][0] if L["emails"] else None


REVIEW_BUSINESS = 0.4  # between this and KEEP_BUSINESS: kept, marked "review" for a human look


def keep(L: dict) -> tuple[str, str]:
    """'qualified', 'review' or 'rejected', with the reason. Three bands: act, check, skip."""
    if L["is_business"] < REVIEW_BUSINESS:
        return "rejected", f"not one {L.get('niche_label', 'niche')} business ({L['is_business']:.2f})"
    if L["in_area"] < KEEP_AREA:
        return "rejected", f"not in the area ({L['in_area']:.2f})"
    if L["fit"] < KEEP_FIT:
        return "rejected", f"weak fit ({L['fit']:.1f}/4)"
    if L["is_business"] < KEEP_BUSINESS:
        return "review", f"maybe not one {L.get('niche_label', 'niche')} business ({L['is_business']:.2f}); check by hand"
    return "qualified", ""


def reason(L: dict) -> str:
    """The why-this-lead line, assembled from the checks Jev passed. Jev never writes it."""
    size = {"solo": "solo", "small": "small team", "mid": "mid-size firm", "large": "large firm"}.get(L["size"], "size unclear")
    contact = "no email found"
    if L.get("email"):
        contact = "general inbox" if L.get("email_role") else "named contact"
    return (f"Fit {L['fit']:.1f}/4 (confidence {L['confidence']:.0%}); {size}; "
            f"in area {L['in_area']:.0%}; {contact}")


def match_websites(jev: Jev, items: list[dict], batch: int = 6) -> dict:
    """[{name, address, results:[...]}] -> {name: domain} where Jev is confident a result is the
    business's own website (probability >= 0.6). Entity matching, not generation."""
    out = {}
    todo = [it for it in items if it["results"]]
    for chunk in _chunks(todo, batch):
        state, qs = {"businesses": {}}, {}
        for j, it in enumerate(chunk):
            state["businesses"][f"b{j}"] = {
                "name": it["name"], "address": it.get("address", ""),
                "results": {f"r{k}": {"domain": r["domain"], "title": r["title"], "snippet": r["snippet"][:200]}
                            for k, r in enumerate(it["results"])}}
            opts = {f"r{k}": f"`businesses.b{j}.results.r{k}` is this business's own website."
                    for k in range(len(it["results"]))}
            opts["none"] = "None of the results is this business's own website (directories, portals and other companies don't count)."
            qs[f"b{j}"] = choice(f"Which result is the official website of the business in `businesses.b{j}`?", opts)
        ans = jev.ask(state, qs)
        for j, it in enumerate(chunk):
            a = ans[f"b{j}"]
            p = (a.probabilities or {}).get(a.value, 0)
            if a.value != "none" and p >= 0.6:
                out[it["name"]] = it["results"][int(a.value[1:])]
    return out


def match_linkedin(jev: Jev, items: list[dict], batch: int = 6) -> dict:
    """[{domain, company, results:[linkedin company pages]}] -> {domain: url} when Jev is confident (>= 0.6)."""
    out = {}
    todo = [it for it in items if it["results"]]
    for chunk in _chunks(todo, batch):
        state, qs = {"companies": {}}, {}
        for j, it in enumerate(chunk):
            state["companies"][f"c{j}"] = {"name": it["company"], "website": it["domain"],
                                           "pages": {f"p{k}": {"url": r["url"], "title": r["title"],
                                                               "snippet": r["snippet"][:200]}
                                                     for k, r in enumerate(it["results"])}}
            opts = {f"p{k}": f"`companies.c{j}.pages.p{k}` is this company's own LinkedIn page."
                    for k in range(len(it["results"]))}
            opts["none"] = "None of these LinkedIn pages belongs to this company."
            qs[f"c{j}"] = choice(f"Which LinkedIn page belongs to the company in `companies.c{j}`?", opts)
        ans = jev.ask(state, qs)
        for j, it in enumerate(chunk):
            a = ans[f"c{j}"]
            if a.value != "none" and (a.probabilities or {}).get(a.value, 0) >= 0.6:
                out[it["domain"]] = it["results"][int(a.value[1:])]["url"]
    return out
