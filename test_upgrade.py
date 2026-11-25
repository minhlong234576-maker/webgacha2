import sys
sys.path.insert(0, "app")
from gacha import load_cases, market_listings

items = market_listings()
print(f"Total market items: {len(items)}")
print("First 5 items:")
for i, item in enumerate(items[:5]):
    print(f"  {i+1}. {item.name}: {item.coin} Coin")

# Test upgrade_targets for 5000 coin stake
from game import upgrade_targets
targets = upgrade_targets(5000)
print(f"\nTargets for 5000 Coin stake: {len(targets)}")
for i, target in enumerate(targets[:5]):
    print(f"  {i+1}. {target['name']}: {target['coin']} Coin ({target['chance']}%)")
