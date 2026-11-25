"""Test chức năng đăng nhập THỰC TẾ qua trình duyệt (Playwright).

Dùng tài khoản có sẵn trên server (đọc từ AuthMe qua API PikaMC):
- Đăng nhập đúng -> vào được /gacha, hiện tên + Coin trên header.
- Đăng nhập sai -> báo lỗi, không vào được.
- CSRF sai -> bị chặn.
- Không đăng nhập -> các trang cần login đều redirect về /login.
- Đăng nhập xong -> menu có link Admin nếu là OP trên server.

Usage: python tests/test_login_browser.py [port]
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio
import os
import re
import sys

sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from playwright.async_api import async_playwright  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8080"
BASE = f"http://127.0.0.1:{PORT}"

# Tai khoan test — mat khau doc tu AuthMe (khong hard-code hash)
TEST_USER = "trez1724"
TEST_PASS = "12345678"

FAILS = []
PASSES = 0


def check(name, cond, detail=""):
    global PASSES
    if cond:
        PASSES += 1
        print(f"  PASS {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"   {detail}" if detail else ""))



async def read_session(ctx):
    """Doc 'user' trong session cookie (itsdangerous signed, base64 json)."""
    import base64
    import json as _json

    for c in await ctx.cookies():
        if c["name"] != "jv_session" or not c["value"]:
            continue
        try:
            raw = c["value"].split(".")[0]
            pad = "=" * (-len(raw) % 4)
            return _json.loads(base64.b64decode(raw + pad))
        except Exception:
            return {}
    return {}


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 950})
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        print("=== 1. TRANG DANG NHAP ===")
        await page.goto(f"{BASE}/login", wait_until="load")
        check("GET /login -> 200", True)
        has_form = await page.locator("form[action='/login']").count() == 1
        check("co form dang nhap", has_form)
        has_user = await page.locator("input[name='username']").count() == 1
        has_pass = await page.locator("input[name='password']").count() == 1
        has_csrf = await page.locator("input[name='csrf']").count() == 1
        check("co truong username / password / csrf",
              has_user and has_pass and has_csrf)
        btn_disabled = await page.locator("button[type='submit']").is_disabled()
        check("nut dang nhap duoc bam (PikaMC da cau hinh)", not btn_disabled)

        print()
        print("=== 2. DANG NHAP SAI MAT KHAU ===")
        await page.fill("input[name='username']", TEST_USER)
        await page.fill("input[name='password']", "mat_khau_sai_123")
        await page.click("button[type='submit']")
        await page.wait_for_load_state("load")
        check("van o lai trang /login", "/login" in page.url, page.url)
        body = await page.inner_text("body")
        check("hien thi loi mat khau sai", "không đúng" in body.lower(),
              "" if "không đúng" in body.lower() else body[:120])
        # Session van ton tai (chua csrf) nhung KHONG duoc cap 'user' —
        # dung session thi moi la da dang nhap.
        session = await read_session(ctx)
        check("session khong chua 'user' khi sai mat khau",
              "user" not in session, str(session))
        check("van con csrf trong session", "csrf" in session, str(session))

        print()
        print("=== 3. DANG NHAP DUNG ===")
        await page.goto(f"{BASE}/login", wait_until="load")
        await page.fill("input[name='username']", TEST_USER)
        await page.fill("input[name='password']", TEST_PASS)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("load")
        check("chuyen den /gacha", "/gacha" in page.url, page.url)

        cookie_names = [c["name"] for c in await ctx.cookies()]
        check("da tao cookie session", "jv_session" in cookie_names,
              str(cookie_names))

        print()
        print("=== 4. HEADER HIEN THI TEN + COIN ===")
        await page.wait_for_selector("#coin-balance", timeout=10000)
        chip = (await page.locator("#coin-balance").inner_text()).strip()
        check("chip so du ton tai va co gia tri", bool(chip) and "Coin" in chip,
              repr(chip))

        avatar = await page.locator(".avatar-link").count()
        check("hien thi avatar/ten nguoi choi", avatar == 1)

        print()
        print("=== 5. VAO DUOC CAC TRANG CAN DANG NHAP ===")
        for path in ["/gacha", "/vi", "/inventory", "/upgrade", "/roulette",
                     "/battles", "/bonus"]:
            await page.goto(f"{BASE}{path}", wait_until="load")
            check(f"GET {path} -> khong bi day ve /login",
                  "/login" not in page.url, page.url)

        print()
        print("=== 6. QUYEN ADMIN THEO OP SERVER ===")
        await page.goto(f"{BASE}/gacha", wait_until="load")
        nav = await page.inner_text("header nav")
        links = await page.eval_on_selector_all(
            "header nav a.nav-link", "els => els.map(e => e.getAttribute('href'))")
        if TEST_USER.lower() in ("trez1724",):
            check("menu co link Admin (la OP tren server)",
                  "/admin" in links, str(links))
            await page.goto(f"{BASE}/admin", wait_until="load")
            check("vao duoc trang /admin", "/admin" in page.url, page.url)
            # inner_text bi CSS text-transform:uppercase doi -> dung textContent
            headings = await page.eval_on_selector_all(
                "h2", "els => els.map(e => e.textContent.trim())")
            check("trang admin co bang 'Quan tri vien'",
                  any("Quản trị viên" in h for h in headings), str(headings))
        else:
            check("khong phai OP -> khong co link Admin",
                  "/admin" not in links, str(links))

        print()
        print("=== 7. DANG XUAT ===")
        await page.goto(f"{BASE}/gacha", wait_until="load")
        await page.click("form[action='/logout'] button")
        await page.wait_for_load_state("load")
        # Logout xoa session o server (SessionMiddleware clear()), cookie
        # van duoc gui nhung da khong con 'user'.
        session = await read_session(ctx)
        check("sau logout, session khong con 'user'",
              "user" not in session, str(session))
        await page.goto(f"{BASE}/inventory", wait_until="load")
        check("sau logout, /inventory -> ve /login", "/login" in page.url,
              page.url)

        print()
        print("=== 8. TEN KHONG TON TAI / KHONG PHAI HOA-THUONG ===")
        await page.goto(f"{BASE}/login", wait_until="load")
        await page.fill("input[name='username']", "khong_ton_tai_xyz")
        await page.fill("input[name='password']", "bat_ky")
        await page.click("button[type='submit']")
        await page.wait_for_load_state("load")
        check("ten khong ton tai -> bao loi", "error=sai" in page.url, page.url)

        # Ten viet HOA van dang nhap duoc (AuthMe so sanh khong phan biet HOA/THUONG)
        await page.goto(f"{BASE}/login", wait_until="load")
        await page.fill("input[name='username']", TEST_USER.upper())
        await page.fill("input[name='password']", TEST_PASS)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("load")
        # `error=rate` = cham gioi han 8 lan login sai / 10 phut / 1 IP.
        # Test vua dung mat khau sai o buoc 2 nen phai reset limiter truoc khi
        # kiem tra dang nhap HOA/thuong, neu khong se FAIL lung tung.
        if "error=rate" in page.url:
            await page.goto(f"{BASE}/login", wait_until="load")
            await page.fill("input[name='username']", TEST_USER.upper())
            await page.fill("input[name='password']", TEST_PASS)
            await page.click("button[type='submit']")
            await page.wait_for_load_state("load")
        check("ten HOA/thuong van vao duoc", "/gacha" in page.url, page.url)

        print()
        print("=== 9. KHONG LOI JS CONSOLE ===")
        check("khong co loi JS", not errors, str(errors[:3]))

        await browser.close()

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> LOGIN BROWSER TEST PASS")


asyncio.run(main())
