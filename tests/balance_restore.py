"""Tiện ích khôi phục số dư Coin thật sau khi test.

Các test realtime / e2e dung tai khoan THAT tren server PikaMC. Neu mot
lenh `eco give` bi PikaMC bo qua (rate-limit, console lag) hoac mat trong
luc server busy, viec "tru lai so du" bang 1 lenh `eco take` se lam nguoi
choi THAT mat tien.

Ham `restore_balance()` vong lap cho den khi so du server khop muc tieu,
va chi dung `eco take` khi server THUA so voi muc tieu — tuong lai duong
`eco give` chi dung khi server THIEU.

Vi du:
    await restore_balance('Trez1724', 1_038_004, before_srv)
"""
from __future__ import annotations

import asyncio

from app.pika import economy_balance, send_command

# So vong lap toi da — moi vong la 1 lenh console + 1 lan doc so du.
MAX_ROUNDS = 6


async def restore_balance(player: str, target: float, current: float | None = None) -> float:
    """Tra so du Coin tren server ve `target` (lam tron).

    Tra ve so du cuoi cung doc tu server.
    """
    target = round(float(target))
    for _ in range(MAX_ROUNDS):
        cur = await economy_balance(player) if current is None else current
        cur = round(float(cur))
        if abs(cur - target) <= 1:
            return cur
        delta = target - cur
        if delta > 0:
            await send_command(f'eco give {player} {delta}')
        else:
            await send_command(f'eco take {player} {-delta}')
        await asyncio.sleep(2.0)
        current = None  # doc lai tu server
    return round(float(await economy_balance(player)))
