# Constraints

Last reviewed: 2026-11-25

Read this file before writing code. Do not weaken thresholds or delete checks to make a change pass.

## Floor (always enforced)
- No new suppression comments (`# noqa`, `# type: ignore`, `@ts-ignore`, `eslint-disable`) without an inline reason.
- No empty exception swallows (`except Exception: pass`) on new financial, auth, or I/O paths — log or surface the error.
- No skipped or deleted tests without an explicit reason in the commit message.
- No secrets, API keys, or tokens in source files, templates, or docs (`.env` and `data/` stay in `.gitignore`).
- Every bug fix must ship with a regression test that fails without the fix and passes with it.

## Enforced Checks

| Dimension | Rule | Checked by | Runs at |
|---|---|---|---|
| Logic & Money Safety | All offline logic, race, and security checks pass | `.\.venv\Scripts\python.exe tests\test_system.py` | task end |
| Security & Regression | Cookie 500 guard, headers, input validation, Nexo/upgrade regressions pass | `.\.venv\Scripts\python.exe tests\test_security_and_fixes.py` | task end |
| Roulette & Battles | Payout & concurrency invariants pass | `.\.venv\Scripts\python.exe tests\test_roulette.py && .\.venv\Scripts\python.exe tests\test_battle_winner_only.py && .\.venv\Scripts\python.exe tests\test_concurrent_battles.py` | task end |
| Upgrade 2-to-1 | No duplicate-id double-count, no clone-item race, failed upgrade keeps stakes | `.\.venv\Scripts\python.exe tests\test_upgrade_two_to_one.py` | upgrade edit |
| Test Path Hygiene | No hardcoded repo paths; `ROOT` defined before use | `.\.venv\Scripts\python.exe tests\test_paths_static.py` | test edit |
| Frontend Web Standards | Zero legacy-pattern findings across `app/` | `npx.cmd -y modern-web-guidance@latest legacy-scan app --json` | HTML/CSS/JS edit |
| Chatbot Knowledge Base | `app/commands_data.json` loads, offline matching resolves, Claude path is optional and degrades gracefully | `.\.venv\Scripts\python.exe tests\test_chatbot.py` | chatbot edit |
| Chatbot Route Safety | CSRF enforced, empty/oversized input rejected, no raw exception strings leak, per-IP rate limit returns 429 | `.\.venv\Scripts\python.exe tests\test_chatbot.py` | chatbot edit |
| Secrets | Zero tracked `.env` or credential prefixes | `git diff --cached` / `Select-String -Path app\*,tests\* -Pattern "ghp_|c7sp_|PIKA_API_KEY=."` | pre-commit |

## Exceptions

| ID | Rule | Path | Reason | Expires |
|---|---|---|---|---|
| — | — | — | None active | — |

