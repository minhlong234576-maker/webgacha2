"""Kiểm chứng UI bằng Playwright: chip số dư realtime cập nhật khi Coin trên server đổi."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio, os, sys, json, base64, itsdangerous
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from playwright.async_api import async_playwright
from app.pika import economy_balance, send_command
from balance_restore import restore_balance

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


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        await ctx.add_cookies([{
            'name': 'jv_session', 'value': cookie,
            'domain': '127.0.0.1', 'path': '/',
        }])
        page = await ctx.new_page()
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append(str(e)))

        await page.goto(f'{BASE}/gacha')
        await page.wait_for_load_state('networkidle')

        chip = page.locator('#coin-balance')
        check('chip số dư tồn tại', await chip.count() == 1)
        before = (await chip.inner_text()).strip()
        print(f'  chip ban đầu: {before!r}')

        srv_before = await economy_balance(ME)

        # Nạp Coin ngoài web -> chờ polling 10s -> chip phải tự đổi
        await send_command(f'eco give {ME} 7000')
        await asyncio.sleep(2.5)

        await page.wait_for_function(
            "() => document.getElementById('coin-balance').textContent !== "
            f"{json.dumps(before)}",
            timeout=20000,
        )
        after = (await chip.inner_text()).strip()
        print(f'  chip sau:     {after!r}')
        check('chip tự cập nhật khi Coin server đổi', after != before, f'{before} -> {after}')

        # Chip poll `/api/balance` moi 10s -> co the hien gia TRUNG GIAN
        # (vd 255) khi server da tang len 7000. Cho chip hoi dap den khi khop
        # voi so du server truoc khi ket luan (tranh FAIL lung tung).
        srv_now = await economy_balance(ME)
        for _ in range(12):
            after = (await chip.inner_text()).strip()
            digits = ''.join(ch for ch in after if ch.isdigit())
            if digits == f'{int(round(srv_now))}':
                break
            await asyncio.sleep(1.5)
            srv_now = await economy_balance(ME)
        check('chip khớp số dư server',
              ''.join(ch for ch in after if ch.isdigit()) ==
              f'{int(round(srv_now))}',
              f'{after} vs {srv_now}')

        await page.screenshot(path=str(ROOT / "tests" / "_realtime.png"))

        # Dọn dẹp — vong lap cho den khi so du server khop muc tieu (mot lenh
        # `eco take` co the khong chay xong -> nguoi choi THAT mat tien).
        final_srv = await restore_balance(ME, srv_before)
        check('số dư server trả về đúng gốc',
              abs(final_srv - round(srv_before)) <= 1,
              f'{final_srv} vs {srv_before}')

        check('không có lỗi JS console', not errors, str(errors[:3]))
        await browser.close()

    print()
    if FAILS:
        print(f'!!! {len(FAILS)} FAIL: {FAILS}')
    else:
        print('>>> UI REALTIME PASS')


asyncio.run(main())
sys.exit(1 if FAILS else 0)
