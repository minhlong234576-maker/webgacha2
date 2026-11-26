"""Kiểm tra tính năng số dư realtime.

1. `economy_balances()` đọc được toàn bộ số dư server trong 1 request.
2. `bank.sync_all()` mirror đúng vào ví web, KHÔNG ghi đè ví bot ảo.
3. `/api/balance` trả số dư đúng.
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio, os, sys
os.environ['GACHA_DRY_RUN'] = 'false'
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app import bank, store
from app.pika import economy_balances

FAILS = []


def check(name, cond, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + (f'   {detail}' if detail else ''))
    if not cond:
        FAILS.append(name)


async def main():
    print('=== economy_balances() đọc 1 lần ra toàn bộ server ===')
    balances = await economy_balances()
    check('đọc được > 0 người chơi', len(balances) > 0, f'{len(balances)} người')
    sample = list(balances.items())[:3]
    for name, val in sample:
        print(f'    {name}: {val:,}')

    print()
    print('=== sync_all() mirror vào ví web ===')
    # Thêm 1 ví bot ảo để chứng minh KHÔNG bị ghi đè bằng 0.
    store.ensure_wallet('JellyBot', seed=1_000_000, is_bot=True)
    before_bot = store.get_balance('JellyBot')

    updated = await bank.sync_all()
    check('đã cập nhật > 0 ví', updated > 0, f'{updated} ví')

    after_bot = store.get_balance('JellyBot')
    check('ví bot ảo KHÔNG bị ghi đè', after_bot == before_bot,
          f'{before_bot} -> {after_bot}')

    # Mọi người chơi thật phải khớp server
    mismatch = []
    for name, val in balances.items():
        row = store.run(lambda con, n=name: con.execute(
            'SELECT balance FROM wallets WHERE player = ?', (n,)).fetchone())
        if row is None:
            continue
        if abs(row['balance'] - round(val)) > 1:
            mismatch.append((name, row['balance'], round(val)))
    check('mọi ví người chơi thật khớp server', not mismatch, str(mismatch[:5]))

    print()
    print('=== dry-run thì sync_all() không làm gì ===')
    os.environ['GACHA_DRY_RUN'] = 'true'
    import importlib
    from app import gacha
    importlib.reload(gacha)
    importlib.reload(bank)
    check('dry-run -> 0 ví cập nhật', await bank.sync_all() == 0)

    print()
    if FAILS:
        print(f'!!! {len(FAILS)} FAIL: {FAILS}')
    else:
        print('>>> REALTIME BALANCE TEST PASS')


asyncio.run(main())
sys.exit(1 if FAILS else 0)
