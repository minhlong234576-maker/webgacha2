from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from fastapi import HTTPException

from .config import ROOT

TMP_DIR = ROOT / "tmp"


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"Khong tim thay database: {path.name}")
    uri = path.resolve().as_posix()
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    try:
        src = sqlite3.connect(f"file:{uri}?mode=ro", uri=True, timeout=8)
        src.backup(mem)
        src.close()
        return mem
    except sqlite3.OperationalError:
        TMP_DIR.mkdir(exist_ok=True)
        snapshot = TMP_DIR / path.name
        shutil.copy2(path, snapshot)
        src = sqlite3.connect(snapshot, timeout=8)
        src.backup(mem)
        src.close()
        return mem


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
