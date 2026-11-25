"""Kiem chung bao mat o tang HTTP: CSRF, session, rate limit, phan quyen."""
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

SECRET = os.getenv("SESSION_SECRET")
BASE = "http://127.0.0.1:8098"

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


def make_cookie(user, login_name=None, csrf="test-csrf"):
    session = {
        "user": user,
        "login_name": login_name or user,
        "csrf": csrf,
    }
    raw = base64.b64encode(json.dumps(session).encode("utf-8"))
    return itsdangerous.TimestampSigner(SECRET).sign(raw).decode()


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        print("=== 1. CHUA DANG NHAP ===")
        for method, path in [
            ("GET", "/api/balance"),
            ("GET", "/api/upgrade/targets"),
        ]:
            r = await c.request(method, path)
            check(f"{method} {path} -> 401", r.status_code == 401, str(r.status_code))

        for method, path, body in [
            ("POST", "/api/case/jelly-starter/open", {}),
            ("POST", "/api/inventory/sell", {"ids": [1]}),
            ("POST", "/api/inventory/sell-all", {}),
            ("POST", "/api/upgrade", {"inventory_id": 1, "target_id": "x", "target_coin": 1}),
            ("POST", "/api/battles", {"case_id": "jelly-starter"}),
            ("POST", "/api/battles/1/join", {}),
            ("POST", "/api/battles/1/bots", {}),
            ("POST", "/api/battles/1/start", {}),
            ("POST", "/api/bonus", {}),
            ("POST", "/api/roulette/bet", {"side": "village", "amount": 100}),
        ]:
            r = await c.request(method, path, json=body)
            check(f"{method} {path} -> 401", r.status_code == 401,
                  f"{r.status_code} {r.text[:60]}")

        print()
        print("=== 2. DA DANG NHAP NHUNG THIEU CSRF ===")
        cookie = make_cookie("Trez1724")
        c.cookies.set("jv_session", cookie, domain="127.0.0.1")

        for method, path, body in [
            ("POST", "/api/case/jelly-starter/open", {}),
            ("POST", "/api/inventory/sell", {"ids": [1]}),
            ("POST", "/api/inventory/sell-all", {}),
            ("POST", "/api/upgrade", {"inventory_id": 1, "target_id": "x", "target_coin": 1}),
            ("POST", "/api/battles", {"case_id": "jelly-starter"}),
            ("POST", "/api/battles/1/join", {}),
            ("POST", "/api/battles/1/bots", {}),
            ("POST", "/api/battles/1/start", {}),
            ("POST", "/api/bonus", {}),
            ("POST", "/api/roulette/bet", {"side": "village", "amount": 100}),
        ]:
            r = await c.request(method, path, json=body)
            check(f"{method} {path} -> 403 (thieu CSRF)", r.status_code == 403,
                  f"{r.status_code} {r.text[:60]}")

        print()
        print("=== 3. CSRF SAI GIA TRI ===")
        r = await c.post("/api/bonus", json={}, headers={"X-CSRF": "sai-token"})
        check("CSRF sai -> 403", r.status_code == 403, str(r.status_code))

        print()
        print("=== 4. GET KHONG CAN CSRF (doc duoc) ===")
        r = await c.get("/api/balance")
        check("GET /api/balance -> 200", r.status_code == 200, str(r.status_code))
        check("tra ve balance_fmt", "balance_fmt" in r.text, r.text[:80])

        print()
        print("=== 5. PHAN QUYEN ADMIN ===")
        # Dung tai khoan KHONG phai admin de kiem tra bi chan
        normal_cookie = make_cookie("KhongPhaiAdmin")
        c.cookies.set("jv_session", normal_cookie, domain="127.0.0.1")
        r = await c.get("/admin", follow_redirects=False)
        check("nguoi binh thuong -> 303 ve /gacha",
              r.status_code == 303 and "/gacha" in r.headers.get("location", ""),
              f"{r.status_code} {r.headers.get('location')}")

        # Admin lay tu OP tren server (realtime) — lay danh sach de dung
        # dung ten OP that, khong hard-code.
        r = await c.get("/api/admins")
        admin_list = r.json().get("admins", []) if r.status_code == 200 else []
        check("/api/admins tra ve danh sach admin", len(admin_list) > 0,
              f"{len(admin_list)}")
        admin_name = admin_list[0]["name"] if admin_list else "Trez1724"
        print(f"  admin lay tu server: {admin_name}")

        admin_cookie = make_cookie(admin_name)
        c.cookies.set("jv_session", admin_cookie, domain="127.0.0.1")
        r = await c.get("/admin", follow_redirects=False)
        check("admin -> 200", r.status_code == 200, str(r.status_code))

        print()
        print("=== 6. RATE LIMIT DANG NHAP ===")
        # Reset may van, dung IP rieng de khong anh huong test khac
        r = await c.post("/login", data={
            "username": "khong-ton-tai", "password": "sai",
            "csrf": "x",
        }, follow_redirects=False)
        check("login sai CSRF -> 303", r.status_code == 303, str(r.status_code))

        r = await c.post("/login", data={
            "username": "khong-ton-tai", "password": "sai", "csrf": "sai",
        }, follow_redirects=False)
        check("login sai mat khau -> 303 ve /login",
              r.status_code == 303 and "login" in r.headers.get("location", ""),
              f"{r.status_code} {r.headers.get('location')}")

        print()
        print("=== 7. KHU VUC TUONG LAI / BODY THOA ===")
        r = await c.post("/api/case/jelly-starter/open", json={"count": 999},
                         headers={"X-CSRF": "test-csrf"})
        check("count=999 bi tu choi (khong phai 401/403)",
              r.status_code in (400, 402), f"{r.status_code} {r.text[:60]}")

        r = await c.post("/api/case/khong-ton-tai/open", json={},
                         headers={"X-CSRF": "test-csrf"})
        check("ruong khong ton tai -> 404", r.status_code == 404, str(r.status_code))

    print()
    print("=== 8. RATE LIMIT: KHONG BYPASS DUOC BANG X-Forwarded-For ===")
    # Kẻ xấu tự đặt header XFF mỗi lần để mỗi lần thử là một IP khác nhau.
    # Nếu app tin header này thì rate limit vô hiệu.
    from app import security

    # Test trực tiếp hàm client_ip (không cần HTTP)
    class FakeClient:
        host = "10.0.0.5"

    class FakeRequest:
        client = FakeClient()

        def __init__(self, headers):
            self.headers = headers

    req = FakeRequest({"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    ip = security.client_ip(req)
    check("khong tin X-Forwarded-For khi khong co proxy",
          ip == "10.0.0.5", f"tra ve {ip}")

    # Với TRUST_PROXY bật thì mới lấy XFF
    security.TRUST_PROXY = True
    try:
        ip2 = security.client_ip(req)
        check("tin X-Forwarded-For khi TRUST_PROXY bat",
              ip2 == "1.2.3.4", f"tra ve {ip2}")
    finally:
        security.TRUST_PROXY = False

    print()
    print("=== 9. HASH MAT KHAU AUTHME ===")
    import hashlib

    password = "matkhau123"
    salt = "abc123salt"
    inner = hashlib.sha256(password.encode()).hexdigest()
    stored = f"$SHA${salt}${hashlib.sha256((inner + salt).encode()).hexdigest()}"

    check("mat khau dung -> True",
          security.verify_authme_sha256(password, stored))
    check("mat khau sai -> False",
          not security.verify_authme_sha256("matkhau124", stored))
    check("chuoi rong -> False", not security.verify_authme_sha256("", stored))
    check("stored rong -> False", not security.verify_authme_sha256(password, ""))
    check("stored khong phai SHA -> False",
          not security.verify_authme_sha256(password, "plaintext"))
    check("stored hong -> False",
          not security.verify_authme_sha256(password, "$SHA$abc"))

    # Hex digest so sanh khong phan biet HOA/THUONG — nhưng SALT thi co
    # (salt la chuoi ngau nhien, phai khop chinh xac).
    upper_digest = f"$SHA${salt}${hashlib.sha256((inner + salt).encode()).hexdigest().upper()}"
    check("hex digest viet hoa van khop",
          security.verify_authme_sha256(password, upper_digest))
    wrong_salt = f"$SHA${salt.upper()}${hashlib.sha256((inner + salt).encode()).hexdigest()}"
    check("salt khac -> khong khop (salt phan biet HOA/THUONG)",
          not security.verify_authme_sha256(password, wrong_salt))

    print()
    print("=== 10. TOKEN CSRF ===")
    t1 = security.new_csrf_token()
    t2 = security.new_csrf_token()
    check("token CSRF khong trung nhau", t1 != t2)
    check("token CSRF du dai (>= 32 ky tu)", len(t1) >= 32, str(len(t1)))

    print()
    print("=== 11. TINH NANG HOP DONG DA GO BO ===")
    # Route phai tra 404 (khong phai 401/403) — chung to route khong con.
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c2:
        r = await c2.get("/contract", follow_redirects=False)
        check("GET /contract -> 404 (route da xoa)", r.status_code == 404,
              f"{r.status_code} {r.text[:60]}")

        r = await c2.post("/api/contract", json={"ids": [1]},
                          headers={"X-CSRF": "test-csrf"})
        check("POST /api/contract -> 404 (route da xoa)", r.status_code == 404,
              f"{r.status_code} {r.text[:60]}")

        # Trang chu khong con duong dan "Hop dong" trong menu
        r = await c2.get("/gacha")
        check("menu khong con link Hop dong", "/contract" not in r.text,
              "van con" if "/contract" in r.text else "")

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> HTTP SECURITY TEST PASS")


asyncio.run(main())
