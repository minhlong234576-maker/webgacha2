"""Tai khoan THAT tren server (AuthMe -> PikaMC): dang nhap + chay chuc nang.

KHONG chay trong `run_all.py` mac dinh — can mat khau tai khoan that.
Chay tay:
    $env:JV_TEST_USER="hhh21"; $env:JV_TEST_PASS="<mat khau>"; \\
        .\\.venv\\Scripts\\python.exe tests\\test_live_account_browser.py 8080

Luu y: script nay DUNG tien that tren server (GACHA_DRY_RUN=false), nen
mo ruong se that tien trong game. Chi chay khi ban muon.
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio
import os
import sys

sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from playwright.async_api import async_playwright  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8080"
BASE = f"http://127.0.0.1:{PORT}"

TEST_USER = os.getenv("JV_TEST_USER", "hhh21")
TEST_PASS = os.getenv("JV_TEST_PASS", "")

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


async def main():
    if not TEST_PASS:
        print("THIEU MAT KHAU: dat JV_TEST_PASS truoc khi chay.")
        return 2

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 950})
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        print("=== 1. DANG NHAP THAT ===")
        await page.goto(f"{BASE}/login", wait_until="load")
        await page.fill("input[name='username']", TEST_USER)
        await page.fill("input[name='password']", TEST_PASS)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("load")
        check("dang nhap thanh cong -> /gacha", "/gacha" in page.url, page.url)
        if "/gacha" not in page.url:
            body = await page.inner_text("body")
            print("     noi dung trang:", body[:200])
            await browser.close()
            return 1

        cookie_names = [c["name"] for c in await ctx.cookies()]
        check("da tao cookie jv_session", "jv_session" in cookie_names, str(cookie_names))

        print()
        print("=== 2. HEADER HIEN THI TEN + COIN ===")
        await page.wait_for_selector("#coin-balance", timeout=15000)
        chip = (await page.locator("#coin-balance").inner_text()).strip()
        check("chip so du co gia tri", bool(chip) and "Coin" in chip, repr(chip))
        check("avatar nguoi choi hien thi",
              await page.locator(".avatar-link").count() == 1)

        print()
        print("=== 3. VAO DUOC MOI TRANG CAN DANG NHAP ===")
        for path, must in [
            ("/gacha", "Mở rương"),
            ("/vi", "Ví"),
            ("/inventory", "Túi đồ"),
            ("/upgrade", "Nâng cấp"),
            ("/roulette", "Roulette"),
            ("/battles", "Battle"),
            ("/bonus", "Bonus"),
        ]:
            await page.goto(f"{BASE}{path}", wait_until="load")
            text = (await page.inner_text("body")).lower()
            check(f"GET {path} -> khong bi day ve /login", "/login" not in page.url, page.url)
            check(f"GET {path} co noi dung '{must}'", must.lower() in text, page.url)

        print()
        print("=== 4. MO RUONG THAT ===")
        await page.goto(f"{BASE}/case/jelly-starter", wait_until="load")
        check("GET /case/jelly-starter -> 200", "/case/jelly-starter" in page.url, page.url)

        before = (await page.locator("#coin-balance").inner_text()).strip()
        opened = await page.evaluate("""async () => {
            const csrf = document.querySelector('meta[name=csrf]').content;
            const r = await fetch('/api/case/jelly-starter/open', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRF': csrf},
                body: JSON.stringify({count: 1})
            });
            return {status: r.status, body: await r.json()};
        }""")
        check("POST /api/case/.../open -> 200",
              opened["status"] == 200, str(opened["status"]) + " " + str(opened["body"])[:120])
        check("co openings tra ve", "openings" in (opened["body"] or {}),
              str(list((opened["body"] or {}).keys()))[:120])

        print()
        print("=== 5. DO DONG VUI ===")
        await page.goto(f"{BASE}/inventory", wait_until="load")
        inv_count = await page.locator(".inv-card").count()
        check("tui do co mon (sau khi mo ruong)", inv_count >= 1, f"{inv_count} mon")

        print()
        print("=== 6. API DOC ===")
        for path, must_key in [
            ("/api/drops", "drops"),
            ("/api/balance", "balance_fmt"),
            ("/api/roulette/state", "round_id"),
            ("/api/upgrade/targets", None),
            ("/api/admins", "admins"),
        ]:
            res = await page.evaluate(f"""async () => {{
                const r = await fetch('{path}');
                return {{status: r.status, body: await r.json()}};
            }}""")
            ok = res["status"] == 200
            if must_key:
                ok = ok and must_key in (res["body"] or {})
            check(f"GET {path} -> 200", ok, str(res["status"]))

        print()
        print("=== 7. LOGOUT VA KHOA ===")
        await page.goto(f"{BASE}/gacha", wait_until="load")
        await page.evaluate("""async () => {
            const csrf = document.querySelector('meta[name=csrf]').content;
            await fetch('/logout', {method: 'POST', headers: {'X-CSRF': csrf}});
        }""")
        await page.goto(f"{BASE}/inventory", wait_until="load")
        check("sau logout /inventory -> ve /login", "/login" in page.url, page.url)

        print()
        print("=== 8. LOI CONSOLE TRONG TRANG ===")
        real_errors = [e for e in errors if "favicon" not in e.lower()]
        check("khong co loi JS console", not real_errors, str(real_errors[:3]))

        await browser.close()

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    for f in FAILS:
        print("FAIL:", f)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
