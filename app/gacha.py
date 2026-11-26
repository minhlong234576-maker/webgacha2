from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import ROOT, STATIC_DIR, dry_run, nexo_withdraw_enabled

# Thu muc chua `gacha.json`. File cu the co the tro bang bien moi truong
# `GACHA_FILE` (server test dung ban sao tam) — doc DONG sau moi lan goi
# de luon khop voi `catalog_admin`, tranh viec doc sai file khi env bi doi.
GACHA_DIR = ROOT
GACHA_NAME = "gacha.json"


def gacha_file() -> Path:
    """Duong dan file danh muc hien tai."""
    override = os.getenv("GACHA_FILE")
    return Path(override) if override else (GACHA_DIR / GACHA_NAME)


IMAGE_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".svg")
NEXO_ID_RE = re.compile(r"^[a-z0-9_:-]{1,64}$")

RARITY_COLORS = {
    "consumer": "#b0c3d9",
    "industrial": "#5e98d9",
    "milspec": "#4b69ff",
    "restricted": "#8847ff",
    "classified": "#d32ce6",
    "covert": "#eb4b4b",
    "extraordinary": "#e4ae39",
    "common": "#b0c3d9",
    "uncommon": "#4b69ff",
    "rare": "#8847ff",
    "epic": "#d32ce6",
    "legendary": "#e4ae39",
}


def rarity_color(rarity: str) -> str:
    return RARITY_COLORS.get(rarity, "#b0c3d9")


def resolve_image(folder: str, item_id: str, explicit: str | None = None, nexo_id: str | None = None) -> str:
    """Ánh xạ ảnh cho item.

    Ưu tiên: explicit URL -> nexo_id (Pika texture) -> local file -> placeholder.
    """
    if explicit:
        return explicit
    # Thử nexo_id: nếu có, trả về URL proxy `/pika/tex/<path>`.
    if nexo_id:
        from base64 import urlsafe_b64encode
        # URL proxy sẽ được resolve trong async context (main.py).
        # Tạm thời encode vào URL để có thể decode sau.
        encoded = urlsafe_b64encode(nexo_id.encode()).decode().rstrip("=")
        return f"/pika/tex/{encoded}"
    # Fallback: tìm ảnh local.
    for ext in IMAGE_EXTS:
        path = STATIC_DIR / folder / f"{item_id}{ext}"
        if path.exists():
            return f"/static/{folder}/{item_id}{ext}"
    return f"/static/{folder}/_placeholder.svg"


@dataclass
class Item:
    id: str
    name: str
    rarity: str
    weight: float
    coin: int
    image: str = ""
    color: str = ""
    nexo_id: str = ""
    nexo_amount: int = 1

    def as_public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "rarity": self.rarity,
            "weight": self.weight,
            "coin": self.coin,
            "image": self.image,
            "color": self.color or rarity_color(self.rarity),
            "nexo_id": self.nexo_id,
            "nexo_amount": self.nexo_amount,
        }


@dataclass
class Case:
    id: str
    name: str
    description: str
    pull_cost: int
    image: str
    items: list[Item] = field(default_factory=list)
    glow: str = "#e4ae39"


def load_config() -> dict:
    path = gacha_file()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"cases": []}


def _parse_item(raw: dict) -> Item:
    item_id = raw["id"]
    rarity = raw.get("rarity", "consumer")
    nexo_id = str(raw.get("nexo_id") or "").strip()
    try:
        nexo_amount = max(1, int(raw.get("nexo_amount") or 1))
    except (TypeError, ValueError):
        nexo_amount = 1
    return Item(
        id=item_id,
        name=raw["name"],
        rarity=rarity,
        weight=float(raw.get("weight", 1)),
        coin=int(raw.get("coin", 0)),
        image=resolve_image("items", item_id, raw.get("image"), nexo_id),
        color=rarity_color(rarity),
        nexo_id=nexo_id,
        nexo_amount=nexo_amount,
    )


def load_cases() -> list[Case]:
    cases = []
    for raw in load_config().get("cases", []):
        items = [_parse_item(item) for item in raw.get("items", [])]
        glow = rarity_color(items[-1].rarity) if items else "#e4ae39"
        case_id = raw["id"]
        # Rương có thể có nexo_id để lấy ảnh từ Pika.
        case_nexo_id = str(raw.get("nexo_id") or "").strip() or None
        cases.append(
            Case(
                id=case_id,
                name=raw["name"],
                description=raw.get("description", ""),
                pull_cost=int(raw.get("pull_cost", 0)),
                image=resolve_image("cases", case_id, raw.get("image"), case_nexo_id),
                items=items,
                glow=glow,
            )
        )
    return cases


def get_case(case_id: str) -> Case | None:
    for item in load_cases():
        if item.id == case_id:
            return item
    return None


def roll(case: Case) -> Item:
    weights = [max(0, item.weight) for item in case.items]
    if not case.items:
        raise ValueError("empty case")
    if sum(weights) <= 0:
        return case.items[0]
    return random.choices(case.items, weights=weights, k=1)[0]


def pull_cost() -> int:
    cases = load_cases()
    return cases[0].pull_cost if cases else 0


def prizes() -> list[Item]:
    cases = load_cases()
    return cases[0].items if cases else []


def take_command(player: str, amount: int) -> str:
    template = load_config().get("take_command", "eco take {player} {amount}")
    return template.format(player=player, amount=amount)


def give_command(player: str, amount: int) -> str:
    template = load_config().get("give_command", "eco give {player} {amount}")
    return template.format(player=player, amount=amount)


def nexo_give_command(player: str, nexo_id: str, amount: int = 1) -> str:
    """Tao lenh console trao NexoItem cho nguoi choi (an toan injection)."""
    clean_id = nexo_id.strip()
    if not NEXO_ID_RE.fullmatch(clean_id):
        raise ValueError(f"Nexo item id khong hop le: {nexo_id!r}")
    qty = max(1, int(amount))
    template = load_config().get("nexo_give_command", "nexo give {player} {item_id} {amount}")
    return template.format(player=player, item_id=clean_id, amount=qty)


def is_dry_run() -> bool:
    return dry_run()


def is_nexo_withdraw_enabled() -> bool:
    return nexo_withdraw_enabled()


def market_listings() -> list[Item]:
    seen: set[tuple[str, int]] = set()
    listings: list[Item] = []
    for case in load_cases():
        for item in case.items:
            key = (item.id, item.coin)
            if key in seen:
                continue
            seen.add(key)
            listings.append(item)
    listings.sort(key=lambda item: item.coin)
    return listings


def find_listing(item_id: str, coin: int | None = None) -> Item | None:
    matches = [item for item in market_listings() if item.id == item_id]
    if not matches:
        return None
    if coin is None:
        return max(matches, key=lambda item: item.coin)
    for item in matches:
        if item.coin == coin:
            return item
    return matches[0]
