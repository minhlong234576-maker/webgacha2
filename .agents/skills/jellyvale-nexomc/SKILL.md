---
name: jellyvale-nexomc
description: Project guide for integrating NexoMC custom items, textures, and `nexo give` withdrawals into JellyVale Gacha (`gacha.json`, `app/static/items/`, `app/gacha.py`, `app/pika.py`).
---

# JellyVale Gacha × NexoMC Integration

Use this skill alongside the global `nexomc` skill when adding real Minecraft Nexo items, resource-pack icons, or in-game item withdrawals.

## 1. Item & Texture Mapping (`gacha.json` ↔ `plugins/Nexo/`)
- Each item in `gacha.json` can declare:
  - `id`: Web item identifier (also determines image file lookup).
  - `nexo_id` *(optional)*: Exact NexoItem ID from `plugins/Nexo/items/*.yml` (must match `^[a-z0-9_:-]{1,64}$`).
  - `nexo_amount` *(optional, default `1`)*: Quantity granted by `nexo give`.
- **Image Auto-Resolver (`app/gacha.py:resolve_image`):**
  - Looks up `app/static/items/<id>.{png,webp,jpg,jpeg,svg}` (PNG takes top priority over existing SVG placeholders).
  - Export Nexo item textures (`plugins/Nexo/pack/assets/<ns>/textures/item/<path>.png`) or rendered icons directly as `app/static/items/<id>.png` — no code edits needed.

## 2. NexoMC Config Conventions (Paper/Folia 1.21.4+)
- **Ids are permanent:** Once a `nexo_id` is mapped in `gacha.json` or placed in-game, never rename the YAML key.
- **Prefer `Components.item_model` over `CustomModelData`** on Minecraft 1.21.4+:
  ```yaml
  starter_jackpot:
    itemname: "<gradient:#fbbf24:#f59e0b>Jackpot Starter"
    material: NETHER_STAR
    Pack:
      texture: jellyvale:item/starter_jackpot
    Components:
      item_model: jellyvale:item/starter_jackpot
  ```
- Reload on the server with `/nexo reload items` (or `/nexo reload` when pack assets change).

## 3. Enabling In-Game Item Withdrawals (`Rút`)
1. Ensure every withdrawable item in `gacha.json` has `"nexo_id": "<id>"`.
2. Ensure `PIKA_API_KEY` has `control.console` permission and `GACHA_DRY_RUN=false`.
3. Set `GACHA_NEXO_WITHDRAW=true` in `.env` and restart the server.
4. `POST /api/inventory/withdraw` validates ownership, `held` status, `USERNAME_RE`, and `NEXO_ID_RE`, runs `nexo give {player} {item_id} {amount}` via `pika.nexo_give_item`, and only then marks the inventory row `withdrawn`.

