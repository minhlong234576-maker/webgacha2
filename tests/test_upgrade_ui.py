"""E2E frontend: trang /upgrade voi co che 2 mon len 1 mon.

Dung Playwright headless (Chromium da cai san).
Usage: python tests/test_upgrade_ui.py [port]
"""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["GACHA_DRY_RUN"] = "true"

from dotenv import load_dotenv  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

load_dotenv(ROOT / ".env")

PORT = sys.argv[1] if len(sys.argv) > 1 else "8101"
BASE = f"http://127.0.0.1:{PORT}"
QA_PLAYER = "QA_Tester_01"

import itsdangerous  # noqa: E402
from app import config  # noqa: E402

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


def make_cookie(user):
    raw = base64.b64encode(json.dumps({
        "user": user, "login_name": user, "csrf": "test-csrf"
    }).encode("utf-8"))
    return itsdangerous.TimestampSigner(config.SESSION_SECRET).sign(raw).decode()


async def main():
    cookie = make_cookie(QA_PLAYER)
    # Dam bao QA_Tester_01 co it nhat 4 mon trong tui (UI test can >= 3
    # checkbox de kiem tra gioi han "chi 2 mon"). Server va test process
    # cung dung mot file DB (GACHA_DB_PATH) nen ghi truc tiep vao do.
    import sqlite3

    db_path = os.getenv("GACHA_DB_PATH") or str(ROOT / "data" / "gacha.db")
    con = sqlite3.connect(db_path)
    have = con.execute(
        "SELECT COUNT(*) FROM inventory WHERE player = ? AND status = 'held'",
        (QA_PLAYER,),
    ).fetchone()[0]
    if have < 4:
        from app.gacha import load_cases

        case = load_cases()[0]
        for item in case.items[: 4 - have]:
            con.execute(
                "INSERT INTO inventory (player, item_id, name, rarity, value,"
                " image, color, source, status, case_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'test', 'held', ?, ?)",
                (QA_PLAYER, item.id, item.name, item.rarity, item.coin,
                 item.image, item.color, case.id, int(__import__("time").time())),
            )
        con.commit()
    con.close()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context()
        await ctx.add_cookies([{
            "name": "jv_session", "value": cookie, "domain": "127.0.0.1", "path": "/",
        }])
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        print("=== 1. TRANG LOAD, KHONG LOI JS ===")
        resp = await page.goto(f"{BASE}/upgrade", wait_until="load")
        check("GET /upgrade -> 200", resp.status == 200, str(resp.status))
        await page.wait_for_timeout(500)
        check("khong co loi JS console", not errors, str(errors[:3]))

        print()
        print("=== 2. CO CHECKBOX (semantics) ===")
        boxes = page.locator("#stakes input[type=checkbox]")
        n = await boxes.count()
        check("co checkbox cho mon cuoc", n >= 2, f"{n} checkbox")
        check("nut 'Nang cap' ban dau disabled", await page.locator("#go").is_disabled())

        print()
        print("=== 3. CHON 1 MON -> VAN CHUA BATC DUOC ===")
        await boxes.nth(0).check()
        await page.wait_for_timeout(400)
        check("chon 1 mon: nut van disabled", await page.locator("#go").is_disabled())
        hint = await page.locator("#stake-hint").inner_text()
        check("chon 1 mon: hint nhac day du 2 mon", "2" in hint, hint)
        check("chon 1 mon: targets chua co mon dich",
              (await page.locator("#targets .tgt").count()) == 0)

        print()
        print("=== 4. CHON MON THU 2 -> TARGETS XUAT HIEN ===")
        await boxes.nth(1).check()
        await page.wait_for_timeout(900)
        n_tgt = await page.locator("#targets .tgt").count()
        check("chon 2 mon: co danh sach mon dich", n_tgt > 0, f"{n_tgt} mon")
        check("chon 2 mon: nut van disabled (chua chon dich)",
              await page.locator("#go").is_disabled())

        print()
        print("=== 5. CHON MON DICH -> NUT BAT ===")
        await page.locator("#targets .tgt").first.click()
        await page.wait_for_timeout(300)
        check("chon dich: nut 'Nang cap' bat", not await page.locator("#go").is_disabled())
        gauge_text = await page.locator("#gauge-label").inner_text()
        check("gauge hien ty le > 0", "%" in gauge_text, gauge_text)

        print()
        print("=== 6. CHON THEM MON THU 3 -> BI CHAN ===")
        # Dùng `click()` chứ không `check()`: app cố ý BỎ TICK checkbox thứ 3,
        # nên `check()` (vốn assert trạng thái phải đổi) sẽ raise error.
        await boxes.nth(2).click()
        await page.wait_for_timeout(400)
        check("chon 3 mon: checkbox thu 3 bi bo tick",
              not await boxes.nth(2).is_checked())
        result_text = await page.locator("#up-result").inner_text()
        check("chon 3 mon: hien thong bao", "2" in result_text, result_text)
        check("chon 3 mon: van chi co 2 mon duoc chon",
              await page.locator("#stakes input[type=checkbox]:checked").count() == 2)

        print()
        print("=== 7. BO MOT MON -> HUY TRANG THAI ===")
        await boxes.nth(1).uncheck()
        await page.wait_for_timeout(500)
        check("bo 1 mon: nut lai disabled", await page.locator("#go").is_disabled())
        check("bo 1 mon: danh sach dich bi reset",
              (await page.locator("#targets .tgt").count()) == 0)

        print()
        print("=== 8. CHON LAI 2 MON -> SAN SANG ===")
        # Sau buoc 7 chi con box 0 con duoc tick -> tick them 1 mon nua la du 2.
        await boxes.nth(1).check()
        await page.wait_for_timeout(900)
        check("chon lai 2 mon: co danh sach dich",
              (await page.locator("#targets .tgt").count()) > 0)
        await page.locator("#targets .tgt").first.click()
        await page.wait_for_timeout(300)
        check("chon lai 2 mon: nut bat", not await page.locator("#go").is_disabled())

        print()
        print("=== 9. BAM 'NANG CAP' -> API TRA KET QUA ===")
        await page.locator("#go").click()
        # Vòng quay mất 3.6s rồi mới hiện kết quả -> chờ tới khi xuất hiện
        # "Thắng"/"Thua" thay vì đợi cứng.
        try:
            await page.wait_for_function(
                "() => { const t = document.querySelector('#up-result')?.textContent || '';"
                " return t.includes('Thắng') || t.includes('Thua'); }",
                timeout=8000,
            )
        except Exception:
            pass
        out = await page.locator("#up-result").inner_text()
        check("bam nang cap: co ket qua (thang/thua)", ("Thắng" in out or "Thua" in out), out)
        check("bam nang cap: khong con 'Dang nang cap'",
              "Đang nâng cấp" not in out, out)

        print()
        print("=== 10. KHONG CO LOI JS ===")
        check("khong loi JS sau khi thao tac", not errors, str(errors[:3]))

        await page.screenshot(path=str(ROOT / "_upgrade_ui.png"))
        await browser.close()

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> UPGRADE UI TEST PASS")


asyncio.run(main())
