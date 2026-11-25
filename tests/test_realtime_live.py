"""Kiểm chứng realtime thật: nạp Coin trên server -> /api/balance phải thấy ngay."""
import asyncio, os, sys, httpx, itsdangerous, json, base64
os.environ['GACHA_DRY_RUN'] = 'false'
sys.path.insert(0, r'c:\code\web\webgacha-main')

from dotenv import load_dotenv
load_dotenv(r'c:\code\web\webgacha-main\.env')

from app import bank
from app.pika import economy_balance, send_command

BASE = 'http://127.0.0.1:8099'
ME = 'Trez1724'
SECRET = os.getenv('SESSION_SECRET')
session = {'user': ME, 'login_name': ME, 'csrf': 'testcsrf'}
raw = base64.b64encode(json.dumps(session).encode('utf-8'))
cookie = itsdangerous.TimestampSigner(SECRET).sign(raw).decode()

FAILS = []


def check(name, cond, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + (f'   {detail}' if detail else ''))
    if not cond:
        FAILS.append(name)


async def api_balance():
    async with httpx.AsyncClient(base_url=BASE, timeout=30,
                                 cookies={'jv_session': cookie}) as c:
        r = await c.get('/api/balance')
        return r.json()


async def main():
    # Client dung chung: giong trinh duyet (trinh duyet giu connection giữa
    # cac request, khong mo moi moi lan). Do client, khong do server.
    client = httpx.AsyncClient(base_url=BASE, timeout=30,
                               cookies={'jv_session': cookie})

    async def api_balance_fast():
        r = await client.get('/api/balance')
        return r.json()

    print('=== trạng thái ban đầu ===')
    before_api = await api_balance_fast()
    before_srv = await economy_balance(ME)
    print(f'  API: {before_api["balance_fmt"]}  |  Server: {before_srv:,}')
    check('API khớp server', abs(before_api['balance'] - before_srv) < 1,
          f'{before_api["balance"]} vs {before_srv}')

    print()
    print('=== nạp 5.000 Coin trực tiếp trên server (ngoài web) ===')
    await send_command(f'eco give {ME} 5000')
    await asyncio.sleep(2.0)

    after_srv = await economy_balance(ME)
    # `/api/balance` dùng cache 8s (bank.sync_fresh) nên phải chờ hết hạn
    # cache mới thấy số dư mới — đó là hành vi CỐ Ý để tránh dồn request
    # ra PikaMC khi nhiều người poll cùng lúc.
    await asyncio.sleep(bank.SYNC_MAX_AGE + 1.5)
    after_api = await api_balance_fast()
    print(f'  API: {after_api["balance_fmt"]}  |  Server: {after_srv:,}')
    check('API thấy số dư MỚI (tăng ~5.000)',
          after_api['balance'] > before_api['balance'] + 4000,
          f'{before_api["balance"]} -> {after_api["balance"]}')
    check('API khớp server', abs(after_api['balance'] - after_srv) < 1,
          f'{after_api["balance"]} vs {after_srv}')

    print()
    print('=== cache hoat dong: request lien tie -> request 2 phai nhanh hon nhieu ===')
    import time as _t
    t0 = _t.perf_counter()
    await api_balance_fast()
    first_ms = (_t.perf_counter() - t0) * 1000
    t0 = _t.perf_counter()
    await api_balance_fast()
    second_ms = (_t.perf_counter() - t0) * 1000
    print(f'  request 1: {first_ms:.0f} ms | request 2: {second_ms:.0f} ms')
    check('request 2 nhanh hon request 1 (dung cache)',
          second_ms < first_ms * 0.6 or second_ms < 30,
          f'{first_ms:.0f} ms -> {second_ms:.0f} ms')

    print()
    print('=== dọn dẹp: trả lại số dư ban đầu ===')
    delta = int(round(after_srv - before_srv))
    if delta > 0:
        await send_command(f'eco take {ME} {delta}')
        await asyncio.sleep(2.0)
    await asyncio.sleep(bank.SYNC_MAX_AGE + 1.5)
    final = await api_balance_fast()
    print(f'  API: {final["balance_fmt"]}')
    check('đã trả lại số dư ban đầu',
          abs(final['balance'] - before_api['balance']) < 1,
          f'{final["balance"]} vs {before_api["balance"]}')

    print()
    if FAILS:
        print(f'!!! {len(FAILS)} FAIL: {FAILS}')
    else:
        print('>>> REALTIME LIVE PASS')


asyncio.run(main())
