---
name: jellyvale-gacha-dev
description: Project workflow and invariants for JellyVale Gacha (FastAPI + SQLite WAL + PikaMC + Vanilla ES modules). Use whenever modifying routes, economy/real-money flows, auth/sessions, or writing tests in webgacha-main.
---

# JellyVale Gacha Development Workflow

## 1. Real-Money Invariants (`GACHA_DRY_RUN=false`)
- **Source of truth:** ExcellentEconomy on Minecraft server (`data.db`). Local SQLite `wallets` is a mirror.
- **Debits (`open_case`, `battles_create`, `battles_join`, `roulette_bet`):**
  1. Validate input & business constraints first.
  2. Call `await bank.take(user, amount)` (protected by per-player `asyncio.Lock` in `app/pika.py`).
  3. Commit local `game.*` / `roulette_manager.*` state.
  4. If local commit fails, immediately refund via `await bank.give(user, amount)`.
  5. Sync mirror via `await bank.sync(user)`.
- **Credits (`inventory_sell`, `inventory_sell_all`, `api_bonus`):**
  1. Compute exact IDs/amount (`sell_preview` / `bonus_preview`).
  2. Call `await bank.give(user, amount)` first.
  3. Commit local `game.sell_items(user, ids)` (never re-query `held` after `await bank.give`!) or `game.claim_bonus(user, prize)` under per-user lock.

## 2. Session, Auth & Security Rules
- Always use `SafeSessionMiddleware` (`app/security.py`) so malformed/corrupted `jv_session` cookies reset cleanly to `{}` instead of causing HTTP 500.
- All state-changing JSON APIs must call `api_auth(request, csrf=True)`.
- Form POSTs must verify `csrf` or `is_same_origin(request)`.
- Parse request JSON via `read_json_dict(request)` and integer fields via `parse_int(...)` so malformed inputs return HTTP 400.
- Never return raw `str(exc)` on unexpected HTTP 500 exceptions; log with `log.exception(...)` and return a generic error message.

## 3. Frontend Rules
- Run `npx.cmd -y modern-web-guidance@latest search/retrieve` before changing HTML/CSS/JS, and run `legacy-scan app --json` after edits.
- Escape every dynamic string inserted into HTML (`esc()`), or prefer DOM APIs (`textContent`, `replaceChildren()`).
- Keep `<meta name="color-scheme" content="light dark">` and `html.dark` synchronized via the toggle script in `app/templates/base.html`.

## 4. Testing Rules
- Derive repo root dynamically with `Path(__file__).resolve().parent.parent` — never hardcode `c:\code\web\...` or `e:\...`.
- Copy `data/gacha.db` to a `tempfile.mkdtemp()` directory and reassign `store.DB_PATH` before running offline tests.
- Never test against real player `Trez1724` on production DB.

## 5. Multi-Item Upgrade (2-to-1)
- Cơ chế nâng cấp dùng **N món cược → 1 món đích** (`UPGRADE_MAX_STAKES` trần, UI dùng 2).
- **Luôn khử trùng id** trước khi tính tổng giá trị — nếu không, `[id, id]` bị đếm 2 lần (tỉ lệ 72% thay vì 36%) và 1 món sinh ra 2 món đích.
- **Chiếm món cược bằng CAS** (`store.commit_upgrade`): `UPDATE ... WHERE id = ? AND status = 'held'` + kiểm tra `rowcount`. Đọc `held` rồi `UPDATE` ở lệnh khác là race → clone item.
- **Chiếm + cộng món đích phải cùng 1 transaction.** Nếu tách, app crash giữa chừng là người chơi mất món cược mà không nhận được món đích.
- Nếu **bất kỳ** món nào không còn `held` → hủy **toàn bộ** lượt (HTTP 409), không được ăn mất món còn lại.
- Client phải chặn chọn quá số lượng và **reset state** (món đích + danh sách) khi bỏ bớt món cược.
- Regression: `tests/test_upgrade_two_to_one.py` (logic) + `tests/test_upgrade_ui.py` (Playwright).

