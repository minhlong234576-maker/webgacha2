"""Đo tốc độ DB hiện tại — baseline trước khi tối ưu."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import os, sys, time, statistics
os.environ['GACHA_DRY_RUN'] = 'false'
sys.path.insert(0, str(ROOT))

from app import store


def bench(name, fn, n=200):
    fn()  # warmup
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    dt = (time.perf_counter() - t0) / n * 1000
    print(f'  {name:<34} {dt:>8.3f} ms/op')
    return dt


print('=== BENCHMARK store.run() ===')
bench('get_balance', lambda: store.get_balance('Trez1724'), 300)
bench('list_inventory (rỗng)', lambda: store.list_inventory('Trez1724', 'held'), 200)
bench('recent_drops', lambda: store.recent_drops(30), 200)
bench('recent_tx', lambda: store.recent_tx('Trez1724', 20), 200)
bench('last_bonus', lambda: store.last_bonus('Trez1724'), 200)
bench('list_battles', store.list_battles, 100)
bench('waiting_battles', store.waiting_battles, 100)
bench('stats', store.stats, 50)

print()
print('=== BENCHMARK thao tác ghi ===')
def write_tx():
    store.run(lambda c: c.execute(
        "INSERT INTO tx (player, kind, amount, note, created_at) VALUES ('bench','x',1,'',0)"))

t0 = time.perf_counter()
for _ in range(100):
    write_tx()
print(f'  {"write tx x100":<34} {(time.perf_counter()-t0)*10:>8.3f} ms/op')

store.run(lambda c: c.execute("DELETE FROM tx WHERE player='bench'"))
