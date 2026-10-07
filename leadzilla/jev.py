"""Jev client — TypeSafe's System One model.

Jev reads text and answers typed questions (yes/no, pick one, score) with
probabilities. It never writes text and cannot do arithmetic, so LEADZILLA uses
it only for judgements and does all counting, ranking and parsing in code.

Two ways to reach it:
  * TYPESAFE_API_KEY in the environment -> the public HTTP API
    (POST https://api.typesafe.ai/v1/systemone, docs.typesafe.ai/api).
  * the `composio` CLI with a connected `jev` toolkit -> JEV_EVALUATE_STATE.
"""
from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _CTX = ssl.create_default_context()

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
# Published price, docs.typesafe.ai/models (read 7 Oct 2026): $0.042 per million
# input tokens, output free.
PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000


class JevError(RuntimeError):
    pass


def noul(instructions, true=None, false=None) -> dict:
    q = {"type": "noul", "instructions": instructions}
    crit = {k: v for k, v in (("true", true), ("false", false)) if v}
    if crit:
        q["criteria"] = crit
    return q


def choice(instructions, options: dict) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def score(instructions, levels: list) -> dict:
    if not 2 <= len(levels) <= 10:
        raise ValueError("a score needs 2-10 ordered levels, lowest first")
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


@dataclass
class Answer:
    kind: str
    value: object
    confidence: float | None
    probabilities: dict


def _parse(raw: dict) -> Answer:
    kind = raw["type"]
    if kind == "noul":
        return Answer("noul", raw["noul"], None, {"true": raw["noul"], "false": 1 - raw["noul"]})
    if kind in ("choice", "score"):
        return Answer(kind, raw[kind], raw.get("confidence"), raw.get("probabilities", {}))
    raise JevError(f"unknown answer type {kind!r}")


@dataclass
class Meter:
    """Counts every token Jev was sent, so each run can print its real cost."""
    input_tokens: int = 0
    calls: int = 0
    seconds: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, tokens: int, seconds: float):
        with self._lock:
            self.input_tokens += tokens
            self.calls += 1
            self.seconds += seconds

    @property
    def cost_usd(self) -> float:
        return self.input_tokens * PRICE_PER_INPUT_TOKEN


class Jev:
    def __init__(self, backend: str | None = None, model: str = MODEL, meter: Meter | None = None,
                 retries: int = 3):
        self.model = model
        self.meter = meter or Meter()
        self.retries = retries
        self.key = os.environ.get("TYPESAFE_API_KEY")
        if backend is None:
            backend = "http" if self.key else ("composio" if _composio() else None)
        if backend is None:
            raise JevError("No way to reach Jev. Set TYPESAFE_API_KEY (typesafe.ai) "
                           "or connect the jev toolkit in Composio.")
        if backend == "http" and not self.key:
            raise JevError("backend 'http' needs TYPESAFE_API_KEY")
        self.backend = backend

    def ask(self, state, questions: dict) -> dict[str, Answer]:
        if not questions:
            raise ValueError("ask() needs at least one question")
        payload = {"model": self.model, "state": state, "questions": questions}
        last = None
        for attempt in range(self.retries):
            t0 = time.time()
            try:
                data = self._http(payload) if self.backend == "http" else self._composio(payload)
                self.meter.add(int(data.get("usage", {}).get("input_tokens", 0)), time.time() - t0)
                return {k: _parse(v) for k, v in data["answers"].items()}
            except (JevError, urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise JevError(f"Jev call failed after {self.retries} tries: {last}")

    def _http(self, payload: dict) -> dict:
        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.key}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise JevError(f"HTTP {e.code}: {e.read()[:300]!r}")

    def _composio(self, payload: dict) -> dict:
        proc = subprocess.run([_composio(), "execute", "JEV_EVALUATE_STATE", "-d", "-"],
                              input=json.dumps(payload), capture_output=True, text=True, timeout=120)
        try:
            body = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise JevError(f"unreadable Composio output: {proc.stdout[:200]} {proc.stderr[:200]}")
        if not body.get("successful"):
            raise JevError(str(body.get("error"))[:300])
        return body["data"]


def _composio() -> str | None:
    found = shutil.which("composio")
    if found:
        return found
    for p in ("~/.local/bin/composio", "~/.composio/bin/composio", "/opt/homebrew/bin/composio",
              "/usr/local/bin/composio"):
        p = os.path.expanduser(p)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None
