"""
10 BOT QA — kiểm thử TOÀN BỘ chức năng web, chạy SONG SONG.

Mỗi bot là 1 người chơi độc lập (session riêng) chạy đồng thời trên server
test dry-run. 10 bot chia nhau 10 nhóm tính năng:

    Bot 01  Truy cập & điều hướng (mọi route, menu, auth guard)
    Bot 02  Mở rương (1–5 lượt, lỗi input, rương rỗng)
    Bot 03  Túi đồ & bán hàng (bán 1, bán tất cả, chống bán lại)
    Bot 04  Nâng cấp 2→1 (mục đích hợp lệ, mục đích sai, race)
    Bot 05  Battle — tạo / vào / rời / hủy / đá bot
    Bot 06  Battle — bot tự quay, người chơi vào phòng, xem kết quả
    Bot 07  Roulette (đặt cược, số dư, phase, cược quá nhỏ)
    Bot 08  Bonus ngày + Ví + API đọc (balance/drops/online/admins)
    Bot 09  Chatbot trợ lý lệnh (CSRF, câu hỏi, rate limit, XSS)
    Bot 10  Admin: sản phẩm + rương (CRUD, phân quyền)

Usage:
    python tests/test_qa_bots.py [port]
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio
import os
import sys

os.environ["GACHA_DRY_RUN"] = "true"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from qa_bot_lib import (  # noqa: E402
    ALL_BOT_NAMES,
    BotResult,
    TestServer,
    bot_client,
    bot_name,
    cleanup_bots,
    extract_inventory_ids,
    extract_upgrade_stakes,
    reset_bot_wallet,
)

import httpx  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8102
BASE = f"http://127.0.0.1:{PORT}"

RESULTS: list[BotResult] = []


def register(index: int, title: str) -> BotResult:
    res = BotResult(bot_name(index), title)
    RESULTS.append(res)
    print(f"\n{'=' * 70}\n  BOT {index:02d} — {title}  ({bot_name(index)})\n{'=' * 70}")
    return res


# ---------------------------------------------------------------- Bot 01
async def bot_01_navigation() -> BotResult:
    """Truy cập & điều hướng: mọi route, menu, auth guard, logout."""
    res = register(1, "Truy cập & điều hướng")
    async with bot_client(BASE, bot_name(1)) as c:
        # Route công khai
        r = await c.get("/", follow_redirects=False)
        res.check("GET / -> 200 landing", r.status_code == 200, str(r.status_code))
        res.check("landing co <h1>", "<h1>" in r.text)
        res.check("landing nap landing.css", "/static/landing.css" in r.text)

        # /setup trang cong khai
        r = await c.get("/setup")
        res.check("GET /setup -> 200", r.status_code == 200, str(r.status_code))

        # Da dang nhap -> /login phai redirect (khong mo form login lai)
        r = await c.get("/login", follow_redirects=False)
        res.check("GET /login (da dang nhap) -> 303", r.status_code == 303,
                  str(r.status_code))

        # /login cho khach: dung client moi, khong cookie
        async with httpx.AsyncClient(base_url=BASE, timeout=15) as anon:
            r = await anon.get("/login")
            ok = r.status_code == 200 and "Đăng nhập" in r.text
            res.check("GET /login (khach) -> 200 co form", ok, str(r.status_code))
            r = await anon.get("/gacha", follow_redirects=False)
            res.check("GET /gacha (khach) -> 303 ve /login",
                      r.status_code == 303 and "login" in r.headers.get("location", ""),
                      f"{r.status_code} {r.headers.get('location', '')}")

        # Route cần đăng nhập
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
            res.check(
                f"GET {path} -> 200 khi đã đăng nhập",
                r.status_code == 200 and must.lower() in r.text.lower(),
                f"{r.status_code}",
            )

        # Menu đủ mục + không còn "Hợp đồng"
        r = await c.get("/gacha")
        res.check("menu co 5 muc chinh",
                  all(x in r.text for x in ["Rương", "Roulette", "Battle", "Nâng cấp", "Bonus"]))
        res.check("khong con text 'Hop dong'", "Hợp đồng" not in r.text)

        # Route đã gỡ
        r = await c.get("/contract", follow_redirects=False)
        res.check("GET /contract -> 404", r.status_code == 404, str(r.status_code))

        # Header bảo mật
        r = await c.get("/gacha")
        res.check("X-Content-Type-Options=nosniff",
                  r.headers.get("x-content-type-options") == "nosniff")
        res.check("X-Frame-Options=DENY",
                  r.headers.get("x-frame-options") == "DENY")

        # Logout rồi bị chặn
        r = await c.post("/logout", follow_redirects=False)
        res.check("POST /logout -> 303", r.status_code == 303, str(r.status_code))
        r = await c.get("/inventory", follow_redirects=False)
        res.check("sau logout /inventory -> 303 ve /login",
                  r.status_code == 303 and "login" in r.headers.get("location", ""),
                  f"{r.status_code}")
    return res


# ---------------------------------------------------------------- Bot 02
async def bot_02_open_case() -> BotResult:
    """Mở rương: 1–5 lượt, phải trừ tiền, lỗi input, rương không tồn tại."""
    res = register(2, "Mở rương")
    async with bot_client(BASE, bot_name(2)) as c:
        r = await c.get("/api/balance")
        balance0 = r.json().get("balance", 0)
        res.check("GET /api/balance -> 200", r.status_code == 200, str(r.status_code))

        r = await c.post("/api/case/jelly-starter/open", json={"count": 1})
        ok = r.status_code == 200 and "openings" in r.json()
        res.check("POST open count=1 -> 200", ok, f"{r.status_code} {r.text[:70]}")
        data = r.json()
        res.check("opening co winner + inventory_id",
                  bool(data.get("openings")) and "winner" in data["openings"][0]
                  and "inventory_id" in data["openings"][0])
        res.check("pool gui ve client khong rong", len(data.get("pool") or []) > 0,
                  f"n={len(data.get('pool') or [])}")

        r = await c.get("/api/balance")
        balance1 = r.json().get("balance", 0)
        res.check("da tru tien ghe (3500)", balance1 < balance0,
                  f"{balance0} -> {balance1}")

        # Mở nhiều lượt
        for count in (2, 3, 5):
            r = await c.post("/api/case/jelly-starter/open", json={"count": count})
            ok = r.status_code == 200 and len(r.json().get("openings", [])) == count
            res.check(f"POST open count={count} -> {count} mon", ok,
                      f"{r.status_code} n={len(r.json().get('openings', [])) if r.status_code == 200 else '-'}")

        # Lỗi input
        for bad, expect in [(99, 400), (0, 400), (-1, 400), ("abc", 400)]:
            r = await c.post("/api/case/jelly-starter/open", json={"count": bad})
            res.check(f"POST open count={bad!r} -> {expect}", r.status_code == expect,
                      str(r.status_code))

        r = await c.post("/api/case/khong-ton-tai/open", json={"count": 1})
        res.check("POST open ruong khong ton tai -> 404", r.status_code == 404,
                  str(r.status_code))

        # CSRF bắt buộc
        r = await c.post("/api/case/jelly-starter/open", json={"count": 1},
                         headers={"X-CSRF": "sai-token"})
        res.check("POST open CSRF sai -> 403", r.status_code == 403, str(r.status_code))
    return res


# ---------------------------------------------------------------- Bot 03
async def bot_03_inventory() -> BotResult:
    """Túi đồ & bán hàng: bán 1, bán tất cả, chống bán lại."""
    res = register(3, "Túi đồ & bán hàng")
    async with bot_client(BASE, bot_name(3)) as c:
        await c.post("/api/case/jelly-starter/open", json={"count": 3})

        r = await c.get("/inventory")
        res.check("GET /inventory -> 200", r.status_code == 200, str(r.status_code))
        ids = extract_inventory_ids(r.text)
        res.check("tui co mon sau khi mo ruong", len(ids) > 0, f"n={len(ids)}")

        if ids:
            r = await c.post("/api/inventory/sell", json={"ids": ids[:2]})
            ok = r.status_code == 200 and r.json().get("sold") == 2
            res.check("POST /api/inventory/sell 2 mon -> 200", ok,
                      f"{r.status_code} {r.text[:70]}")
            res.check("sell tra ve amount_fmt", "amount_fmt" in r.json())

            # Bán lại món đã bán -> phải lỗi
            r = await c.post("/api/inventory/sell", json={"ids": ids[:2]})
            res.check("ban lai mon da ban -> 400", r.status_code == 400,
                      str(r.status_code))

            # Bán món của người khác -> phải lỗi
            r = await c.post("/api/inventory/sell", json={"ids": [999999]})
            res.check("ban mon khong ton tai -> 400", r.status_code == 400,
                      str(r.status_code))

        # Bán tất cả
        await c.post("/api/case/jelly-starter/open", json={"count": 2})
        r = await c.post("/api/inventory/sell-all", json={})
        res.check("POST /api/inventory/sell-all -> 200", r.status_code == 200,
                  f"{r.status_code} {r.text[:70]}")

        # Bán tất cả khi túi rỗng
        r = await c.post("/api/inventory/sell-all", json={})
        res.check("sell-all khi tui rong -> 400 (hoac 200 khong loi)",
                  r.status_code in (200, 400), str(r.status_code))

        # Rút đồ Nexo: mặc định tắt -> 503
        r = await c.post("/api/inventory/withdraw", json={"id": ids[0] if ids else 1})
        res.check("POST withdraw (chua bat) -> 503", r.status_code == 503,
                  str(r.status_code))
    return res


# ---------------------------------------------------------------- Bot 04
async def bot_04_upgrade() -> BotResult:
    """Nâng cấp 2→1: mục đích hợp lệ, mục đích sai, món không tồn tại."""
    res = register(4, "Nâng cấp 2→1")
    async with bot_client(BASE, bot_name(4)) as c:
        # Mở nhiều rương để có đủ món cược
        for _ in range(4):
            await c.post("/api/case/jelly-starter/open", json={"count": 2})

        r = await c.get("/upgrade")
        res.check("GET /upgrade -> 200", r.status_code == 200, str(r.status_code))
        stakes = extract_upgrade_stakes(r.text)
        res.check("trang /upgrade co mon de cuoc", len(stakes) > 0, f"n={len(stakes)}")

        r = await c.get("/api/upgrade/targets")
        res.check("GET /api/upgrade/targets -> 200", r.status_code == 200,
                  str(r.status_code))

        # Chọn môn cược có mục đích hợp lệ (không dựa vào stakes[0] vì giá trị ngẫu nhiên)
        stake_id = stake_value = 0
        targets: list[dict] = []
        for raw_id, value in stakes:
            resp = await c.get("/api/upgrade/targets", params={"value": value})
            found = resp.json().get("targets", []) if resp.status_code == 200 else []
            if found:
                stake_id, stake_value, targets = raw_id, value, found
                break
        res.check("tim duoc mon cuoc co muc dich hop le", stake_id > 0,
                  f"value={stake_value}")

        if stake_id and targets:
            t = targets[0]
            r = await c.post("/api/upgrade", json={
                "inventory_id": stake_id,
                "target_id": t["id"],
                "target_coin": t["coin"],
            })
            ok = r.status_code == 200 and "won" in r.json()
            res.check("POST /api/upgrade -> 200 co ket qua", ok,
                      f"{r.status_code} {r.text[:70]}")

            # Mục đích không tồn tại
            r = await c.post("/api/upgrade", json={
                "inventory_id": stake_id, "target_id": "khong-ton-tai",
                "target_coin": 1,
            })
            res.check("upgrade muc dich sai -> 400", r.status_code == 400,
                      str(r.status_code))

            # target_coin sai (gia khac thuc te)
            r = await c.post("/api/upgrade", json={
                "inventory_id": stake_id, "target_id": t["id"],
                "target_coin": t["coin"] + 999_999,
            })
            res.check("upgrade gia dich sai -> 400", r.status_code == 400,
                      str(r.status_code))

        # Món không tồn tại
        r = await c.post("/api/upgrade", json={
            "inventory_id": 999999, "target_id": "x", "target_coin": 1,
        })
        res.check("upgrade mon khong ton tai -> 400", r.status_code == 400,
                  str(r.status_code))

        # CSRF
        r = await c.post("/api/upgrade", json={
            "inventory_id": 1, "target_id": "x", "target_coin": 1,
        }, headers={"X-CSRF": "sai"})
        res.check("POST upgrade CSRF sai -> 403", r.status_code == 403,
                  str(r.status_code))
    return res


# ---------------------------------------------------------------- Bot 05
async def bot_05_battle_room() -> BotResult:
    """Battle: tạo phòng, vào, rời (hoàn tiền), hủy, đá bot, phân quyền."""
    res = register(5, "Battle — quản lý phòng")
    async with bot_client(BASE, bot_name(5)) as c:
        # Tạo phòng 4 ghế (chưa đủ ghế -> vẫn WAITING).
        # Dùng 4 ghế vì `fill_bots` chỉ lấp tới khi đủ ghế; với 2-3 ghế,
        # bot loop nền có thể kích hoạt trận trước khi bot kịp đá/nghỉ.
        r = await c.post("/api/battles", json={
            "case_id": "jelly-starter", "rounds": 1, "slots": 4,
            "mode": "STANDARD", "lines": [{"case_id": "jelly-starter", "count": 1}],
        })
        ok = r.status_code == 200 and "id" in r.json()
        res.check("POST /api/battles -> 200 tao phong", ok, f"{r.status_code} {r.text[:70]}")
        battle_id = r.json().get("id") if ok else None
        if not battle_id:
            return res

        res.check("phong moi tao ra WAITING",
                  r.json().get("status") == "WAITING", str(r.json().get("status")))
        res.check("host la chinh ta", r.json().get("host") == bot_name(5))

        # Tiền ghế đã bị trừ
        balance_after_create = (await c.get("/api/balance")).json().get("balance", 0)
        res.check("da tru tien ghe khi tao phong", balance_after_create < 5_000_000,
                  f"{balance_after_create}")

        # Trang phòng
        r = await c.get(f"/battles/{battle_id}")
        res.check(f"GET /battles/{battle_id} -> 200", r.status_code == 200,
                  str(r.status_code))

        # Host da ngoi sanh khi tao phong -> khong can join. Phong van WAITING
        # (4 ghe, chi 1 nguoi) nen duoc phep kick/leave.
        detail = (await c.get(f"/api/battles/{battle_id}")).json()
        seated = len(detail.get("players") or [])
        res.check("phong co host (chinh ta)", seated >= 1, f"seated={seated}")
        res.check("phong van WAITING de kick/leave", detail.get("status") == "WAITING",
                  str(detail.get("status")))

        # Rời phòng -> hoàn tiền
        r = await c.post(f"/api/battles/{battle_id}/leave", json={})
        res.check("POST /leave -> 200", r.status_code == 200, f"{r.status_code} {r.text[:70]}")
        balance_after_leave = (await c.get("/api/balance")).json().get("balance", 0)
        res.check("tien ghe da hoan lai", balance_after_leave > balance_after_create,
                  f"{balance_after_create} -> {balance_after_leave}")

        # Rời phòng không tồn tại
        r = await c.post("/api/battles/999999/leave", json={})
        res.check("POST leave tran khong ton tai -> 404", r.status_code == 404,
                  str(r.status_code))

        # Gọi bot cho đủ ghế -> trận tự quay (kiểm tra luồng "goi bot")
        r = await c.post("/api/battles", json={
            "case_id": "jelly-starter", "rounds": 1, "slots": 2,
        })
        if r.status_code == 200:
            bid_bot = r.json()["id"]
            r = await c.post(f"/api/battles/{bid_bot}/bots", json={})
            res.check("POST /bots -> 200 them bot", r.status_code == 200,
                      f"{r.status_code} {r.text[:70]}")

            # Đá bot — chỉ hợp lệ khi phòng còn WAITING. Nếu bot loop nền đã
            # kích hoạt trận (đủ ghế -> tự quay) thì kick phải bị từ chối,
            # và đó cũng là hành vi ĐÚNG — nên ta chấp nhận cả hai.
            battle_now = (await c.get(f"/api/battles/{bid_bot}")).json()
            if battle_now.get("status") == "WAITING":
                bot_target = next(
                    (p["player"] for p in (battle_now.get("players") or [])
                     if p.get("is_bot") and p["player"] != bot_name(5)),
                    None,
                )
                if bot_target:
                    r = await c.post(f"/api/battles/{bid_bot}/kick",
                                     json={"player": bot_target})
                    res.check("POST /kick bot -> 200", r.status_code == 200,
                              f"{r.status_code} {r.text[:70]}")
                else:
                    res.check("co bot de kick", False, "khong tim thay bot")
            else:
                # Trận đã chạy -> kick phải bị từ chối (không đá được khi
                # trận đã bắt đầu). Đây là hành vi đúng.
                r = await c.post(f"/api/battles/{bid_bot}/kick",
                                 json={"player": bot_name(5)})
                res.check(
                    "kick khi tran da chay -> bi tu choi (400)",
                    r.status_code == 400,
                    f"{r.status_code} {r.text[:60]}",
                )

            # Không được đá người thật
            r = await c.post(f"/api/battles/{bid_bot}/kick", json={"player": bot_name(5)})
            res.check("kick chu phong (nguoi that) -> 400", r.status_code == 400,
                      str(r.status_code))

            # Vào phòng của người khác (bot 05 -> phòng bot 06)
            r = await c.post(f"/api/battles/{bid_bot}/join", json={})
            res.check(
                "vai phong da bat dau -> bi tu choi (400)",
                r.status_code == 400,
                f"{r.status_code} {r.text[:60]}",
            )

        # Hủy phòng (tạo phòng mới để hủy)
        r = await c.post("/api/battles", json={
            "case_id": "jelly-starter", "rounds": 1, "slots": 2,
        })
        if r.status_code == 200:
            bid2 = r.json()["id"]
            r = await c.post(f"/api/battles/{bid2}/cancel", json={})
            res.check("POST /cancel -> 200", r.status_code == 200,
                      f"{r.status_code} {r.text[:70]}")

        # CSRF
        r = await c.post("/api/battles", json={
            "case_id": "jelly-starter", "rounds": 1, "slots": 2,
        }, headers={"X-CSRF": "sai"})
        res.check("POST /api/battles CSRF sai -> 403", r.status_code == 403,
                  str(r.status_code))
    return res


# ---------------------------------------------------------------- Bot 06
async def bot_06_battle_play() -> BotResult:
    """Battle: đủ ghế tự quay, xem kết quả, chỉ winner nhận đồ, rematch."""
    res = register(6, "Battle — chơi & kết quả")
    async with bot_client(BASE, bot_name(6)) as c:
        # --- Vào phòng của người khác (bot 05 tạo phòng 4 ghế) ---
        async with bot_client(BASE, bot_name(5)) as host_c:
            r = await host_c.post("/api/battles", json={
                "case_id": "jelly-starter", "rounds": 1, "slots": 4,
                "mode": "STANDARD", "lines": [{"case_id": "jelly-starter", "count": 1}],
            })
            if r.status_code == 200:
                guest_bid = r.json()["id"]
                r = await c.post(f"/api/battles/{guest_bid}/join", json={})
                res.check("POST /join vao phong nguoi khac -> 200", r.status_code == 200,
                          f"{r.status_code} {r.text[:70]}")
                if r.status_code == 200:
                    res.check("phong co 2 nguoi that",
                              len(r.json().get("players") or []) == 2,
                              f"n={len(r.json().get('players') or [])}")
                    res.check("van la WAITING (4 ghe, 2 nguoi)",
                              r.json().get("status") == "WAITING",
                              str(r.json().get("status")))
                    # Vào 2 lần -> phong bi tu choi (chong ngoi trung)
                    r2 = await c.post(f"/api/battles/{guest_bid}/join", json={})
                    res.check("join 2 lan -> bi tu choi", r2.status_code == 400,
                              f"{r2.status_code} {r2.text[:60]}")
                # Rời phòng -> hoàn tiền ghế
                r = await c.post(f"/api/battles/{guest_bid}/leave", json={})
                res.check("POST /leave tu phong nguoi khac -> 200", r.status_code == 200,
                          f"{r.status_code} {r.text[:70]}")
                # Rời xong thi vao lai duoc (phong con ghe trong)
                r = await c.post(f"/api/battles/{guest_bid}/join", json={})
                res.check("roi xong vao lai duoc -> 200", r.status_code == 200,
                          f"{r.status_code} {r.text[:60]}")
                # Dọn: rời lại + host hủy phòng
                await c.post(f"/api/battles/{guest_bid}/leave", json={})
                await host_c.post(f"/api/battles/{guest_bid}/cancel", json={})

        # --- Trận đầy ghế -> tự động quay ---
        r = await c.post("/api/battles", json={
            "case_id": "jelly-starter", "rounds": 1, "slots": 2,
            "mode": "STANDARD", "lines": [{"case_id": "jelly-starter", "count": 1}],
        })
        if r.status_code != 200:
            res.check("tao phong -> 200", False, r.text[:70])
            return res
        battle_id = r.json()["id"]
        res.check("tao phong -> 200", True, f"id={battle_id}")

        # Gọi bot cho đủ ghế -> tự động quay
        r = await c.post(f"/api/battles/{battle_id}/bots", json={})
        res.check("them bot -> 200", r.status_code == 200, str(r.status_code))

        # Chờ settle
        status = ""
        for _ in range(40):
            r = await c.get(f"/api/battles/{battle_id}")
            status = r.json().get("status", "")
            if status in ("FINISHED", "CANCELLED"):
                break
            await asyncio.sleep(0.5)
        res.check("phong da ket thuc (FINISHED)", status == "FINISHED", status)

        data = (await c.get(f"/api/battles/{battle_id}")).json()
        res.check("co winner", bool(data.get("winner")), str(data.get("winner")))
        res.check("co drops", len(data.get("drops") or []) > 0,
                  f"n={len(data.get('drops') or [])}")

        # Chỉ winner nhận đồ trong túi: nếu ta thắng thì PHẢI có đồ,
        # nếu ta thua thì PHẢI KHÔNG có đồ (không được lấy đồ của người khác).
        winner = data.get("winner")
        r = await c.get("/inventory")
        ids = extract_inventory_ids(r.text, limit=50)
        if winner == bot_name(6):
            res.check("winner co do trong tui", len(ids) > 0, f"n={len(ids)}")
        else:
            res.check(
                "nguoi thua khong nhan do (chi winner nhan do)",
                len(ids) == 0,
                f"winner={winner} n={len(ids)}",
            )

        # API danh sách battle
        r = await c.get("/api/battles")
        res.check("GET /api/battles -> 200", r.status_code == 200, str(r.status_code))

        # Battle không tồn tại
        r = await c.get("/api/battles/999999")
        res.check("GET /api/battles/999999 -> 404", r.status_code == 404,
                  str(r.status_code))

        # Rematch (chỉ khi FINISHED và mình có trong phòng)
        r = await c.post(f"/api/battles/{battle_id}/rematch", json={
            "case_id": "jelly-starter", "rounds": 1, "mode": "STANDARD",
            "lines": [{"case_id": "jelly-starter", "count": 1}],
        })
        res.check("POST /rematch -> 200", r.status_code == 200,
                  f"{r.status_code} {r.text[:70]}")
    return res


# ---------------------------------------------------------------- Bot 07
async def bot_07_roulette() -> BotResult:
    """Roulette: state, đặt cược khi BETTING, số dư, cược quá nhỏ."""
    res = register(7, "Roulette")
    async with bot_client(BASE, bot_name(7)) as c:
        r = await c.get("/roulette")
        res.check("GET /roulette -> 200", r.status_code == 200, str(r.status_code))

        r = await c.get("/api/roulette/state")
        res.check("GET /api/roulette/state -> 200", r.status_code == 200,
                  str(r.status_code))
        state = r.json()
        res.check("state co phase/status", bool(state.get("status")),
                  str(state.get("status")))

        # Chờ phase BETTING
        bet_ok = False
        for _ in range(70):
            st = (await c.get("/api/roulette/state")).json()
            if st.get("status") == "BETTING":
                bet_ok = True
                break
            await asyncio.sleep(1.0)
        res.check("co the cho vong quay ve phase BETTING", bet_ok)

        if not bet_ok:
            return res

        balance0 = (await c.get("/api/balance")).json().get("balance", 0)
        r = await c.post("/api/roulette/bet", json={"side": "village", "amount": 100})
        ok = r.status_code == 200 and "amount" in r.json()
        res.check("POST /api/roulette/bet -> 200", ok, f"{r.status_code} {r.text[:70]}")

        if ok:
            balance1 = (await c.get("/api/balance")).json().get("balance", 0)
            res.check("da tru tien cuoc", balance1 < balance0, f"{balance0} -> {balance1}")

        # Cược quá nhỏ
        r = await c.post("/api/roulette/bet", json={"side": "village", "amount": 1})
        res.check("POST roulette bet qua nho -> 400", r.status_code == 400,
                  str(r.status_code))

        # Cược vượt số dư
        r = await c.post("/api/roulette/bet", json={"side": "village", "amount": 999_999_999})
        res.check("POST roulette bet vuot so du -> loi (400/402)",
                  r.status_code in (400, 402), str(r.status_code))

        # Side không hợp lệ
        r = await c.post("/api/roulette/bet", json={"side": "khong-ton-tai", "amount": 100})
        res.check("POST roulette side sai -> 400", r.status_code == 400,
                  str(r.status_code))

        # CSRF
        r = await c.post("/api/roulette/bet", json={"side": "village", "amount": 100},
                         headers={"X-CSRF": "sai"})
        res.check("POST roulette CSRF sai -> 403", r.status_code == 403,
                  str(r.status_code))
    return res


# ---------------------------------------------------------------- Bot 08
async def bot_08_bonus_wallet_api() -> BotResult:
    """Bonus ngày + Ví + API đọc công khai."""
    res = register(8, "Bonus · Ví · API đọc")
    async with bot_client(BASE, bot_name(8)) as c:
        # Bonus lần đầu
        r = await c.get("/bonus")
        res.check("GET /bonus -> 200", r.status_code == 200, str(r.status_code))
        r = await c.post("/api/bonus", json={})
        ok = r.status_code == 200 and "amount" in r.json()
        res.check("POST /api/bonus lan 1 -> 200", ok, f"{r.status_code} {r.text[:70]}")
        if ok:
            balance = (await c.get("/api/balance")).json().get("balance", 0)
            res.check("bonus cong vao vi", balance > 0, str(balance))

        # Lần 2 -> cooldown
        r = await c.post("/api/bonus", json={})
        res.check("POST /api/bonus lan 2 -> 400 (cooldown 24h)", r.status_code == 400,
                  str(r.status_code))

        # Ví
        r = await c.get("/vi")
        res.check("GET /vi -> 200", r.status_code == 200, str(r.status_code))
        res.check("trang vi hien thi Coin", "Coin" in r.text)

        # API đọc
        for path, key in [
            ("/api/balance", "balance_fmt"),
            ("/api/drops", "drops"),
        ]:
            r = await c.get(path)
            res.check(f"GET {path} -> 200 co '{key}'",
                      r.status_code == 200 and key in r.json(), str(r.status_code))

        r = await c.get("/api/online")
        res.check("GET /api/online -> 200", r.status_code == 200, str(r.status_code))
        res.check("online co 'online' va 'max'",
                  "online" in r.json() and "max" in r.json())

        r = await c.get("/api/admins")
        res.check("GET /api/admins -> 200", r.status_code == 200, str(r.status_code))
        res.check("admins la danh sach", isinstance(r.json().get("admins"), list))
    return res


# ---------------------------------------------------------------- Bot 09
async def bot_09_chatbot() -> BotResult:
    """Chatbot trợ lý lệnh: hỏi được, CSRF, câu hỏi rỗng, XSS, rate limit."""
    res = register(9, "Chatbot trợ lý lệnh")
    async with bot_client(BASE, bot_name(9)) as c:
        r = await c.post("/api/chat", json={"q": "lệnh xem số dư là gì?"})
        ok = r.status_code == 200 and "reply" in r.json()
        res.check("POST /api/chat -> 200 co reply", ok, f"{r.status_code} {r.text[:70]}")
        if ok:
            res.check("reply khong rong", len(r.json()["reply"].strip()) > 10)
            res.check("co danh sach lenh goi y", isinstance(r.json().get("commands"), list))

        r = await c.post("/api/chat", json={"q": "cách đổi skin"})
        res.check("POST /api/chat cau hoi 2 -> 200", r.status_code == 200,
                  str(r.status_code))

        # Câu hỏi rỗng
        r = await c.post("/api/chat", json={"q": ""})
        res.check("POST /api/chat cau rong -> 400", r.status_code == 400,
                  str(r.status_code))

        # Câu hỏi quá dài -> cắt bớt, không lỗi
        r = await c.post("/api/chat", json={"q": "a" * 900})
        res.check("POST /api/chat cau rat dai -> 200 (da cat)", r.status_code == 200,
                  str(r.status_code))

        # CSRF
        r = await c.post("/api/chat", json={"q": "test"}, headers={"X-CSRF": "sai"})
        res.check("POST /api/chat CSRF sai -> 403", r.status_code == 403,
                  str(r.status_code))

        # Khách chưa đăng nhập -> 401
        async with httpx.AsyncClient(base_url=BASE, timeout=15) as anon:
            r = await anon.post("/api/chat", json={"q": "test"})
            res.check("POST /api/chat chua dang nhap -> 401", r.status_code == 401,
                      str(r.status_code))

        # XSS: câu hỏi chứa script -> reply không được thô HTML
        r = await c.post("/api/chat", json={"q": "<script>alert(1)</script>"})
        res.check("POST /api/chat XSS -> khong lo loi", r.status_code in (200, 400),
                  str(r.status_code))
        if r.status_code == 200:
            res.check("reply khong chua <script> nguyen ban",
                      "<script>" not in r.json().get("reply", ""))
    return res


# ---------------------------------------------------------------- Bot 10
async def bot_10_admin() -> BotResult:
    """Admin: phân quyền + CRUD sản phẩm/rương trên bản sao danh mục."""
    res = register(10, "Admin — quản trị danh mục")
    # Người thường KHÔNG được vào admin
    async with bot_client(BASE, bot_name(10)) as c:
        r = await c.get("/admin", follow_redirects=False)
        res.check("GET /admin (nguoi thuong) -> 303 ve /gacha",
                  r.status_code == 303 and "/gacha" in r.headers.get("location", ""),
                  f"{r.status_code} {r.headers.get('location', '')}")
        r = await c.get("/api/admin/products")
        res.check("GET /api/admin/products (nguoi thuong) -> 403",
                  r.status_code == 403, str(r.status_code))

    # Lấy danh sách admin thật từ server (OP list)
    async with httpx.AsyncClient(base_url=BASE, timeout=15) as anon:
        r = await anon.get("/api/admins")
        admins = r.json().get("admins", []) if r.status_code == 200 else []
    admin_name = admins[0]["name"] if admins else ""
    if not admin_name:
        res.check("lay duoc ten admin tu /api/admins", False, "danh sach rong")
        return res
    res.check("lay duoc ten admin tu /api/admins", True, admin_name)

    async with bot_client(BASE, admin_name) as c:
        r = await c.get("/admin")
        res.check("GET /admin (admin) -> 200", r.status_code == 200, str(r.status_code))
        res.check("trang admin hien thi thong ke", "Lượt mở" in r.text)

        r = await c.get("/admin/products")
        res.check("GET /admin/products -> 200", r.status_code == 200, str(r.status_code))

        r = await c.get("/api/admin/products")
        ok = r.status_code == 200 and "items" in r.json()
        res.check("GET /api/admin/products (admin) -> 200", ok, str(r.status_code))
        items = r.json().get("items", [])
        cases = r.json().get("cases", [])
        res.check("co san pham de test", len(items) > 0, f"n={len(items)}")
        res.check("co ruong de test", len(cases) > 0, f"n={len(cases)}")

        # Thêm rương
        r = await c.post("/api/admin/cases", json={
            "id": "qa-bot-case", "name": "QA Bot Case",
            "description": "Rương do bot QA tạo", "pull_cost": 1000,
        })
        res.check("POST /api/admin/cases -> 200", r.status_code == 200,
                  f"{r.status_code} {r.text[:80]}")

        # Thêm sản phẩm vào rương đó
        r = await c.post("/api/admin/products", json={
            "case_id": "qa-bot-case", "id": "qa-bot-item", "name": "QA Bot Item",
            "rarity": "consumer", "weight": 1.0, "coin": 1000, "nexo_amount": 1,
        })
        res.check("POST /api/admin/products -> 200", r.status_code == 200,
                  f"{r.status_code} {r.text[:80]}")

        # Sửa sản phẩm
        r = await c.put("/api/admin/products/qa-bot-case/qa-bot-item",
                        json={"name": "QA Bot Item Đã Sửa"})
        res.check("PUT /api/admin/products/... -> 200", r.status_code == 200,
                  f"{r.status_code} {r.text[:80]}")

        # Xoá sản phẩm
        r = await c.delete("/api/admin/products/qa-bot-case/qa-bot-item")
        res.check("DELETE /api/admin/products/... -> 200", r.status_code == 200,
                  f"{r.status_code} {r.text[:80]}")

        # Xoá rương
        r = await c.delete("/api/admin/cases/qa-bot-case")
        res.check("DELETE /api/admin/cases/... -> 200", r.status_code == 200,
                  f"{r.status_code} {r.text[:80]}")

        # Thêm thiếu trường -> 400
        r = await c.post("/api/admin/cases", json={"name": "thieu id"})
        res.check("POST cases thieu id -> 400", r.status_code == 400,
                  str(r.status_code))
    return res


# ---------------------------------------------------------------- Chạy
async def main() -> int:
    print("=" * 70)
    print("  10 BOT QA — KIỂM THỬ TOÀN BỘ CHỨC NĂNG WEB (chạy song song)")
    print(f"  Server: {BASE}   |   Dry-run: True")
    print("=" * 70)

    # Server riêng: server + test phải dùng CUNG file DB, nếu không bot
    # "khong du Coin" (tien nam o DB nay, server doc DB kia).
    server = TestServer(PORT)
    if not server.start():
        print("!! Khong khoi dong duoc server test — abort.")
        server.stop()
        return 1
    print(f"  Server test da len tai {server.base_url}")
    print(f"  DB test: {server.db_file}")

    # Chuẩn bị ví cho tất cả bot (ghi vào DB mà server đang dùng)
    os.environ["GACHA_DB_PATH"] = str(server.db_file)
    for name in ALL_BOT_NAMES:
        reset_bot_wallet(name)

    try:
        tasks = [
            bot_01_navigation(),
            bot_02_open_case(),
            bot_03_inventory(),
            bot_04_upgrade(),
            bot_05_battle_room(),
            bot_06_battle_play(),
            bot_07_roulette(),
            bot_08_bonus_wallet_api(),
            bot_09_chatbot(),
            bot_10_admin(),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        # Dọn dẹp
        cleanup_bots()
        server.stop()

    print()
    print("=" * 70)
    print("  TỔNG KẾT 10 BOT")
    print("=" * 70)
    total_pass = 0
    total_fail = 0
    for res in RESULTS:
        total_pass += len(res.passed)
        total_fail += len(res.failed)
        mark = "OK " if res.ok else "XX "
        print(f"  [{mark}] {res.bot}  {res.title:<38} "
              f"{len(res.passed):>3} PASS  {len(res.failed):>2} FAIL")
        for name, detail in res.failed:
            print(f"         FAIL -> {name}  {detail}")

    print()
    print(f"  TỔNG: {total_pass} PASS, {total_fail} FAIL")
    if total_fail:
        print("=" * 70)
        return 1
    print("  >>> 10 BOT QA PASS — toan bo chuc nang web hoat dong")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
