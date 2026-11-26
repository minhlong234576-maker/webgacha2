"""Test roulette payout path với tiền thật (mock console)."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio, os, sys, tempfile, shutil
os.environ['GACHA_DRY_RUN'] = 'false'
sys.path.insert(0, str(ROOT))

# Dùng DB tạm để KHÔNG đụng vào ví thật.
TMP = tempfile.mkdtemp(prefix='jvroulette_')
shutil.copy(ROOT / 'data' / 'gacha.db', os.path.join(TMP, 'gacha.db'))

# Danh muc mau cho test — KHONG doc `gacha.json` that (admin co the xoa het
# san pham / ca ruong, neu vay test se khong co gi de mo ruong).
sys.path.insert(0, str(ROOT / "tests"))
import fixture_catalog  # noqa: E402

fixture_catalog.use_fixture(Path(TMP))


import app.pika as pika
import app.roulette as roulette
from app import store
store.DB_PATH = Path(TMP) / 'gacha.db'

FAKE = {'trez1724': 100_000.0}
CALLS = []


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
        FAKE[who] = cur + amt if verb == 'give' else max(0.0, cur - amt)


pika.sqlite_query = fake_sqlite_query
pika.send_command = fake_send_command

FAILS = []


def check(name, cond, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + (f'   {detail}' if detail else ''))
    if not cond:
        FAILS.append(name)


async def main():
    mgr = roulette.roulette_manager

    print('=== Roulette: cược thắng phải cộng Coin in-game ===')
    FAKE['trez1724'] = 100_000.0
    CALLS.clear()

    # Ép vòng quay đang BETTING và phe thắng = village
    mgr.status = roulette.STATUS_BETTING
    mgr.winning_side = roulette.SIDE_VILLAGE
    mgr.bets = {roulette.SIDE_VILLAGE: [], roulette.SIDE_STEVE: [], roulette.SIDE_PILLAGER: []}

    store.run(lambda c: c.execute(
        "INSERT OR IGNORE INTO wallets (player, balance, is_bot, created_at) VALUES ('trez1724', 0, 0, 0)"))
    store.set_wallet('trez1724', 100_000)

    mgr.place_bet('trez1724', roulette.SIDE_VILLAGE, 1000, is_bot=False)
    # Thêm 1 bot cược để chắc chắn nhánh bot được bỏ qua
    mgr.bets[roulette.SIDE_VILLAGE].append(
        {'player': 'JellyBot', 'side': roulette.SIDE_VILLAGE, 'amount': 5000,
         'is_bot': True, 'timestamp': 0})

    before = FAKE['trez1724']
    mgr._settle_payouts()
    await mgr.payout_real_bets()
    after = FAKE['trez1724']

    check('người chơi được trả x2 (1000 -> +2000)', abs((after - before) - 2000) < 1,
          f'{before} -> {after}')
    check('bot KHÔNG được trả Coin thật',
          len([c for c in CALLS if 'JellyBot' in c]) == 0, CALLS)
    check('chỉ 1 lệnh give cho người chơi',
          len([c for c in CALLS if 'trez1724' in c]) == 1, CALLS)

    print()
    print('=== Roulette: cược thua không được trả ===')
    FAKE['trez1724'] = 100_000.0
    CALLS.clear()
    mgr.status = roulette.STATUS_BETTING
    mgr.winning_side = roulette.SIDE_STEVE
    mgr.bets = {roulette.SIDE_VILLAGE: [], roulette.SIDE_STEVE: [], roulette.SIDE_PILLAGER: []}
    mgr.place_bet('trez1724', roulette.SIDE_VILLAGE, 1000, is_bot=False)
    before = FAKE['trez1724']
    mgr._settle_payouts()
    await mgr.payout_real_bets()
    check('không cộng Coin thật khi thua', FAKE['trez1724'] == before, f'{FAKE["trez1724"]}')
    check('không gửi lệnh give', len(CALLS) == 0, CALLS)

    print()
    if FAILS:
        print(f'!!! {len(FAILS)} FAIL: {FAILS}')
    else:
        print('>>> ROULETTE TEST PASS')


asyncio.run(main())
shutil.rmtree(TMP, ignore_errors=True)
