from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import HTTPException


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Sao lưu nguyên vẹn SQLite DB vào :memory: qua SQLite Backup API (không copy file sống)."""
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"Khong tim thay database: {path.name}")
    uri = path.resolve().as_posix()
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    src: sqlite3.Connection | None = None
    try:
        src = sqlite3.connect(f"file:{uri}?mode=ro", uri=True, timeout=15)
        src.execute("PRAGMA busy_timeout=15000")
        src.backup(mem)
        return mem
    except sqlite3.OperationalError:
        if src is not None:
            src.close()
            src = None
        try:
            src = sqlite3.connect(f"file:{uri}?immutable=1", uri=True, timeout=15)
            src.backup(mem)
            return mem
        except sqlite3.Error as exc:
            mem.close()
            raise HTTPException(status_code=503, detail=f"Khong doc duoc database: {path.name}") from exc
    finally:
        if src is not None:
            src.close()


def find_authme_user(path: Path, username: str) -> sqlite3.Row | None:
    con = connect_readonly(path)
    try:
        return con.execute(
            """
            SELECT username, realname, password
            FROM authme
            WHERE LOWER(username) = LOWER(?)
            LIMIT 1
            """,
            (username.strip(),),
        ).fetchone()
    finally:
        con.close()


def find_economy_user(path: Path, username: str) -> sqlite3.Row | None:
    con = connect_readonly(path)
    try:
        return con.execute(
            """
            SELECT uuid, name, last_seen, money, coins, shards
            FROM excellenteconomy_users
            WHERE LOWER(name) = LOWER(?)
            LIMIT 1
            """,
            (username.strip(),),
        ).fetchone()
    finally:
        con.close()
