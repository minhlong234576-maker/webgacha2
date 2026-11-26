"""
Test: Nhiều trận battle chạy song song (concurrent) - kiểm tra race conditions.

Chạy trên DB tạm + DRY-RUN để không đụng ví thật (jellyvale-gacha-dev §4).
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent


import os
import shutil
import sys
import tempfile
import threading
import json
from concurrent.futures import ThreadPoolExecutor

os.environ["GACHA_DRY_RUN"] = "true"
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="jvconcurrent_")
shutil.copy(ROOT / "data" / "gacha.db", os.path.join(TMP, "gacha.db"))

# Danh muc mau cho test — KHONG doc `gacha.json` that (admin co the xoa het
# san pham / ca ruong, neu vay test se khong co gi de mo ruong).
sys.path.insert(0, str(ROOT / "tests"))
import fixture_catalog  # noqa: E402

fixture_catalog.use_fixture(Path(TMP))


from app import game, store  # noqa: E402

store.DB_PATH = Path(TMP) / "gacha.db"


def test_concurrent_battles_no_fixture():
    """Tạo 5 trận, mỗi trận 2 người thật. Roll tất cả cùng lúc.
    
    Không dùng fixture để tránh reload issues.
    """
    store.init()
    
    players = [f"P{i}" for i in range(1, 11)]  # 10 người
    battles = []
    
    print("\n=== Phase 1: Seed ===")
    for p in players:
        try:
            # Bản copy DB có thể đã mang ví P1..P10 với số dư cũ (0 hoặc hết) ->
            # xoá hẳn dòng ví để `seed_wallet` tạo mới với số dư seed.
            store.run(lambda con, n=p: con.execute("DELETE FROM wallets WHERE player = ?", (n,)))
            bal = game.seed_wallet(p)
            print(f"  {p}: {bal:,} Coin")
            assert bal > 0, f"{p} không có Coin"
        except Exception as e:
            print(f"  {p}: FAIL {e}")
            raise
    
    print("\n=== Phase 2: Tạo 5 trận ===")
    def create_battle(idx: int):
        host = players[idx * 2]
        lines = [{"case_id": "jelly-starter", "count": 2 + idx}]
        b = game.create_battle(host, "jelly-starter", slots=2, rounds=2 + idx, mode="STANDARD", lines=lines)
        print(f"  Battle {idx}: created by {host}, id={b['id']}, rounds={b.get('rounds')}")
        return (idx, b)
    
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(create_battle, range(5)))
    
    for idx, b in results:
        assert b is not None, f"Battle {idx} creation failed"
        battles.append(b)
        assert b["status"] == "WAITING"
    print(f"✓ {len(battles)} battles created")
    
    print("\n=== Phase 3: Join ===")
    def join_battle(idx: int):
        b = battles[idx]
        player2 = players[idx * 2 + 1]
        updated = game.join_existing_battle(player2, b["id"])
        print(f"  Battle {idx}: {player2} joined, now {len(updated.get('players', []))} players, status={updated['status']}")
        return (idx, updated)
    
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(join_battle, range(5)))
    
    for idx, b in results:
        assert b is not None, f"Battle {idx} join failed"
        battles[idx] = b
    print("✓ All battles full (or auto-started)")
    
    print("\n=== Phase 4: Roll all concurrently ===")
    def settle(idx: int):
        b = battles[idx]
        result = game.settle_battle(b["id"])
        status = result.get("status")
        winner = result.get("winner")
        drops_count = len(result.get("drops", []))
        print(f"  Battle {idx}: status={status}, winner={winner}, drops={drops_count}")
        return (idx, result)
    
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(settle, range(5)))
    
    for idx, b in results:
        assert b is not None, f"Battle {idx} settle failed"
        assert b["status"] == "FINISHED", f"Battle {idx} status={b['status']}, expected FINISHED"
        battles[idx] = b
    
    print("\n=== Phase 5: Verify ===")
    total_drops = 0
    for idx, b in enumerate(battles):
        bid = b["id"]
        expected_rounds = 2 + idx
        
        fresh = store.get_battle(bid)
        assert fresh is not None
        assert fresh["status"] == "FINISHED"
        assert fresh["winner"] in [players[idx * 2], players[idx * 2 + 1]]
        
        drops = fresh.get("drops", [])
        total_drops += len(drops)
        
        # Mỗi người trong trận phải có expected_drops_per_player drops
        drops_by_player = {}
        for drop in drops:
            p = drop["player"]
            drops_by_player.setdefault(p, 0)
            drops_by_player[p] += 1
        
        p1 = players[idx * 2]
        p2 = players[idx * 2 + 1]
        c1 = drops_by_player.get(p1, 0)
        c2 = drops_by_player.get(p2, 0)
        
        print(f"  Battle {idx}: {fresh['winner']} won. {p1}={c1} drops, {p2}={c2} drops (expected {expected_rounds} each)")
        assert c1 == expected_rounds and c2 == expected_rounds, f"Battle {idx} drops wrong"
    
    # Mỗi trận có `expected_rounds` vòng và MỖI người chơi roll 1 lần mỗi vòng
    # -> tổng drops = 2 * tổng vòng = 2 * (2+3+4+5+6) = 40.
    print(f"\n✓ Total drops: {total_drops} (expected 40)")
    assert total_drops == 40, f"Expected 40 total drops, got {total_drops}"


def test_join_full_auto_starts():
    """Người cuối ngồi vào -> trận tự động bắt đầu."""
    store.init()
    
    host = "Host"
    p2 = "Player2"
    store.run(lambda con: con.execute("DELETE FROM wallets WHERE player IN (?, ?)", (host, p2)))
    game.seed_wallet(host)
    game.seed_wallet(p2)
    
    print("\n=== Create battle (2 slots) ===")
    b = game.create_battle(host, "jelly-starter", slots=2, rounds=1, mode="STANDARD")
    bid = b["id"]
    print(f"Battle {bid}: waiting for 1 more player")
    
    print("=== P2 joins (should auto-start) ===")
    b2 = game.join_existing_battle(p2, bid)
    status = b2['status']
    print(f"After join: status={status}")
    
    # Nếu auto-start hoạt động, phải là FINISHED ngay
    assert status == "FINISHED", f"Expected FINISHED (auto-start), got {status}"
    assert b2["winner"] in [host, p2]
    print(f"✓ Auto-started & finished, winner: {b2['winner']}")


if __name__ == "__main__":
    import sys
    try:
        print("TEST 1: Concurrent battles")
        test_concurrent_battles_no_fixture()
        print("\n" + "="*60)
        print("✓ TEST 1 PASSED")
    except Exception as e:
        print(f"\n✗ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    try:
        print("\n" + "="*60)
        print("TEST 2: Auto-start when full")
        test_join_full_auto_starts()
        print("✓ TEST 2 PASSED")
    except Exception as e:
        print(f"\n✗ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("\n" + "="*60)
    print("✓✓✓ ALL TESTS PASSED ✓✓✓")
