# JellyVale Gacha — Agent Guide

Read `CONSTRAINTS.md` before writing code. Do not weaken it to make a change pass.

## Ngôn ngữ
**Luôn trả lời người dùng bằng tiếng Việt.** Giữ nguyên tiếng Anh cho tên file, định danh kỹ thuật và thông báo lỗi gốc.

## Tech Stack
- **Backend:** Python 3.12+, FastAPI, Starlette (`SafeSessionMiddleware`), Jinja2, SQLite (WAL mode, thread-local connections in `app/store.py`).
- **Frontend:** Server-rendered Jinja2 templates (`app/templates/`), vanilla ES modules & scripts (`app/static/`), custom CSS tokens (`app/static/style.css`).
- **Minecraft / Hosting:** PikaMC panel API (`app/pika.py`), AuthMe SHA256 (`app/security.py`), ExcellentEconomy (`eco take` / `eco give`), OP-based admin auth (`/ops.json` via `app/admins.py`), NexoMC (`nexo give`).

## Key Commands
- **Run dev server (dry-run):** `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080`
- **Run offline logic & security tests:**
 - `.\.venv\Scripts\python.exe tests\test_system.py`
 - `.\.venv\Scripts\python.exe tests\test_security_and_fixes.py`
 - `.\.venv\Scripts\python.exe tests\test_roulette.py`
 - `.\.venv\Scripts\python.exe tests\test_battle_winner_only.py`
 - `.\.venv\Scripts\python.exe tests\test_concurrent_battles.py`
 - `.\.venv\Scripts\python.exe tests\test_upgrade_two_to_one.py`
 - `.\.venv\Scripts\python.exe tests\test_paths_static.py`
- **Run full suite (requires live test servers on 8080/8099/8101):** `.\.venv\Scripts\python.exe tests\run_all.py`
- **Run live-account suite (needs real password, uses real money):**
  `$env:JV_TEST_USER="<name>"; $env:JV_TEST_PASS="<pass>"; .\.venv\Scripts\python.exe tests\test_live_account_browser.py 8080`
- **Frontend pattern check:** `npx.cmd -y modern-web-guidance@latest legacy-scan app --json`

## Architecture Map
- `app/main.py` — FastAPI routes, middleware (`SafeSessionMiddleware`, security headers), request validation.
- `app/templates/landing.html` + `app/static/landing.css` + `app/static/landing.js` — landing page `/` (video nền lazy-load, bảng giá rương). CSS/JS riêng, chỉ nạp khi render landing.
- `app/static/media/` — video nền landing (`landing-loop.mp4` / `.webm`) + poster JPEG. Nguon nằm trong `data-src` để JS quyết định có tải hay không.
- `app/security.py` — AuthMe SHA256 verification, IP rate limiting, CSRF tokens, `SafeSessionMiddleware`, `is_same_origin`.
- `app/game.py` — Case opening, selling, upgrading, battles, daily bonus rules.
- `app/store.py` — SQLite schema, atomic `debit`/`credit`, battle CAS lock (`try_claim_battle_start`).
- `app/bank.py` & `app/pika.py` — Real-money sync (`eco take`/`eco give`, `nexo give`) and PikaMC API client.
- `app/gacha.py` — `gacha.json` loader, image auto-resolver (`png > webp > jpg > jpeg > svg`), Nexo command builder.
- `app/roulette.py` & `app/bots.py` — Background Coinflip Roulette and bot loops.

## Non-Negotiable Boundaries
1. **Real-Money Ordering (`GACHA_DRY_RUN=false`):**
   - Debit/verify Coin in-game (`bank.take`) **before** committing case opens, battle entries, or roulette bets; refund via `bank.give` if local commit fails.
   - Credit Coin in-game (`bank.give`) **before** marking inventory items `sold` or committing daily `bonus`.
   - Execute `nexo_give_item` **before** marking an inventory item `withdrawn`.
   - Never fabricate or seed virtual balances when `GACHA_DRY_RUN=false`.
2. **Input & Console Safety:**
   - Validate player names with `USERNAME_RE` and Nexo IDs with `NEXO_ID_RE` before formatting any Minecraft console command.
   - Escape all dynamic strings (`player`, `item.name`, `case_name`) before inserting into HTML/DOM (`esc()` or `textContent` / `replaceChildren()`).
   - Never return raw internal `Exception` strings to clients in HTTP 500 responses.
3. **Test Data Safety:**
   - Never mutate real player accounts (`Trez1724`) or `data/gacha.db` in automated tests; copy `data/gacha.db` to `tempfile.mkdtemp()` or use `QA_Tester_01` on dry-run servers.
   - Never hardcode the repo path in tests — derive it with `Path(__file__).resolve().parent.parent`. `tests/test_paths_static.py` enforces this.
4. **Secrets:**
   - Never commit `.env`, `data/`, or real `PIKA_API_KEY` / `SESSION_SECRET` / GitHub tokens.
5. **Frontend Standard (`modern-web-guidance`):**
   - Always consult `modern-web-guidance` before editing HTML/CSS/client JS.
   - **Browser Support:** Baseline Widely Available features by default; dark mode uses `<meta name="color-scheme" content="light dark">` synchronized with `:root` CSS `color-scheme` and `html.dark`.

## Project Skills
- `.agents/skills/jellyvale-gacha-dev/SKILL.md` — Core backend, money-flow, security, and testing workflow.
- `.agents/skills/jellyvale-nexomc/SKILL.md` — NexoMC item/texture/command integration workflow.

