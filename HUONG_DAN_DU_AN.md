# HƯỚNG DẪN CHI TIẾT DỰ ÁN JELLYVALE GACHA (WEB GACHA MINECRAFT)

> **Cập nhật ngày:** 23/11/2026  
> **Phiên bản:** v2.0 — Phong cách tươi sáng, Hỗ trợ Mở nhiều rương (1x, 2x, 3x, 4x, 5x), 7 Rương hoàn chỉnh & Đổi theme Sáng/Tối.

---

## 1. Tổng Quan & Cảm Hứng Thiết Kế

Dự án được xây dựng lấy cảm hứng trực tiếp từ nền tảng **CaseForge** (mở hòm CS2 chuyên nghiệp), nhưng được thiết kế lại toàn bộ bằng **Python (FastAPI) + SQLite (WAL Mode)** để phù hợp hoàn hảo với hệ sinh thái server **Minecraft (Nexo / ItemsAdder / ExcellentEconomy / AuthMe)**:
- **Siêu nhẹ & Tối ưu**: Thay vì tốn 2.5GB – 4GB RAM như bản gốc CaseForge (chạy Next.js + NestJS + Redis + Postgres + Worker), web này chỉ tiêu thụ **~50MB RAM**, khởi động trong tích tắc.
- **Phong cách Tươi Sáng**: Thiết kế nền sáng dịu mắt, thẻ trắng viền tinh xảo, hiệu ứng vàng kim bắt mắt chuẩn game phiêu lưu, có sẵn nút chuyển đổi qua lại giữa giao diện Tươi Sáng và Ban Đêm (☀️/🌙).
- **Core Loop Hoàn Chỉnh**: Mở rương (1x–5x) ➔ Túi đồ ➔ Bán lấy Coin ➔ Nâng cấp (Upgrade) ➔ Case Battle với Bot ➔ Vòng quay may mắn (Daily Bonus).

---

## 2. Hệ Thống 7 Rương Mặc Định & Cấu Trúc

Toàn bộ thông số rương, tỷ lệ rơi (`weight`) và giá trị Coin nằm trong file `gacha.json`:

| ID Rương | Tên Rương | Giá Mở | Đồ Nổi Bật |
| :--- | :--- | :---: | :--- |
| `jelly-starter` | **Rương Jelly Starter** | 5.000 Coin | Bụi vàng, Táo vàng, Túi Coin, Phôi Netherite, Jackpot Starter |
| `jelly-magic` | **Rương Ma Pháp** *(Mới)* | 15.000 Coin | Thạch anh tím, Ngọc Ender, Đinh ba Thủy thần, Trượng Ma Pháp |
| `jelly-elite` | **Rương Elite** | 25.000 Coin | Kim cương, Sách Elite, Totem bất tử, Cánh Elytra, Mangekyo |
| `jelly-vault` | **Rương Vault** | 50.000 Coin | Khối Netherite, Mangekyo, Trứng rồng, Vương miện Jelly |
| `jelly-nether` | **Rương Hỏa Ngục Nether** *(Mới)* | 75.000 Coin | Que quỷ lửa, Đầu lâu Wither, Hỏa Kiếm Nether, Sao Địa Ngục |
| `jelly-celestial` | **Rương Thiên Giới** *(Mới)* | 150.000 Coin | Lông vũ Thiên Sứ, Cánh Ánh Kim, Cung Ánh Sáng, Cầu Vũ Trụ |
| `jelly-jackpot` | **Rương Hoàng Gia VIP** *(Mới)* | 300.000 Coin | Khối Kim Cương, Đầu Rồng, Vương trượng, Lõi Thần & Kho Báu Bất Tận |

---

## 3. Tính Năng Mở Đa Rương (1x, 2x, 3x, 4x, 5x)

- **Bộ nút Preset**: Cho phép người chơi chọn nhanh số lượng mở: `×1`, `×2`, `×3`, `×4`, `×5`.
- **Hiệu ứng trực quan**:
  - Khi chọn **×1**: Dải quay Roulette ngang (Horizontal) truyền thống.
  - Khi chọn **×2 – ×5**: Hệ thống tự động chuyển sang **Đa dải cuộn dọc (Multi Vertical Reels)** xếp hàng ngang. Các dải dừng so le 260ms tạo cảm giác hồi hộp như các sàn gacha lớn.
- **Bảng tổng kết Drop (Drop Results)**:
  - Hiển thị đầy đủ thông số: **Đã chi**, **Tổng nhận**, **Chênh lệch lãi/lỗ (+/-)**.
  - Mỗi món rơi ra có thẻ riêng hiển thị ảnh, tên, giá bán và nút **"Bán"** lẻ.
  - Nút **"Bán tất cả (X món)"** giúp thanh lý nhanh toàn bộ để nhận lại Coin ngay tại trang mở rương.

---

## 4. Tính Năng Coinflip Roulette Minecraft (Phong cách CSGOEmpire) *(Mới)*

Lấy cảm hứng từ chế độ Roulette trứ danh của CSGOEmpire, hệ thống được thiết kế lại hoàn toàn theo phong cách Minecraft:
- **Dải quay 15 ô chuẩn tỷ lệ**:
  - 🏠 **7 ô Ngôi Làng (Village)**: Hệ số **x2** (thay cho phe T vàng), biểu tượng huân chương ngôi làng và ngọc lục bảo.
  - 🏹 **7 ô Pillager (Kẻ cướp)**: Hệ số **x2** (thay cho phe CT đen), biểu tượng khuôn mặt Pillager hung hãn viền đỏ.
  - 👑 **1 ô Steve Đặc Biệt**: Hệ số **x14** (thay cho xúc xắc Empire Dice), biểu tượng khuôn mặt Steve huyền thoại viền phát sáng kim cương.
- **Cơ chế thời gian thực & Bot chơi cùng**:
  - **15 giây nhận cược (Betting)**: Đồng hồ đếm ngược trực quan, thanh tiến trình đổi màu. Dàn Bot (JellyBot, ValeBot,...) tự động vào đặt cược sôi động.
  - **6 giây quay cuộn (Rolling)**: Dải băng 150 ô trượt mượt mà với gia tốc vật lý chuẩn bezier `cubic-bezier(0.12, 0.82, 0.14, 1)` và kim chỉ trung tâm.
  - **4 giây kết toán (Settled)**: Tự động cộng tiền thưởng vào ví web, cập nhật số dư tức thì, lưu lịch sử 100 vòng gần nhất.
- **Bảng điều khiển cược chuyên nghiệp**:
  - Bộ nút tăng nhanh: `+1K`, `+5K`, `+10K`, `+50K`.
  - Phím tiện ích: `1/2`, `2X`, `Max`, `Xóa`.
  - Hiển thị danh sách cược trực tiếp của 3 phe (nổi bật cược của chính người chơi).
  - Tích hợp chuẩn **Provably Fair** (mã hóa SHA-256 commit cho từng vòng).

---

## 5. Hướng Dẫn Thay Đổi & Thêm Ảnh Rương / Vật Phẩm

Hệ thống được thiết kế với cơ chế **Auto Image Resolver**, tuyệt đối **không hard-code đường dẫn ảnh**.

### 4.1. Thư mục chứa ảnh
- **Ảnh rương**: Nằm trong `app/static/cases/`
- **Ảnh vật phẩm**: Nằm trong `app/static/items/`

### 4.2. Quy tắc đặt tên file
Tên file ảnh phải trùng khớp chính xác với `id` khai báo trong `gacha.json`:
- Ví dụ rương `jelly-magic` ➔ file ảnh là `jelly-magic.png` (hoặc `.svg`, `.webp`, `.jpg`).
- Ví dụ item `inferno_sword` ➔ file ảnh là `inferno_sword.png`.

### 4.3. Thứ tự ưu tiên định dạng
`png` ➔ `webp` ➔ `jpg` ➔ `jpeg` ➔ `svg`.  
*(Hiện tại dự án đã tạo sẵn đầy đủ ảnh vector `.svg` cho 100% rương và item mới. Sau này bạn chỉ cần thả ảnh `.png` đẹp hơn vào là web sẽ tự động nhận diện file `.png` thay thế file `.svg`, không cần sửa code).*

### 4.4. Bảng mã màu phẩm cấp (Rarity)
- `consumer` / `common`: `#b0c3d9` (Trắng / Xám nhạt)
- `industrial`: `#5e98d9` (Xanh da trời)
- `milspec` / `uncommon`: `#4b69ff` (Xanh dương)
- `restricted` / `rare`: `#8847ff` (Tím ma thuật)
- `classified` / `epic`: `#d32ce6` (Hồng cánh sen)
- `covert`: `#eb4b4b` (Đỏ rực rỡ)
- `extraordinary` / `legendary`: `#e4ae39` (Vàng kim / Hổ phách)

---

## 5. Khả Thi & Hướng Dẫn Host Miễn Phí (Free Hosting)

Web viết bằng FastAPI rất nhẹ (~50MB RAM). Tuy nhiên do sử dụng **SQLite (`data/gacha.db`)** và có **tiến trình Bot chạy nền liên tục (`bots.py`)**, bạn cần lưu ý lựa chọn nền tảng phù hợp:

### Lựa chọn 1: Cloudflare Tunnel (Khuyên dùng nhất ⭐⭐⭐⭐⭐)
Nếu bạn đã có máy tính chạy server Minecraft hoặc VPS Windows/Linux:
1. Chạy web ngay trên máy chủ qua lệnh: `start.bat`.
2. Cài đặt **Cloudflare Tunnel (miễn phí 100%)**:
   - Trỏ domain (ví dụ `gacha.yourserver.com`) về port `8080` nội bộ.
   - Có ngay kết nối **HTTPS**, tường lửa chống DDoS mạnh mẽ của Cloudflare, không cần mở port modem (No Port Forwarding).

### Lựa chọn 2: Oracle Cloud Always Free (⭐⭐⭐⭐⭐)
- Miễn phí trọn đời 1 VPS cấu hình cao (lên tới 4 OCPU, 24GB RAM).
- Chạy Linux, cài Python, bật web chạy vĩnh viễn 24/7, ổ cứng lưu SQLite an toàn không bao giờ bị mất dữ liệu.

### Lựa chọn 3: Fly.io (⭐⭐⭐⭐)
- Cho phép gắn **Persistent Volume 3GB miễn phí** để lưu database `gacha.db`.
- Không bị reset dữ liệu khi khởi động lại.

### ⚠️ Lưu ý với Render.com / Koyeb / Vercel:
- **Render / Koyeb**: Gói miễn phí dùng ổ cứng tạm thời (Ephemeral Storage) — mỗi lần web khởi động lại sẽ **mất sạch file SQLite**. Ngoài ra sau 15 phút không có người vào web sẽ bị sleep làm bot dừng hoạt động.
- **Vercel / Netlify**: Chỉ dành cho serverless stateless, **không thể chạy tiến trình Bot nền**.

---

## 6. Hướng Dẫn Chạy & Cấu Hình

### Khởi động dự án trên máy:
Nhấp đúp chuột vào file:
```cmd
start.bat
```
Truy cập: `http://127.0.0.1:8080/gacha`

### Cấu hình file `.env`:
- `GACHA_DRY_RUN=true`: Chế độ an toàn / thử nghiệm. Người chơi nạp tiền ảo (seed 250.000 Coin) trên web để test toàn bộ tính năng mà không ảnh hưởng tới kinh tế server thật.
- Khi muốn kết nối trừ Coin in-game thật:
  1. Thêm API key PikaMC vào `PIKA_API_KEY`.
  2. Đặt `GACHA_DRY_RUN=false`.
  3. Khởi động lại `start.bat`.
