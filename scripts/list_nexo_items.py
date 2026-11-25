"""List NexoMC items with textures for gacha.json mapping."""
import asyncio
import sys
import yaml

sys.path.insert(0, ".")
from app import pika


async def main():
    server = await pika.resolve_server_uuid()
    rows = []

    # Scan item yml files
    for folder in ["plugins/Nexo/items/nexo_defaults", "plugins/Nexo/items"]:
        entries = await pika.list_dir(folder)
        yml_files = []

        for entry in entries:
            name = str(entry.get("name") or "")
            if not name:
                continue
            if entry.get("directory"):
                try:
                    sub = await pika.list_dir(f"{folder}/{name}")
                except Exception:
                    continue
                for sub_entry in sub:
                    sub_name = str(sub_entry.get("name") or "")
                    if sub_name.endswith((".yml", ".yaml")):
                        yml_files.append(f"{folder}/{name}/{sub_name}")
            elif name.endswith((".yml", ".yaml")):
                yml_files.append(f"{folder}/{name}")

        for yml_path in yml_files:
            text = await pika.read_file(yml_path)
            if not text:
                continue
            try:
                data = yaml.safe_load(text) or {}
            except Exception:
                continue
            if not isinstance(data, dict):
                continue

            for item_id, cfg in data.items():
                if not isinstance(cfg, dict):
                    continue
                pack = cfg.get("Pack")
                if not isinstance(pack, dict):
                    continue
                texture = pack.get("texture")
                if not texture:
                    continue
                itemname = cfg.get("itemname", "")
                # Remove color codes
                import re
                clean = re.sub(r"<[^>]+>", "", str(itemname)).strip()
                rows.append({"id": item_id, "texture": str(texture), "name": clean})

    rows.sort(key=lambda x: x["id"])

    # Output
    print(f"{'Item ID':<35} | {'Texture Path':<45} | Name")
    print("-" * 100)
    for r in rows:
        print(f"{r['id']:<35} | {r['texture']:<45} | {r['name'][:44]}")

    print(f"\n=== TOTAL: {len(rows)} items ===")


asyncio.run(main())
