"""
Test hồi quy: animation mở rương + cơ chế thoát Battle/bot.

Bắt được các lỗi đã gặp:
1. `case.html` gọi `celebrate()` mà KHÔNG import -> ReferenceError chặn luôn
   việc đăng ký handler "Bán" / "Bán tất cả" (chức năng chết, không chỉ mất
   hiệu ứng).
2. `fx-glow-up` được add vào <html> nhưng không có rule CSS -> hiệu ứng glow
   không tồn tại.
3. Rời phòng Battle khi phòng còn bot -> phòng treo WAITING vô hạn (bot
   không tự rời) -> lobby lấp rác.

Chạy trên DB tạm + DRY-RUN để không đụng ví thật (jellyvale-gacha-dev §4).
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import os
import shutil
import sys
import tempfile

os.environ["GACHA_DRY_RUN"] = "true"
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="jvfx_")
shutil.copy(ROOT / "data" / "gacha.db", os.path.join(TMP, "gacha.db"))

sys.path.insert(0, str(ROOT / "tests"))
import fixture_catalog  # noqa: E402

fixture_catalog.use_fixture(Path(TMP))

from app import bots, game, store  # noqa: E402

store.DB_PATH = Path(TMP) / "gacha.db"

FAILS: list[str] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    print(("  PASS " if ok else "  FAIL ") + label + (f"  {extra}" if extra else ""))
    if not ok:
        FAILS.append(label)


def test_case_html_imports_celebrate() -> None:
    """case.html phải import celebrate (và dùng try/catch quanh lệnh gọi)."""
    print("\n=== 1. TEMPLATE case.html ===")
    src = (ROOT / "app" / "templates" / "case.html").read_text(encoding="utf-8")

    check(
        "case.html import celebrate tu fx.js",
        'import { celebrate } from "/static/fx.js";' in src,
    )
    check("case.html co goi celebrate", "celebrate(" in src)

    # Lỗi gốc: celebrate() ném ReferenceError giữa chừng -> handler bán hàng
    # phía dưới không được đăng ký. Phải bọc try/catch.
    idx_call = src.find("celebrate({")
    idx_guard = src.find("try {", max(0, idx_call - 400))
    check(
        "loi celebrate duoc bao try/catch",
        idx_call != -1 and idx_guard != -1 and idx_guard > idx_call - 400,
    )


def test_fx_glow_up_has_css() -> None:
    """fx-glow-up phải có rule CSS, nếu không hiệu ứng glow không tồn tại."""
    print("\n=== 2. CSS fx-glow-up ===")
    css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")

    check("style.css co rule cho fx-glow-up", "fx-glow-up" in css)
    check("fx-glow-up co keyframes", "@keyframes fx-glow-up" in css)
    check(
        "fx-glow-up dung pseudo-element (::after)",
        "fx-glow-up::after" in css,
    )
    check(
        "fx-glow-up co pointer-events: none (khong chan click)",
        "pointer-events: none" in css,
    )


def test_leave_battle_cancels_bot_only_room() -> None:
    """Rời phòng khi còn bot -> phòng phải bị hủy, không treo WAITING."""
    print("\n=== 3. RỜI PHÒNG CÒN BOT ===")
    store.init()

    host = "FX_Host"
    store.set_wallet(host, 500_000)
    game.seed_wallet(host)

    case = game.get_case("jelly-starter")
    assert case is not None
    # 3 ghế: host + bot = 2/3 -> phong van WAITING (du ghế thi tu dong quay).
    created = game.create_battle(host, case.id, 3, 1, "STANDARD")
    battle_id = created["id"]

    # Ngồi thêm 1 bot -> phòng có người thật + bot.
    bot = store.BOT_NAMES[0]
    game.seed_wallet(bot, is_bot=True)
    game.join_existing_battle(bot, battle_id, is_bot=True)

    detail = store.get_battle(battle_id)
    assert detail is not None
    check("phong co 2 nguoi (that + bot)", len(detail["players"]) == 2)
    check("phong van WAITING", detail["status"] == "WAITING", f"({detail['status']})")

    balance_before = store.get_balance(host)
    check("host bi tru tien ghe khi tao phong", balance_before < 500_000, f"({balance_before})")

    result = game.leave_battle(host, battle_id)

    check(
        "roi phong bao deleted=True (phong khong con nguoi that)",
        bool(result.get("deleted")),
        f"(deleted={result.get('deleted')})",
    )
    check(
        "tien ghe da hoan cho host",
        store.get_balance(host) == 500_000,
        f"({balance_before} -> {store.get_balance(host)})",
    )
    check(
        "phong da bi xoa / huy (khong treo WAITING)",
        store.get_battle(battle_id) is None
        or store.get_battle(battle_id)["status"] == "CANCELLED",
    )

    # Bot trong phong cung phai duoc hoan tien ghe (khong bi "bi lot" mat coin).
    bot_balance = store.get_balance(bot)
    check(
        "bot duoc hoan tien ghe khi phong bi huy",
        bot_balance >= 1_000_000,
        f"({bot_balance})",
    )


def test_cleanup_bot_only_rooms() -> None:
    """Vòng nền bot phải dọn phòng chỉ còn bot (WAITING > 30s)."""
    print("\n=== 4. BOT DỌN PHÒNG MA ===")
    store.init()

    bot = store.BOT_NAMES[1]
    game.seed_wallet(bot, is_bot=True)
    case = game.get_case("jelly-starter")
    assert case is not None
    # 3 ghe: chi 1 bot = 1/3 -> van WAITING (khong tu dong quay).
    created = game.create_battle(bot, case.id, 3, 1, "STANDARD", is_bot=True)
    battle_id = created["id"]

    detail = store.get_battle(battle_id)
    assert detail is not None
    check("phong bot duoc tao", len(detail["players"]) == 1)

    # Tạo phòng MỚI -> bot dọn dẹp phải BỎ QUA (người chơi vừa vào).
    bots._cleanup_bot_only_rooms(store.waiting_battles())
    fresh = store.get_battle(battle_id)
    check(
        "phong moi (<30s) duoc giu nguyen",
        fresh is not None and fresh["status"] == "WAITING",
    )

    # Giả lập phòng cũ (>30s) -> phải bị hủy.
    store.run(
        lambda con: con.execute(
            "UPDATE battles SET created_at = created_at - 120 WHERE id = ?", (battle_id,)
        )
    )
    bots._cleanup_bot_only_rooms(store.waiting_battles())
    fresh = store.get_battle(battle_id)
    check(
        "phong chi con bot (>30s) da bi huy",
        fresh is None or fresh["status"] == "CANCELLED",
        f"(status={fresh['status'] if fresh else 'DELETED'})",
    )


def test_leave_battle_keeps_room_with_other_player() -> None:
    """Phòng còn người THẬT khác thì KHÔNG được hủy khi mình rời."""
    print("\n=== 5. RỜI PHÒNG — CÒN NGƯỜI THẬT KHÁC ===")
    store.init()

    a = "FX_A"
    b = "FX_B"
    for p in (a, b):
        store.set_wallet(p, 500_000)
        game.seed_wallet(p)

    case = game.get_case("jelly-starter")
    assert case is not None
    created = game.create_battle(a, case.id, 3, 1, "STANDARD")
    battle_id = created["id"]
    game.join_existing_battle(b, battle_id)

    result = game.leave_battle(a, battle_id)
    check("khong huy phong khi con nguoi that khac", not result.get("deleted"))

    fresh = store.get_battle(battle_id)
    check(
        "phong van con, host chuyen sang nguoi con lai",
        fresh is not None and fresh["host"] == b,
        f"(host={fresh['host'] if fresh else None})",
    )
    check(
        "nguoi con lai van duoc giu cho",
        fresh is not None and len(fresh["players"]) == 1,
    )


def main() -> int:
    print("=" * 68)
    print("  FX + BATTLE EXIT REGRESSION TEST")
    print("=" * 68)
    test_case_html_imports_celebrate()
    test_fx_glow_up_has_css()
    test_leave_battle_cancels_bot_only_room()
    test_cleanup_bot_only_rooms()
    test_leave_battle_keeps_room_with_other_player()
    print("\n" + "=" * 68)
    if FAILS:
        print(f"  FAIL: {len(FAILS)} loi -> {FAILS}")
        print("=" * 68)
        return 1
    print("  PASS: 0 loi")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
