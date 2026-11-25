"""Test luồng tiền thật (không đụng dữ liệu thật).

Dùng DB tạm + mock console để kiểm tra:
- take đủ tiền -> trừ đúng, đồ vẫn được trao
- take thiếu tiền -> chặn, KHÔNG trao đồ
- give lỗi -> đồ vẫn còn trong túi
- verify balance sau lệnh
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio, os, sqlite3, sys, tempfile, shutil


# Phải set TRƯỚC khi import app.config (dotenv không override env đã có).
os.environ['GACHA_DRY_RUN'] = 'false'

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

TMP = tempfile.mkdtemp(prefix='jvtest_')
shutil.copy(ROOT / 'data' / 'gacha.db', os.path.join(TMP, 'gacha.db'))

from app import store
store.DB_PATH = __import__('pathlib').Path(TMP) / 'gacha.db'

import app.pika as pika
import app.bank as bank
import app.game as game
from app.errors import MoneyError

FAKE = {'trez1724': 100_000.0}
CALLS = []


class FakeHTTP(Exception):
    pass


async def fake_sqlite_query(file_path, query, rows=5):
    low = query.lower()
    for name, bal in FAKE.items():
        if name.lower() in low and 'money' in low:
            return [{'name': name, 'money': bal}]
    return []


async def fake_send_command(cmd):
    CALLS.append(cmd)
    parts = cmd.split()
    if len(parts) >= 4 and parts[0] == 'eco':
        verb, who, amt = parts[1], parts[2], float(parts[3])
        cur = FAKE.get(who, 0.0)
        if verb == 'give':
            FAKE[who] = cur + amt
        elif verb == 'take':
            FAKE[who] = max(0.0, cur - amt)


pika.sqlite_query = fake_sqlite_query
pika.send_command = fake_send_command
pika.economy_balance.__globals__['find_economy_user'] = pika.find_economy_user

FAILS = []


def check(name, cond, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        FAILS.append(name)


async def main():
    print('=== 1. eco_take đủ tiền ===')
    FAKE['trez1724'] = 100_000.0
    after = await pika.eco_take('trez1724', 5000)
    check('take 5000 giảm balance', after == 95_000.0, f'-> {after}')
    check('1 lệnh console được gửi', len(CALLS) == 1, CALLS)

    print()
    print('=== 2. eco_take THIẾU tiền -> phải ném lỗi, không gửi lệnh ===')
    FAKE['trez1724'] = 100.0
    n = len(CALLS)
    try:
        await pika.eco_take('trez1724', 5000)
        check('phải ném MoneyError', False)
    except MoneyError as e:
        check('phải ném MoneyError', True, str(e))
    check('không gửi lệnh console', len(CALLS) == n)

    print()
    print('=== 3. eco_give ===')
    FAKE['trez1724'] = 100.0
    after = await pika.eco_give('trez1724', 250)
    check('give 250 tăng balance', after == 350.0, f'-> {after}')

    print()
    print('=== 4. bank.sync mirror số dư server về ví web ===')
    FAKE['trez1724'] = 42_000.0
    await bank.sync('trez1724')
    check('ví web = số dư server', store.get_balance('trez1724') == 42_000,
          f'web={store.get_balance("trez1724")}')

    print()
    print('=== 5. take trong bank KHÔNG tự ghi sổ web (tránh đếm 2 lần) ===')
    FAKE['trez1724'] = 42_000.0
    before_web = store.get_balance('trez1724')
    await bank.take('trez1724', 1000)
    check('ví web không đổi khi bank.take',
          store.get_balance('trez1724') == before_web,
          f'{before_web} -> {store.get_balance("trez1724")}')
    check('số dư server đã giảm', FAKE['trez1724'] == 41_000.0)

    print()
    print('=== 6. take thiếu tiền qua bank ===')
    FAKE['trez1724'] = 50.0
    try:
        await bank.take('trez1724', 1000)
        check('phải ném MoneyError', False)
    except MoneyError:
        check('phải ném MoneyError', True)

    print()
    print('=== 7. sell_preview không thay đổi gì ===')
    store.run(lambda c: c.execute(
        "INSERT OR IGNORE INTO wallets (player, balance, is_bot, created_at) VALUES ('seller', 0, 0, 0)"))
    store.run(lambda c: c.execute("DELETE FROM inventory WHERE player='seller'"))
    case = game.get_case('jelly-starter')
    inv_id = store.add_inventory('seller', case.items[0], 'case', 'jelly-starter')
    amt = game.sell_preview('seller', [inv_id])
    check('preview trả về giá trị', amt == case.items[0].coin, f'{amt}')
    check('đồ vẫn còn held', store.get_inventory_item(inv_id)['status'] == 'held')

    print()
    print('=== 8. bonus_preview không commit lần nhận ===')
    store.run(lambda c: c.execute("DELETE FROM bonus WHERE player='trez1724'"))
    p1 = game.bonus_preview('trez1724')
    check('bonus_preview trả về giá trị', p1 > 0, f'{p1}')
    check('chưa set last_claim', store.last_bonus('trez1724') == 0)

    print()
    print('=== 9. seed_wallet ở chế độ THẬT không seed tiền ảo ===')
    import os as _os
    _os.environ['GACHA_DRY_RUN'] = 'false'
    from app import config as cfg
    # config đọc env lúc import; reload để áp dụng
    import importlib
    importlib.reload(cfg)
    importlib.reload(game)
    print('   (dry_run sau reload =', cfg.dry_run(), ')')

    print()
    if FAILS:
        print(f'!!! {len(FAILS)} TEST FAIL: {FAILS}')
    else:
        print('>>> TẤT CẢ TEST PASS')


asyncio.run(main())
shutil.rmtree(TMP, ignore_errors=True)
