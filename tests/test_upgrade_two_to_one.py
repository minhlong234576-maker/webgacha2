"""Regression test cho tính năng nâng cấp "2 món lên 1 món".

Bắt được các bug đã gặp:
1. Chọn trùng cùng 1 món 2 lần -> tổng giá trị bị đếm 2 lần (tỉ lệ 72%
   thay vì 36%), tức là 1 món sinh ra 2 món đích.
2. Race condition: 2 request song song dùng cùng 2 món -> CẢ HAI đều
   thành công -> clone item (mất 2 món, nhận 2 món đích).
3. Một trong 2 món đã bị dùng (bán/rút) -> lượt nâng cấp phải hủy toàn bộ,
   KHÔNG được ăn mất món còn lại.
4. Món cược của người khác -> phải bị chặn.
5. Target không tồn tại / coin sai -> phải bị chặn, món cược giữ nguyên.

Chạy trên DB tạm + DRY-RUN (jellyvale-gacha-dev §4).
"""
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["GACHA_DRY_RUN"] = "true"
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="jvupgrade_")
shutil.copy(ROOT / "data" / "gacha.db", os.path.join(TMP, "gacha.db"))

from app import game, store  # noqa: E402
from app.gacha import market_listings  # noqa: E402

store.DB_PATH = Path(TMP) / "gacha.db"
store.init()

PASSES = 0
FAILS: list[str] = []
MARKET = market_listings()
# Món đích: giá 2.500 Coin -> với 1 món 1.000 tỉ lệ 36%, với 2 món 72%.
TARGET = next((m for m in MARKET if m.coin >= 2500), None)
assert TARGET is not None, "gacha.json phai co mon gia >= 2500"


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSES
    if cond:
        PASSES += 1
        print(f"  PASS {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"   {detail}" if detail else ""))


def make_item(player: str, value: int, name: str = "Mon Test") -> int:
    base = MARKET[0]
    obj = type(base)(
        id=base.id,
        name=name,
        rarity=base.rarity,
        weight=base.weight,
        coin=value,
        image=base.image,
        color=base.color,
    )
    return store.add_inventory(player, obj, "test")


def status_of(item_id: int) -> str:
    row = store.get_inventory_item(item_id)
    return row["status"] if row else "<missing>"


def held_count(player: str) -> int:
    return len(store.list_inventory(player, "held"))


print("=== 1. 1 MON LEN 1 MON (BASELINE) ===")
p = "UpSingle1"
one = make_item(p, 1000)
r = game.do_upgrade(p, [one], TARGET.id, TARGET.coin)
check("1 mon: thanh cong", r["won"] in (True, False))
check("1 mon: tỉ lệ 36%", r["chance"] == 36.0, f"chance={r['chance']}")
check("1 mon: status -> upgraded", status_of(one) == "upgraded", status_of(one))
if r["won"]:
    check("1 mon thang: co mon dich trong túi", r["reward_id"] is not None)
else:
    check("1 mon thua: khong co mon dich", r["reward_id"] is None)

print()
print("=== 2. 2 MON LEN 1 MON ===")
p = "UpDouble1"
a, b = make_item(p, 1000), make_item(p, 1000)
held_before = held_count(p)
r = game.do_upgrade(p, [a, b], TARGET.id, TARGET.coin)
check("2 mon: thanh cong", r["won"] in (True, False))
check("2 mon: tỉ lệ 72% (tong gia tri x2)", r["chance"] == 72.0, f"chance={r['chance']}")
check("2 mon a -> upgraded", status_of(a) == "upgraded", status_of(a))
check("2 mon b -> upgraded", status_of(b) == "upgraded", status_of(b))
check(
    "2 mon: so mon 'held' giam dung 2 (hoac 3 neu thang)",
    held_count(p) == held_before - 2 + (1 if r["won"] else 0),
    f"before={held_before} after={held_count(p)} won={r['won']}",
)
check("2 mon: response co 2 stakes", len(r["stakes"]) == 2, str(len(r["stakes"])))

print()
print("=== 3. CHON TRUNG ID (BUG: tỉ lệ bi double-count) ===")
p = "UpDup1"
dup = make_item(p, 1000)
r = game.do_upgrade(p, [dup, dup], TARGET.id, TARGET.coin)
check("trung ID: tỉ lệ phai la 36% (khong 72%)", r["chance"] == 36.0, f"chance={r['chance']}")
check("trung ID: chi 1 mon bi dung", status_of(dup) == "upgraded")
check(
    "trung ID: khong tao 2 mon dich",
    held_count(p) == (1 if r["won"] else 0),
    f"held={held_count(p)} won={r['won']}",
)

print()
print("=== 4. RACE: 2 REQUEST SONG SONG DUNG CUNG 2 MON ===")
p = "UpRace1"
r1, r2 = make_item(p, 1000), make_item(p, 1000)
outcomes: list[str] = []


def worker() -> None:
    try:
        res = game.do_upgrade(p, [r1, r2], TARGET.id, TARGET.coin)
        outcomes.append("OK")
    except game.GameError:
        outcomes.append("ERR")


threads = [threading.Thread(target=worker) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()

ok_count = outcomes.count("OK")
check("race: chi 1 request duoc thanh cong", ok_count == 1, f"outcomes={outcomes}")
check(
    "race: khong clone item (khong con 2 mon dich)",
    held_count(p) == (1 if outcomes.count("OK") else 0),
    f"held={held_count(p)}",
)

print()
print("=== 5. MOT MON DA BI DUNG -> HUY TOAN BO ===")
p = "UpUsed1"
used = make_item(p, 1000)
fresh = make_item(p, 1000)
store.set_inventory_status([used], "sold")
held_before = held_count(p)
try:
    game.do_upgrade(p, [used, fresh], TARGET.id, TARGET.coin)
    check("mon da dung: phai bi chan", False, "khong nem loi")
except game.GameError as exc:
    check("mon da dung: bi chan", True, exc.message)
check(
    "mon da dung: mon con lai van 'held' (khong bi an)",
    status_of(fresh) == "held",
    status_of(fresh),
)
check("mon da dung: khong tao mon dich", held_count(p) == held_before, f"{held_before} -> {held_count(p)}")

print()
print("=== 6. MON CUA NGUOI KHAC ===")
p = "UpOwner1"
thief = "UpThief1"
mine = make_item(p, 1000)
theirs = make_item(thief, 1000)
try:
    game.do_upgrade(p, [mine, theirs], TARGET.id, TARGET.coin)
    check("do cua nguoi khac: bi chan", False, "khong nem loi")
except game.GameError as exc:
    check("do cua nguoi khac: bi chan", True, exc.message)
check("do cua nguoi khac: mon cua tao van 'held'", status_of(mine) == "held", status_of(mine))

print()
print("=== 7. TARGET KHONG HOP LE ===")
p = "UpTarget1"
c1 = make_item(p, 1000)
try:
    game.do_upgrade(p, [c1, make_item(p, 1000)], "khong-ton-tai", 999)
    check("target khong ton tai: bi chan", False, "khong nem loi")
except game.GameError as exc:
    check("target khong ton tai: bi chan", True, exc.message)
check("target khong ton tai: mon cược van 'held'", status_of(c1) == "held", status_of(c1))

p = "UpTarget2"
c2 = make_item(p, 1000)
try:
    game.do_upgrade(p, [c2, make_item(p, 1000)], TARGET.id, TARGET.coin + 1)
    check("target sai coin: bi chan", False, "khong nem loi")
except game.GameError as exc:
    check("target sai coin: bi chan", True, exc.message)
check("target sai coin: mon cược van 'held'", status_of(c2) == "held", status_of(c2))

print()
print("=== 8. DANH SACH RONG / QUA NHIEU / ID SAI ===")
p = "UpEdge1"
try:
    game.do_upgrade(p, [], TARGET.id, TARGET.coin)
    check("danh sach rong: bi chan", False)
except game.GameError as exc:
    check("danh sach rong: bi chan", True, exc.message)

try:
    game.do_upgrade(p, [0, -5], TARGET.id, TARGET.coin)
    check("id khong hop le: bi chan", False)
except game.GameError as exc:
    check("id khong hop le: bi chan", True, exc.message)

too_many = [make_item(p, 100) for _ in range(game.UPGRADE_MAX_STAKES + 1)]
try:
    game.do_upgrade(p, too_many, TARGET.id, TARGET.coin)
    check("qua so luong mon: bi chan", False)
except game.GameError as exc:
    check("qua so luong mon: bi chan", True, exc.message)

print()
print("=== 9. UPGRADE THAT BAI -> KHONG DUOC HUNG MON ===")
p = "UpFail1"
f1 = make_item(p, 1000)
f2 = make_item(p, 1000)
held_before = held_count(p)
try:
    game.do_upgrade(p, [f1, f2], TARGET.id, TARGET.coin + 7)
except game.GameError:
    pass
check("that bai: ca 2 mon van 'held'", status_of(f1) == "held" and status_of(f2) == "held",
      f"{status_of(f1)} / {status_of(f2)}")
check("that bai: khong doi so mon trong túi", held_count(p) == held_before,
      f"{held_before} -> {held_count(p)}")

print()
print("=== 10. TARGET RE (ty le) ===")
p = "UpOdds1"
o1, o2 = make_item(p, 1000), make_item(p, 1000)
r = game.do_upgrade(p, [o1, o2], TARGET.id, TARGET.coin)
expected = round(min(0.85, (2000 / TARGET.coin) * 0.9) * 100, 2)
check("tỉ lệ 2 mon dung cong thuc", r["chance"] == expected, f"{r['chance']} vs {expected}")

print()
print("=== 11. HISTORY GHI LAI DUNG (2 mon -> 1 dong, tong gia tri) ===")
rows = store.run(
    lambda c: c.execute(
        "SELECT stake_name, stake_value FROM upgrades WHERE player = ? ORDER BY id DESC LIMIT 1",
        ("UpOdds1",),
    ).fetchone()
)
check("history: stake_value = tong gia tri 2 mon", rows and rows["stake_value"] == 2000,
      str(dict(rows)) if rows else "khong co dong")
check("history: stake_name gop 2 mon", rows and rows["stake_name"].count("+") == 1,
      rows["stake_name"] if rows else "")

print()
print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
if FAILS:
    print("FAIL:", FAILS)
    sys.exit(1)
print(">>> UPGRADE 2-TO-1 TEST PASS")
