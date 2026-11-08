"""SQLite state: events, one-time codes, approvals, assignments, inventory, settings."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, mac TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS events_mac_ts ON events (mac, ts);
CREATE TABLE IF NOT EXISTS codes (
    id INTEGER PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL, zone TEXT NOT NULL, mac TEXT,
    expires REAL NOT NULL, used_at REAL, created_by TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY, mac TEXT NOT NULL, zone TEXT NOT NULL, status TEXT NOT NULL,
    created REAL NOT NULL, expires REAL NOT NULL, decided_by TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS assignments (
    mac TEXT PRIMARY KEY, entry TEXT NOT NULL, wim TEXT NOT NULL, idx INTEGER NOT NULL,
    disk INTEGER NOT NULL, backup INTEGER NOT NULL DEFAULT 0, label TEXT NOT NULL,
    token TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, started REAL, finished REAL,
    created_by TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS inventory (mac TEXT PRIMARY KEY, ts REAL NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

APPROVAL_TTL = 15 * 60      # an approval opens the zone for this MAC for 15 minutes
CODE_GRACE = 15 * 60        # a code stays valid this long after its first use, on that MAC only
ASSIGNMENT_TTL = 24 * 3600  # a pending assignment expires after a day


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class DB:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.execute("PRAGMA journal_mode=WAL")

    def q(self, sql: str, *args) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def x(self, sql: str, *args) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            return cur.lastrowid or cur.rowcount

    # ------------------------------------------------------------ events
    def event(self, mac: str, kind: str, detail: str = "", ts: float | None = None) -> None:
        self.x("INSERT INTO events (ts, mac, kind, detail) VALUES (?, ?, ?, ?)",
               ts or time.time(), mac, kind, detail[:500])

    def events(self, limit: int = 100, mac: str | None = None) -> list[dict]:
        if mac:
            rows = self.q("SELECT * FROM events WHERE mac = ? ORDER BY id DESC LIMIT ?", mac, limit)
        else:
            rows = self.q("SELECT * FROM events ORDER BY id DESC LIMIT ?", limit)
        return [dict(r) for r in rows]

    def last_events(self, since: float) -> dict[str, dict]:
        rows = self.q("""SELECT e.* FROM events e JOIN (
                           SELECT mac, MAX(id) AS id FROM events WHERE ts >= ? GROUP BY mac) m
                         ON e.id = m.id""", since)
        return {r["mac"]: dict(r) for r in rows}

    def prune(self, keep_days: int = 60) -> None:
        self.x("DELETE FROM events WHERE ts < ?", time.time() - keep_days * 86400)
        self.x("DELETE FROM codes WHERE expires < ?", time.time() - 86400)
        self.x("DELETE FROM approvals WHERE expires < ?", time.time() - 86400)

    # ------------------------------------------------------------ one-time codes
    def new_code(self, zone: str, ttl: int, mac: str | None = None, by: str = "") -> str:
        code = f"{secrets.randbelow(10**8):08d}"
        self.x("INSERT INTO codes (code_hash, zone, mac, expires, created_by) VALUES (?, ?, ?, ?, ?)",
               _hash(code), zone, mac, time.time() + ttl, by)
        return code

    def check_code(self, code: str, zone: str, mac: str) -> bool:
        now = time.time()
        rows = self.q("SELECT * FROM codes WHERE code_hash = ? AND zone = ?", _hash(code), zone)
        if not rows:
            return False
        r = rows[0]
        if r["expires"] < now or (r["mac"] and r["mac"] != mac):
            return False
        if r["used_at"] is None:
            # First use binds the code to this PC and shortens its life.
            self.x("UPDATE codes SET used_at = ?, mac = ?, expires = MIN(expires, ?) WHERE id = ?",
                   now, mac, now + CODE_GRACE, r["id"])
        return True

    def codes(self) -> list[dict]:
        return [dict(r) for r in self.q(
            "SELECT id, zone, mac, expires, used_at, created_by FROM codes WHERE expires > ? ORDER BY id DESC",
            time.time())]

    # ------------------------------------------------------------ approvals
    def approval(self, mac: str, zone: str) -> dict | None:
        rows = self.q("SELECT * FROM approvals WHERE mac = ? AND zone = ? AND expires > ? ORDER BY id DESC LIMIT 1",
                      mac, zone, time.time())
        return dict(rows[0]) if rows else None

    def request_approval(self, mac: str, zone: str) -> tuple[dict, bool]:
        """Return (approval, created_now)."""
        cur = self.approval(mac, zone)
        if cur and cur["status"] in ("pending", "approved"):
            return cur, False
        now = time.time()
        aid = self.x("INSERT INTO approvals (mac, zone, status, created, expires) VALUES (?, ?, 'pending', ?, ?)",
                     mac, zone, now, now + 10 * 60)
        return dict(self.q("SELECT * FROM approvals WHERE id = ?", aid)[0]), True

    def decide(self, aid: int, approve: bool, by: str) -> dict | None:
        rows = self.q("SELECT * FROM approvals WHERE id = ? AND status = 'pending'", aid)
        if not rows:
            return None
        status = "approved" if approve else "denied"
        self.x("UPDATE approvals SET status = ?, decided_by = ?, expires = ? WHERE id = ?",
               status, by, time.time() + APPROVAL_TTL, aid)
        return {**dict(rows[0]), "status": status}

    def pending_approvals(self) -> list[dict]:
        return [dict(r) for r in self.q(
            "SELECT * FROM approvals WHERE status = 'pending' AND expires > ? ORDER BY id", time.time())]

    # ------------------------------------------------------------ assignments
    def assign(self, mac: str, entry: str, wim: str, idx: int, disk: int, backup: bool, label: str,
               by: str = "") -> str:
        token = secrets.token_urlsafe(18)
        self.x("""INSERT OR REPLACE INTO assignments
                  (mac, entry, wim, idx, disk, backup, label, token, status, created, created_by)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
               mac, entry, wim, idx, disk, int(backup), label, token, time.time(), by)
        return token

    def assignment(self, mac: str) -> dict | None:
        rows = self.q("SELECT * FROM assignments WHERE mac = ?", mac)
        if not rows:
            return None
        a = dict(rows[0])
        if a["status"] == "pending" and a["created"] < time.time() - ASSIGNMENT_TTL:
            self.x("UPDATE assignments SET status = 'expired' WHERE mac = ?", mac)
            a["status"] = "expired"
        return a

    def active_assignment(self, mac: str) -> dict | None:
        a = self.assignment(mac)
        return a if a and a["status"] in ("pending", "started") else None

    def set_assignment_status(self, mac: str, status: str) -> None:
        col = {"started": "started", "done": "finished", "failed": "finished"}.get(status)
        if col:
            self.x(f"UPDATE assignments SET status = ?, {col} = ? WHERE mac = ?", status, time.time(), mac)
        else:
            self.x("UPDATE assignments SET status = ? WHERE mac = ?", status, mac)

    def unassign(self, mac: str) -> None:
        self.x("DELETE FROM assignments WHERE mac = ?", mac)

    def assignments(self) -> list[dict]:
        return [{k: v for k, v in dict(r).items() if k != "token"}
                for r in self.q("SELECT * FROM assignments ORDER BY created DESC")]

    # ------------------------------------------------------------ inventory
    def save_inventory(self, mac: str, data: dict) -> None:
        self.x("INSERT OR REPLACE INTO inventory (mac, ts, data) VALUES (?, ?, ?)",
               mac, time.time(), json.dumps(data, ensure_ascii=False))

    def inventory(self, mac: str | None = None) -> list[dict]:
        rows = self.q("SELECT * FROM inventory WHERE mac = ?", mac) if mac else self.q("SELECT * FROM inventory")
        return [{"mac": r["mac"], "ts": r["ts"], "data": json.loads(r["data"])} for r in rows]

    # ------------------------------------------------------------ key/value state
    def get(self, key: str, default: str | None = None) -> str | None:
        rows = self.q("SELECT value FROM state WHERE key = ?", key)
        return rows[0]["value"] if rows else default

    def put(self, key: str, value: str | None) -> None:
        if value is None:
            self.x("DELETE FROM state WHERE key = ?", key)
        else:
            self.x("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", key, value)
