"""SQLite memory: every domain ever looked at, every lead kept, per campaign.

Re-running a campaign asks for N *more* leads and never re-fetches or
re-judges a domain it has already seen.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY, key TEXT UNIQUE, niche TEXT, place TEXT, offer TEXT, created REAL);
CREATE TABLE IF NOT EXISTS domains (
  campaign_id INTEGER, domain TEXT, status TEXT, reason TEXT, source TEXT, seen REAL,
  PRIMARY KEY (campaign_id, domain));
CREATE TABLE IF NOT EXISTS leads (
  campaign_id INTEGER, domain TEXT, company TEXT, website TEXT, email TEXT, email_status TEXT,
  email_role INTEGER, phone TEXT, address TEXT, socials TEXT, size TEXT, fit REAL, confidence REAL,
  in_area REAL, reason TEXT, source TEXT, data TEXT, created REAL,
  PRIMARY KEY (campaign_id, domain));
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, campaign_id INTEGER, started REAL, finished REAL, stats TEXT);
"""


class Store:
    def __init__(self, path: str | Path):
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)

    def campaign(self, niche: str, place: str, offer: str) -> int:
        key = f"{niche.strip().lower()}|{place.strip().lower()}|{offer.strip().lower()}"
        self.db.execute("INSERT OR IGNORE INTO campaigns(key,niche,place,offer,created) VALUES(?,?,?,?,?)",
                        (key, niche, place, offer, time.time()))
        self.db.commit()
        return self.db.execute("SELECT id FROM campaigns WHERE key=?", (key,)).fetchone()[0]

    def seen(self, cid: int, domain: str) -> bool:
        return self.db.execute("SELECT 1 FROM domains WHERE campaign_id=? AND domain=?",
                               (cid, domain)).fetchone() is not None

    def mark(self, cid: int, domain: str, status: str, reason: str = "", source: str = ""):
        self.db.execute("INSERT OR REPLACE INTO domains VALUES(?,?,?,?,?,?)",
                        (cid, domain, status, reason, source, time.time()))
        self.db.commit()

    def add_lead(self, cid: int, lead: dict):
        self.db.execute(
            "INSERT OR REPLACE INTO leads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, lead["domain"], lead.get("company"), lead.get("website"), lead.get("email"),
             lead.get("email_status"), int(bool(lead.get("email_role"))), lead.get("phone"),
             lead.get("address"), json.dumps(lead.get("socials", {})), lead.get("size"), lead.get("fit"),
             lead.get("confidence"), lead.get("in_area"), lead.get("reason"), lead.get("source"),
             json.dumps(lead.get("data", {})), time.time()))
        self.db.commit()

    def lead_count(self, cid: int, min_fit: float = 0.0) -> int:
        return self.db.execute("SELECT COUNT(*) FROM leads WHERE campaign_id=? AND fit>=?",
                               (cid, min_fit)).fetchone()[0]

    def leads(self, cid: int) -> list[dict]:
        cur = self.db.execute("SELECT * FROM leads WHERE campaign_id=? ORDER BY fit DESC, confidence DESC",
                              (cid,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def log_run(self, cid: int, started: float, stats: dict):
        self.db.execute("INSERT INTO runs(campaign_id,started,finished,stats) VALUES(?,?,?,?)",
                        (cid, started, time.time(), json.dumps(stats)))
        self.db.commit()
