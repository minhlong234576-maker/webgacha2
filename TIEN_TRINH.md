# JellyVale Gacha — Tiến trình phát triển

Cập nhật: 2026-11-25 (UTC+7)
Repo: https://github.com/minhlong234576-maker/webgacha
Nhánh: `main` — commit hiện tại: `c08851f` (121 file)

---

## 1. Trạng thái hiện tại

| Hạng mục | Trạng thái |
| :--- | :--- |
| Web gacha FastAPI + SQLite (WAL) | ✅ Hoàn thành |
| Đăng nhập AuthMe (SHA256) + CSRF + rate limit | ✅ Hoàn thành |
| Coin realtime từ PikaMC (ExcellentEconomy) | ✅ Hoàn thành |
| Quyền admin động đọc `ops.json` | ✅ Hoàn thành |
| Mở rương / Túi đồ / Bán / Nâng cấp / Battle / Bonus / Roulette | ✅ Hoàn thành |
| Xóa tính năng "Hợp đồng" (contract) | ✅ Hoàn thành |
| Test tự động (14 suite) | ✅ 14/14 PASS — 625 assertions |
| Push lên GitHub | ✅ Đã push `0a59f6d..c08851f` |

---

## 2. Các thay đổi trong phiên làm việc gần nhất

### 2.1 Xóa tính năng "Hợp đồng"

- Gỡ link `<a class="nav-link" href="/contract">Hợp đồng</a>` khỏi `app/templates/base.html`.
- Xóa route `GET /contract` và `POST /api/contract` khỏi `app/main.py`.
- Xóa logic `record_contract` và bảng `contracts` khỏi `app/store.py`
  (kèm migration `DROP TABLE IF EXISTS contracts`).
- Xóa mọi tham chiếu còn sót trong `admin.html`, `setup.html`,
  `catalogue.html`, `inventory.html`.
- Test xác nhận: `GET /contract` → `404`, `POST /api/contract` → `404`.

### 2.2 Quyền admin realtime từ OP trên PikaMC

Nguồn sự thật là file `/ops.json` trên server Minecraft.

**`app/pika.py`**

- `read_file(file_path)` — đọc file qua
  `GET /api/client/servers/{uuid}/files/contents?file={path}`.
- `server_ops()` / `server_op_names()` — parse danh sách OP, trả về
  tập tên đã lowercase.
- Chỉ cần quyền `files.*`, **không** cần `control.console`.

**`app/admins.py`**

- Cache TTL `OPS_TTL = 60.0` giây.
- `refresh()` — đọc lại `ops.json`, bỏ qua cache.
- `op_names()` — trả cache nếu còn hạn, ngược lại gọi `refresh()`.
- `is_admin_now(name)` — kiểm tra bằng cache (không gọi mạng, dùng khi render).
- `is_admin(name)` — bản async, làm mới danh sách OP.
- `admin_list()` — gộp `.env` + OP server, kèm nguồn (`server-op` / `env`).
- `loop()` + `start(app)` — vòng lặp nền refresh mỗi 60s.

**`app/main.py`**

- `lifespan` gọi `await admins.refresh()` **trước** khi phục vụ request
  → admin có quyền ngay khi server vừa boot.
- `require_admin(request)` so khớp **cả** `session["login_name"]` và
  `session["user"]` (case-insensitive) → không bỏ sót OP khi realname
  khác username.
- `GET /api/admins` — endpoint công khai trả danh sách admin.

**`app/config.py`** — `ADMIN_USERS` mặc định rỗng, thêm `PIKA_OPS_FILE`.

> Lưu ý: tên trong `ops.json` có thể có tiền tố `.` (ví dụ `.anacon2`,
> `.NgocLann`, `.RudoOfGames`). Vì vậy cần so khớp cả hai trường session.

### 2.3 Đơn giản hoá `.env`

- Xóa `ADMIN_USERS=Trez1724` (đã có trong OP).
- Xóa `PIKA_OPS_FILE=/ops.json` (dùng mặc định).
- File còn 11 dòng: `SESSION_SECRET`, `HOST`, `PORT`, `PIKA_BASE_URL`,
  `PIKA_API_KEY`, `PIKA_SERVER_UUID`, `PIKA_AUTHME_DB`,
  `PIKA_ECONOMY_DB`, `GACHA_DRY_RUN`.

### 2.4 Đẩy lên GitHub

- Khởi tạo repo git trong `web-gacha/`, nhánh `main`.
- Viết `.gitignore` loại trừ `.env`, `data/`, `.venv/`, `__pycache__/`,
  `.codegraph/`, `_shots/`, `caseforge-main/`, `Nexo/`, `*.zip`.
- Commit `c08851f` — 121 file.
- Remote: `https://github.com/minhlong234576-maker/webgacha.git`
- Rebase trên commit `0a59f6d` (Initial commit có sẵn `README.md`) rồi push.
- Đã **gỡ token khỏi remote URL** sau khi push (`git remote -v` chỉ hiện
  URL công khai).

---

## 3. Lỗi đã biết & cách xử lý

### 3.1 Cookie `jv_session` hỏng → mọi trang trả 500 (CHƯA SỬA)

**Triệu chứng:** người dùng báo mọi trang trả `500 Internal Server Error`.

**Log:**

```
File "...\starlette\middleware\sessions.py", line 50, in __call__
  scope["session"] = json.loads(b64decode(data))
binascii.Error: Invalid base64-encoded string: number of data characters (41)
cannot be 1 more than a multiple of 4
```

**Nguyên nhân:** `SessionMiddleware` của Starlette chỉ bắt `BadSignature`:

```python
try:
    data = self.signer.unsign(data, max_age=self.max_age)
    scope["session"] = json.loads(b64decode(data))   # lỗi ở đây
    initial_session_was_empty = False
except BadSignature:
    scope["session"] = {}
```

Chữ ký hợp lệ nhưng payload bên trong không phải base64 chuẩn của JSON
(41 ký tự — dấu hiệu URL-safe base64 sinh ra `-`/`_` bị `b64decode` loại bỏ).
Lỗi `binascii.Error` không nằm trong `except` → **không ai bắt** → 500.

Kích hoạt bởi: đổi `SESSION_SECRET` giữa chừng, hoặc cookie cũ của phiên
bản trước còn nằm trong trình duyệt.

**Hệ quả:** người dùng bị "đá" khỏi web vĩnh viễn (mọi request đều 500)
cho tới khi tự xóa cookie.

**Cách sửa (đề xuất):** subclass `SessionMiddleware` để bắt thêm
`binascii.Error` / `ValueError` / `json.JSONDecodeError` quanh bước decode
→ reset `scope["session"] = {}` thay vì trả 500.

**Cách vá nhanh:** đổi `session_cookie="jv_session"` → `"jv_session_v2"`
để browser bỏ cookie cũ.

### 3.2 Rate limit đăng nhập

`app/security.py`: tối đa **8 lần sai / 10 phút / IP** (`_MAX_ATTEMPTS = 8`,
`_WINDOW_SECONDS = 600`). Bộ đếm nằm trong RAM nên **restart server là xóa
sạch**. Nếu user gặp lỗi phiên rồi bấm đăng nhập liên tục, họ sẽ thấy
`/login?error=rate` — dễ nhầm với lỗi khác.

### 3.3 Lỗi syntax đã sửa

- `app/main.py`: thiếu `import pika` trong `lifespan` → `NameError`.
- `tests/run_all.py`: sai số ngoặc trong danh sách tham số `subprocess`.
- `tests/test_login_browser.py`: `inner_text()` trả `"QUẢN TRỊ VIÊN"` do
  CSS `text-transform: uppercase` → chuyển sang đọc `textContent`.

---

## 4. Bộ test

```bash
python tests/run_all.py
```

| # | Suite | Cần server |
| :--- | :--- | :--- |
| 1 | Logic + bảo mật hệ thống | — |
| 2 | Tất cả chức năng web | 8101 |
| 3 | Bảo mật HTTP (CSRF/session/quyền) | 8101 |
| 4 | Tiền thật — đơn giản | — |
| 5 | Tiền thật — end to end | — |
| 6 | Tiền thật — race condition | — |
| 7 | Roulette | — |
| 8 | Realtime — khó | — |
| 9 | Realtime — thực | 8099 |
| 10 | Realtime — UI | 8099 |
| 11 | UI — menu | 8101 |
| 12 | Quyền admin realtime (đọc OP từ PikaMC) | — |
| 13 | Quyền admin realtime — HTTP | 8101 |
| 14 | Đăng nhập thực (Playwright) | 8080 |

**Kết quả lần chạy gần nhất: 14/14 PASS — 625 assertions.**

### Quy tắc an toàn dữ liệu test

- **Không** sửa tài khoản thật (`Trez1724`).
- Dùng tài khoản QA riêng: `QA_Tester_01`.
- Script tự dọn các dòng sinh ra (`inventory`, `bonus`, `pulls`, `drops`,
  `tx`, `upgrades`, `wallets`, `battles`, `battle_players`, `battle_drops`).
- Test web-wallet chạy trên server dry-run riêng (port `8098`, `8101`).
- Production chạy `GACHA_DRY_RUN=false` (tiền thật).

---

## 5. Cấu trúc mã nguồn

| File | Vai trò |
| :--- | :--- |
| `app/main.py` | FastAPI app, toàn bộ route + template |
| `app/pika.py` | Client PikaMC: console, sqlite-query, files/contents |
| `app/admins.py` | Quyền admin realtime từ `ops.json` |
| `app/game.py` | Mở rương / bán / nâng cấp / battle |
| `app/store.py` | SQLite (WAL) — schema, ví, inventory, tx |
| `app/bank.py` | Đồng bộ ví web ↔ Coin in-game |
| `app/bots.py` | Bot mở rương + ngồi battle |
| `app/roulette.py` | Coinflip Roulette + vòng quay |
| `app/gacha.py` | Nạp `gacha.json`, roll, lệnh eco |
| `app/security.py` | AuthMe SHA256, CSRF, rate limit |
| `app/config.py` | Nạp `.env`, hằng số cấu hình |
| `gacha.json` | Rương, tỉ lệ, giá |
| `app/static/` | Template, CSS, JS, ảnh rương/đồ |

### Schema SQLite (`data/gacha.db`)

`pulls`, `wallets`, `inventory`, `drops`, `battles`, `battle_players`,
`battle_drops`, `upgrades`, `bonus`, `tx` — kèm 14 index.

---

## 6. Vận hành

```bash
# Chạy production (tiền thật)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080

# Chạy dry-run (ví web, seed 250.000 Coin)
$env:GACHA_DRY_RUN="true"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8101
```

Hoặc nhấp đúp `start.bat`.

**Các trang:** `/gacha` · `/case/{slug}` · `/inventory` · `/upgrade` ·
`/battles` · `/roulette` · `/bonus` · `/vi` · `/admin` · `/setup`

**PikaMC:** https://hub.pikamc.vn/server/de021d06

- DB: `/plugins/AuthMe/authme.db`, `/plugins/ExcellentEconomy/data.db`
- Bật trừ Coin thật cần quyền `control.console` trên API key.

---

## 7. Việc tiếp theo

- [ ] Sửa lỗi cookie phiên hỏng → 500 (mục 3.1)
- [ ] Thay ảnh đồ/rương bằng PNG Nexo / ItemsAdder
- [ ] `nexo give` — rút đồ vào server thay vì chỉ bán Coin
- [ ] HTTPS + VPS (Cloudflare Tunnel / Oracle Cloud Always Free)
- [ ] **Revoke token GitHub** — token `ghp_...` đã từng nằm trong remote URL
      khi push lần đầu. Xem danh sách token tại
      <https://github.com/settings/tokens> và thu hồi.

---

## 8. Bảo mật dữ liệu

`.gitignore` loại trừ: `.env` (chứa API key PikaMC + session secret),
`data/` (SQLite chứa tiền thật + inventory người chơi),
`.venv/`, `__pycache__/`, `.codegraph/`, `_shots/`, `caseforge-main/`,
`Nexo/`, `*.zip`.

Đã quét toàn bộ file staged bằng regex `ghp_|c7sp_|PIKA_API_KEY=.` trước khi
commit → chỉ còn dạng placeholder `ghp_...` / `c7sp_...` trong tài liệu này,
không có giá trị thật nào được commit.
