import sys
sys.path.insert(0, '.')
from app.game import upgrade_targets

targets = upgrade_targets(5000)
print(f'Targets for 5000 Coin: {len(targets)} items')
if targets:
    print('First 5 targets:')
    for target in targets[:5]:
        print(f"  {target['name']}: {target['coin']} Coin ({target['chance']}%)")
else:
    print("  (no targets)")
