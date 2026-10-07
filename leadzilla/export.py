"""Turn the lead database into files people actually import.

  csv       one row per lead, every field, opens in Excel / Google Sheets / Numbers
  xlsx      the same, formatted: bold frozen header, filters, clickable links, best fit first
  instantly / smartlead / lemlist   column names those cold-email tools map automatically
  linkedin  for LinkedIn outreach: company page, website, contact details

CSV files are written as UTF-8 with a byte-order mark so Excel shows accents
(Engel & Völkers) correctly; Google Sheets ignores the mark.
"""
from __future__ import annotations

import csv
import json
import re

from .pipeline import _names_from_email

SOCIALS = ("linkedin", "instagram", "facebook", "x", "youtube", "tiktok")


def rows(leads: list[dict]) -> list[dict]:
    out = []
    for r in leads:
        s = json.loads(r.get("socials") or "{}")
        first, last = _names_from_email(r.get("email"))
        data = json.loads(r.get("data") or "{}")
        out.append({
            "Status": data.get("status", "qualified"),
            "Company": r.get("company") or "", "Website": r.get("website") or "",
            "Email": r.get("email") or "", "Email type": ("" if not r.get("email") else
                                                           "general inbox" if r.get("email_role") else "named"),
            "Email check": r.get("email_status") or "", "First name": first, "Last name": last,
            "Phone": r.get("phone") or "", "Address": r.get("address") or "",
            "LinkedIn": s.get("linkedin", ""), "Instagram": s.get("instagram", ""),
            "Facebook": s.get("facebook", ""), "X": s.get("x", ""), "YouTube": s.get("youtube", ""),
            "TikTok": s.get("tiktok", ""),
            "Fit (0-4)": r.get("fit"), "Confidence": r.get("confidence"), "Size": r.get("size") or "",
            "Why this lead": r.get("reason") or "",
            "Other emails": "; ".join(e for e in data.get("all_emails", []) if e != r.get("email")),
            "Found via": r.get("source") or "",
        })
    return out


PRESETS = {
    # Instantly: email required; extra columns import as custom variables.
    "instantly": [("email", "Email"), ("first_name", "First name"), ("last_name", "Last name"),
                  ("company_name", "Company"), ("website", "Website"), ("phone", "Phone"),
                  ("linkedin", "LinkedIn"), ("fit", "Fit (0-4)"), ("why", "Why this lead")],
    "smartlead": [("email", "Email"), ("first_name", "First name"), ("last_name", "Last name"),
                  ("company_name", "Company"), ("website", "Website"), ("phone_number", "Phone"),
                  ("linkedin_profile", "LinkedIn"), ("location", "Address"), ("fit", "Fit (0-4)")],
    "lemlist": [("email", "Email"), ("firstName", "First name"), ("lastName", "Last name"),
                ("companyName", "Company"), ("companyDomain", "Website"), ("phone", "Phone"),
                ("linkedinUrl", "LinkedIn"), ("icebreaker", "Why this lead")],
    "linkedin": [("Company", "Company"), ("LinkedIn", "LinkedIn"), ("Website", "Website"),
                 ("Email", "Email"), ("Phone", "Phone"), ("Fit (0-4)", "Fit (0-4)"),
                 ("Why this lead", "Why this lead")],
}


def write(leads: list[dict], path: str, fmt: str = "csv") -> int:
    table = rows(leads)
    if fmt in PRESETS:
        cols = PRESETS[fmt]
        if fmt != "linkedin":
            table = [r for r in table if r["Email"]]  # email tools reject rows without one
        else:
            table = [r for r in table if r["LinkedIn"]]
        table = [{new: r[old] for new, old in cols} for r in table]
    if fmt == "xlsx":
        _xlsx(table, path)
    else:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            fields = list(table[0].keys()) if table else [c for c, _ in PRESETS.get(fmt, [("Company", "")])]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(table)
    return len(table)


def _xlsx(table: list[dict], path: str):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    headers = list(table[0].keys()) if table else ["Company"]
    ws.append(headers)
    for r in table:
        ws.append([r[h] for h in headers])
    head = PatternFill("solid", fgColor="1F2937")
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), head
        c.alignment = Alignment(vertical="center")
    link_cols = {i + 1 for i, h in enumerate(headers)
                 if h in ("Website", "LinkedIn", "Instagram", "Facebook", "X", "YouTube", "TikTok")}
    for row in ws.iter_rows(min_row=2):
        for c in row:
            v = c.value
            if c.column in link_cols and isinstance(v, str) and v.startswith("http"):
                c.hyperlink, c.font = v, Font(color="2563EB", underline="single")
            elif headers[c.column - 1] == "Email" and v:
                c.hyperlink, c.font = f"mailto:{v}", Font(color="2563EB", underline="single")
    widths = {"Company": 32, "Website": 30, "Email": 30, "Why this lead": 60, "Address": 40,
              "Other emails": 40, "Found via": 40}
    for i, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(h, max(10, min(28, len(h) + 4)))
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def guess_format(path: str, fmt: str | None) -> str:
    if fmt:
        return fmt
    return "xlsx" if re.search(r"\.xlsx$", path, re.I) else "csv"
