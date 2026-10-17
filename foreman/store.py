"""SQLite persistence for incidents and the human review trail."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL,            -- reasoning | pending_review | approved | rejected | error
    trigger TEXT NOT NULL,           -- vision | sensor | upload
    part_id TEXT,
    linked_parts INTEGER NOT NULL DEFAULT 0,
    detection TEXT NOT NULL,
    sensors TEXT NOT NULL,
    sections TEXT NOT NULL,
    diagnosis TEXT,
    llm TEXT,
    image_url TEXT,
    heatmap_url TEXT,
    work_order_no TEXT,
    reviewer TEXT,
    review_note TEXT,
    reviewed_at REAL,
    error TEXT
);
"""

JSON_FIELDS = ("detection", "sensors", "sections", "diagnosis", "llm")


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def _row(self, row: sqlite3.Row | None, images: bool = True) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        for f in JSON_FIELDS:
            if d.get(f):
                d[f] = json.loads(d[f])
        if not images:
            d.pop("image_url", None)
            d.pop("heatmap_url", None)
        return d

    def create(self, **fields: Any) -> dict[str, Any]:
        now = time.time()
        fields = {**fields, "created_at": now, "updated_at": now}
        for f in JSON_FIELDS:
            if f in fields and not isinstance(fields[f], str):
                fields[f] = json.dumps(fields[f])
        cols = ", ".join(fields)
        qs = ", ".join("?" for _ in fields)
        with self._lock:
            cur = self._conn.execute(f"INSERT INTO incidents ({cols}) VALUES ({qs})", list(fields.values()))
            self._conn.commit()
            new_id = cur.lastrowid
        return self.get(new_id)

    def update(self, incident_id: int, **fields: Any) -> dict[str, Any]:
        fields["updated_at"] = time.time()
        for f in JSON_FIELDS:
            if f in fields and fields[f] is not None and not isinstance(fields[f], str):
                fields[f] = json.dumps(fields[f])
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE incidents SET {sets} WHERE id = ?", [*fields.values(), incident_id])
            self._conn.commit()
        return self.get(incident_id)

    def bump_linked(self, incident_id: int) -> dict[str, Any]:
        with self._lock:
            self._conn.execute("UPDATE incidents SET linked_parts = linked_parts + 1, updated_at = ? WHERE id = ?", (time.time(), incident_id))
            self._conn.commit()
        return self.get(incident_id)

    def get(self, incident_id: int, images: bool = True) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return self._row(row, images)

    def recent(self, limit: int = 20, images: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r, images) for r in rows]

    def open_incident(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM incidents WHERE status IN ('reasoning', 'pending_review') ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return self._row(row, images=False)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute("SELECT status, COUNT(*) FROM incidents GROUP BY status").fetchall()
            wo = self._conn.execute(
                "SELECT COALESCE(SUM(json_extract(diagnosis, '$.work_order.est_downtime_min')), 0) FROM incidents WHERE status = 'approved'"
            ).fetchone()[0]
        by = {r[0]: r[1] for r in rows}
        return {"by_status": by, "approved_downtime_min": wo}
