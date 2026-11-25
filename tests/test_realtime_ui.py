"""Kiểm chứng UI bằng Playwright: chip số dư realtime cập nhật khi Coin trên server đổi."""
import asyncio, os, sys, json, base64, itsdangerous
from dotenv import load_dotenv

load_dotenv(r'c:\code\web\webgacha-main\.env')
sys.path.insert(0, r'c:\code\web\webgacha-main')

from playwright.async_api import async_playwright
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
        check('chip khớp số dư server',
              ''.join(ch for ch in after if ch.isdigit()) ==
              f'{int(round(await economy_balance(ME)))}',
              f'{after} vs {await economy_balance(ME)}')

        await page.screenshot(path=r'c:\code\web\webgacha-main\tests\_realtime.png')

        # Dọn dẹp
        delta = int(round(await economy_balance(ME) - srv_before))
        if delta > 0:
            await send_command(f'eco take {ME} {delta}')
            await asyncio.sleep(2)

        check('không có lỗi JS console', not errors, str(errors[:3]))
        await browser.close()

    print()
    if FAILS:
        print(f'!!! {len(FAILS)} FAIL: {FAILS}')
    else:
        print('>>> UI REALTIME PASS')


asyncio.run(main())
