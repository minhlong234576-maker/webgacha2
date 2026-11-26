"""Sinh `gacha.json` mau cho server test.

Test KHONG duoc phu thuoc vao danh muc production (`gacha.json` that).
Admin co the xoa het san pham / ca ruong, nen file that co the rong — luc do
test se khong co gi de mo ruong, bay len, nang cap hay battle.

Ham `build_fixture()` tao danh muc day du (ruong + san pham) de test luon
co du lieu on dinh, khong phu thuoc trang thai production.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# (id, ten, gia quay, so san pham, nexo_id)
# So san pham phai >= len(ITEM_COINS) de moi muc gia deu xuat hien trong
# danh muc mau (market + targets nang cap).
FIXTURE_CASES: list[tuple[str, str, int, int, str]] = [
    ("jelly-starter", "Rương Jelly Starter", 3500, 10, "jelly_starter"),
    ("jelly-magic", "Rương Ma Pháp", 15000, 10, "jelly_magic"),
    ("jelly-elite", "Rương Elite", 22000, 10, "jelly_elite"),
    ("jelly-vault", "Rương Vault", 70000, 10, "jelly_vault"),
    ("jelly-nether", "Rương Hỏa Ngục Nether", 100000, 10, "jelly_nether"),
    ("jelly-celestial", "Rương Thiên Giới", 200000, 10, "jelly_celestial"),
    ("jelly-jackpot", "Rương Hoàng Gia VIP", 500000, 10, "jelly_jackpot"),
    ("jelly-farm", "Rương Nông Trại", 8000, 10, "jelly_farm"),
    ("jelly-arsenal", "Rương Kho Vũ Khí", 45000, 10, "jelly_arsenal"),
    ("jelly-phantom", "Rương Dao Phantom", 300000, 10, "jelly_phantom"),
]

RARITIES = ["consumer", "industrial", "milspec", "restricted", "classified"]

# Gia tri cua cac mon trong MOI ruong mau. Chon co dinh de test "nang cap 2 mon
# len 1 mon" co ty le 36% / 72% (90% * 1000/2500, 90% * 2000/2500) — mon
# gia 1000 lam "cuc", 2500 la "dich" cho test do.
#
# Phai phu nhieu muc gia (khong chi 3) de `upgrade_targets()` luon tim duoc
# muc dich cho moi muc cuoc cua nguoi choi.
ITEM_COINS = (
    1000, 2500, 5000, 12000, 30000, 75000, 200000, 500000,
    1500000, 5000000,
)


def build_fixture() -> dict[str, Any]:
    """Tra ve danh muc mau (cau truc giong het `gacha.json` that).

    KHONG dat `nexo_id` cho item: `nexo_id` khong ton tai tren server
    Minecraft -> web se goi `/pika/tex/...` va nhan 404 (loi JS console) +
    treo request. Item mau chi dung de test logic, khong rut do that.
    """
    cases: list[dict[str, Any]] = []
    for case_id, name, cost, n_items, nexo_id in FIXTURE_CASES:
        items: list[dict[str, Any]] = []
        for i in range(n_items):
            item_id = f"{case_id.replace('-', '_')}_item_{i + 1}"
            items.append({
                "id": item_id,
                "name": f"{name} — Món {i + 1}",
                "rarity": RARITIES[i % len(RARITIES)],
                "weight": 1.0 + i,
                "coin": ITEM_COINS[i % len(ITEM_COINS)],
                "nexo_amount": 1,
            })
        cases.append({
            "id": case_id,
            "name": name,
            "description": f"{name} — danh muc mau cho test.",
            "pull_cost": cost,
            "items": items,
        })
    return {
        "cases": cases,
        "take_command": "eco take {player} {amount}",
        "give_command": "eco give {player} {amount}",
        "nexo_give_command": "nexo give {player} {item_id} {amount}",
    }


def write_fixture(target: Path) -> Path:
    """Ghi danh muc mau ra `target` va tra ve duong dan file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_fixture(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def use_fixture(tmp_dir: Path | None = None, *, name: str = "gacha.json") -> Path:
    """Tro `GACHA_FILE` toi danh muc mau va tra ve duong dan file do.

    Dung cho test chay DOC LAP (khong qua `run_all.py`): test duoc danh muc
    mau on dinh thay vi doc `gacha.json` that — file that co the rong khi
    admin xoa het san pham / ca ruong.
    """
    import os
    import tempfile

    if tmp_dir is None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="jvfixture_"))
    target = Path(tmp_dir) / name
    write_fixture(target)
    os.environ["GACHA_FILE"] = str(target)
    return target


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("gacha.fixture.json")
    write_fixture(out)
    print(f"Da tao danh muc mau: {out}")
