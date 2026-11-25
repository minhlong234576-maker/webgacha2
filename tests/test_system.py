"""Kiem chung logic + bao mat toan he thong (chay tren DB tam, khong dung DB that).

Nhom kiem tra:
1. Tien that: khong the mo ruong / ban do / cuoc khong du tien
2. Race condition: nhieu request dong thoi khong lam mat Coin
3. Phan quyen: khong the go y do cua nguoi khac
4. SQL injection: input nham khong phai SQL
5. Business logic: ban trung, ban lai, ban mot lot
6. Roulette: cuoc qua/bien gioi han
7. Bonus: cooldown 24h
8. Upgrade / Battle
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import os
import shutil
import sys
import tempfile
import threading

os.environ["GACHA_DRY_RUN"] = "true"
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="jvtest_")
shutil.copy(ROOT / "data" / "gacha.db", os.path.join(TMP, "gacha.db"))

from app import game, store  # noqa: E402

store.DB_PATH = Path(TMP) / "gacha.db"

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


def fresh_player(name, balance=100_000):
    store.set_wallet(name, balance)
    store.run(lambda c: c.execute("DELETE FROM inventory WHERE player = ?", (name,)))
    store.run(lambda c: c.execute("DELETE FROM tx WHERE player = ?", (name,)))
    return name


ITEM = {
    "id": "test_item",
    "name": "Item Test",
    "rarity": "common",
    "coin": 1000,
    "image": "/static/items/dust.svg",
    "color": "#ffffff",
}


def make_item(player, coin=1000):
    data = dict(ITEM, coin=coin)
    return store.add_inventory(player, data, "case")


print("=== 1. TIEN THAT ===")
p = fresh_player("TesterA", 100_000)
try:
    store.debit(p, 200_000, "test", "khong du")
    check("debit qua so du bi chan", False, "khong nem loi")
except ValueError:
    check("debit qua so du bi chan", True)
check("so du khong doi khi debit fail", store.get_balance(p) == 100_000)

store.debit(p, 100_000, "test", "het")
check("debit het so du thanh cong", store.get_balance(p) == 0)

fresh_player(p, 100_000)
store.debit(p, 0, "test", "zero")
store.debit(p, -50, "test", "am")
check("debit 0/am khong doi so du", store.get_balance(p) == 100_000)

store.credit(p, -9999, "test", "am")
check("credit am khong tao tien ao", store.get_balance(p) == 100_000)

before = len(store.recent_tx(p, 100))
store.set_wallet(p, 55_555)
after = len(store.recent_tx(p, 100))
check("set_wallet khong ghi them giao dich",
      before == after and store.get_balance(p) == 55_555)

print()
print("=== 2. RACE CONDITION ===")
p = fresh_player("TesterB", 1000)


def debit_worker():
    try:
        store.debit(p, 100, "race", "x")
    except ValueError:
        pass


threads = [threading.Thread(target=debit_worker) for _ in range(20)]
for t in threads:
    t.start()
for t in threads:
    t.join()
bal = store.get_balance(p)
check("so du khong bao am sau race", bal >= 0, str(bal))
check("so du = 0 sau race (chi 10 lan duoc tru)", bal == 0, str(bal))

# 2b. race nghiem trong: 30 thread deu debIT so du DUONG 2000
# (mua 2000 xuoc dong), ton tai 2000 -> phai con du 0, khong am
p1b = fresh_player("TesterB2", 2000)


def debit_big():
    try:
        store.debit(p1b, 2000, "race", "big")
    except ValueError:
        pass


threads = [threading.Thread(target=debit_big) for _ in range(30)]
for t in threads:
    t.start()
for t in threads:
    t.join()
bal1b = store.get_balance(p1b)
check("race debit toan bo so du -> khong bao am",
      bal1b == 0, str(bal1b))
check("race debit toan bo so du -> khong con tien ao",
      bal1b == 0 and store.get_balance(p1b) == 0, str(bal1b))

# 2c. REGRESSION: connection dung lai + credit vao vi chua ton tai
# Bug cu: `con.total_changes` la tong luy ke cua ca connection nen
# `credit` khong tao dong vi -> crash khi doc balance.
p1c = "TesterB3"
store.run(lambda c: c.execute("DELETE FROM wallets WHERE player = ?", (p1c,)))
# Ghi de truoc de dam bao total_changes > 0 (mo phong connection da dung)
store.credit("TesterB2", 1, "warm", "lam total_changes khac 0")
try:
    bal1c = store.credit(p1c, 500, "test", "vi moi")
    check("REGRESSION: credit tao vi moi tren connection dung lai",
          bal1c == 500, str(bal1c))
except Exception as exc:
    check("REGRESSION: credit tao vi moi tren connection dung lai", False,
          f"{type(exc).__name__}: {exc}")

p2 = fresh_player("TesterC", 0)


def mixed_worker(i):
    if i % 2 == 0:
        store.credit(p2, 10, "race", "in")
    else:
        try:
            store.debit(p2, 10, "race", "out")
        except ValueError:
            pass


threads = [threading.Thread(target=mixed_worker, args=(i,)) for i in range(50)]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("credit/debit xen ke khong phai so du",
      store.get_balance(p2) == 0, str(store.get_balance(p2)))

print()
print("=== 3. PHAN QUYEN: KHONG THE GO Y DO CUA NGUOI KHAC ===")
owner = fresh_player("Owner1", 50_000)
thief = fresh_player("Thief1", 50_000)
item = make_item(owner, 5000)

try:
    game.sell_preview(thief, [item])
    check("khong the xem gia tri do cua nguoi khac", False, "khong nem loi")
except game.GameError:
    check("khong the xem gia tri do cua nguoi khac", True)

try:
    game.sell_items(thief, [item])
    check("khong the ban do cua nguoi khac", False, "khong nem loi")
except game.GameError:
    check("khong the ban do cua nguoi khac", True)
check("do cua nguoi khac van con trong túi",
      store.get_inventory_item(item)["status"] == "held")

try:
    game.do_upgrade(thief, item, "x", 1)
    check("khong the upgrade do cua nguoi khac", False, "khong nem loi")
except game.GameError:
    check("khong the upgrade do cua nguoi khac", True)

print()
print("=== 4. SQL INJECTION ===")
evil = "'; DROP TABLE wallets; --"
store.get_balance(evil)
store.list_inventory(evil, "held")
store.recent_tx(evil, 20)
store.last_bonus(evil)
store.get_inventory_items([1, 2, 3])
alive = store.run(
    lambda c: c.execute("SELECT COUNT(*) FROM wallets").fetchone()[0])
check("bang wallets con nguyen sau SQL injection", alive > 0, str(alive))
check("ten nham duoc xu ly nhu chuoi binh thuong",
      store.get_balance(evil) == 0)

print()
print("=== 5. LOGIC BAN HANG ===")
p = fresh_player("Seller1", 0)
items = [make_item(p, 1000) for _ in range(3)]
total = game.sell_preview(p, items)
check("sell_preview dung tong gia tri", total == 3000, str(total))

res = game.sell_items(p, items)
check("sell_items tra ve so mon", res["sold"] == 3, str(res["sold"]))
check("so du cong dung", res["balance"] == 3000, str(res["balance"]))

try:
    game.sell_items(p, items)
    check("khong the ban lai mon da ban", False, "khong nem loi")
except game.GameError:
    check("khong the ban lai mon da ban", True)
check("so du khong bi cong them lan 2",
      store.get_balance(p) == 3000, str(store.get_balance(p)))

fresh = make_item(p, 500)
try:
    game.sell_items(p, [items[0], fresh])
    check("ban mot mon da ban + mot mon moi -> fail ca lot", False)
except game.GameError:
    check("ban mot mon da ban + mot mon moi -> fail ca lot", True)
check("mon moi van con held (khong bi ban nua)",
      store.get_inventory_item(fresh)["status"] == "held")

print()
print("=== 6. ROULETTE ===")
from app import roulette  # noqa: E402

p = fresh_player("Bettor1", 100_000)
mgr = roulette.roulette_manager
mgr.status = roulette.STATUS_BETTING
mgr.bets = {roulette.SIDE_VILLAGE: [], roulette.SIDE_STEVE: [],
            roulette.SIDE_PILLAGER: []}

try:
    mgr.place_bet(p, roulette.SIDE_VILLAGE, 999_999, is_bot=False)
    check("cuoc qua so du bi chan", False, "khong nem loi")
except ValueError:
    check("cuoc qua so du bi chan", True)

try:
    mgr.place_bet(p, roulette.SIDE_VILLAGE, 50, is_bot=False)
    check("cuoc duoi muc toi thieu bi chan", False)
except ValueError:
    check("cuoc duoi muc toi thieu bi chan", True)

try:
    mgr.place_bet(p, roulette.SIDE_VILLAGE, 99_999_999, is_bot=False)
    check("cuoc tren muc toi da bi chan", False)
except ValueError:
    check("cuoc tren muc toi da bi chan", True)

bal_before = store.get_balance(p)
mgr.place_bet(p, roulette.SIDE_VILLAGE, 1000, is_bot=False)
check("cuoc hop le tru tien",
      store.get_balance(p) == bal_before - 1000,
      f"{bal_before} -> {store.get_balance(p)}")

bal2 = store.get_balance(p)
mgr.winning_side = roulette.SIDE_STEVE
mgr._settle_payouts()
check("cuoc thua khong duoc cong tien",
      store.get_balance(p) == bal2, str(store.get_balance(p)))

bal3 = store.get_balance(p)
mgr.winning_side = roulette.SIDE_VILLAGE
mgr._settle_payouts()
check("cuoc thang duoc cong x2",
      store.get_balance(p) == bal3 + 2000,
      f"{bal3} -> {store.get_balance(p)}")

print()
print("=== 7. BONUS COOLDOWN ===")
p = fresh_player("Bonus1", 0)
store.run(lambda c: c.execute("DELETE FROM bonus WHERE player = ?", (p,)))
first = game.bonus_preview(p)
check("bonus lan dau cho phep", first > 0, str(first))

game.claim_bonus(p, first)
try:
    game.bonus_preview(p)
    check("bonus lan 2 bi chan (cooldown 24h)", False, "khong nem loi")
except game.GameError:
    check("bonus lan 2 bi chan (cooldown 24h)", True)

store.run(lambda c: c.execute(
    "UPDATE bonus SET last_claim = ? WHERE player = ?",
    (store.now() - 25 * 3600, p)))
try:
    game.bonus_preview(p)
    check("bonus cho phep lai sau 25h", True)
except game.GameError:
    check("bonus cho phep lai sau 25h", False)

print()
print("=== 8. UPGRADE ===")
p = fresh_player("Upgrader1", 0)
stake = make_item(p, 1000)
try:
    game.do_upgrade(p, stake, "khong-ton-tai", 999)
    check("upgrade muc dich khong ton tai bi chan", False)
except game.GameError:
    check("upgrade muc dich khong ton tai bi chan", True)

from app.gacha import market_listings  # noqa: E402

market = market_listings()
cheaper = next((m for m in market if m.coin < 1000), None)
if cheaper:
    try:
        game.do_upgrade(p, stake, cheaper.id, cheaper.coin)
        check("upgrade sang muc re hon bi chan", False)
    except game.GameError:
        check("upgrade sang muc re hon bi chan", True)

other = fresh_player("Upgrader2", 0)
try:
    game.do_upgrade(other, stake, "x", 1)
    check("upgrade do cua nguoi khac bi chan", False)
except game.GameError:
    check("upgrade do cua nguoi khac bi chan", True)

print()
print("=== 9. BATTLE ===")
p = fresh_player("Battler1", 500_000)
case = game.get_case("jelly-starter")
battle_id = store.create_battle(
    p, case.id, 1, 2, "STANDARD", case.pull_cost, False)
store.set_battle_status(battle_id, "RUNNING")

try:
    game.join_existing_battle(p, battle_id)
    check("join tran da bat dau bi chan", False, "khong nem loi")
except game.GameError:
    check("join tran da bat dau bi chan", True)

try:
    game.join_existing_battle(p, 999_999)
    check("join tran khong ton tai bi chan", False)
except game.GameError:
    check("join tran khong ton tai bi chan", True)

print()
print("=== 10. TINH NANG HOP DONG DA DUOC GO BO ===")
# Chức năng Hợp đồng đã bị xóa hoàn toàn. Route /contract và /api/contract
# phải trả 404, và không còn hàm do_contract trong tầng game.
check("khong con ham do_contract trong game",
      not hasattr(game, "do_contract"))
check("khong con ham record_contract trong store",
      not hasattr(store, "record_contract"))
check("khong con bang contracts trong DB",
      not store.run(
          lambda c: c.execute(
              "SELECT COUNT(*) FROM sqlite_master "
              "WHERE type='table' AND name='contracts'"
          ).fetchone()[0]))

shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
if FAILS:
    print("FAIL:", FAILS)
    sys.exit(1)
print(">>> SYSTEM TEST PASS")
