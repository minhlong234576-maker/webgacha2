"""Yeu cau dang nhap truoc khi dung chuc nang.

Kiem tra:
- Khach (chua dang nhap) bi day ve /login khi mo trang game.
- `next` giu lai trang dich -> dang nhap xong quay lai dung cho.
- `next` khong hop le (domain ngoai) -> quay ve /gacha (chong open-redirect).
- API tra 401 cho khach, tru API cong khai (drops/admins).
- Landing page (`/`) van mo cho khach.

Usage: python tests/test_require_login.py [port]
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import asyncio
import sys

import httpx
from playwright.async_api import async_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8101"
BASE = f"http://127.0.0.1:{PORT}"

FAILS = []
PASSES = 0

# Trang co chuc nang -> khach phai bi day ve /login.
GAME_PAGES = ["/gacha", "/battles", "/bonus", "/roulette", "/upgrade", "/inventory", "/vi"]

# API can dang nhap -> phai tra 401.
# (path, method) — method phai dung method that cua route, neu sai se ra 405.
PROTECTED_APIS = [
    ("/api/balance", "GET"),
    ("/api/case/jelly-starter/open", "POST"),
    ("/api/inventory/sell", "POST"),
    ("/api/upgrade/targets", "GET"),
    ("/api/bonus", "POST"),
    ("/api/roulette/state", "GET"),
    ("/api/battles", "GET"),
]

# API cong khai -> van tra 200 cho khach.
PUBLIC_APIS = ["/api/drops", "/api/admins"]


def check(name, cond, detail=""):
    global PASSES
    if cond:
        PASSES += 1
        print(f"  PASS {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"   {detail}" if detail else ""))


async def main():
    print("=== 1. TRANG GAME: KHACH BI DAY VE /LOGIN ===")
    async with httpx.AsyncClient(base_url=BASE, timeout=30,
                                 follow_redirects=False) as c:
        for path in GAME_PAGES:
            r = await c.get(path)
            is_redirect = r.status_code in (302, 303, 307)
            to_login = "login" in r.headers.get("location", "")
            check(f"{path} -> redirect /login", is_redirect and to_login,
                  f"status={r.status_code} loc={r.headers.get('location', '')}")

        print()
        print("=== 2. API: KHACH BI 401 ===")
        for path, method in PROTECTED_APIS:
            r = await c.request(method, path)
            check(f"{method} {path} -> 401", r.status_code == 401, str(r.status_code))

        print()
        print("=== 3. API CONG KHAI VAN 200 ===")
        for path in PUBLIC_APIS:
            r = await c.get(path)
            check(f"GET {path} -> 200", r.status_code == 200, str(r.status_code))

        print()
        print("=== 4. LANDING PAGE VAN MO CHO KHACH ===")
        r = await c.get("/")
        check("/ -> 200", r.status_code == 200, str(r.status_code))
        check("landing co video nen", 'class="lp-video"' in r.text)

        print()
        print("=== 5. NEXT: GIU LAI TRANG DICH ===")
        r = await c.get("/roulette")
        loc = r.headers.get("location", "")
        check("redirect co next=/roulette", "next=%2Froulette" in loc
              or "next=/roulette" in loc, loc)

        print()
        print("=== 6. NEXT KHONG HOP LE -> /gacha (CHONG OPEN-REDIRECT) ===")
        for bad in ["https://evil.com/x", "//evil.com/x", "/etc/passwd", "/"]:
            r = await c.get("/login", params={"next": bad})
            # Trang login van render; kiem tra form co next an toan.
            body = r.text
            m = body.split('name="next" value="')[1].split('"')[0] if 'name="next" value="' in body else ""
            expected = bad if bad in ("/gacha", "/upgrade", "/inventory", "/vi",
                                      "/bonus", "/battles", "/roulette") else "/gacha"
            check(f"next={bad!r} -> {expected}", m == expected, f"got {m!r}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 950})
        page = await ctx.new_page()

        print()
        print("=== 7. UI: MENU KHACH CO O KHOA + HUONG TAI TRANG DANG NHAP ===")
        await page.goto(f"{BASE}/", wait_until="load")
        locked = await page.locator("header nav .nav-link.is-locked").count()
        check("menu khach co 5 muc khoa", locked == 5, str(locked))
        # Bam menu "Ruong" -> ra trang login, khong phai trang game.
        await page.locator("header nav .nav-link.is-locked").first.click()
        await page.wait_for_load_state("load")
        check("bam menu -> den /login", "/login" in page.url, page.url)
        check("trang login hien thong bao 'can dang nhap'",
              "cần đăng nhập" in (await page.inner_text("body")).lower())
        check("login co form next an toan",
              await page.locator('input[name="next"]').count() == 1)

        print()
        print("=== 8. UI: TRANG GAME KHACH KHONG MO DUOC ===")
        for path in ["/gacha", "/bonus", "/roulette", "/battles"]:
            await page.goto(f"{BASE}{path}", wait_until="load")
            check(f"{path} -> /login", "/login" in page.url, page.url)

        print()
        print("=== 9. UI: FORM DANG NHAP LUU NEXT ===")
        await page.goto(f"{BASE}/bonus", wait_until="load")
        nxt = await page.locator('input[name="next"]').get_attribute("value")
        check("next = /bonus", nxt == "/bonus", str(nxt))

        await browser.close()

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> REQUIRE LOGIN TEST PASS")


asyncio.run(main())
