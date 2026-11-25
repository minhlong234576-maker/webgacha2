"""Đo tốc độ đồng bộ — đường găng tiền thật."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio, os, sys, time
os.environ['GACHA_DRY_RUN'] = 'false'
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app import bank, store
from app.pika import economy_balance, economy_balances


async def main():
    print('=== 1. economy_balances(): đọc TOÀN BỘ server trong 1 request ===')
    t0 = time.perf_counter()
    bal = await economy_balances()
    dt = (time.perf_counter() - t0) * 1000
    print(f'  {len(bal)} người chơi trong {dt:.0f} ms')

    print()
    print('=== 2. economy_balance(): đọc 1 người ===')
    t0 = time.perf_counter()
    await economy_balance('Trez1724')
    print(f'  {(time.perf_counter() - t0) * 1000:.0f} ms')

    print()
    print('=== 3. bank.sync_all(): mirror toàn bộ ví web ===')
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        n = await bank.sync_all()
        times.append((time.perf_counter() - t0) * 1000)
    print(f'  {n} ví, mỗi lần: {min(times):.0f}–{max(times):.0f} ms')

    print()
    print('=== 4. bank.sync(): đồng bộ 1 người ===')
    t0 = time.perf_counter()
    await bank.sync('Trez1724')
    print(f'  {(time.perf_counter() - t0) * 1000:.0f} ms')

    print()
    print('=== 5. Ghi số dư 41 ví (phần local của sync) ===')
    t0 = time.perf_counter()
    store.run(lambda c: c.executemany(
        "UPDATE wallets SET balance = balance WHERE player = ?",
        [(p,) for p in list(bal)[:41]]))
    print(f'  {(time.perf_counter() - t0) * 1000:.1f} ms')


asyncio.run(main())
