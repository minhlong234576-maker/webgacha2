"""Kiem tra moi nexo_id trong gacha.json co texture that tren server."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import pika_textures  # noqa: E402


async def main() -> int:
    data = json.loads((ROOT / "gacha.json").read_text(encoding="utf-8"))

    used: set[str] = set()
    for case in data.get("cases", []):
        for item in case.get("items", []):
            nexo = str(item.get("nexo_id") or "").strip()
            if nexo:
                used.add(nexo)

    print(f"Distinct nexo_id dung trong gacha.json: {len(used)}")

    index = await pika_textures.refresh()
    print(f"Index tren server: {len(index)} item co texture\n")

    missing = sorted(used - set(index))
    if missing:
        print(f"!! THIEU {len(missing)} nexo_id khong co tren server:")
        for m in missing:
            print(f"   - {m}")
        return 1

    print(f"OK — tat ca {len(used)} nexo_id deu co texture that tren server.")

    # Kiem tra file texture thuc su tai duoc.
    ok = 0
    fail = []
    for nexo in sorted(used):
        path = index[nexo]
        result = await pika.read_binary(path)
        if result and len(result[0]) > 0:
            ok += 1
        else:
            fail.append((nexo, path))
    print(f"Tai duoc: {ok}/{len(used)}")
    for nexo, path in fail:
        print(f"   FAIL {nexo} -> {path}")
    return 1 if fail else 0


raise SystemExit(asyncio.run(main()))
