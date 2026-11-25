"""Quyen admin realtime — doc danh sach OP tu PikaMC.

Nguon su that: file `ops.json` tren server Minecraft. Ai co OP tren server
thi co quyen quan tri web (va nguoc lai).

Vi sao doc file thay vi goi console:
  - 1 request, khong ton vong lenh console (console la tai nguyen bi chan).
  - Khong can quyen `control.console`, chi can quyen doc file.

Cache ngan: danh sach OP doi the he thong, khong can hoi server moi request.
TTL 60 giay la du: thay doi OP la vi truc khong phai lien tuc.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import HTTPException

from .config import ADMIN_USERS
from .errors import MoneyError
from .pika import server_op_names

log = logging.getLogger("jellyvale.admins")

# Doi danh sach OP la viec hiem, nen cache lau hon balance (8s).
OPS_TTL = 60.0

_ops_cache: set[str] | None = None
_ops_at: float = 0.0
_lock = asyncio.Lock()


def local_admin_users() -> set[str]:
    """Admin khai bao trong .env (luon co quyen, ke ca khi API loi)."""
    return set(ADMIN_USERS)


def _cache_age() -> float:
    return time.monotonic() - _ops_at


async def refresh() -> set[str]:
    """Doc lai danh sach OP tu server, bo qua cache."""
    global _ops_cache, _ops_at
    async with _lock:
        try:
            names = await server_op_names()
        except (HTTPException, MoneyError):
            log.warning("doc ops.json that bai", exc_info=True)
            names = set()
        except Exception:
            log.warning("doc ops.json that bai", exc_info=True)
            names = set()
        if names:
            _ops_cache = names
            _ops_at = time.monotonic()
        return _ops_cache or set()


async def op_names() -> set[str]:
    """Danh sach ten OP (chữ thường). Có cache TTL."""
    if _ops_cache is not None and _cache_age() < OPS_TTL:
        return _ops_cache
    return await refresh()


def _cached_names() -> set[str]:
    return _ops_cache or set()


def is_admin_now(name: str | None) -> bool:
    """Kiem tra admin dung du lieu da cache (khong goi mang).

    Dung trong template/render de khong block request bang viec goi API.
    Cache da duoc lam moi nen o day da du " moi".
    """
    if not name:
        return False
    key = name.strip().lower()
    if not key:
        return False
    if key in local_admin_users():
        return True
    return key in _cached_names()


async def is_admin(name: str | None) -> bool:
    """Kiem tra admin co lam moi danh sach OP tu server."""
    if not name:
        return False
    key = name.strip().lower()
    if not key:
        return False
    if key in local_admin_users():
        return True
    return key in await op_names()


async def admin_list() -> list[dict]:
    """Danh sach admin hien tai (gop .env + OP tren server), kem level OP."""
    names = await op_names()
    merged = set(names) | local_admin_users()
    out = []
    for n in sorted(merged):
        out.append({
            "name": n,
            "source": "server-op" if n in names else "env",
        })
    return out


async def loop() -> None:
    """Vong lap nen: lam moi danh sach OP moi 60 giay."""
    while True:
        try:
            await refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("lam moi danh sach OP that bai", exc_info=True)
        await asyncio.sleep(OPS_TTL)


def start(app) -> None:
    """Khoi dong vong lap nen (gan vao app.state de de dung)."""
    task = asyncio.create_task(loop())
    app.state.admins_task = task


__all__ = [
    "is_admin",
    "is_admin_now",
    "op_names",
    "admin_list",
    "local_admin_users",
    "refresh",
    "loop",
    "start",
]
