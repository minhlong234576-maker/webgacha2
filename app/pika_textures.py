"""Index texture NexoMC từ server Minecraft (đọc qua PikaMC API).

Mục đích: web lấy ảnh item trực tiếp từ server thay vì bản sao local.

Cơ chế:
1. Đọc các file `.yml` item trong `plugins/Nexo/items/**` -> mỗi item có
   `Pack.texture` trỏ tới texture trong resource pack.
2. `Pack.texture` có 2 dạng:
   - `namespace:duong_dan`   -> `assets/<ns>/textures/<duong_dan>.png`
   - `namespace/duong_dan`   -> `assets/<ns>/textures/<duong_dan>.png`
   - `duong_dan` (khong co namespace) -> `assets/minecraft/textures/<duong_dan>.png`
3. Chỉ những texture **ton tai that** tren server moi duoc dung.

Index duoc cache lau (mac dinh 5 phut) vi doc lai toan bo server la rat
nhieu request. Texture tren server doi theo lap nhieu lan, khong can lam
moi lien tuc.

Cache dung chung cho ca `nexo_id` -> duong_dan va `texture path` -> file that.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import yaml

from .errors import MoneyError
from .pika import list_dir, read_file

log = logging.getLogger("jellyvale.textures")

# Thu muc chua item NexoMC va resource pack.
ITEM_DIRS = ("plugins/Nexo/items",)
PACK_ROOT = "plugins/Nexo/pack"

# Cho phep nghe: thay doi `Pack.texture` -> doi file khac.
ALT_SUFFIXES = ("", ".png")

# File anh hop le trong resource pack.
IMAGE_EXTS = (".png",)

# Cache TTL (giay). Texture tren server doi theo lap nhieu lan.
TTL = 300.0

# Khoa trong qua trong khi quet server (tranh quet trung nhieu lan).
_lock = asyncio.Lock()

# Index hien tai: nexo_id -> duong dan file that tren server.
_index: dict[str, str] = {}
# Tap duong dan texture da xac nhan ton tai (dung cho fallback theo duong dan).
_known_paths: set[str] = set()
_indexed_at: float = 0.0


def _age() -> float:
    return time.monotonic() - _indexed_at


def is_fresh() -> bool:
    return bool(_index) and _age() < TTL


def _texture_to_path(texture: str) -> str:
    """Chuyen `Pack.texture` thanh duong dan file that tren server.

    `namespace:duong_dan` va `namespace/duong_dan` deu tro toi
    `assets/<namespace>/textures/<duong_dan>.png`.
    """
    raw = texture.strip()
    if not raw:
        return ""
    # Bo duoi .png neu co (mot so ban khai bao san duoi .png).
    if raw.lower().endswith(".png"):
        raw = raw[:-4]
    namespace = "minecraft"
    body = raw
    if ":" in raw:
        namespace, body = raw.split(":", 1)
    elif "/" in raw:
        # `namespace/duong_dan` — phan dau la namespace.
        head, tail = raw.split("/", 1)
        if head and not head.lower().endswith(".png"):
            namespace, body = head, tail
    return f"{PACK_ROOT}/assets/{namespace}/textures/{body}.png"


async def _collect_png_files(directory: str, depth: int = 0) -> set[str]:
    """Quet de quyet moi file `.png` trong mot thu muc (recursive, gian han)."""
    found: set[str] = set()
    if depth > 5:
        return found
    try:
        entries = await list_dir(directory)
    except (MoneyError, Exception):  # noqa: BLE001 - loi mang -> bo qua
        return found
    for entry in entries:
        name = str(entry.get("name") or "")
        if not name:
            continue
        full = f"{directory}/{name}" if directory else name
        if entry.get("directory"):
            found |= await _collect_png_files(full, depth + 1)
        elif name.lower().endswith(IMAGE_EXTS):
            found.add(full)
    return found


async def _read_item_yml(path: str) -> dict[str, Any]:
    """Doc mot file `.yml` item NexoMC, tra ve dict item -> config."""
    text = await read_file(path)
    if not text:
        return {}
    try:
        data = yaml.safe_load(text)
    except Exception:
        log.warning("YAML khong doc duoc: %s", path, exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


async def _scan_items() -> list[tuple[str, str]]:
    """Tra ve danh sach `(nexo_id, texture_path)` tu moi file item yml."""
    pairs: list[tuple[str, str]] = []
    seen_yml: set[str] = set()

    for root in ITEM_DIRS:
        # Gom het file .yml trong cac thu muc con (1 cap la du cho NexoMC).
        yml_files: list[str] = []
        try:
            entries = await list_dir(root)
        except Exception:
            entries = []
        for entry in entries:
            name = str(entry.get("name") or "")
            if not name:
                continue
            if entry.get("directory"):
                try:
                    sub = await list_dir(f"{root}/{name}")
                except Exception:
                    continue
                for sub_entry in sub:
                    sub_name = str(sub_entry.get("name") or "")
                    if sub_name.endswith((".yml", ".yaml")):
                        yml_files.append(f"{root}/{name}/{sub_name}")
            elif name.endswith((".yml", ".yaml")):
                yml_files.append(f"{root}/{name}")

        for yml_path in yml_files:
            if yml_path in seen_yml:
                continue
            seen_yml.add(yml_path)
            items = await _read_item_yml(yml_path)
            for item_id, cfg in items.items():
                if not isinstance(cfg, dict):
                    continue
                pack = cfg.get("Pack")
                if not isinstance(pack, dict):
                    continue
                texture = pack.get("texture")
                if not texture:
                    continue
                pairs.append((str(item_id), _texture_to_path(str(texture))))
    return pairs


async def refresh() -> dict[str, str]:
    """Quet server va cap nhat index (bo qua cache).

    Tra ve mapping `nexo_id -> duong dan file` cho item co texture that.
    """
    global _index, _known_paths, _indexed_at

    pairs = await _scan_items()
    if not pairs:
        return _index

    # Chi giu duong dan da xac nhan ton tai that tren server.
    existing = await _collect_png_files(f"{PACK_ROOT}/assets")

    index: dict[str, str] = {}
    known: set[str] = set()
    for item_id, path in pairs:
        if path in existing:
            index[item_id.lower()] = path
            known.add(path)

    _index = index
    _known_paths = known
    _indexed_at = time.monotonic()
    log.info(
        "Da index %d texture NexoMC (%d item)", len(index), len(existing)
    )
    return index


async def get_index() -> dict[str, str]:
    """Mapping `nexo_id -> duong dan file` (co cache TTL)."""
    if is_fresh():
        return _index
    async with _lock:
        if is_fresh():
            return _index
        try:
            await refresh()
        except Exception:
            log.warning("Khong quet duoc texture NexoMC", exc_info=True)
    return _index


async def resolve_nexo_id(nexo_id: str | None) -> str | None:
    """Tra ve duong dan file texture cho `nexo_id` (None neu khong co).

    Neu `nexo_id` rong -> None. Neu `nexo_id` khong co trong index ->
    thu gọc theo chuan hoa ten (bo dau `_`, `-`) truoc khi tra lai.
    """
    if not nexo_id:
        return None
    key = nexo_id.strip().lower()
    if not key:
        return None
    index = await get_index()
    if key in index:
        return index[key]
    # Thu chuan hoa: `leviathan_helmet` <-> `leviathan-helmet`.
    norm = re.sub(r"[^a-z0-9]", "", key)
    for item_id, path in index.items():
        if re.sub(r"[^a-z0-9]", "", item_id) == norm:
            return path
    return None


async def resolve_texture_path(texture: str) -> str | None:
    """Tra ve duong dan file that cho mot `Pack.texture` bat ky."""
    path = _texture_to_path(texture)
    if not path:
        return None
    index = await get_index()
    known = _known_paths or set(index.values())
    if path in known:
        return path
    # Chua biet -> thu tai vi: ton tai that tren server khong?
    try:
        entries = await list_dir(path.rsplit("/", 1)[0])
    except Exception:
        return None
    target = path.rsplit("/", 1)[1]
    for entry in entries:
        if str(entry.get("name") or "") == target:
            return path
    return None


def stats() -> dict[str, int]:
    """Thong ke index hien tai (de phong doi)."""
    return {
        "items": len(_index),
        "paths": len(_known_paths),
        "age": int(_age()),
    }
