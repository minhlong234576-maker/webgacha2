import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-only-change-me")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8080"))

PIKA_BASE_URL = os.getenv("PIKA_BASE_URL", "https://hub.pikamc.vn").rstrip("/")
PIKA_API_KEY = os.getenv("PIKA_API_KEY", "").strip()
PIKA_SERVER_UUID = os.getenv("PIKA_SERVER_UUID", "").strip()
PIKA_AUTHME_DB = os.getenv("PIKA_AUTHME_DB", "/plugins/AuthMe/authme.db")
PIKA_ECONOMY_DB = os.getenv("PIKA_ECONOMY_DB", "/plugins/ExcellentEconomy/data.db")
# File danh sách operator của server Minecraft. Ai có OP ở đây thì có quyền
# admin trên web — đọc trực tiếp từ server nên luôn khớp, không cần sửa
# tay danh sách ADMIN_USERS khi thêm/bớt OP.
PIKA_OPS_FILE = os.getenv("PIKA_OPS_FILE", "/ops.json")
# server.properties chứa `online-players=<danh sách đang online>` — nguồn
# miễn phí cho số người online trên web (không cần websocket console).
PIKA_SERVER_PROPERTIES = os.getenv("PIKA_SERVER_PROPERTIES", "/server.properties")
# Log server Minecraft — nguồn thực cho số người đang online (Paper ghi rõ
# lúc vào/rời game). Đọc 1 file, không cần websocket console.
PIKA_SERVER_LOG = os.getenv("PIKA_SERVER_LOG", "/logs/latest.log")
# Admin khai báo thêm trong .env — rỗng mặc định vì quyền admin đã lấy từ
# OP trên server. Điền vào chỉ khi cần ai đó có quyền web mà KHÔNG có OP
# (ví dụ khi API PikaMC lỗi và cần một admin dự phòng).
ADMIN_USERS = {
    name.strip().lower()
    for name in os.getenv("ADMIN_USERS", "").split(",")
    if name.strip()
}
STATIC_DIR = ROOT / "app" / "static"


def pika_ready() -> bool:
    return bool(PIKA_API_KEY)


def dry_run() -> bool:
    return os.getenv("GACHA_DRY_RUN", "true").strip().lower() in {"1", "true", "yes"}


def nexo_withdraw_enabled() -> bool:
    return os.getenv("GACHA_NEXO_WITHDRAW", "false").strip().lower() in {"1", "true", "yes"}


def session_https_only() -> bool:
    return os.getenv("SESSION_HTTPS_ONLY", "false").strip().lower() in {"1", "true", "yes"}
