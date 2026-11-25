# JellyVale Gacha

Web gacha cho server Minecraft — đăng nhập bằng tài khoản AuthMe, dùng Coin
in-game (ExcellentEconomy) làm tiền thật, quyền admin lấy động từ danh sách
OP trên server PikaMC.

Xem [`TIEN_TRINH.md`](TIEN_TRINH.md) để biết tiến trình phát triển chi tiết
và [`HUONG_DAN_DU_AN.md`](HUONG_DAN_DU_AN.md) cho hướng dẫn thiết kế/hosting.

## Tính năng

- **Đăng nhập AuthMe** — verify SHA256, CSRF token, giới hạn 8 lần sai / 10 phút / IP.
- **Mở rương** — 7 rương, mở 1x–5x, dải quay ngang/dọc nhiều dải.
- **Túi đồ & bán** — bán lẻ hoặc bán tất cả, nhận lại Coin.
- **Nâng cấp** — cược món rẻ để giành món đắt, hiển thị tỉ lệ.
- **Case Battle** — Standard / Crazy, đấu với bot, tự động vào trận.
- **Coinflip Roulette** — 3 phe (Làng x2, Pillager x2, Steve x14), 15s cược / 6s quay / 4s chốt.
- **Live drop** — dải đồ rơi realtime qua WebSocket-free polling.
- **Bonus ngày**, **ví web** (`/vi`), **thống kê admin** (`/admin`).

## Yêu cầu

- Python 3.12+
- Server Minecraft có plugin **AuthMe** và **ExcellentEconomy**
- Tài khoản PikaMC (panel: https://hub.pikamc.vn) với quyền `files.*`
  (đọc `/ops.json`, sqlite-query) và `control.console` khi bật tiền thật

## Cài đặt

```bash
git clone https://github.com/minhlong234576-maker/webgacha.git
cd webgacha
pip install -r requirements.txt
copy .env.example .env      # Windows
```

Sửa `.env`:

```dotenv
SESSION_SECRET=doi-chuoi-nay-thanh-chuoi-ngau-nhien
HOST=127.0.0.1
PORT=8080

PIKA_BASE_URL=https://hub.pikamc.vn
PIKA_API_KEY=
PIKA_SERVER_UUID=
PIKA_AUTHME_DB=/plugins/AuthMe/authme.db
PIKA_ECONOMY_DB=/plugins/ExcellentEconomy/data.db

# true = chơi trên ví web (seed 250.000 Coin), không đụng Coin in-game
# false = tiền thật, trừ/cộng Coin qua lệnh console `eco take` / `eco give`
GACHA_DRY_RUN=true
```

> `.env` **không** được commit — đã có trong `.gitignore`.

## Chạy

```bash
# Windows
start.bat

# hoặc thủ công
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Truy cập <http://127.0.0.1:8080/gacha>.

## Bật tiền thật (`GACHA_DRY_RUN=false`)

1. API key PikaMC cần có quyền `control.console`.
2. Đặt `GACHA_DRY_RUN=false` trong `.env`.
3. Restart server.

Lúc này mở rương / vào battle sẽ `eco take`; bán / bonus sẽ `eco give`.
Coin in-game là nguồn sự thật duy nhất, ví web chỉ là bản mirror.

## Quyền admin

Không cần khai báo danh sách admin thủ công — app đọc `/ops.json` trên
server Minecraft và tự tra quyền cho ai có OP. Cache 60 giây, làm mới nền
mỗi phút; admin có quyền ngay khi server vừa khởi động.

Muốn thêm admin dự phòng (khi API PikaMC lỗi), điền `ADMIN_USERS=tên1,tên2`
trong `.env`.

## Cấu trúc

```
app/
  main.py       FastAPI app + toàn bộ route
  pika.py       Client PikaMC (console, sqlite-query, files/contents)
  admins.py     Quyền admin realtime từ ops.json
  game.py       Mở rương / bán / nâng cấp / battle
  store.py      SQLite (WAL) — schema, ví, inventory, tx
  bank.py       Đồng bộ ví web ↔ Coin in-game
  bots.py       Bot mở rương + ngồi battle
  roulette.py   Coinflip Roulette
  gacha.py      Nạp gacha.json, roll, lệnh eco
  security.py   AuthMe SHA256, CSRF, rate limit
  config.py     Nạp .env
  templates/    Jinja2
  static/       CSS, JS, ảnh rương/đồ
gacha.json      Rương, tỉ lệ, giá
tests/          14 suite tự động
```

## Test

```bash
python tests/run_all.py
```

Một số suite cần server chạy sẵn ở port `8080` / `8099` / `8101` — xem
`tests/run_all.py` để biết chi tiết.

## Triển khai

Web rất nhẹ (~50MB RAM) nhưng cần SQLite lâu dài và tiến trình bot nền.
Nên dùng **Cloudflare Tunnel** (nếu đã có máy chủ/VPS) hoặc
**Oracle Cloud Always Free**. Tránh Render/Koyeb (mất file SQLite khi
restart) và Vercel/Netlify (không chạy được tiến trình nền).
Chi tiết ở [`HUONG_DAN_DU_AN.md`](HUONG_DAN_DU_AN.md).

## Giấy phép

Code của dự án này chưa khai báo giấy phép cụ thể.
