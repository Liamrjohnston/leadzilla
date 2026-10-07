"""Deterministic extraction — no model involved.

Pulls the contact data a page already exposes: mailto:/tel: links, emails and
phones in the text (including "name [at] domain [dot] com"), schema.org JSON-LD
(Organization / LocalBusiness / RealEstateAgent ...), title, description,
social profiles and links that probably lead to contact or team pages.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from urllib.parse import urljoin, urlparse

from lxml import html as lhtml

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+)\s*([A-Za-z0-9-]+(?:\s*(?:\[dot\]|\(dot\)|\s+dot\s+|\.)\s*[A-Za-z0-9-]+)+)",
    re.I)
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\b([2-9]\d{2})\)?[\s.-]?([2-9]\d{2})[\s.-]?(\d{4})\b")
BAD_EMAIL_PARTS = ("example.", "sentry", "wixpress", "@2x", ".png", ".jpg", ".jpeg", ".gif", ".webp",
                   ".svg", "domain.com", "email.com", "yourname", "u003e", "@sentry")
CONTACT_HINTS = ("contact", "about", "team", "agent", "realtor", "people", "staff", "our-", "leadership",
                 "broker", "office", "connect", "get-in-touch")
SOCIAL = {"linkedin.com": "linkedin", "instagram.com": "instagram", "facebook.com": "facebook",
          "x.com": "x", "twitter.com": "x", "youtube.com": "youtube", "tiktok.com": "tiktok"}
JSONLD_TYPES = ("Organization", "LocalBusiness", "RealEstateAgent", "ProfessionalService", "Corporation",
                "Person", "Store", "Dentist", "HomeAndConstructionBusiness")


def domain_of(url: str) -> str:
    host = urlparse(url if "//" in url else "//" + url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def clean_email(e: str) -> str | None:
    e = htmllib.unescape(e).strip().strip(".,;:'\"<>()[]").lower()
    if e.startswith("mailto:"):
        e = e[7:]
    e = e.split("?")[0]
    if not EMAIL_RE.fullmatch(e) or any(b in e for b in BAD_EMAIL_PARTS) or len(e) > 80:
        return None
    return e


def normalise_phone(m: re.Match) -> str | None:
    if m.group(1) == "900" or m.group(1)[1:] == "11":   # premium-rate or N11: never a business line
        return None
    return f"({m.group(1)}) {m.group(2)}-{m.group(3)}"


def _jsonld_nodes(doc) -> list[dict]:
    out = []
    for s in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(s.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                if "@graph" in n:
                    stack.extend(n["@graph"] if isinstance(n["@graph"], list) else [n["@graph"]])
                t = n.get("@type")
                types = t if isinstance(t, list) else [t]
                if any(isinstance(x, str) and any(k in x for k in JSONLD_TYPES) for x in types):
                    out.append(n)
            elif isinstance(n, list):
                stack.extend(n)
    return out


def _flat_address(a) -> str:
    if isinstance(a, list):
        a = a[0] if a else ""
    if isinstance(a, dict):
        parts = [a.get(k, "") for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
        return ", ".join(str(p) for p in parts if p)
    return str(a or "")


def extract(page_html: str, url: str) -> dict:
    """Everything usable on one page. Pure function: same HTML in, same dict out."""
    try:
        doc = lhtml.fromstring(page_html)
    except (ValueError, lhtml.etree.ParserError):
        return {"url": url, "emails": [], "phones": [], "links": [], "socials": {}, "text": "",
                "title": "", "description": "", "jsonld": []}
    for bad in doc.xpath("//script[not(@type='application/ld+json')]|//style|//noscript|//svg"):
        bad.drop_tree()

    emails, phones = [], []
    for href in doc.xpath("//a/@href"):
        h = href.strip()
        if h.lower().startswith("mailto:"):
            e = clean_email(h)
            if e:
                emails.append(e)
        elif h.lower().startswith("tel:"):
            digits = re.sub(r"\D", "", h)
            if len(digits) == 11 and digits.startswith("1"):
                digits = digits[1:]
            if len(digits) == 10 and digits[0] in "23456789" and digits[3] in "23456789" and digits[:3] != "900":
                phones.append(f"({digits[:3]}) {digits[3:6]}-{digits[6:]}")

    text = " ".join(" ".join(doc.itertext()).split())
    for e in EMAIL_RE.findall(text):
        e = clean_email(e)
        if e:
            emails.append(e)
    for m in OBFUSCATED_RE.finditer(text):
        dom = re.sub(r"\s*(?:\[dot\]|\(dot\)|\s+dot\s+)\s*", ".", m.group(2), flags=re.I).replace(" ", "")
        e = clean_email(f"{m.group(1)}@{dom}")
        if e:
            emails.append(e)
    for m in PHONE_RE.finditer(text):
        if normalise_phone(m):
            phones.append(normalise_phone(m))

    jsonld = []
    for n in _jsonld_nodes(doc):
        item = {"type": n.get("@type"), "name": n.get("name"), "telephone": n.get("telephone"),
                "email": n.get("email"), "address": _flat_address(n.get("address")),
                "employees": n.get("numberOfEmployees"), "area": n.get("areaServed")}
        if item.get("email"):
            e = clean_email(str(item["email"]))
            if e:
                emails.append(e)
        if item.get("telephone"):
            m = PHONE_RE.search(str(item["telephone"]))
            if m and normalise_phone(m):
                phones.append(normalise_phone(m))
        jsonld.append({k: v for k, v in item.items() if v})

    site = domain_of(url)
    links, socials, seen = [], {}, set()
    for a in doc.xpath("//a[@href]"):
        href = urljoin(url, a.get("href").strip())
        if not href.startswith("http"):
            continue
        d = domain_of(href)
        for key, name in SOCIAL.items():
            if d.endswith(key) and name not in socials:
                socials[name] = href.split("?")[0]
        anchor = " ".join(a.text_content().split())[:80]
        key = href.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        links.append({"url": key, "text": anchor, "internal": d == site})

    title = " ".join((doc.findtext(".//title") or "").split())
    desc = doc.xpath('string(//meta[@name="description"]/@content)') or \
        doc.xpath('string(//meta[@property="og:description"]/@content)')
    return {"url": url, "title": title[:200], "description": " ".join(desc.split())[:400],
            "emails": list(dict.fromkeys(emails)), "phones": list(dict.fromkeys(phones)),
            "jsonld": jsonld[:5], "socials": socials, "links": links, "text": text}


def contact_links(page: dict, limit: int = 12) -> list[dict]:
    """Internal links whose URL or anchor suggests contact, about or team pages."""
    hits = []
    for l in page["links"]:
        if not l["internal"]:
            continue
        s = (l["url"] + " " + l["text"]).lower()
        if any(h in s for h in CONTACT_HINTS):
            hits.append(l)
    return hits[:limit]


def external_sites(page: dict) -> list[dict]:
    """Outbound links to other websites (for directory pages), socials excluded."""
    out, seen = [], set()
    for l in page["links"]:
        if l["internal"]:
            continue
        d = domain_of(l["url"])
        if not d or d in seen or any(d.endswith(k) for k in SOCIAL):
            continue
        seen.add(d)
        out.append({"domain": d, "url": l["url"], "text": l["text"]})
    return out


def phone_from_any(raw: str) -> str | None:
    """Normalise a North American number written any way ("+1-778-374-3100")."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "23456789" and digits[3] in "23456789" and digits[:3] != "900":
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return None
