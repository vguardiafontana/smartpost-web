from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


class StateDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS client_cache (
                seller TEXT PRIMARY KEY,
                client_id INTEGER NOT NULL,
                empresa TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sent_ledger (
                report_sha256 TEXT NOT NULL,
                whatsapp_group TEXT NOT NULL,
                seller TEXT NOT NULL,
                run_date TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY(report_sha256, whatsapp_group)
            );
            CREATE TABLE IF NOT EXISTS report_cache (
                cache_key TEXT PRIMARY KEY,
                seller TEXT NOT NULL,
                run_date TEXT NOT NULL,
                report_path TEXT NOT NULL,
                report_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                run_date TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                detail TEXT
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def start_run(self, run_id: str, run_date: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO runs(run_id, run_date, status, started_at) VALUES(?,?,?,?)",
            (run_id, run_date, "running", datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def finish_run(self, run_id: str, status: str, detail: str = "") -> None:
        self.conn.execute(
            "UPDATE runs SET status=?, finished_at=?, detail=? WHERE run_id=?",
            (status, datetime.now().isoformat(timespec="seconds"), detail, run_id),
        )
        self.conn.commit()

    def client_cache_dict(self) -> dict:
        rows = self.conn.execute("SELECT seller, client_id, empresa FROM client_cache").fetchall()
        return {r["seller"]: {"cliente_id": r["client_id"], "empresa": r["empresa"]} for r in rows}

    def save_client(self, seller: str, client_id: int, empresa: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO client_cache(seller, client_id, empresa, updated_at) VALUES(?,?,?,?)",
            (seller, client_id, empresa, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def already_sent(self, report_sha256: str, group: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sent_ledger WHERE report_sha256=? AND whatsapp_group=?",
            (report_sha256, group),
        ).fetchone()
        return row is not None

    def mark_sent(self, report_sha256: str, group: str, seller: str, run_date: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO sent_ledger(report_sha256, whatsapp_group, seller, run_date, sent_at) VALUES(?,?,?,?,?)",
            (report_sha256, group, seller, run_date, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def get_cached_report(self, cache_key: str):
        return self.conn.execute("SELECT * FROM report_cache WHERE cache_key=?", (cache_key,)).fetchone()

    def save_cached_report(self, cache_key: str, seller: str, run_date: str, report_path: Path, report_sha256: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO report_cache(cache_key, seller, run_date, report_path, report_sha256, created_at) VALUES(?,?,?,?,?,?)",
            (cache_key, seller, run_date, str(report_path), report_sha256, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()
