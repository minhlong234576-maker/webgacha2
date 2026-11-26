"""Số người đang online trên server Minecraft — đọc log server qua PikaMC.

PikaMC (bản Pterodactyl) không có endpoint REST "đang có ai online". Ba cách
đều không ổn:
  - websocket console: mỗi lần đọc là một socket, tốn tài nguyên.
  - `server.properties`: key `online-players=` chỉ được ghi lại khi server lưu
    cấu hình, nên thường vắng mặt (server này không bật).
  - `AuthMe`/DB economy: chỉ có tài khoản từng đăng nhập, không phải đang online.

Nguồn đúng là log server: Paper ghi rõ hai dòng cho mỗi lần vào/ra:
  - `X logged in with entity id ...`  → vào game
  - `X lost connection: ...`         → rời game

Đọc `/logs/latest.log` rồi dựng lại tập người đang online. Sai sót: người
vào rồi rời giữa chừng không có dòng "joined the game" ở bản log này — nên
dùng "logged in with entity id" (có ở mọi lần vào, kể cả reconnect) làm
chuẩn, và "lost connection" làm chuẩn ra.

Có cache TTL: log dài và host tính tiền theo băng thông, nên không poll liên
tục. Đọc lỗi thì giữ số cũ — 0 là thông tin sai làm người xem tưởng
server vắng.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from fastapi import HTTPException

from . import pika
from .config import PIKA_SERVER_LOG
from .errors import MoneyError

log = logging.getLogger("jellyvale.liveplayers")

# Số người online đổi ở tốc độ người vào/ra server; vài chục giây là đủ và
# đọc log mỗi lần khá tốn băng thông.
TTL = 20.0

# Paper/Folia ghi: `[12:02:04] [Server thread/INFO]: Ten[/ip:port] logged in ...`
# và `[...] [Server thread/INFO]: Ten lost connection: ...`
_JOIN_RE = re.compile(r":\s+(\S+)\[")
_LOGIN_RE = re.compile(r"logged in with entity id")
_LEAVE_RE = re.compile(r"lost connection")
# Dòng join của một số bản có UUID thay vì IP: `ST_KIRA__090 (uuid) logged in`
_NAME_RE = re.compile(r":\s+([A-Za-z0-9_.-]+)\s*(?:\(|\[)")

_lock: asyncio.Lock | None = None
_cache: dict[str, Any] | None = None
_cache_at: float = 0.0


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def parse_online(log_text: str) -> list[str]:
    """Dựng danh sách người đang online từ nội dung log server.

    Thứ tự giữ nguyên lúc vào game. Trả về danh sách tên, không trùng.
    """
    online: list[str] = []
    seen: set[str] = set()
    for line in log_text.splitlines():
        if _LOGIN_RE.search(line):
            match = _NAME_RE.search(line)
            if match:
                name = match.group(1)
                if name not in seen:
                    seen.add(name)
                    online.append(name)
        elif _LEAVE_RE.search(line):
            match = _NAME_RE.search(line)
            if match:
                name = match.group(1)
                if name in seen:
                    seen.discard(name)
                    online.remove(name)
    return online


def parse_player_count(log_text: str) -> tuple[int, int] | None:
    """Đọc dòng `Online Players 2/50: ...` — cặp (đang online, tối đa).

    Paper ghi dòng này mỗi khi có người vào/ra, nên nó là con số chính xác
    nhất nếu có. Trả về None nếu log chưa có dòng này.
    """
    best: tuple[int, int] | None = None
    for line in log_text.splitlines():
        if "Online Players" not in line:
            continue
        match = re.search(r"Online Players\s+(\d+)\s*/\s*(\d+)", line)
        if match:
            best = (int(match.group(1)), int(match.group(2)))
    return best


async def refresh() -> dict[str, Any]:
    """Đọc lại log server từ PikaMC và cập nhật cache."""
    global _cache, _cache_at
    async with _get_lock():
        try:
            text = await pika.read_file(PIKA_SERVER_LOG)
        except (HTTPException, MoneyError):
            log.warning("doc log server that bai", exc_info=True)
            text = None
        except Exception:
            log.warning("doc log server that bai", exc_info=True)
            text = None
        if text:
            players = parse_online(text)
            counts = parse_player_count(text)
            _cache = {
                "players": players,
                "online": counts[0] if counts else len(players),
                "max": counts[1] if counts else None,
            }
            _cache_at = time.monotonic()
        return _snapshot()


def _snapshot() -> dict[str, Any]:
    if _cache is None:
        return {"players": [], "online": 0, "max": None}
    return {
        "players": list(_cache["players"]),
        "online": _cache["online"],
        "max": _cache["max"],
    }


async def snapshot() -> dict[str, Any]:
    """Số người online (có cache TTL). Không bao giờ ném lỗi ra ngoài."""
    if _cache is not None and time.monotonic() - _cache_at < TTL:
        return _snapshot()
    return await refresh()


def cached() -> dict[str, Any] | None:
    """Cache hiện tại (không gọi mạng) — dùng khi render trang."""
    if _cache is None:
        return None
    return _snapshot()


async def loop() -> None:
    """Vòng lặp nền: làm mới cache mỗi TTL giây."""
    while True:
        try:
            await refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("lam moi online that bai", exc_info=True)
        await asyncio.sleep(TTL)


def start(app) -> None:
    """Khởi động vòng lặp nền (gán vào app.state để dễ dùng)."""
    task = asyncio.create_task(loop())
    app.state.liveplayers_task = task


__all__ = [
    "TTL",
    "snapshot",
    "refresh",
    "cached",
    "loop",
    "start",
    "parse_online",
    "parse_player_count",
]
