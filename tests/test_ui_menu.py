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
    con = sqlite3.connect(
        os.getenv("GACHA_DB_PATH") or str(ROOT / "data" / "gacha.db")
    )
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

        print()
        print("=== 6. LANDING PAGE ===")
        await page.goto(f"{BASE}/", wait_until="load")
        h1 = await page.locator("h1").count()
        check("landing co duy nhat 1 h1", h1 == 1, str(h1))
        check("landing co video nen", await page.locator("video.lp-video").count() == 1)
        check("landing co bang gia ruong",
              await page.locator(".lp-table tbody tr").count() >= 5)
        check("landing co 3 buoc", await page.locator(".lp-steps li").count() == 3)
        check("landing co 3 che do", await page.locator(".lp-mode").count() == 3)
        check("landing nap landing.css",
              await page.locator('link[href="/static/landing.css"]').count() == 1)
        errors.clear()
        await page.wait_for_timeout(600)
        check("landing khong co loi JS console", not errors, str(errors[:2]))
        # Khong dung game vi nguoi choi -> khong duoc co link Admin
        await page.goto(f"{BASE}/", wait_until="load")
        landing_text = await page.inner_text("body")
        check("landing co CTA dang nhap hoac vao ruong",
              "Đăng nhập" in landing_text or "quầy rương" in landing_text.lower(),
              landing_text[:80])

        print()
        print("=== 7. VIDEO NEN (LANDING) ===")
        # Kiem tra `data-src` TRUOC khi JS kich hoat -> dung context moi de
        # trinh duyet chua co`src` nao (neu kiem tra sau khi JS chay thi
        # `src` da duoc gan va khong con cach nao de chung minh).
        ctx_raw = await browser.new_context(viewport={"width": 1400, "height": 950})
        raw_page = await ctx_raw.new_page()
        # Chan JS module de trinh duyet chua gan `src` (intercept request).
        await raw_page.route("**/static/landing.js", lambda route: route.abort())
        await raw_page.goto(f"{BASE}/", wait_until="load")
        raw_src = await raw_page.eval_on_selector_all(
            "video.lp-video source", "els => els.map(e => e.getAttribute('src'))",
        )
        raw_data = await raw_page.eval_on_selector_all(
            "video.lp-video source", "els => els.map(e => e.getAttribute('data-src'))",
        )
        check("nguon video dung data-src (khong tu tai)",
              all(s is None for s in raw_src) and all(d for d in raw_data),
              f"src={raw_src} data-src={raw_data}")
        await ctx_raw.close()

        await page.goto(f"{BASE}/", wait_until="load")
        check("video co poster",
              await page.locator("video.lp-video").get_attribute("poster")
              == "/static/media/landing-poster.jpg")
        check("video muted + playsinline (khong autoplay keo theo audio)",
              await page.locator("video.lp-video[muted]").count() == 1
              and await page.locator("video.lp-video[playsinline]").count() == 1)
        await page.wait_for_timeout(2500)
        vinfo = await page.evaluate("""() => {
            const v = document.querySelector('video.lp-video');
            return {paused: v.paused, t: v.currentTime, w: v.videoWidth};
        }""")
        check("video phat (khong paused, co currentTime > 0)",
              not vinfo["paused"] and vinfo["t"] > 0, str(vinfo))
        check("video co kich thuoc video thuc", vinfo["w"] > 0, str(vinfo))
        # Khong tran ngang o kich thuoc nho — do bang `scrollX` thuc te sau khi
        # cuon sang phai (scrollWidth co the phan anh noi dung da duoc clip).
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.wait_for_timeout(500)
        sx = await page.evaluate("""() => {
            window.scrollTo(9999, 0);
            const x = window.scrollX;
            window.scrollTo(0, 0);
            return x;
        }""")
        check("landing khong tran ngang tren mobile", sx == 0, f"scrollX={sx}")
        await page.set_viewport_size({"width": 1400, "height": 950})

        await page.screenshot(path=str(ROOT / "_menu.png"))

        await browser.close()

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> UI MENU TEST PASS")


asyncio.run(main())
