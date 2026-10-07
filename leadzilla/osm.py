"""OpenStreetMap discovery: businesses tagged on the open map, inside the place's bounds.

Free open data (ODbL; credit "© OpenStreetMap contributors"). Nominatim turns the
place into a bounding box (1 request, under their 1-per-second policy) and
Overpass returns every mapped business with the matching tag. Jev picks which
tags fit the niche, so "real estate brokerages" becomes office=estate_agent
without anyone hand-mapping it.
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request

from .jev import Jev, choice

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _CTX = ssl.create_default_context()

UA = "LEADZILLA/0.1 (open-source lead finder; https://github.com/Liamrjohnston/leadzilla)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter")

TAGS = {
    "office=estate_agent": "Real estate agents, brokerages and realtors",
    "office=lawyer": "Law firms and lawyers",
    "office=accountant": "Accountants and bookkeepers",
    "office=insurance": "Insurance brokers and agents",
    "office=financial_advisor": "Financial advisors and wealth managers",
    "office=it": "IT services and software companies",
    "office=marketing": "Marketing agencies",
    "office=advertising_agency": "Advertising agencies",
    "office=architect": "Architects",
    "office=consulting": "Consultants",
    "office=employment_agency": "Recruiters and staffing agencies",
    "office=property_management": "Property managers",
    "office=mortgage": "Mortgage brokers",
    "office=travel_agent": "Travel agencies",
    "office=coworking": "Coworking spaces",
    "amenity=dentist": "Dentists and dental clinics",
    "amenity=doctors": "Medical clinics and doctors",
    "amenity=clinic": "Clinics",
    "amenity=veterinary": "Vets",
    "amenity=restaurant": "Restaurants",
    "amenity=cafe": "Cafes and coffee shops",
    "amenity=bar": "Bars and pubs",
    "healthcare=physiotherapist": "Physiotherapists",
    "healthcare=chiropractor": "Chiropractors",
    "healthcare=optometrist": "Optometrists",
    "leisure=fitness_centre": "Gyms and fitness studios",
    "shop=hairdresser": "Hair salons and barbers",
    "shop=beauty": "Beauty salons, spas and nail salons",
    "shop=car_repair": "Auto repair shops",
    "shop=car": "Car dealerships",
    "shop=furniture": "Furniture stores",
    "shop=clothes": "Clothing boutiques",
    "shop=florist": "Florists",
    "shop=jewelry": "Jewellers",
    "shop=bakery": "Bakeries",
    "craft=roofer": "Roofers",
    "craft=plumber": "Plumbers",
    "craft=electrician": "Electricians",
    "craft=hvac": "Heating and air conditioning contractors",
    "craft=carpenter": "Carpenters",
    "craft=painter": "Painters",
    "craft=builder": "Builders and general contractors",
    "craft=photographer": "Photographers",
    "tourism=hotel": "Hotels",
}


def _get(url: str, data: bytes | None = None, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read()


def bbox(place: str) -> tuple[float, float, float, float]:
    """(south, west, north, east) for a place name, via Nominatim."""
    q = urllib.parse.urlencode({"q": place, "format": "json", "limit": 1})
    hits = json.loads(_get(f"{NOMINATIM}?{q}", timeout=30))
    if not hits:
        raise ValueError(f"OpenStreetMap doesn't know the place {place!r}")
    s, n, w, e = (float(x) for x in hits[0]["boundingbox"])
    return s, w, n, e


def widen(box, km: float) -> tuple:
    d = km / 111.0
    s, w, n, e = box
    return s - d, w - d * 1.5, n + d, e + d * 1.5


def pick_tags(jev: Jev, niche: str) -> list[str]:
    """Jev chooses the map tag(s) that mean this niche. Up to two, each with probability >= 0.2."""
    ans = jev.ask({"niche": niche}, {"tag": choice(
        "Which kind of map listing would a business in `niche` be tagged as?",
        {**TAGS, "none": "None of these describes the niche."})})["tag"]
    ranked = sorted(((p, t) for t, p in (ans.probabilities or {}).items() if t != "none"), reverse=True)
    tags = [t for p, t in ranked[:2] if p >= 0.2]
    return tags or ([ans.value] if ans.value != "none" else [])


def businesses(tags: list[str], box: tuple) -> list[dict]:
    s, w, n, e = box
    parts = "".join(f'nwr["{k}"="{v}"]({s},{w},{n},{e});' for k, v in (t.split("=", 1) for t in tags))
    query = f"[out:json][timeout:60];({parts});out tags center;"
    last = None
    for ep in OVERPASS:
        try:
            raw = _get(ep, data=urllib.parse.urlencode({"data": query}).encode())
            elements = json.loads(raw)["elements"]
            break
        except Exception as ex:  # one mirror busy: try the next
            last = ex
            time.sleep(2)
    else:
        raise RuntimeError(f"OpenStreetMap Overpass unavailable: {last}")
    out = []
    for el in elements:
        t = el.get("tags", {})
        name = t.get("name")
        if not name:
            continue
        addr = ", ".join(x for x in (" ".join(filter(None, (t.get("addr:housenumber"), t.get("addr:street")))),
                                     t.get("addr:city"), t.get("addr:province") or t.get("addr:state"),
                                     t.get("addr:postcode")) if x)
        out.append({"name": name, "website": t.get("website") or t.get("contact:website") or t.get("url"),
                    "email": t.get("email") or t.get("contact:email"),
                    "phone": t.get("phone") or t.get("contact:phone"), "address": addr,
                    "osm": f"https://www.openstreetmap.org/{el['type']}/{el['id']}"})
    return out
