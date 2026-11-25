"""Kiem tra TOAN BO chuc nang cua web: moi route, moi tinh nang.

Chay o che do DRY-RUN (khong dung Coin that), tren server local.
- Moi route GET/POST deu duoc goi va kiem tra ma loi + noi dung.
- Moi tinh nang chinh (mo ruong, ban do, nang cap, battle, bonus, roulette,
  vi, admin) duoc chay qua vong tronh chuc nang.
- Route da go bo (Hop dong) phai tra 404.

Usage: python tests/test_all_features.py [port]
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio
import base64
import json
import os
import sys

import httpx
import itsdangerous


os.environ["GACHA_DRY_RUN"] = "true"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

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


def make_cookie(user, csrf="test-csrf"):
    session = {"user": user, "login_name": user, "csrf": csrf}
    raw = base64.b64encode(json.dumps(session).encode("utf-8"))
    return itsdangerous.TimestampSigner(SECRET).sign(raw).decode()



QA_PLAYER = "QA_Tester_01"


def reset_player(name, coin=500_000):
    """Dat lai vi web cua nguoi choi de test chay lap lai duoc.

    Dry-run: Coin la 'a o' trong DB web nen nap truc tiep vao SQLite.
    """
    import sqlite3
    db = os.getenv("GACHA_DB_PATH") or str(ROOT / "data" / "gacha.db")
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO wallets (player, balance, is_bot, created_at) "
        "VALUES (?, ?, 0, 0) ON CONFLICT(player) DO UPDATE SET balance = ?",
        (name, coin, coin),
    )
    con.execute("DELETE FROM inventory WHERE player = ?", (name,))
    con.execute("DELETE FROM bonus WHERE player = ?", (name,))
    con.commit()
    con.close()


async def main():
    cookie = make_cookie(QA_PLAYER)

    # Reset vi + bonus de test chay lap lai duoc
    reset_player(QA_PLAYER)

    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        print("=== 1. TRANG CONG: LANDING + TRANG CAN DANG NHAP ===")
        r = await c.get("/", follow_redirects=False)
        check("GET / -> 200 landing page", r.status_code == 200, str(r.status_code))
        check("landing co h1", "<h1>" in r.text)
        check("landing nap landing.css", "/static/landing.css" in r.text)

        # Trang co chuc nang -> khach chua dang nhap bi day ve /login.
        for path in ["/gacha", "/roulette", "/battles", "/bonus"]:
            r = await c.get(path, follow_redirects=False)
            check(f"GET {path} -> 303 ve /login (chua dang nhap)",
                  r.status_code == 303 and "login" in r.headers.get("location", ""),
                  f"{r.status_code} {r.headers.get('location', '')}")

        # Trang van mo cho khach: landing, login, setup.
        for path, must in [
            ("/login", "Đăng nhập"),
            ("/setup", "PikaMC"),
        ]:
            r = await c.get(path)
            ok = r.status_code == 200 and must.lower() in r.text.lower()
            check(f"GET {path} -> 200 + noi dung dung", ok,
                  f"{r.status_code} len={len(r.text)}")

        print()
        print("=== 2. TRANG CAN DANG NHAP ===")
        c.cookies.clear()
        for path in ["/inventory", "/upgrade", "/vi"]:
            r = await c.get(path, follow_redirects=False)
            check(f"GET {path} -> 303 ve /login",
                  r.status_code == 303 and "login" in r.headers.get("location", ""),
                  f"{r.status_code} {r.headers.get('location')}")

        print()
        print("=== 3. ROUTE DA GO BO: HOP DONG ===")
        c.cookies.set("jv_session", cookie, domain="127.0.0.1")
        r = await c.get("/contract", follow_redirects=False)
        check("GET /contract -> 404", r.status_code == 404, str(r.status_code))
        r = await c.post("/api/contract", json={"ids": [1]},
                         headers={"X-CSRF": "test-csrf"})
        check("POST /api/contract -> 404", r.status_code == 404, str(r.status_code))
        r = await c.get("/gacha")
        check("menu khong con link Hop dong", "/contract" not in r.text)

        print()
        print("=== 4. TRANG DA DANG NHAP ===")
        for path, must in [
            ("/gacha", "Mở rương"),
            ("/inventory", "Túi đồ"),
            ("/upgrade", "Nâng cấp"),
            ("/vi", "Ví"),
            ("/roulette", "Roulette"),
            ("/battles", "Battle"),
            ("/bonus", "Bonus"),
        ]:
            r = await c.get(path)
            ok = r.status_code == 200 and must.lower() in r.text.lower()
            check(f"GET {path} (da dang nhap) -> 200", ok,
                  f"{r.status_code} len={len(r.text)}")

        # /admin chi admin moi vao duoc -> lay ten admin tu server (OP)
        r = await c.get("/api/admins")
        admin_list = r.json().get("admins", []) if r.status_code == 200 else []
        admin_name = admin_list[0]["name"] if admin_list else "Trez1724"
        c.cookies.set("jv_session", make_cookie(admin_name), domain="127.0.0.1")
        r = await c.get("/admin")
        ok = r.status_code == 200 and "Lượt mở" in r.text
        check("GET /admin (admin) -> 200", ok, str(r.status_code))

        # Nguoi binh thuong -> bi chan
        c.cookies.set("jv_session", make_cookie(QA_PLAYER), domain="127.0.0.1")
        r = await c.get("/admin", follow_redirects=False)
        check("GET /admin (nguoi thuong) -> 303 ve /gacha",
              r.status_code == 303 and "/gacha" in r.headers.get("location", ""),
              f"{r.status_code} {r.headers.get('location')}")
        c.cookies.set("jv_session", cookie, domain="127.0.0.1")

        print()
        print("=== 5. API DOC (GET) ===")
        r = await c.get("/api/drops")
        ok = r.status_code == 200 and "drops" in r.json()
        check("GET /api/drops -> 200 co drops", ok, str(r.status_code))

        r = await c.get("/api/balance")
        ok = r.status_code == 200 and "balance_fmt" in r.json()
        check("GET /api/balance -> 200 co balance_fmt", ok, str(r.status_code))

        r = await c.get("/api/roulette/state")
        check("GET /api/roulette/state -> 200", r.status_code == 200,
              str(r.status_code))

        r = await c.get("/api/upgrade/targets")
        check("GET /api/upgrade/targets -> 200", r.status_code == 200,
              str(r.status_code))

        r = await c.get("/api/battles/999999")
        check("GET /api/battles/{id} khong ton tai -> 404",
              r.status_code == 404, str(r.status_code))

        print()
        print("=== 6. MO RUONG ===")
        r = await c.get("/case/jelly-starter")
        check("GET /case/jelly-starter -> 200", r.status_code == 200,
              str(r.status_code))

        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         headers={"X-CSRF": "test-csrf"})
        ok = r.status_code == 200 and "openings" in r.json()
        check("POST /api/case/.../open -> 200 co openings", ok,
              f"{r.status_code} {r.text[:80]}")

        r = await c.post("/api/case/jelly-starter/open", json={"count": 2},
                         headers={"X-CSRF": "test-csrf"})
        ok = r.status_code == 200 and len(r.json().get("openings", [])) == 2
        check("POST open count=2 -> 2 mon", ok,
              f"{r.status_code} n={len(r.json().get('openings', []))}")

        r = await c.post("/api/case/jelly-starter/open", json={"count": 99},
                         headers={"X-CSRF": "test-csrf"})
        check("POST open count=99 -> 400", r.status_code == 400,
              str(r.status_code))

        r = await c.post("/api/case/khong-ton-tai/open", json={},
                         headers={"X-CSRF": "test-csrf"})
        check("POST open ruong khong ton tai -> 404", r.status_code == 404,
              str(r.status_code))

        print()
        print("=== 7. BAN DO ===")
        r = await c.get("/inventory")
        check("GET /inventory -> 200", r.status_code == 200, str(r.status_code))

        # Lay id mon trong túi tu HTML (checkbox name="id" value="<id>")
        import re
        ids = re.findall(r'name="id" value="(\d+)"', r.text) or \
            re.findall(r'data-id="(\d+)"', r.text)
        item_ids = [int(x) for x in ids][:3]

        if item_ids:
            r = await c.post("/api/inventory/sell", json={"ids": item_ids},
                             headers={"X-CSRF": "test-csrf"})
            ok = r.status_code == 200 and r.json().get("sold") == len(item_ids)
            check("POST /api/inventory/sell -> 200 ban duoc", ok,
                  f"{r.status_code} {r.text[:80]}")

            # ban lai -> phai fail
            r = await c.post("/api/inventory/sell", json={"ids": item_ids},
                             headers={"X-CSRF": "test-csrf"})
            check("POST sell lai mon da ban -> loi (400)", r.status_code == 400,
                  f"{r.status_code} {r.text[:60]}")
        else:
            check("co mon trong túi de test ban", False, "tui rong")

        # "Ban het" chi meaningful khi con mon trong túi. Truoc het mo them
        # 1 ruong de chắc chắn túi khong rong.
        await c.post("/api/case/jelly-starter/open", json={"count": 1},
                     headers={"X-CSRF": "test-csrf"})
        r = await c.post("/api/inventory/sell-all", json={},
                         headers={"X-CSRF": "test-csrf"})
        check("POST /api/inventory/sell-all -> 200", r.status_code == 200,
              f"{r.status_code} {r.text[:60]}")

        print()
        print("=== 8. NANG CAP ===")
        # Can co it nhat 1 mon trong tui de cuoc. Mua them 2 ruong.
        await c.post("/api/case/jelly-starter/open", json={"count": 2},
                     headers={"X-CSRF": "test-csrf"})

        r = await c.get("/upgrade")
        # Template moi dung checkbox: <input type="checkbox" name="stake"
        # value="<id>" data-value="<gia tri>">.
        stakes = re.findall(
            r'<input type="checkbox"[^>]*name="stake"[^>]*value="(\d+)"[^>]*data-value="(\d+)"',
            r.text,
        )
        ids = [int(a) for a, _ in stakes]
        stake_value = int(stakes[0][1]) if stakes else 0
        check("trang /upgrade co mon de cuoc", len(stakes) > 0,
              f"n={len(stakes)}")
        targets = await c.get("/api/upgrade/targets",
                              params={"value": stake_value})
        tl = targets.json().get("targets", []) if targets.status_code == 200 else []
        check("GET /api/upgrade/targets co muc dich", len(tl) > 0,
              f"value={stake_value} n={len(tl)}")

        if ids and tl:
            t = tl[0]
            r = await c.post("/api/upgrade", json={
                "inventory_id": ids[0],
                "target_id": t["id"],
                "target_coin": t["coin"],
            }, headers={"X-CSRF": "test-csrf"})
            ok = r.status_code == 200 and "won" in r.json()
            check("POST /api/upgrade -> 200 co ket qua", ok,
                  f"{r.status_code} {r.text[:80]}")

        r = await c.post("/api/upgrade", json={
            "inventory_id": 999999, "target_id": "x", "target_coin": 1,
        }, headers={"X-CSRF": "test-csrf"})
        check("POST upgrade mon khong ton tai -> loi", r.status_code == 400,
              str(r.status_code))

        print()
        print("=== 9. BATTLE ===")
        r = await c.post("/api/battles", json={
            "case_id": "jelly-starter", "rounds": 1, "slots": 2,
        }, headers={"X-CSRF": "test-csrf"})
        ok = r.status_code == 200 and "id" in r.json()
        check("POST /api/battles -> 200 tao tranh", ok,
              f"{r.status_code} {r.text[:80]}")
        battle_id = r.json().get("id") if ok else None

        if battle_id:
            r = await c.post(f"/api/battles/{battle_id}/bots", json={},
                             headers={"X-CSRF": "test-csrf"})
            check("POST /api/battles/{id}/bots -> 200 them bot",
                  r.status_code == 200, f"{r.status_code} {r.text[:60]}")

            r = await c.post(f"/api/battles/{battle_id}/start", json={},
                             headers={"X-CSRF": "test-csrf"})
            # Bot loop trong background co the da settle tran truoc -> tra 400
            # "Trận đã xong.". Trong ca hai truong hop, GET lai tran phai ra
            # FINISHED (khong trung giu, khong roll 2 lan).
            if r.status_code != 200:
                r = await c.get(f"/api/battles/{battle_id}")
            ok = r.status_code == 200 and r.json().get("status") == "FINISHED"
            check("POST /api/battles/{id}/start -> FINISHED", ok,
                  f"{r.status_code} {r.text[:80]}")

            r = await c.get(f"/battles/{battle_id}")
            check(f"GET /battles/{battle_id} -> 200", r.status_code == 200,
                  str(r.status_code))

            r = await c.get(f"/api/battles/{battle_id}")
            check(f"GET /api/battles/{battle_id} -> 200", r.status_code == 200,
                  str(r.status_code))

        r = await c.post("/api/battles/999999/join", json={},
                         headers={"X-CSRF": "test-csrf"})
        check("POST join tran khong ton tai -> 404", r.status_code == 404,
              str(r.status_code))

        print()
        print("=== 10. BONUS ===")
        r = await c.get("/bonus")
        check("GET /bonus -> 200", r.status_code == 200, str(r.status_code))

        r = await c.post("/api/bonus", json={}, headers={"X-CSRF": "test-csrf"})
        ok = r.status_code == 200 and "amount" in r.json()
        check("POST /api/bonus -> 200 co amount", ok,
              f"{r.status_code} {r.text[:80]}")

        # lan 2 phai bi chan (cooldown 24h)
        r = await c.post("/api/bonus", json={}, headers={"X-CSRF": "test-csrf"})
        check("POST /api/bonus lan 2 -> 400 (cooldown)", r.status_code == 400,
              f"{r.status_code} {r.text[:60]}")

        print()
        print("=== 11. ROULETTE ===")
        r = await c.get("/roulette")
        check("GET /roulette -> 200", r.status_code == 200, str(r.status_code))

        # Chi dat cuoc duoc khi vong quay dang o phase BETTING. Cho toi
        # toi da 60s (chu ky vong quay) neu can.
        bet_ok = False
        for _ in range(70):
            st = (await c.get("/api/roulette/state")).json()
            if st.get("status") == "BETTING":
                bet_ok = True
                break
            await asyncio.sleep(1.0)
        check("co the cho vong quay ve phase BETTING", bet_ok)

        if bet_ok:
            r = await c.post("/api/roulette/bet", json={
                "side": "village", "amount": 100,
            }, headers={"X-CSRF": "test-csrf"})
            ok = r.status_code == 200 and "amount" in r.json()
            check("POST /api/roulette/bet -> 200", ok,
                  f"{r.status_code} {r.text[:80]}")

            r = await c.post("/api/roulette/bet", json={
                "side": "village", "amount": 1,
            }, headers={"X-CSRF": "test-csrf"})
            check("POST roulette bet qua nho -> 400", r.status_code == 400,
                  f"{r.status_code} {r.text[:60]}")
        else:
            check("POST /api/roulette/bet -> 200", False, "khong vao duoc phase BETTING")
            check("POST roulette bet qua nho -> 400", False, "khong vao duoc phase BETTING")

        print()
        print("=== 12. VI + ADMIN ===")
        r = await c.get("/vi")
        ok = r.status_code == 200 and "Coin" in r.text
        check("GET /vi -> 200 hien thi Coin", ok, str(r.status_code))

        c.cookies.set("jv_session", make_cookie(admin_name), domain="127.0.0.1")
        r = await c.get("/admin")
        ok = r.status_code == 200 and "Lượt mở" in r.text
        check("GET /admin -> 200 hien thi thong ke", ok, str(r.status_code))
        c.cookies.set("jv_session", cookie, domain="127.0.0.1")

        print()
        print("=== 13. LOGOUT + DANG NHAP LAI ===")
        r = await c.post("/logout", follow_redirects=False)
        check("POST /logout -> 303", r.status_code == 303, str(r.status_code))

        r = await c.get("/inventory", follow_redirects=False)
        check("sau logout, /inventory -> 303 ve /login",
              r.status_code == 303 and "login" in r.headers.get("location", ""),
              f"{r.status_code} {r.headers.get('location')}")

        r = await c.get("/login")
        check("GET /login -> 200 sau logout", r.status_code == 200,
              str(r.status_code))

    # Don dep: xoa hoan toan du lieu test cua player QA
    import sqlite3
    db = os.getenv("GACHA_DB_PATH") or str(ROOT / "data" / "gacha.db")
    con = sqlite3.connect(db)
    for tbl in ("inventory", "bonus", "pulls", "drops", "tx", "upgrades"):
        con.execute(f"DELETE FROM {tbl} WHERE player = ?", (QA_PLAYER,))
    con.execute("DELETE FROM wallets WHERE player = ?", (QA_PLAYER,))
    con.commit()
    con.close()

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> ALL FEATURES TEST PASS")


asyncio.run(main())
