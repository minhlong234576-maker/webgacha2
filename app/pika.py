from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx
from fastapi import HTTPException

from .config import (
    PIKA_API_KEY,
    PIKA_AUTHME_DB,
    PIKA_BASE_URL,
    PIKA_ECONOMY_DB,
    PIKA_OPS_FILE,
    PIKA_SERVER_UUID,
)
from .errors import MoneyError
from .gacha import give_command, take_command

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
_cached_server: str | None = None

# Khoá theo từng người chơi. `eco_take` là chuỗi đọc-số-dư → kiểm tra → gửi
# lệnh: nếu 2 request cùng chạy, cả hai đều đọc số dư cũ, cả hai đều thấy
# đủ tiền, rồi cả hai cùng trừ — người chơi mất tiền. Khoá theo từng người
# (không phải toàn cục) nên người chơi khác vẫn giao dịch song song.
_player_locks: dict[str, asyncio.Lock] = {}

# Cache số dư toàn bộ người chơi (giây). Nhiều người poll cùng lúc sẽ dùng
# chung 1 request thay vì mỗi người một request ra PikaMC.
BALANCES_TTL = 5.0
_balances_cache: dict[str, float] | None = None
_balances_at: float = 0.0


def _player_lock(username: str) -> asyncio.Lock:
    lock = _player_locks.get(username)
    if lock is None:
        lock = asyncio.Lock()
        _player_locks[username] = lock
    return lock


# Một client HTTP dùng chung cho mọi request ra PikaMC. Tạo client mới cho
# mỗi lần gọi nghĩa là mỗi lần đều phải bắt tay TLS và mở socket mới —
# tốn ~100ms mỗi request. Client dùng chung giữ kết nối sống, các request
# sau chỉ mất vài mili-giây.
_client: httpx.AsyncClient | None = None


def get_client(timeout: float = 20.0) -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_client() -> None:
    """Đóng client HTTP dùng chung (gọi khi app tắt)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _headers() -> dict[str, str]:
    if not PIKA_API_KEY:
        raise HTTPException(status_code=503, detail="Chua cau hinh PIKA_API_KEY")
    return {
        "Authorization": f"Bearer {PIKA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _safe_username(username: str) -> str | None:
    name = username.strip()
    if not USERNAME_RE.fullmatch(name):
        return None
    return name


def _require_safe_name(username: str) -> None:
    """Chặn tên lọn trước khi đưa vào lệnh console Minecraft.

    Tên đến từ DB server nên vốn đã tin cậy, nhưng lệnh console là shell:
    một tên chứa ký tự lạ có thể nối thêm lệnh khác. Chặn ở đây rẻ hơn nhiều
    so với phải tin rằng mọi nơi đều lọc đúng.
    """
    if not USERNAME_RE.fullmatch(username.strip()):
        raise MoneyError("Tên người chơi không hợp lệ.")


def _cell(value: dict[str, Any] | None) -> Any:
    if value is None:
        return None
    if value.get("type") == "null":
        return None
    raw = value.get("value")
    return raw


def _rows_as_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results") or []
    if not results:
        return []
    first = results[0]
    columns = [col.get("name") for col in first.get("columns") or []]
    out: list[dict[str, Any]] = []
    for row in first.get("rows") or []:
        out.append({name: _cell(cell) for name, cell in zip(columns, row)})
    return out


async def list_servers() -> list[dict[str, str]]:
    url = f"{PIKA_BASE_URL}/api/client/servers"
    params = {
        "page": 1,
        "per_page": 25,
        "other": "false",
        "scope": "owned",
        "sort": "created",
    }
    response = await get_client().get(url, headers=_headers(), params=params)
    if response.status_code == 401:
        raise HTTPException(status_code=503, detail="API key PikaMC khong hop le")
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail=f"PikaMC servers HTTP {response.status_code}")
    data = response.json().get("servers", {}).get("data", [])
    return [
        {
            "uuid": item.get("uuid", ""),
            "name": item.get("name", ""),
            "short": item.get("uuid_short", ""),
        }
        for item in data
        if item.get("uuid")
    ]


async def get_server(server_id: str) -> dict[str, str]:
    url = f"{PIKA_BASE_URL}/api/client/servers/{server_id}"
    response = await get_client().get(url, headers=_headers())
    if response.status_code == 401:
        raise HTTPException(status_code=503, detail="API key PikaMC khong hop le")
    if response.status_code == 403:
        raise HTTPException(
            status_code=503,
            detail="API key thieu quyen xem server. Can files.query-raw; neu test danh sach can them servers.read",
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail=f"PikaMC server HTTP {response.status_code}")
    item = response.json().get("server") or response.json()
    return {
        "uuid": item.get("uuid") or server_id,
        "name": item.get("name") or "",
        "short": item.get("uuid_short") or server_id,
    }


async def resolve_server_uuid() -> str:
    global _cached_server
    if _cached_server:
        return _cached_server
    if PIKA_SERVER_UUID:
        _cached_server = PIKA_SERVER_UUID
        return _cached_server
    servers = await list_servers()
    if not servers:
        raise HTTPException(status_code=503, detail="Tai khoan PikaMC khong co server")
    _cached_server = servers[0]["uuid"]
    return _cached_server


async def sqlite_query(file_path: str, query: str, rows: int = 5) -> list[dict[str, Any]]:
    server = await resolve_server_uuid()
    url = f"{PIKA_BASE_URL}/api/client/servers/{server}/files/sqlite-query"
    body = {
        "file": file_path,
        "query": query,
        "rows": rows,
        "read_only": True,
    }
    response = await get_client(timeout=25.0).post(
        url, headers=_headers(), json=body
    )
    if response.status_code == 404:
        raise HTTPException(status_code=503, detail=f"Khong tim thay file tren PikaMC: {file_path}")
    if response.status_code == 401:
        raise HTTPException(status_code=503, detail="API key PikaMC khong hop le")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=503,
            detail=f"PikaMC sqlite-query HTTP {response.status_code}",
        )
    return _rows_as_dicts(response.json())


async def read_file(file_path: str) -> str | None:
    """Đọc nội dung một file trên server (trả về None nếu không tồn tại)."""
    server = await resolve_server_uuid()
    url = f"{PIKA_BASE_URL}/api/client/servers/{server}/files/contents"
    response = await get_client(timeout=25.0).get(
        url, headers=_headers(), params={"file": file_path}
    )
    if response.status_code in (403, 404):
        return None
    if response.status_code >= 400:
        raise HTTPException(
            status_code=503,
            detail=f"PikaMC files/contents HTTP {response.status_code}",
        )
    # Endpoint trả về JSON nếu file là .json, ngược lại trả về text thô.
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.text
    return response.text


async def server_ops() -> list[dict[str, Any]]:
    """Danh sách operator (OP) của server Minecraft, đọc từ `ops.json`.

    Đây là nguồn sự thật cho quyền admin của web: ai có OP trên server thì
    có quyền quản trị web. Đọc file trực tiếp thay vì hỏi console vì:
      - 1 request, không tốn vòng lệnh console
      - không cần quyền `control.console` (chỉ cần `files.*`)
    """
    raw = await read_file(PIKA_OPS_FILE)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            level = int(item.get("level", 4))
        except (TypeError, ValueError):
            level = 4
        out.append({
            "name": name,
            "uuid": str(item.get("uuid") or ""),
            "level": level,
        })
    return out


async def server_op_names() -> set[str]:
    """Tập tên (chữ thường) của các OP trên server."""
    ops = await server_ops()
    return {op["name"].lower() for op in ops}


async def find_authme_user(username: str) -> dict[str, Any] | None:
    name = _safe_username(username)
    if not name:
        return None
    query = (
        "SELECT username, realname, password FROM authme "
        f"WHERE LOWER(username) = LOWER('{name}') LIMIT 1"
    )
    rows = await sqlite_query(PIKA_AUTHME_DB, query, rows=1)
    return rows[0] if rows else None


async def send_command(command: str) -> None:
    server = await resolve_server_uuid()
    url = f"{PIKA_BASE_URL}/api/client/servers/{server}/command"
    response = await get_client().post(
        url, headers=_headers(), json={"command": command}
    )
    if response.status_code == 403:
        raise HTTPException(
            status_code=503,
            detail="API key thieu quyen control.console. Bat quyen nay tren hub.pikamc.vn roi tao lai key.",
        )
    if response.status_code == 401:
        raise HTTPException(status_code=503, detail="API key PikaMC khong hop le")
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail=f"PikaMC command HTTP {response.status_code}")


def coin_amount(eco: dict[str, Any] | None) -> float:
    if not eco:
        return 0.0
    try:
        return float(eco.get("money") or 0)
    except (TypeError, ValueError):
        return 0.0


async def economy_balance(username: str) -> float:
    """Số dư Coin in-game hiện tại của người chơi.

    Ném HTTPException nếu không đọc được DB server — không bao giờ trả về 0
    khi lỗi mạng, vì 0 sẽ bị hiểu là "hết tiền" và khóa nhầm người chơi.
    """
    eco = await find_economy_user(username)
    if eco is None:
        return 0.0
    return coin_amount(eco)


async def economy_balances() -> dict[str, float]:
    """Số dư Coin in-game của TẤT CẢ người chơi, trong 1 request.

    Dùng để đồng bộ nền: một lần đọc cả bảng rẻ hơn nhiều so với hỏi từng
    người một. Key là tên đúng như trong DB (không hạ chữ thường).

    Cache TTL ngắn: nhiều người chơi poll cùng lúc sẽ dùng chung 1 request
    thay vì mỗi người một request.
    """
    global _balances_cache, _balances_at
    age = time.monotonic() - _balances_at
    if _balances_cache is not None and age < BALANCES_TTL:
        return _balances_cache

    rows = await sqlite_query(
        PIKA_ECONOMY_DB,
        "SELECT name, money FROM excellenteconomy_users",
        rows=500,
    )
    out: dict[str, float] = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        if name:
            out[name] = coin_amount(row)
    _balances_cache = out
    _balances_at = time.monotonic()
    return out


async def _wait_for_balance(username: str, target: float, timeout: float = 4.0) -> float:
    """Chờ số dư server cập nhật, polling mỗi 0,4s.

    Plugin `eco` ghi vào SQLite nền (ExcellentEconomy), nên đọc ngay sau khi
    gửi lệnh có thể thấy số dư CŨ. Phải chờ cho tới khi số dư khớp hoặc hết
    thời gian chờ.
    """
    deadline = time.monotonic() + timeout
    last = await economy_balance(username)
    while time.monotonic() < deadline:
        await asyncio.sleep(0.4)
        last = await economy_balance(username)
        if abs(last - target) < 1:
            return last
    return last


async def eco_take(username: str, amount: int) -> float:
    """Trừ Coin in-game, có kiểm tra lại số dư sau khi lệnh chạy.

    Plugin `eco take` KHÔNG báo lỗi khi người chơi không đủ tiền: nó chỉ clamp
    về 0 và console vẫn trả HTTP 200. Nếu tin vào HTTP status thì người chơi
    có thể mở rương miễn phí. Vì vậy phải đọc lại số dư và so sánh.

    Khoá theo người chơi để hai request đồng thời không cùng thấy số dư cũ.
    """
    amount = int(amount)
    if amount <= 0:
        return await economy_balance(username)
    _require_safe_name(username)
    async with _player_lock(username):
        before = await economy_balance(username)
        if before + 1 < amount:
            raise MoneyError(
                f"Không đủ Coin in-game. Cần {amount:,}, bạn có {int(before):,}."
            )
        await send_command(take_command(username, amount))
        after = await _wait_for_balance(username, before - amount)
        if after > before - amount + 1:
            raise MoneyError("Trừ Coin in-game thất bại, hãy thử lại.")
        return after


async def eco_give(username: str, amount: int) -> float:
    """Cộng Coin in-game, có kiểm tra lại số dư sau khi lệnh chạy."""
    amount = int(amount)
    if amount <= 0:
        return await economy_balance(username)
    _require_safe_name(username)
    async with _player_lock(username):
        before = await economy_balance(username)
        await send_command(give_command(username, amount))
        after = await _wait_for_balance(username, before + amount)
        if after < before + amount - 1:
            raise MoneyError("Cộng Coin in-game thất bại, hãy thử lại.")
        return after


async def find_economy_user(username: str) -> dict[str, Any] | None:
    name = _safe_username(username)
    if not name:
        return None
    query = (
        "SELECT uuid, name, last_seen, money, coins, shards "
        "FROM excellenteconomy_users "
        f"WHERE LOWER(name) = LOWER('{name}') LIMIT 1"
    )
    rows = await sqlite_query(PIKA_ECONOMY_DB, query, rows=1)
    return rows[0] if rows else None
