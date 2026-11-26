"""Regression & security tests for SafeSessionMiddleware, input validation, headers, and NexoMC."""
from __future__ import annotations

from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio
import base64
import json
import os
import shutil
import sys
import tempfile

import httpx
import itsdangerous

os.environ["GACHA_DRY_RUN"] = "true"
os.environ["GACHA_NEXO_WITHDRAW"] = "false"
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="jvsec_")
shutil.copy(ROOT / "data" / "gacha.db", os.path.join(TMP, "gacha.db"))

# Danh muc mau cho test — KHONG doc `gacha.json` that (admin co the xoa het
# san pham / ca ruong, neu vay test se khong co gi de mo ruong).
sys.path.insert(0, str(ROOT / "tests"))
import fixture_catalog  # noqa: E402

fixture_catalog.use_fixture(Path(TMP))


from app import config, gacha, main as web_main, pika, store  # noqa: E402

store.DB_PATH = Path(TMP) / "gacha.db"

PASSES = 0
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSES
    if cond:
        PASSES += 1
        print(f"  PASS {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"   {detail}" if detail else ""))


def make_cookie(payload: dict, csrf: str = "test-csrf") -> str:
    session = {**payload, "csrf": csrf}
    raw = base64.b64encode(json.dumps(session).encode("utf-8"))
    return itsdangerous.TimestampSigner(config.SESSION_SECRET).sign(raw).decode()


async def run_tests() -> None:
    transport = httpx.ASGITransport(app=web_main.app)
    signer = itsdangerous.TimestampSigner(config.SESSION_SECRET)

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        print("=== 1. COOKIE HONG KHONG DUOC TRA 500 ===")
        # 41-char URL-safe base64 payload signed with valid secret (exact TIEN_TRINH 3.1 repro)
        bad_41 = signer.sign(b"a" * 41).decode()
        bad_json = signer.sign(base64.b64encode(b"{not-json")).decode()
        non_dict = signer.sign(base64.b64encode(b"[1, 2, 3]")).decode()

        for label, cookie_val in [
            ("signed 41-char invalid base64", bad_41),
            ("signed invalid json", bad_json),
            ("signed non-dict json", non_dict),
            ("tampered signature", "invalid.cookie.value"),
        ]:
            # `/gacha` la trang co chuc nang -> khach chua dang nhap bi day ve
            # `/login` (303). Dieu quan trong: KHONG duoc tra 500 (500 la loi).
            r_page = await client.get("/gacha", cookies={"jv_session": cookie_val})
            check(f"GET /gacha with {label} -> khong 5xx",
                  r_page.status_code < 500, str(r_page.status_code))
            check(f"GET /gacha with {label} -> 303 ve /login",
                  r_page.status_code == 303
                  and "/login" in r_page.headers.get("location", ""),
                  f"{r_page.status_code} {r_page.headers.get('location', '')}")

            r_api = await client.get("/api/drops", cookies={"jv_session": cookie_val})
            check(f"GET /api/drops with {label} -> 200", r_api.status_code == 200, str(r_api.status_code))
            set_cookie = r_api.headers.get("set-cookie", "")
            check(f"GET /api/drops with {label} clears broken cookie", "jv_session=null" in set_cookie, set_cookie)

        print()
        print("=== 2. SECURITY HEADERS & LOGIN FORM ===")
        r_login = await client.get("/login")
        check("GET /login -> 200", r_login.status_code == 200)
        check("X-Content-Type-Options=nosniff", r_login.headers.get("x-content-type-options") == "nosniff")
        check("X-Frame-Options=DENY", r_login.headers.get("x-frame-options") == "DENY")
        check("Referrer-Policy present", "strict-origin" in (r_login.headers.get("referrer-policy") or ""))
        check("login.html has autocomplete=current-password", 'autocomplete="current-password"' in r_login.text)
        check("login.html has autocomplete=username", 'autocomplete="username"' in r_login.text)

        print()
        print("=== 3. INPUT VALIDATION (400 INSTEAD OF 500) ===")
        cookie = make_cookie({"user": "QA_Tester_01", "login_name": "QA_Tester_01"})
        headers = {"X-CSRF": "test-csrf"}
        cookies = {"jv_session": cookie}

        r_bad_json = await client.post(
            "/api/inventory/sell",
            content="{bad json",
            headers={**headers, "Content-Type": "application/json"},
            cookies=cookies,
        )
        check("POST /api/inventory/sell invalid JSON -> 400", r_bad_json.status_code == 400, str(r_bad_json.status_code))

        r_bad_int = await client.post(
            "/api/upgrade",
            json={"inventory_id": "abc", "target_id": "x", "target_coin": 100},
            headers=headers,
            cookies=cookies,
        )
        check("POST /api/upgrade non-int inventory_id -> 400", r_bad_int.status_code == 400, str(r_bad_int.status_code))

        r_bad_battle = await client.post(
            "/api/battles",
            json={"case_id": "jelly-starter", "rounds": "nan", "slots": 2},
            headers=headers,
            cookies=cookies,
        )
        check("POST /api/battles non-int rounds -> 400", r_bad_battle.status_code == 400, str(r_bad_battle.status_code))

        r_bad_bet = await client.post(
            "/api/roulette/bet",
            json={"side": "village", "amount": "lots"},
            headers=headers,
            cookies=cookies,
        )
        check("POST /api/roulette/bet non-int amount -> 400", r_bad_bet.status_code == 400, str(r_bad_bet.status_code))

        print()
        print("=== 4. LOGOUT ORIGIN CHECK ===")
        r_cross = await client.post(
            "/logout",
            headers={"Origin": "https://evil.example", "Host": "127.0.0.1:8080"},
            cookies=cookies,
            follow_redirects=False,
        )
        check("POST /logout cross-origin -> 403", r_cross.status_code == 403, str(r_cross.status_code))

        r_same = await client.post(
            "/logout",
            headers={"Origin": "http://127.0.0.1:8080", "Host": "127.0.0.1:8080"},
            cookies=cookies,
            follow_redirects=False,
        )
        check("POST /logout same-origin -> 303", r_same.status_code == 303, str(r_same.status_code))

        print()
        print("=== 5. UPGRADE MODULE EXPORT & FRONTEND CHECKS ===")
        upgrade_js = (ROOT / "app" / "static" / "upgrade.js").read_text(encoding="utf-8")
        check("upgrade.js exports mountGauge", "export function mountGauge" in upgrade_js)

        r_case = await client.get("/case/jelly-starter", cookies=cookies)
        check("case.html uses replaceChildren()", "replaceChildren()" in r_case.text)
        r_roulette = await client.get("/roulette", cookies=cookies)
        check("roulette.html uses toReversed()", "toReversed()" in r_roulette.text)
        r_base = await client.get("/gacha", cookies=cookies)
        check("base.html declares meta color-scheme", '<meta name="color-scheme" content="light dark">' in r_base.text)

        print()
        print("=== 6. NEXOMC INTEGRATION ===")
        cmd = gacha.nexo_give_command("QA_Tester_01", "jellyvale:ruby_sword", 2)
        check("nexo_give_command formats safely", cmd == "nexo give QA_Tester_01 jellyvale:ruby_sword 2", cmd)

        try:
            gacha.nexo_give_command("QA_Tester_01", "sword; op evil", 1)
            check("nexo_give_command blocks injection", False)
        except ValueError:
            check("nexo_give_command blocks injection", True)

        r_wd_disabled = await client.post(
            "/api/inventory/withdraw",
            json={"id": 1},
            headers=headers,
            cookies=cookies,
        )
        check("withdraw disabled by default -> 503", r_wd_disabled.status_code == 503, str(r_wd_disabled.status_code))

        # Test withdraw enabled with real-money mode & mocked nexo_id + console
        os.environ["GACHA_NEXO_WITHDRAW"] = "true"
        os.environ["GACHA_DRY_RUN"] = "false"
        sent_cmds: list[str] = []
        orig_send = pika.send_command
        orig_find_listing = web_main.find_listing

        async def fake_send(command: str) -> None:
            sent_cmds.append(command)

        def fake_find_listing(item_id: str, coin: int | None = None):
            item = orig_find_listing(item_id, coin)
            if item:
                item.nexo_id = "jellyvale:starter_dust"
                item.nexo_amount = 1
            return item

        pika.send_command = fake_send
        web_main.find_listing = fake_find_listing
        try:
            case = gacha.get_case("jelly-starter")
            inv_id = store.add_inventory("QA_Tester_01", case.items[0], "case", "jelly-starter")
            r_wd = await client.post(
                "/api/inventory/withdraw",
                json={"id": inv_id},
                headers=headers,
                cookies=cookies,
            )
            check("withdraw enabled -> 200", r_wd.status_code == 200, r_wd.text)
            check("nexo give command dispatched", sent_cmds == ["nexo give QA_Tester_01 jellyvale:starter_dust 1"], str(sent_cmds))
            row = store.get_inventory_item(inv_id)
            check("inventory status updated to withdrawn", row is not None and row["status"] == "withdrawn")
        finally:
            pika.send_command = orig_send
            web_main.find_listing = orig_find_listing
            os.environ["GACHA_NEXO_WITHDRAW"] = "false"
            os.environ["GACHA_DRY_RUN"] = "true"


asyncio.run(run_tests())
shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
if FAILS:
    print("FAIL:", FAILS)
    sys.exit(1)
print(">>> SECURITY & FIXES TEST PASS")

