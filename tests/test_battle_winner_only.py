"""
Test: Battle inventory - chỉ winner nhận đồ.

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

TMP = tempfile.mkdtemp(prefix="jvbattle_")
shutil.copy(ROOT / "data" / "gacha.db", os.path.join(TMP, "gacha.db"))

# Danh muc mau cho test — KHONG doc `gacha.json` that (admin co the xoa het
# san pham / ca ruong, neu vay test se khong co gi de mo ruong).
sys.path.insert(0, str(ROOT / "tests"))
import fixture_catalog  # noqa: E402

fixture_catalog.use_fixture(Path(TMP))


from app import game, store  # noqa: E402

store.DB_PATH = Path(TMP) / "gacha.db"


def test_only_winner_gets_items():
    """Standard mode: chỉ winner được các items từ drops của winner."""
    store.init()
    
    host = "Host"
    p2 = "Player2"
    # Bản copy DB có thể mang số dư cũ (hoặc 0) -> set lại trong DB tạm.
    store.set_wallet(host, 500_000)
    store.set_wallet(p2, 500_000)
    game.seed_wallet(host)
    game.seed_wallet(p2)
    
    # Lưu inventory trước battle
    inv_host_before = set(row["id"] for row in store.list_inventory(host))
    inv_p2_before = set(row["id"] for row in store.list_inventory(p2))
    
    print(f"\nBefore battle:")
    print(f"  Host inventory: {len(inv_host_before)} items")
    print(f"  P2 inventory: {len(inv_p2_before)} items")
    
    # Tạo battle 3 vòng
    b = game.create_battle(host, "jelly-starter", slots=2, rounds=3, mode="STANDARD")
    bid = b["id"]
    print(f"\nBattle {bid} created (3 rounds)")
    
    # P2 vào -> auto-start + settle
    b_full = game.join_existing_battle(p2, bid)
    print(f"After join: status={b_full['status']}, winner={b_full.get('winner')}")
    
    # Lấy kết quả chi tiết
    fresh = store.get_battle(bid)
    winner = fresh["winner"]
    loser = host if winner == p2 else p2
    drops = fresh.get("drops", [])
    
    print(f"\n=== Battle Result ===")
    print(f"Winner: {winner}")
    print(f"Loser: {loser}")
    print(f"Total drops recorded: {len(drops)}")
    
    drops_by_player = {}
    for drop in drops:
        p = drop["player"]
        drops_by_player.setdefault(p, [])
        drops_by_player[p].append(drop)
    
    print(f"\nDrops by player:")
    for p in [host, p2]:
        d_list = drops_by_player.get(p, [])
        print(f"  {p}: {len(d_list)} drops")
        for d in d_list:
            print(f"    - {d['name']} ({d['rarity']}) {d['value']:,} Coin")
    
    # Kiểm tra inventory sau battle
    inv_host_after = set(row["id"] for row in store.list_inventory(host))
    inv_p2_after = set(row["id"] for row in store.list_inventory(p2))
    
    inv_host_gained = inv_host_after - inv_host_before
    inv_p2_gained = inv_p2_after - inv_p2_before
    
    print(f"\n=== Inventory After Battle ===")
    print(f"Host gained: {len(inv_host_gained)} items")
    print(f"P2 gained: {len(inv_p2_gained)} items")
    
    # Chỉ winner được nhận đồ
    if winner == host:
        assert len(inv_host_gained) == 3, f"Host (winner) should gain 3 items, got {len(inv_host_gained)}"
        assert len(inv_p2_gained) == 0, f"P2 (loser) should gain 0 items, got {len(inv_p2_gained)}"
        print(f"\n✓ Host won → Host gained 3 items, P2 gained 0 items (CORRECT)")
    else:
        assert len(inv_p2_gained) == 3, f"P2 (winner) should gain 3 items, got {len(inv_p2_gained)}"
        assert len(inv_host_gained) == 0, f"Host (loser) should gain 0 items, got {len(inv_host_gained)}"
        print(f"\n✓ P2 won → P2 gained 3 items, Host gained 0 items (CORRECT)")


if __name__ == "__main__":
    try:
        test_only_winner_gets_items()
        print("\n" + "="*60)
        print("✓ TEST PASSED - Only winner gets battle items")
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        import sys
        sys.exit(1)
