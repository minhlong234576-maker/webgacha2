"""
Hạ tầng dùng chung cho 10 bot QA.

Mỗi bot là một "người chơi" độc lập với session riêng, chạy SONG SONG trên
server test (dry-run) để kiểm thử toàn bộ chức năng web như người thật.

Nguyên tắc (jellyvale-gacha-dev §4):
- Copy `data/gacha.db` vào thư mục tạm, KHÔNG chạm DB production.
- Root suy ra động: `Path(__file__).resolve().parent.parent`.
- Mọi tài khoản test dùng tiền giả trong DB tạm, không đụng ví thật.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import itsdangerous

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent

# Tên bot QA — tiền tố rõ ràng để dễ quét/dọn trong DB.
BOT_PREFIX = "QA_Bot_"


def bot_name(index: int) -> str:
    """Tên 10 bot QA: QA_Bot_01 .. QA_Bot_10."""
    return f"{BOT_PREFIX}{index:02d}"


ALL_BOT_NAMES = [bot_name(i) for i in range(1, 11)]


def load_secret() -> str:
    """Lấy SESSION_SECRET từ .env (không ghi vào source)."""
    secret = os.getenv("SESSION_SECRET")
    if secret:
        return secret
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SESSION_SECRET="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise RuntimeError("Khong tim thay SESSION_SECRET trong .env")


SECRET = load_secret()


def make_session_cookie(user: str, csrf: str = "qa-bot-csrf") -> str:
    """Tạo cookie `jv_session` đã ký cho user (giống hệt format server dùng)."""
    session = {"user": user, "login_name": user, "csrf": csrf}
    raw = base64.b64encode(json.dumps(session).encode("utf-8"))
    return itsdangerous.TimestampSigner(SECRET).sign(raw).decode()


def db_path() -> Path:
    return Path(os.getenv("GACHA_DB_PATH") or (ROOT / "data" / "gacha.db"))


class TestServer:
    """Server test riêng cho bộ bot QA.

    Server phải dùng CÙNG file DB mà test ghi vào, nếu không bot sẽ "không
    đủ Coin" (tiền nằm ở DB này, server lại đọc DB kia). Vì vậy bộ bot tự
    bật server thay vì dùng server dùng chung của `run_all.py`.

    - DB: bản sao tạm của `data/gacha.db` (không chạm production).
    - Danh mục: bản sao tạm của danh mục mẫu (`fixture_catalog`).
    """

    def __init__(self, port: int = 8102):
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.tmp_dir: Path | None = None
        self.proc: subprocess.Popen | None = None
        self.db_file: Path | None = None
        self.catalog_file: Path | None = None

    def _kill_port(self) -> None:
        if os.name == "nt":
            cmd = ["powershell", "-NoProfile", "-Command",
                   f"Get-NetTCPConnection -LocalPort {self.port} -State Listen "
                   f"-ErrorAction SilentlyContinue | ForEach-Object "
                   f"{{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"]
        else:
            cmd = ["sh", "-c",
                   f"lsof -ti tcp:{self.port} | xargs -r kill -9 2>/dev/null || true"]
        subprocess.run(cmd, capture_output=True)

    def start(self, timeout: float = 45.0) -> bool:
        import tempfile

        self._kill_port()
        time.sleep(1.5)

        self.tmp_dir = Path(tempfile.mkdtemp(prefix="jvqabots_"))
        self.db_file = self.tmp_dir / "gacha.db"
        shutil.copy(ROOT / "data" / "gacha.db", self.db_file)

        self.catalog_file = self.tmp_dir / "gacha.json"
        sys.path.insert(0, str(TESTS))
        import fixture_catalog

        fixture_catalog.write_fixture(self.catalog_file)

        env = dict(os.environ)
        env["GACHA_DB_PATH"] = str(self.db_file)
        env["GACHA_FILE"] = str(self.catalog_file)
        env["GACHA_DRY_RUN"] = "true"

        self.proc = subprocess.Popen(
            [sys.executable, str(TESTS / "run_test_server.py"), str(self.port)],
            cwd=str(ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                httpx.get(f"{self.base_url}/login", timeout=2)
                return True
            except Exception:
                time.sleep(0.5)
        return False

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
            self.proc = None
        if self.tmp_dir is not None:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
            self.tmp_dir = None


def reset_bot_wallet(name: str, coin: int = 5_000_000) -> None:
    """Đặt lại ví web + xoá dữ liệu cũ của bot để test chạy lặp lại được."""
    con = sqlite3.connect(db_path())
    try:
        con.execute(
            "INSERT INTO wallets (player, balance, is_bot, created_at) "
            "VALUES (?, ?, 0, 0) ON CONFLICT(player) DO UPDATE SET balance = ?",
            (name, coin, coin),
        )
        for tbl in ("inventory", "bonus", "pulls", "drops", "tx", "upgrades"):
            try:
                con.execute(f"DELETE FROM {tbl} WHERE player = ?", (name,))
            except sqlite3.OperationalError:
                # Bảng chưa tồn tại trong DB cũ -> bỏ qua, không phải lỗi test.
                pass
        con.commit()
    finally:
        con.close()


def cleanup_bots() -> None:
    """Xoá sạch dữ liệu của cả 10 bot (gọi 1 lần khi test kết thúc)."""
    con = sqlite3.connect(db_path())
    try:
        for name in ALL_BOT_NAMES:
            for tbl in ("inventory", "bonus", "pulls", "drops", "tx", "upgrades"):
                try:
                    con.execute(f"DELETE FROM {tbl} WHERE player = ?", (name,))
                except sqlite3.OperationalError:
                    pass
            con.execute("DELETE FROM wallets WHERE player = ?", (name,))
        con.commit()
    finally:
        con.close()


def bot_client(base_url: str, user: str) -> httpx.AsyncClient:
    """Tạo HTTP client đã đăng nhập sẵn cho 1 bot."""
    client = httpx.AsyncClient(
        base_url=base_url,
        timeout=30,
        headers={
            "X-CSRF": "qa-bot-csrf",
            "User-Agent": "JellyVale-QABot/1.0",
        },
    )
    client.cookies.set(
        "jv_session", make_session_cookie(user), domain="127.0.0.1", path="/"
    )
    return client


class BotResult:
    """Kết quả của 1 bot: danh sách kiểm tra pass/fail."""

    def __init__(self, bot: str, title: str):
        self.bot = bot
        self.title = title
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def check(self, name: str, cond: bool, detail: str = "") -> bool:
        if cond:
            self.passed.append(name)
            print(f"  PASS [{self.bot}] {name}" + (f"   {detail}" if detail else ""))
        else:
            self.failed.append((name, detail))
            print(f"  FAIL [{self.bot}] {name}" + (f"   {detail}" if detail else ""))
        return bool(cond)

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        return (
            f"[{self.bot}] {self.title}: "
            f"{len(self.passed)} PASS, {len(self.failed)} FAIL"
        )


async def get_html(c: httpx.AsyncClient, path: str) -> str:
    r = await c.get(path)
    return r.text


def extract_inventory_ids(html: str, limit: int = 5) -> list[int]:
    """Rút id đồ trong túi từ HTML trang /inventory."""
    import re

    ids = re.findall(r'name="id" value="(\d+)"', html)
    if not ids:
        ids = re.findall(r'data-id="(\d+)"', html)
    out: list[int] = []
    for raw in ids:
        value = int(raw)
        if value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return out


def extract_upgrade_stakes(html: str) -> list[tuple[int, int]]:
    """Rút (id, giá trị) của các ô cược trên trang /upgrade."""
    import re

    pairs = re.findall(
        r'<input type="checkbox"[^>]*name="stake"[^>]*value="(\d+)"[^>]*data-value="(\d+)"',
        html,
    )
    return [(int(a), int(b)) for a, b in pairs]
