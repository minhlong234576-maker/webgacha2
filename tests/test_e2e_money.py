"""Kiểm chứng luồng tiền thật END-TO-END với server PikaMC thật.

Dùng tài khoản Trez1724 (admin, ví 0 Coin). Sẽ:
1. Cho 1 khoản nhỏ vào ví
2. Mở 1 rương (kiểm tra tiền bị trừ đúng, đồ vào túi)
3. Bán đồ (kiểm tra tiền được cộng lại)
4. Kiểm tra số dư server khớp số dư web
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio, os, sys
os.environ['GACHA_DRY_RUN'] = 'false'
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx
from app import bank, game, store
from app.pika import economy_balance, send_command

ME = 'Trez1724'
FAILS = []


def check(name, cond, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + (f'   {detail}' if detail else ''))
    if not cond:
        FAILS.append(name)


async def main():
    print('=== Chuẩn bị: dọn túi + nạp 20.000 Coin thật ===')
    store.run(lambda c: c.execute("DELETE FROM inventory WHERE player=?", (ME,)))
    await send_command(f'eco give {ME} 20000')
    await asyncio.sleep(1.5)
    bal0 = await economy_balance(ME)
    check('ví server = 20.000', abs(bal0 - 20000) < 1, f'-> {bal0}')
    await bank.sync(ME)
    check('ví web mirror = server', store.get_balance(ME) == round(bal0),
          f'web={store.get_balance(ME)}')

    print()
    print('=== Mở rương jelly-starter (giá 3.500) ===')
    case = game.get_case('jelly-starter')
    cost = case.pull_cost
    before = await economy_balance(ME)
    batch = game.open_case_batch(ME, 'jelly-starter', count=1)  # ghi sổ web
    await bank.take(ME, cost)                                  # trừ tiền thật
    after = await economy_balance(ME)
    check(f'đã trừ {cost} Coin thật', abs((before - after) - cost) < 1,
          f'{before} -> {after} (chênh {before-after})')
    inv = store.list_inventory(ME, 'held')
    check('đồ vào túi', len(inv) == 1, f'{len(inv)} món')
    check('tiền thật khớp giá rương', round(before - after) == cost)

    print()
    print('=== Bán đồ ===')
    item = inv[0]
    sell_val = item['value']
    before = await economy_balance(ME)
    await bank.give(ME, sell_val)          # cộng tiền thật
    game.sell_items(ME, [item['id']])       # ghi sổ web
    after = await economy_balance(ME)
    check(f'đã cộng {sell_val} Coin thật', abs((after - before) - sell_val) < 1,
          f'{before} -> {after}')
    check('đồ không còn held', len(store.list_inventory(ME, 'held')) == 0)

    print()
    print('=== Chặn khi thiếu tiền ===')
    await send_command(f'eco take {ME} 999999')
    await asyncio.sleep(1.5)
    bal = await economy_balance(ME)
    check('ví server gần 0', bal < 100, f'-> {bal}')
    try:
        await bank.take(ME, 5000)
        check('phải chặn (MoneyError)', False, 'KHÔNG ném lỗi!')
    except Exception as e:
        check('phải chặn (MoneyError)', True, f'{type(e).__name__}: {e}')

    print()
    print('=== Dọn dẹp: trả lại 0 Coin + xoá lịch sử test ===')
    await send_command(f'eco take {ME} 999999')
    await asyncio.sleep(1.5)
    final = await economy_balance(ME)
    check('ví server = 0', final < 1, f'-> {final}')
    await bank.sync(ME)
    check('ví web = 0', store.get_balance(ME) == 0)

    # Dọn toàn bộ dấu vết test khỏi DB thật (pulls/drops/tx/inventory của ME).
    def cleanup(con):
        for t in ('pulls', 'drops', 'inventory', 'tx'):
            con.execute(f'DELETE FROM "{t}" WHERE player = ?', (ME,))
    store.run(cleanup)
    left = {t: store.run(lambda con, t=t: con.execute(
        f'SELECT COUNT(*) FROM "{t}" WHERE player = ?', (ME,)).fetchone()[0])
        for t in ('pulls', 'drops', 'inventory', 'tx')}
    check('không còn dữ liệu test trong DB', all(v == 0 for v in left.values()), str(left))

    print()
    if FAILS:
        print(f'!!! {len(FAILS)} FAIL: {FAILS}')
    else:
        print('>>> END-TO-END PASS')


asyncio.run(main())
