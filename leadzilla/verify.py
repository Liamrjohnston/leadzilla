"""Free email checks, done in code: syntax, does the domain accept mail (MX), role inbox."""
from __future__ import annotations

import functools

import dns.exception
import dns.resolver

from .extract import EMAIL_RE

ROLE = {"info", "office", "admin", "contact", "hello", "sales", "support", "team", "reception",
        "inquiries", "enquiries", "mail", "general", "frontdesk", "help"}
NEVER = {"noreply", "no-reply", "donotreply", "do-not-reply", "privacy", "abuse", "postmaster",
         "webmaster", "careers", "jobs", "hr", "billing", "accounts"}


@functools.lru_cache(maxsize=4096)
def accepts_mail(domain: str) -> bool | None:
    """True if the domain publishes MX (or A as fallback) records; None if DNS failed."""
    try:
        dns.resolver.resolve(domain, "MX", lifetime=6)
        return True
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        try:
            dns.resolver.resolve(domain, "A", lifetime=6)
            return True
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return False
        except dns.exception.DNSException:
            return None
    except dns.exception.DNSException:
        return None


def check(email: str) -> dict:
    local, _, domain = email.partition("@")
    if not EMAIL_RE.fullmatch(email):
        return {"status": "invalid", "role": False}
    if local.lower() in NEVER:
        return {"status": "do_not_use", "role": True}
    mx = accepts_mail(domain.lower())
    status = {True: "domain_accepts_mail", False: "domain_has_no_mail", None: "dns_unreachable"}[mx]
    return {"status": status, "role": local.lower() in ROLE}
