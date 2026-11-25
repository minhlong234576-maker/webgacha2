from __future__ import annotations

"""Tầng tiền thật: đồng bộ ví web với Coin in-game (ExcellentEconomy).

Khi `GACHA_DRY_RUN=false`:
- Coin in-game trên server là tiền thật và là nguồn sự thật duy nhất.
- Ví web (`data/gacha.db`) chỉ là bản mirror để hiển thị và ghi sổ.

Quy ước quan trọng — `take`/`give` KHÔNG đụng vào ví web:
    - `take` / `give` chỉ thao tác Coin in-game (qua console).
    - `sync` mới là thứ ghi số dư server xuống ví web.
    - Việc ghi sổ ví web (trừ/cộng + dòng `tx`) thuộc `app.game`.

Nhờ vậy mỗi Coin chỉ bị đếm một lần: `game.debit` ghi sổ web, `bank.take`
trừ tiền thật, và `bank.sync` xác nhận hai bên khớp nhau.
"""

import asyncio
import logging
import time

from fastapi import HTTPException

from . import store
from .gacha import is_dry_run
from .pika import eco_give, eco_take, economy_balance, economy_balances

log = logging.getLogger("jellyvale.bank")

# Chu kỳ đồng bộ nền (giây). Server không cần cập nhật tức thời vì mọi giao
# dịch tiền thật đều đã sync ngay sau khi thực hiện; vòng này chỉ bắt các
# thay đổi Coin xảy ra ngoài web (nạp trong game, phần thưởng admin...).
SYNC_INTERVAL = 20.0

# Số giây tối đa số dư cache được tin là còn mới. Mỗi lần gọi server tốn
# ~150ms + 1 request ra PikaMC, nên poll 10s/lần với N người sẽ là N*6
# request/phút. Cache giữ tải ổn định mà vẫn realtime.
SYNC_MAX_AGE = 8.0

# Mốc thời gian (monotonic) lần sync gần nhất của từng người chơi.
_synced_at: dict[str, float] = {}


def mark_synced(player: str) -> None:
    """Đánh dấu số dư của người chơi vừa được lấy từ server.

    Dùng khi đã biết số dư chính xác từ nguồn khác (ví dụ `find_economy_user`
    trong `player_ctx`) — để `sync_fresh` không hỏi lại server vô ích.
    """
    _synced_at[player] = time.monotonic()


async def sync(player: str) -> float:
    """Đọc số dư Coin in-game rồi ghi đè vào ví web.

    Dry-run: giữ nguyên ví web (không có Coin in-game để đồng bộ).
    """
    if is_dry_run():
        return float(store.get_balance(player))
    balance = await economy_balance(player)
    store.set_wallet(player, round(balance))
    _synced_at[player] = time.monotonic()
    return balance


async def sync_fresh(player: str, max_age: float = SYNC_MAX_AGE) -> float:
    """Số dư đồng bộ, chỉ gọi server lại khi cache đã cũ.

    Mọi lần đọc số dư từ server tốn ~150ms và tạo 1 request ra PikaMC. Nếu
    mỗi người chơi poll mỗi 10s thì 100 người = 600 request/phút. Cache
    theo thời gian giữ tải ổn định mà vẫn realtime trong `max_age` giây.

    Lỗi mạng: trả số dư cache, KHÔNG trả 0 (0 bị hiểu là hết tiền).
    """
    if is_dry_run():
        return float(store.get_balance(player))

    age = time.monotonic() - _synced_at.get(player, 0.0)
    if age < max_age:
        return float(store.get_balance(player))
    try:
        return await sync(player)
    except (HTTPException, MoneyError):
        return float(store.get_balance(player))


async def sync_all() -> int:
    """Đồng bộ toàn bộ ví web theo số dư server. Trả về số ví đã cập nhật.

    Chỉ cập nhật dòng ví ĐÃ TỒN TẠI — không tạo ví mới cho người chơi chưa
    từng vào web. Nhờ vậy bot ảo và ví rác không bị ghi đè bằng 0.
    """
    if is_dry_run():
        return 0
    balances = await economy_balances()
    if not balances:
        return 0
    lowered = {name.lower(): value for name, value in balances.items()}

    def inner(con):
        updated = 0
        for row in con.execute("SELECT player FROM wallets").fetchall():
            player = row["player"]
            value = balances.get(player)
            if value is None:
                value = lowered.get(player.lower())
            if value is None:
                continue
            con.execute(
                "UPDATE wallets SET balance = ? WHERE player = ?",
                (max(0, round(value)), player),
            )
            _synced_at[player] = time.monotonic()
            updated += 1
        return updated

    return store.run(inner)


async def take(player: str, amount: int) -> float:
    """Trừ Coin in-game. Ném MoneyError nếu không đủ tiền hoặc lệnh thất bại.

    Không đụng ví web — caller tự ghi sổ và gọi `sync` sau khi xong.

    Dry-run: không động vào Coin in-game.
    """
    amount = int(amount)
    if amount <= 0 or is_dry_run():
        return float(store.get_balance(player))
    # Khoá theo người chơi nằm trong `pika.eco_take` — nơi đọc số dư và gửi
    # lệnh console. Ở đây chỉ gọi xuống.
    return await eco_take(player, amount)


async def give(player: str, amount: int) -> float:
    """Cộng Coin in-game. Ném MoneyError nếu lệnh thất bại.

    Không đụng ví web — caller tự ghi sổ và gọi `sync` sau khi xong.

    Dry-run: không động vào Coin in-game.
    """
    amount = int(amount)
    if amount <= 0 or is_dry_run():
        return float(store.get_balance(player))
    return await eco_give(player, amount)


async def loop() -> None:
    """Vòng lặp đồng bộ nền — giữ ví web khớp với Coin in-game.

    Bỏ qua lỗi mạng: lần sau sẽ thử lại. Lỗi không được làm sập app.
    """
    if is_dry_run():
        return
    await asyncio.sleep(SYNC_INTERVAL)
    while True:
        try:
            await sync_all()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("đồng bộ nền thất bại", exc_info=True)
        await asyncio.sleep(SYNC_INTERVAL)


def start(app) -> None:
    """Khởi động vòng đồng bộ nền (gắn vào app.state cho dễ dừng)."""
    task = asyncio.create_task(loop())
    app.state.bank_task = task


__all__ = ["sync", "sync_fresh", "sync_all", "take", "give", "mark_synced", "loop", "start"]
