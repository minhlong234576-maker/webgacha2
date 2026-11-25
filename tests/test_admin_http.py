"""Kiem tra tich hop HTTP cua quyen admin realtime.

- `/api/admins` tra ve danh sach admin doc tu server.
- OP tren server vao duoc `/admin` va thay menu co link Admin.
- Nguoi khong phai OP bi day ra `/gacha`.
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio
import base64
import json
import os
import sys

sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import httpx  # noqa: E402
import itsdangerous  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8102"
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


def make_cookie(user):
    session = {"user": user, "login_name": user, "csrf": "test-csrf"}
    raw = base64.b64encode(json.dumps(session).encode("utf-8"))
    return itsdangerous.TimestampSigner(SECRET).sign(raw).decode()


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        print("=== 1. API DANH SACH ADMIN ===")
        r = await c.get("/api/admins")
        check("GET /api/admins -> 200", r.status_code == 200, str(r.status_code))
        data = r.json()
        lst = data.get("admins", [])
        check("co danh sach admin", len(lst) > 0, f"{len(lst)}")
        check("moi dong co name + source",
              all("name" in row and "source" in row for row in lst))
        server_ops = [row for row in lst if row["source"] == "server-op"]
        check("co admin tu server-op", len(server_ops) > 0, f"{len(server_ops)}")
        print(f"  {[row['name'] for row in lst]}")

        print()
        print("=== 2. OP SERVER VAO DUOC /ADMIN ===")
        for row in server_ops:
            name = row["name"]
            c.cookies.set("jv_session", make_cookie(name), domain="127.0.0.1")
            r = await c.get("/admin", follow_redirects=False)
            check(f"OP '{name}' -> /admin 200", r.status_code == 200,
                  str(r.status_code))

            r = await c.get("/gacha")
            check(f"OP '{name}' thay menu co link Admin",
                  'href="/admin"' in r.text)

        print()
        print("=== 3. NGUOI THUONG BI CHAN ===")
        for fake in ["nguoi_thuong_xyz", "Trez1725", "op_gi_mao"]:
            c.cookies.set("jv_session", make_cookie(fake), domain="127.0.0.1")
            r = await c.get("/admin", follow_redirects=False)
            check(f"'{fake}' -> /admin 303 ve /gacha",
                  r.status_code == 303 and "/gacha" in r.headers.get("location", ""),
                  f"{r.status_code} {r.headers.get('location')}")

            r = await c.get("/gacha")
            check(f"'{fake}' khong thay link Admin",
                  'href="/admin"' not in r.text)

        print()
        print("=== 4. TRANG ADMIN HIEN THI DANH SACH ===")
        c.cookies.set("jv_session", make_cookie(server_ops[0]["name"]),
                      domain="127.0.0.1")
        r = await c.get("/admin")
        ok = r.status_code == 200 and "Quản trị viên" in r.text
        check("/admin co bang 'Quan tri vien'", ok, str(r.status_code))
        ok = "OP trên server" in r.text
        check("/admin danh dau nguon la server-op", ok)

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> ADMIN HTTP TEST PASS")


asyncio.run(main())
