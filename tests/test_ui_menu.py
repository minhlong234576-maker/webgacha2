"""Kiem tra UI thuc: menu khong con 'Hop dong', va cac trang van render dung.

Dung Playwright headless (Chromium da cai san).
Usage: python tests/test_ui_menu.py [port]
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio
import base64
import json
import os
import sys

from dotenv import load_dotenv
from playwright.async_api import async_playwright


os.environ["GACHA_DRY_RUN"] = "true"
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

PORT = sys.argv[1] if len(sys.argv) > 1 else "8101"
BASE = f"http://127.0.0.1:{PORT}"
SECRET = os.getenv("SESSION_SECRET")

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


QA_PLAYER = "QA_Tester_01"


def make_cookie(user):
    session = {"user": user, "login_name": user, "csrf": "test-csrf"}
    raw = base64.b64encode(json.dumps(session).encode("utf-8"))
    return itsdangerous_signed(raw)


def itsdangerous_signed(raw):
    import itsdangerous
    return itsdangerous.TimestampSigner(SECRET).sign(raw).decode()


async def main():
    cookie = make_cookie(QA_PLAYER)
    # Dam bao player QA ton tai trong DB (vi khong can login that)
    import sqlite3
    con = sqlite3.connect(str(ROOT / "data" / "gacha.db"))
    con.execute(
        "INSERT INTO wallets (player, balance, is_bot, created_at) "
        "VALUES (?, 500000, 0, 0) ON CONFLICT(player) DO UPDATE SET balance = 500000",
        (QA_PLAYER,),
    )
    con.commit()
    con.close()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context()
        await ctx.add_cookies([{
            "name": "jv_session", "value": cookie, "domain": "127.0.0.1",
            "path": "/",
        }])
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        print("=== 1. MENU KHONG CON 'HOP DONG' ===")
        for path in ["/gacha", "/roulette", "/battles", "/upgrade", "/bonus",
                     "/inventory", "/vi", "/admin"]:
            await page.goto(f"{BASE}{path}", wait_until="load")
            links = await page.eval_on_selector_all(
                "header nav a.nav-link",
                "els => els.map(e => ({href: e.getAttribute('href'), text: e.textContent.trim()}))",
            )
            has_contract = any(l["href"] == "/contract" for l in links)
            check(f"{path}: menu khong co /contract", not has_contract,
                  str([l["href"] for l in links]))
            check(f"{path}: menu van render day du", len(links) >= 5,
                  f"{len(links)} link")

        print()
        print("=== 2. KHONG CON TEXT 'HOP DONG' O BAT KY TRANG ===")
        for path in ["/gacha", "/inventory", "/upgrade", "/vi", "/admin",
                     "/roulette", "/battles", "/bonus"]:
            await page.goto(f"{BASE}{path}", wait_until="load")
            text = await page.inner_text("body")
            check(f"{path}: khong con chu 'Hop dong'", "Hợp đồng" not in text,
                  "van con" if "Hợp đồng" in text else "")

        print()
        print("=== 3. /contract TRA VE 404 ===")
        resp = await page.goto(f"{BASE}/contract", wait_until="load")
        check("GET /contract -> 404", resp.status == 404, str(resp.status))

        print()
        print("=== 4. CAC TRANG VAN HOAT DONG (khong loi JS) ===")
        for path in ["/gacha", "/roulette", "/battles", "/upgrade", "/bonus",
                     "/inventory", "/vi", "/admin"]:
            errors.clear()
            await page.goto(f"{BASE}{path}", wait_until="load")
            await page.wait_for_timeout(700)
            check(f"{path}: khong co loi JS console", not errors, str(errors[:2]))

        print()
        print("=== 5. MENU HIEN THI DUNG ===")
        await page.goto(f"{BASE}/gacha", wait_until="load")
        nav_text = await page.inner_text("header nav")
        for want in ["Rương", "Roulette", "Battle", "Nâng cấp", "Bonus"]:
            check(f"menu co '{want}'", want in nav_text)

        await page.screenshot(path=str(ROOT / "_menu.png"))

        await browser.close()

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> UI MENU TEST PASS")


asyncio.run(main())
