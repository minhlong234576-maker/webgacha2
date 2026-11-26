"""
Test hồi quy: `/api/case/{slug}/open` phải trả 400 khi `count` sai kiểu.

Lỗi gốc: route nuốt lỗi parse trong `except Exception: count = 1`, nên gửi
`{"count": "abc"}` lại mở rương 1 lượt và VẪN bị tính tiền — người chơi
tưởng mở nhiều lượt nhưng thực ra chỉ mở 1, không có báo lỗi nào.

Đã sửa bằng `parse_int` (chuẩn của dự án) -> 400 với thông báo rõ ràng.
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
sys.path.insert(0, str(ROOT / "tests"))

from qa_bot_lib import TestServer, make_session_cookie  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8103
BASE = f"http://127.0.0.1:{PORT}"

FAILS: list[str] = []
PASSES = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSES
    if cond:
        PASSES += 1
        print(f"  PASS {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"   {detail}" if detail else ""))


async def main() -> int:
    print("=" * 68)
    print("  REGRESSION: /api/case/{slug}/open — count sai kieu -> 400")
    print("=" * 68)

    server = TestServer(PORT)
    if not server.start():
        print("!! Khong khoi dong duoc server test")
        server.stop()
        return 1

    os.environ["GACHA_DB_PATH"] = str(server.db_file)
    user = "QA_Bot_02"
    import sqlite3

    con = sqlite3.connect(server.db_file)
    con.execute(
        "INSERT INTO wallets (player, balance, is_bot, created_at) "
        "VALUES (?, ?, 0, 0) ON CONFLICT(player) DO UPDATE SET balance = ?",
        (user, 5_000_000, 5_000_000),
    )
    con.commit()
    con.close()

    try:
        async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
            c.cookies.set("jv_session", make_session_cookie(user),
                          domain="127.0.0.1", path="/")
            # Cookie phi chua CSRF token -> moi request deu can header X-CSRF.
            c.headers["X-CSRF"] = "qa-bot-csrf"

            r = await c.get("/api/balance")
            balance0 = r.json().get("balance", 0)

            # count sai kieu -> phai 400, KHONG duoc quay nga am tham.
            for bad in ["abc", "1.5", [], {}, "3.5"]:
                r = await c.post("/api/case/jelly-starter/open", json={"count": bad})
                check(
                    f"count={bad!r} -> 400",
                    r.status_code == 400,
                    f"{r.status_code} {r.text[:60]}",
                )
                check(
                    f"count={bad!r} co thong bao loi bang chu",
                    "detail" in r.json(),
                    str(r.json())[:60],
                )

            # count rong / None -> coi nhu KHONG gui count -> mac dinh 1 lượt.
            for empty in ["", None]:
                r = await c.post("/api/case/jelly-starter/open", json={"count": empty})
                check(
                    f"count={empty!r} -> 200 (mac dinh 1 luot)",
                    r.status_code == 200,
                    f"{r.status_code} {r.text[:60]}",
                )

            # count hop le -> duoc tro tien dung 1 luot (3500 Coin).
            r = await c.get("/api/balance")
            balance_before = r.json().get("balance", 0)
            r = await c.post("/api/case/jelly-starter/open", json={"count": 1})
            check("count=1 -> 200", r.status_code == 200, str(r.status_code))
            r = await c.get("/api/balance")
            balance_after = r.json().get("balance", 0)
            check(
                "tru dung 1 luot (3500 Coin)",
                balance_before - balance_after == 3500,
                f"{balance_before} -> {balance_after}",
            )

            # count=2 van chay binh thuong.
            r = await c.post("/api/case/jelly-starter/open", json={"count": 2})
            check("count=2 van chay -> 200", r.status_code == 200,
                  f"{r.status_code} {r.text[:60]}")
            check("count=2 tra ve 2 mon",
                  r.status_code == 200 and len(r.json().get("openings", [])) == 2)

            # Không count -> mặc định 1 (không lỗi).
            r = await c.post("/api/case/jelly-starter/open", json={})
            check("khong gui count -> 200 (mac dinh 1)", r.status_code == 200,
                  str(r.status_code))

            # count la chuoi so -> parse_int chuyen doi duoc -> van 200.
            r = await c.post("/api/case/jelly-starter/open", json={"count": "2"})
            check("count='2' (chuoi so) -> 200", r.status_code == 200,
                  f"{r.status_code} {r.text[:60]}")
    finally:
        server.stop()

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        return 1
    print(">>> OPEN CASE COUNT REGRESSION PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
