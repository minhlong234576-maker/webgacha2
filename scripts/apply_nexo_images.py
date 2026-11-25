"""Gan `nexo_id` cho item trong gacha.json tro toi texture NexoMC tren server.

Quy tac: item co ten cu the (khong phai "Do ... 12") duoc gan texture
phu hop theo nghhia. Item ten generic dung texture theo vong tron
de van du mien texture cho moi muc do rarity.

Chay: .\\.venv\\Scripts\\python.exe scripts\\apply_nexo_images.py [--dry]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GACHA = ROOT / "gacha.json"

# ---------------------------------------------------------------------
# Texture co san tren server (49 item, doc tu scripts/list_nexo_items.py)
# ---------------------------------------------------------------------
NEXO = [
    # --- Levianthan Set (bi khoa kinh, chat) ---
    "leviathan_helmet",
    "leviathan_chestplate",
    "leviathan_leggings",
    "leviathan_boots",
    # --- Prismatic (mau sac) ---
    "prismatic_helmet",
    "prismatic_chestplate",
    "prismatic_leggings",
    "prismatic_boots",
    "prismatic_sword",
    "prismatic_axe",
    "prismatic_pickaxe",
    "prismatic_shovel",
    "prismatic_hoe",
    # --- Sakura ---
    "ec_sakura_helmet_armor",
    "ec_sakura_chestplate_armor",
    "ec_sakura_leggings_armor",
    "ec_sakura_boots_armor",
    # --- Wukong ---
    "ec_wukong_helmet",
    "ec_wukong_chestplate",
    "ec_wukong_leggings",
    "ec_wukong_boots",
    # --- Eagle Ascendant ---
    "eagle_ascendant_helmet",
    "eagle_ascendant_chestplate",
    "eagle_ascendant_leggings",
    "eagle_ascendant_boots",
    # --- Little Unicorn ---
    "little_unicorn_helmet",
    "little_unicorn_chestplate",
    "little_unicorn_leggings",
    "little_unicorn_boots",
    # --- Forest Guardian ---
    "forest_helmet",
    "forest_chestplate",
    "forest_leggings",
    "forest_boots",
    "forest_wolf_armor",
    "forest_horse_armor",
    "forest_llama_armor",
    # --- Crystalline Core ---
    "crystalline_core_pack_helmet",
    "crystalline_core_pack_chestplate",
    "crystalline_core_pack_leggings",
    "crystalline_core_pack_boots",
    # --- Mahoraga / Susanoo (trang bi) ---
    "sword_of_extermination",
    "mahoraga_talisman",
    "susanoo_control_scroll",
    "susanoo_mangekyo",
    # --- Khac ---
    "mount_signal_feather",
]

# Nhom texture theo chu de de gan vong tron theo rarity.
GROUPS: list[list[str]] = [
    # consumer -> icon nho / pho bien
    [
        "prismatic_shovel",
        "prismatic_pickaxe",
        "prismatic_axe",
        "forest_boots",
        "forest_leggings",
        "mount_signal_feather",
    ],
    # industrial
    [
        "forest_chestplate",
        "forest_helmet",
        "prismatic_boots",
        "prismatic_leggings",
        "crystalline_core_pack_boots",
    ],
    # milspec
    [
        "crystalline_core_pack_leggings",
        "crystalline_core_pack_chestplate",
        "leviathan_boots",
        "leviathan_leggings",
    ],
    # restricted
    [
        "leviathan_chestplate",
        "leviathan_helmet",
        "ec_sakura_boots_armor",
        "ec_sakura_leggings_armor",
    ],
    # classified
    [
        "ec_sakura_chestplate_armor",
        "ec_sakura_helmet_armor",
        "crystalline_core_pack_helmet",
        "eagle_ascendant_boots",
    ],
    # covert
    [
        "eagle_ascendant_leggings",
        "eagle_ascendant_chestplate",
        "eagle_ascendant_helmet",
        "ec_wukong_helmet",
    ],
    # extraordinary
    [
        "sword_of_extermination",
        "mahoraga_talisman",
        "susanoo_mangekyo",
        "susanoo_control_scroll",
    ],
]

RARITY_ORDER = [
    "consumer",
    "industrial",
    "milspec",
    "restricted",
    "classified",
    "covert",
    "extraordinary",
]

# ---------------------------------------------------------------------
# Gan theo ten rieng (item ten co nghia cu the)
# ---------------------------------------------------------------------
EXACT: dict[str, str] = {
    # --- Mahoraga / Susanoo ---
    "elite_susanoo": "susanoo_mangekyo",
    "vault_susanoo_1": "susanoo_mangekyo",
    "vault_susanoo_2": "susanoo_mangekyo",
    # --- Feather / lua ---
    "celestial_feather_1": "mount_signal_feather",
    "celestial_feather_2": "mount_signal_feather",
    # --- Scroll / sach (dung icon cuon) ---
    "starter_scroll": "susanoo_control_scroll",
    "elite_scroll": "susanoo_control_scroll",
    "elite_scroll_2": "susanoo_control_scroll",
    "vault_scroll_1": "susanoo_control_scroll",
    "vault_scroll_2": "susanoo_control_scroll",
    # --- Mahoraga talisman cho "cuon phep" ---
    "starter_book": "mahoraga_talisman",
    "elite_book": "mahoraga_talisman",
    "elite_book_2": "mahoraga_talisman",
    # --- Vu khi: prismatic sword / axe ---
    "arsenal_01": "prismatic_sword",
    "arsenal_02": "prismatic_axe",
    "arsenal_03": "prismatic_pickaxe",
    "arsenal_04": "prismatic_shovel",
    "arsenal_05": "prismatic_hoe",
    # --- Giap: theo thu tu ---
    "elite_elytra": "eagle_ascendant_helmet",
    "vault_elytra_1": "eagle_ascendant_chestplate",
    "vault_elytra_2": "eagle_ascendant_leggings",
    # --- Wukong (rung / hoang gia) ---
    "royal_36": "ec_wukong_helmet",
    "royal_35": "ec_wukong_chestplate",
    "royal_34": "ec_wukong_leggings",
    "royal_33": "ec_wukong_boots",
    # --- Starter: bui / vang bac / tao / da quy / go / sach ---
    "starter_dust_1": "mount_signal_feather",
    "starter_dust_2": "mount_signal_feather",
    "starter_apple_1": "mount_signal_feather",
    "starter_apple_2": "mount_signal_feather",
    "starter_gem": "prismatic_shovel",
    "starter_stone": "forest_boots",
    "starter_pouch_1": "forest_leggings",
    "starter_pouch_2": "forest_chestplate",
    "starter_iron": "forest_helmet",
    "starter_crystal": "crystalline_core_pack_helmet",
    "starter_jackpot": "sword_of_extermination",
    # --- Elite ---
    "elite_pouch": "prismatic_boots",
    "elite_pouch_2": "prismatic_leggings",
    "elite_diamond": "prismatic_pickaxe",
    "elite_emerald": "prismatic_axe",
    "elite_totem": "mahoraga_talisman",
    "elite_netherite": "crystalline_core_pack_chestplate",
    "elite_dragon": "eagle_ascendant_helmet",
    "elite_jackpot": "sword_of_extermination",
    # --- Vault ---
    "vault_totem_1": "mahoraga_talisman",
    "vault_totem_2": "susanoo_control_scroll",
    "vault_ruby": "prismatic_hoe",
    "vault_netherite": "crystalline_core_pack_chestplate",
    "vault_emerald": "leviathan_boots",
    "vault_dragon": "eagle_ascendant_chestplate",
    "vault_crown": "prismatic_helmet",
    "vault_jackpot": "sword_of_extermination",
    # --- Celestial ---
    "celestial_light_1": "prismatic_sword",
    "celestial_light_2": "prismatic_axe",
    "celestial_elytra_1": "eagle_ascendant_leggings",
    "celestial_elytra_2": "eagle_ascendant_boots",
    "celestial_bow_1": "prismatic_hoe",
    "celestial_bow_2": "prismatic_pickaxe",
    "celestial_dragon_1": "ec_wukong_helmet",
    "celestial_dragon_2": "ec_wukong_chestplate",
    "celestial_halo": "ec_wukong_leggings",
    "celestial_crown": "ec_wukong_boots",
    "celestial_orb": "mahoraga_talisman",
}

# Item ten chua chu "Do ... <so>" -> generic, dung texture theo vong tron rarity.
GENERIC_RE = re.compile(r"^đồ\s+.*\s+\d+$", re.IGNORECASE)


def is_generic(name: str) -> bool:
    return bool(GENERIC_RE.match(name.strip()))


def pick_for_rarity(rarity: str, counter: int) -> str:
    """Chon texture theo rarity, xoay vong trong nhom tuong ung."""
    idx = RARITY_ORDER.index(rarity) if rarity in RARITY_ORDER else 0
    group = GROUPS[idx]
    return group[counter % len(group)]


def main() -> int:
    dry = "--dry" in sys.argv
    data = json.loads(GACHA.read_text(encoding="utf-8"))

    counters: dict[str, int] = {}
    changed = 0
    total = 0

    for case in data.get("cases", []):
        for item in case.get("items", []):
            total += 1
            item_id = item.get("id", "")
            name = str(item.get("name") or "")

            # 1) Neu item da co nexo_id -> giu nguyen.
            if item.get("nexo_id"):
                continue

            # 2) Ban do ten rieng.
            nexo = EXACT.get(item_id)

            # 3) Item generic -> xoay vong theo rarity.
            if not nexo and is_generic(name):
                rarity = item.get("rarity", "consumer")
                n = counters.get(rarity, 0)
                counters[rarity] = n + 1
                nexo = pick_for_rarity(rarity, n)

            if not nexo:
                continue

            item["nexo_id"] = nexo
            changed += 1

    print(f"Tong item: {total} | da gan nexo_id: {changed}")
    print(f"Con lai khong co nexo_id: {total - changed}")

    if dry:
        print("\n--- DRY RUN: khong ghi file ---")
        for case in data.get("cases", [])[:2]:
            for item in case.get("items", [])[:6]:
                print(f"  {item['id']:24} -> {item.get('nexo_id','(none)')}")
        return 0

    GACHA.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nDa ghi {GACHA.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
