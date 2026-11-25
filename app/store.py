from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Iterable

from .config import ROOT

DB_PATH = ROOT / "data" / "gacha.db"
_lock = threading.Lock()

# Kết nối theo từng thread. sqlite3 không cho dùng chung connection giữa
# các thread, nên mỗi thread giữ connection riêng và dùng lại — thay vì mở
# connection mới cho mọi truy vấn.
_local = threading.local()

BOT_NAMES = (
    "JellyBot",
    "ValeBot",
    "SlimeAI",
    "HoneyBot",
    "NightOwl",
    "ForgeBot",
    "GolemAI",
    "BeeKeeper",
)

# Số dòng drop giữ lại cho dải "live drop". Bảng này chỉ để hiển thị nên
# giữ ít là đủ — và cắt bằng id chứ không phải created_at (id tăng đơn điệu
# nên việc cắt luôn đúng, không phụ thuộc đồng hồ).
DROPS_KEEP = 200


def _connect() -> sqlite3.Connection:
    """Connection thread-local, khởi tạo schema đúng 1 lần cho mỗi thread.

    Trước đây mỗi lần gọi `run()` đều mở connection mới VÀ chạy lại toàn bộ
    `CREATE TABLE`/`CREATE INDEX` — lãng phí phần lớn thời gian của mọi truy
    vấn. Giờ schema chỉ tạo 1 lần, các lần sau dùng lại connection.
    """
    con = getattr(_local, "con", None)
    if con is not None and getattr(_local, "path", None) == str(DB_PATH):
        return con
    if con is not None:
        con.close()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    # NORMAL là nhanh hơn FULL: WAL chỉ mất dữ liệu khi máy mất điện, không
    # mất khi app crash — đủ an toàn cho ví tiền trong game.
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA cache_size=-16000")  # 16 MB page cache
    _init(con)
    con.commit()
    _local.con = con
    _local.path = str(DB_PATH)
    return con


def _init(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS pulls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player TEXT NOT NULL,
            cost INTEGER NOT NULL,
            prize_id TEXT NOT NULL,
            prize_name TEXT NOT NULL,
            rarity TEXT NOT NULL,
            prize_coin INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            case_id TEXT NOT NULL DEFAULT '',
            dry_run INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS wallets (
            player TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            is_bot INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player TEXT NOT NULL,
            item_id TEXT NOT NULL,
            name TEXT NOT NULL,
            rarity TEXT NOT NULL,
            value INTEGER NOT NULL,
            image TEXT NOT NULL,
            color TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'held',
            case_id TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player TEXT NOT NULL,
            is_bot INTEGER NOT NULL DEFAULT 0,
            item_id TEXT NOT NULL,
            name TEXT NOT NULL,
            rarity TEXT NOT NULL,
            value INTEGER NOT NULL,
            image TEXT NOT NULL,
            color TEXT NOT NULL,
            case_id TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT NOT NULL,
            case_id TEXT NOT NULL,
            rounds INTEGER NOT NULL DEFAULT 1,
            slots INTEGER NOT NULL,
            mode TEXT NOT NULL DEFAULT 'STANDARD',
            status TEXT NOT NULL,
            winner TEXT,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            finished_at INTEGER,
            entry_price INTEGER NOT NULL DEFAULT 0,
            lines TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS battle_players (
            battle_id INTEGER NOT NULL,
            player TEXT NOT NULL,
            is_bot INTEGER NOT NULL DEFAULT 0,
            slot INTEGER NOT NULL,
            total INTEGER NOT NULL DEFAULT 0,
            paid INTEGER NOT NULL,
            PRIMARY KEY (battle_id, player)
        );
        CREATE TABLE IF NOT EXISTS battle_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            player TEXT NOT NULL,
            round INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            name TEXT NOT NULL,
            rarity TEXT NOT NULL,
            value INTEGER NOT NULL,
            image TEXT NOT NULL,
            color TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS upgrades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player TEXT NOT NULL,
            stake_name TEXT NOT NULL,
            stake_value INTEGER NOT NULL,
            target_name TEXT NOT NULL,
            target_value INTEGER NOT NULL,
            chance REAL NOT NULL,
            roll REAL NOT NULL,
            won INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bonus (
            player TEXT PRIMARY KEY,
            last_claim INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tx (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player TEXT NOT NULL,
            kind TEXT NOT NULL,
            amount INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pulls_player ON pulls(player);
        CREATE INDEX IF NOT EXISTS idx_pulls_recent ON pulls(id DESC);
        CREATE INDEX IF NOT EXISTS idx_pulls_rarity ON pulls(rarity);
        CREATE INDEX IF NOT EXISTS idx_pulls_player_count ON pulls(player, id DESC);
        CREATE INDEX IF NOT EXISTS idx_inv_player ON inventory(player, status);
        CREATE INDEX IF NOT EXISTS idx_inv_status ON inventory(status);
        CREATE INDEX IF NOT EXISTS idx_drops_created ON drops(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_drops_recent ON drops(id DESC);
        CREATE INDEX IF NOT EXISTS idx_battles_status ON battles(status, id DESC);
        CREATE INDEX IF NOT EXISTS idx_battle_players_battle ON battle_players(battle_id, slot);
        CREATE INDEX IF NOT EXISTS idx_battle_drops_battle ON battle_drops(battle_id, round, id);
        CREATE INDEX IF NOT EXISTS idx_tx_player ON tx(player, id DESC);
        CREATE INDEX IF NOT EXISTS idx_tx_created ON tx(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_upgrades_player ON upgrades(player, id DESC);
        """
    )
    cols = {row[1] for row in con.execute("PRAGMA table_info(pulls)")}
    if "case_id" not in cols:
        con.execute("ALTER TABLE pulls ADD COLUMN case_id TEXT NOT NULL DEFAULT ''")
    if "dry_run" not in cols:
        con.execute("ALTER TABLE pulls ADD COLUMN dry_run INTEGER NOT NULL DEFAULT 0")
    # Battle multi-rương (chuẩn web gốc): mỗi trận là 1 playlist các line
    # [{case_id, count}], giá ghế = tổng giá mọi vòng, thứ tự vòng giữ nguyên.
    bcols = {row[1] for row in con.execute("PRAGMA table_info(battles)")}
    if "entry_price" not in bcols:
        con.execute("ALTER TABLE battles ADD COLUMN entry_price INTEGER NOT NULL DEFAULT 0")
    if "lines" not in bcols:
        con.execute("ALTER TABLE battles ADD COLUMN lines TEXT NOT NULL DEFAULT ''")
    dcols = {row[1] for row in con.execute("PRAGMA table_info(battle_drops)")}
    if "case_id" not in dcols:
        con.execute("ALTER TABLE battle_drops ADD COLUMN case_id TEXT NOT NULL DEFAULT ''")

    # Bảng `contracts` đã bị gỡ khỏi tính năng Hợp đồng — xóa đi cho sạch.
    # Bảng rỗng nên không mất dữ liệu nào.
    con.execute("DROP TABLE IF EXISTS contracts")


def init() -> None:
    with _lock:
        con = _connect()
        try:
            _init(con)
            con.commit()
        finally:
            pass


def run(fn):
    with _lock:
        con = _connect()
        try:
            result = fn(con)
            con.commit()
            return result
        except Exception:
            con.rollback()
            raise


def now() -> int:
    return int(time.time())


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows(items: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(item) for item in items]


def ensure_wallet(player: str, seed: int = 0, is_bot: bool = False) -> int:
    def inner(con: sqlite3.Connection) -> int:
        row = con.execute("SELECT balance FROM wallets WHERE player = ?", (player,)).fetchone()
        if row:
            return int(row["balance"])
        con.execute(
            "INSERT INTO wallets (player, balance, is_bot, created_at) VALUES (?, ?, ?, ?)",
            (player, max(0, int(seed)), 1 if is_bot else 0, now()),
        )
        if seed:
            con.execute(
                "INSERT INTO tx (player, kind, amount, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (player, "seed", int(seed), "nạp ví web", now()),
            )
        return max(0, int(seed))

    return run(inner)


def set_wallet(player: str, balance: int) -> int:
    """Đặt số dư ví (không ghi lịch sử giao dịch).

    Dùng ở chế độ tiền thật: Coin in-game là nguồn sự thật, ví web chỉ là bản sao
    nên cần đặt thẳng theo số dư server thay vì cộng dồn.
    """

    def inner(con: sqlite3.Connection) -> int:
        amount = max(0, int(balance))
        row = con.execute("SELECT balance FROM wallets WHERE player = ?", (player,)).fetchone()
        if row:
            con.execute("UPDATE wallets SET balance = ? WHERE player = ?", (amount, player))
        else:
            con.execute(
                "INSERT INTO wallets (player, balance, is_bot, created_at) VALUES (?, ?, 0, ?)",
                (player, amount, now()),
            )
        return amount

    return run(inner)


def get_balance(player: str) -> int:
    def inner(con: sqlite3.Connection) -> int:
        row = con.execute("SELECT balance FROM wallets WHERE player = ?", (player,)).fetchone()
        return int(row["balance"]) if row else 0

    return run(inner)


def credit(player: str, amount: int, kind: str, note: str = "") -> int:
    amount = int(amount)
    if amount <= 0:
        return get_balance(player)

    def inner(con: sqlite3.Connection) -> int:
        # `cursor.rowcount` là số dòng của LỆNH NÀY. `con.total_changes` là
        # tổng luỹ kế của cả connection — dùng nó sẽ cho kết quả sai khi
        # connection được dùng lại (xem `store._connect`).
        cur = con.execute(
            "UPDATE wallets SET balance = balance + ? WHERE player = ?",
            (amount, player),
        )
        if cur.rowcount == 0:
            con.execute(
                "INSERT INTO wallets (player, balance, is_bot, created_at) VALUES (?, ?, 0, ?)",
                (player, amount, now()),
            )
        con.execute(
            "INSERT INTO tx (player, kind, amount, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (player, kind, amount, note, now()),
        )
        row = con.execute("SELECT balance FROM wallets WHERE player = ?", (player,)).fetchone()
        return int(row["balance"]) if row else 0

    return run(inner)


def debit(player: str, amount: int, kind: str, note: str = "") -> int:
    amount = int(amount)
    if amount <= 0:
        return get_balance(player)

    def inner(con: sqlite3.Connection) -> int:
        # Trừ trong MỘT câu lệnh có điều kiện. Đọc số dư rồi mới trừ là
        # check-then-write: hai request song song có thể cùng thấy đủ tiền và
        # cùng trừ, làm số dư âm.
        cur = con.execute(
            "UPDATE wallets SET balance = balance - ? "
            "WHERE player = ? AND balance >= ?",
            (amount, player, amount),
        )
        if cur.rowcount == 0:
            # Không có dòng ví, hoặc số dư không đủ.
            raise ValueError("Không đủ Coin.")
        con.execute(
            "INSERT INTO tx (player, kind, amount, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (player, kind, -amount, note, now()),
        )
        row = con.execute("SELECT balance FROM wallets WHERE player = ?", (player,)).fetchone()
        return int(row["balance"]) if row else 0

    return run(inner)


def add_inventory(player: str, item, source: str, case_id: str = "") -> int:
    public = item.as_public() if hasattr(item, "as_public") else item

    def inner(con: sqlite3.Connection) -> int:
        cur = con.execute(
            """
            INSERT INTO inventory (
                player, item_id, name, rarity, value, image, color, source, status, case_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'held', ?, ?)
            """,
            (
                player,
                public["id"],
                public["name"],
                public["rarity"],
                int(public["coin"]),
                public["image"],
                public["color"],
                source,
                case_id,
                now(),
            ),
        )
        return int(cur.lastrowid)

    return run(inner)


def get_inventory_item(item_pk: int) -> dict[str, Any] | None:
    return run(
        lambda con: row_dict(
            con.execute("SELECT * FROM inventory WHERE id = ?", (item_pk,)).fetchone()
        )
    )


def get_inventory_items(item_pks: list[int]) -> dict[int, dict[str, Any]]:
    """Lấy nhiều món đồ trong 1 truy vấn, trả về dict {id: row}.

    Dùng thay cho vòng lặp `get_inventory_item` — mỗi món một query, nên bán
    20 món là 20 lần đọc DB (N+1).
    """
    if not item_pks:
        return {}
    placeholders = ",".join("?" * len(item_pks))
    return run(
        lambda con: {
            row["id"]: dict(row)
            for row in con.execute(
                f"SELECT * FROM inventory WHERE id IN ({placeholders})", list(item_pks)
            )
        }
    )


def list_inventory(player: str, status: str = "held") -> list[dict[str, Any]]:
    return run(
        lambda con: rows(
            con.execute(
                """
                SELECT * FROM inventory
                WHERE player = ? AND status = ?
                ORDER BY value DESC, id DESC
                """,
                (player, status),
            )
        )
    )


def set_inventory_status(item_pks: list[int], status: str) -> None:
    if not item_pks:
        return

    def inner(con: sqlite3.Connection) -> None:
        con.executemany(
            "UPDATE inventory SET status = ? WHERE id = ?",
            [(status, pk) for pk in item_pks],
        )

    run(inner)


def record_drop(player: str, item, case_id: str, is_bot: bool = False) -> None:
    public = item.as_public() if hasattr(item, "as_public") else item

    def inner(con: sqlite3.Connection) -> None:
        con.execute(
            """
            INSERT INTO drops (
                player, is_bot, item_id, name, rarity, value, image, color, case_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player,
                1 if is_bot else 0,
                public["id"],
                public["name"],
                public["rarity"],
                int(public["coin"]),
                public["image"],
                public["color"],
                case_id,
                now(),
            ),
        )
        # Chỉ dọn khi vượt ngưỡng — trước đây mỗi lần drop đều quét toàn
        # bảng để tìm dòng thừa, tốn công vô ích khi bảng còn nhỏ.
        count = con.execute("SELECT COUNT(*) FROM drops").fetchone()[0]
        if count > DROPS_KEEP:
            con.execute(
                "DELETE FROM drops WHERE id NOT IN "
                "(SELECT id FROM drops ORDER BY id DESC LIMIT ?)",
                (DROPS_KEEP,),
            )

    run(inner)


def recent_drops(limit: int = 30) -> list[dict[str, Any]]:
    return run(
        lambda con: rows(
            con.execute(
                "SELECT * FROM drops ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        )
    )


def record_pull(player: str, cost: int, prize, case_id: str = "", dry: bool = False) -> None:
    public = prize.as_public() if hasattr(prize, "as_public") else prize

    def inner(con: sqlite3.Connection) -> None:
        con.execute(
            """
            INSERT INTO pulls (
                player, cost, prize_id, prize_name, rarity, prize_coin,
                created_at, case_id, dry_run
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player,
                cost,
                public["id"],
                public["name"],
                public["rarity"],
                int(public["coin"]),
                now(),
                case_id,
                1 if dry else 0,
            ),
        )

    run(inner)


def record_upgrade(player: str, stake: dict, target: dict, chance: float, roll: float, won: bool) -> None:
    run(
        lambda con: con.execute(
            """
            INSERT INTO upgrades (
                player, stake_name, stake_value, target_name, target_value,
                chance, roll, won, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player,
                stake["name"],
                int(stake["coin"]),
                target["name"],
                int(target["coin"]),
                chance,
                roll,
                1 if won else 0,
                now(),
            ),
        )
    )


def last_bonus(player: str) -> int:
    def inner(con: sqlite3.Connection) -> int:
        row = con.execute("SELECT last_claim FROM bonus WHERE player = ?", (player,)).fetchone()
        return int(row["last_claim"]) if row else 0

    return run(inner)


def set_bonus(player: str) -> None:
    stamp = now()

    def inner(con: sqlite3.Connection) -> None:
        con.execute(
            "INSERT INTO bonus (player, last_claim) VALUES (?, ?) ON CONFLICT(player) DO UPDATE SET last_claim = ?",
            (player, stamp, stamp),
        )

    run(inner)


def create_battle(host: str, case_id: str, rounds: int, slots: int, mode: str, paid: int, host_is_bot: bool, lines: str = "", entry_price: int = 0) -> int:
    """Tạo phòng battle. Chuẩn web gốc: lưu thêm playlist `lines` (JSON) + `entry_price`.

    - Trận cũ (1 rương): lines rỗng -> tự suy ra [{case_id, count: rounds}].
    - Trận mới (multi-rương): truyền lines JSON + entry_price (giá 1 ghế).
    """
    import json as _json

    if not lines:
        try:
            lines = _json.dumps([{"case_id": case_id, "count": int(rounds)}], ensure_ascii=False)
        except Exception:
            lines = ""
    if not entry_price:
        entry_price = int(paid)
    def inner(con: sqlite3.Connection) -> int:
        cur = con.execute(
            """
            INSERT INTO battles (host, case_id, rounds, slots, mode, status, created_at, entry_price, lines)
            VALUES (?, ?, ?, ?, ?, 'WAITING', ?, ?, ?)
            """,
            (host, case_id, rounds, slots, mode, now(), int(entry_price), lines),
        )
        battle_id = int(cur.lastrowid)
        con.execute(
            """
            INSERT INTO battle_players (battle_id, player, is_bot, slot, total, paid)
            VALUES (?, ?, ?, 0, 0, ?)
            """,
            (battle_id, host, 1 if host_is_bot else 0, paid),
        )
        return battle_id

    return run(inner)


def get_battle(battle_id: int) -> dict[str, Any] | None:
    def inner(con: sqlite3.Connection) -> dict[str, Any] | None:
        battle = row_dict(con.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone())
        if not battle:
            return None
        battle["players"] = rows(
            con.execute(
                "SELECT * FROM battle_players WHERE battle_id = ? ORDER BY slot",
                (battle_id,),
            )
        )
        battle["drops"] = rows(
            con.execute(
                "SELECT * FROM battle_drops WHERE battle_id = ? ORDER BY round, id",
                (battle_id,),
            )
        )
        return battle

    return run(inner)


def list_battles() -> dict[str, list[dict[str, Any]]]:
    def inner(con: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
        open_rows = rows(
            con.execute(
                """
                SELECT b.*, COUNT(p.player) AS seated
                FROM battles b
                JOIN battle_players p ON p.battle_id = b.id
                WHERE b.status IN ('WAITING', 'RUNNING')
                GROUP BY b.id
                ORDER BY b.id DESC
                LIMIT 40
                """
            )
        )
        finished = rows(
            con.execute(
                """
                SELECT b.*, COUNT(p.player) AS seated
                FROM battles b
                JOIN battle_players p ON p.battle_id = b.id
                WHERE b.status = 'FINISHED'
                GROUP BY b.id
                ORDER BY b.id DESC
                LIMIT 12
                """
            )
        )
        ids = [row["id"] for row in open_rows + finished]
        players_by: dict[int, list] = {}
        if ids:
            placeholders = ",".join("?" * len(ids))
            for player in con.execute(
                f"SELECT * FROM battle_players WHERE battle_id IN ({placeholders}) ORDER BY slot",
                ids,
            ):
                players_by.setdefault(player["battle_id"], []).append(dict(player))
        for row in open_rows + finished:
            row["players"] = players_by.get(row["id"], [])
        return {"open": open_rows, "finished": finished}

    return run(inner)


def join_battle(battle_id: int, player: str, is_bot: bool, paid: int) -> dict[str, Any]:
    def inner(con: sqlite3.Connection) -> dict[str, Any]:
        battle = row_dict(con.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone())
        if not battle:
            raise ValueError("Không có trận này.")
        if battle["status"] != "WAITING":
            raise ValueError("Trận đã bắt đầu.")
        existing = con.execute(
            "SELECT player FROM battle_players WHERE battle_id = ? AND player = ?",
            (battle_id, player),
        ).fetchone()
        if existing:
            raise ValueError("Bạn đã ngồi trận này.")
        seated = con.execute(
            "SELECT COUNT(*) AS n FROM battle_players WHERE battle_id = ?",
            (battle_id,),
        ).fetchone()["n"]
        if seated >= battle["slots"]:
            raise ValueError("Hết chỗ.")
        con.execute(
            """
            INSERT INTO battle_players (battle_id, player, is_bot, slot, total, paid)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (battle_id, player, 1 if is_bot else 0, seated, paid),
        )
        battle["seated"] = seated + 1
        return battle

    return run(inner)


def set_battle_status(battle_id: int, status: str, **extra) -> None:
    fields = ["status = ?"]
    values: list[Any] = [status]
    if "winner" in extra:
        fields.append("winner = ?")
        values.append(extra["winner"])
    if "started_at" in extra:
        fields.append("started_at = ?")
        values.append(extra["started_at"])
    if "finished_at" in extra:
        fields.append("finished_at = ?")
        values.append(extra["finished_at"])
    values.append(battle_id)

    def inner(con: sqlite3.Connection) -> None:
        con.execute(f"UPDATE battles SET {', '.join(fields)} WHERE id = ?", values)

    run(inner)


# --- Fix kẹt RUNNING + race khi Start (vấn đề 1) ---------------------------
# Trước đây: check WAITING rồi mới set RUNNING bằng 2 query riêng nên 2
# request Start cùng lúc đều lọt qua (roll + thưởng 2 lần). Nếu crash giữa
# RUNNING -> FINISHED thì phòng kẹt RUNNING vĩnh viễn.
STALE_RUNNING_SECONDS = 90


def try_claim_battle_start(battle_id: int) -> dict[str, Any]:
    """Giành quyền quay 1 cách nguyên tử (compare-and-swap).

    Trả về {"claimed": bool, "battle": dict|None, "reason": str}.
    - WAITING -> chuyển sang RUNNING trong CÙNG 1 transaction rồi trả battle.
    - RUNNING còn mới -> claimed=False (trận đang quay, không roll lại).
    - RUNNING quá hạn STALE_RUNNING_SECONDS -> coi như crash, reset về
      WAITING rồi giành quyền luôn để trận không kẹt vĩnh viễn.
    - FINISHED/CANCELLED -> claimed=False.
    """

    def inner(con: sqlite3.Connection) -> dict[str, Any]:
        battle = row_dict(con.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone())
        if not battle:
            return {"claimed": False, "battle": None, "reason": "missing"}
        status = battle["status"]
        if status == "WAITING":
            cur = con.execute(
                "UPDATE battles SET status = 'RUNNING', started_at = ? WHERE id = ? AND status = 'WAITING'",
                (now(), battle_id),
            )
            # rowcount == 1 mới là người thắng race. _lock đã serialize thread
            # trong cùng process, còn điều kiện WHERE giữ an toàn khi chạy
            # nhiều worker/process.
            if cur.rowcount != 1:
                return {"claimed": False, "battle": None, "reason": "race-lost"}
            full = row_dict(con.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone())
            assert full is not None
            full["players"] = rows(
                con.execute("SELECT * FROM battle_players WHERE battle_id = ? ORDER BY slot", (battle_id,))
            )
            full["drops"] = rows(
                con.execute("SELECT * FROM battle_drops WHERE battle_id = ? ORDER BY round, id", (battle_id,))
            )
            return {"claimed": True, "battle": full, "reason": ""}
        if status == "RUNNING":
            started = int(battle.get("started_at") or 0)
            if started and (now() - started) < STALE_RUNNING_SECONDS:
                return {"claimed": False, "battle": None, "reason": "running"}
            # Crash giữa chừng: chưa có kết quả FINISHED nên reset an toàn.
            con.execute("UPDATE battles SET status = 'WAITING', started_at = NULL WHERE id = ?", (battle_id,))
            con.execute(
                "UPDATE battles SET status = 'RUNNING', started_at = ? WHERE id = ? AND status = 'WAITING'",
                (now(), battle_id),
            )
            full = row_dict(con.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone())
            assert full is not None
            full["players"] = rows(
                con.execute("SELECT * FROM battle_players WHERE battle_id = ? ORDER BY slot", (battle_id,))
            )
            full["drops"] = rows(
                con.execute("SELECT * FROM battle_drops WHERE battle_id = ? ORDER BY round, id", (battle_id,))
            )
            return {"claimed": True, "battle": full, "reason": "recovered"}
        return {"claimed": False, "battle": None, "reason": "finished"}

    return run(inner)


def reset_battle_to_waiting(battle_id: int) -> None:
    """Trả phòng về WAITING khi roll/settle lỗi giữa chừng (chống kẹt)."""

    def inner(con: sqlite3.Connection) -> None:
        con.execute("UPDATE battles SET status = 'WAITING', started_at = NULL WHERE id = ? AND status = 'RUNNING'", (battle_id,))

    run(inner)


def stale_running_battles(limit: int = 20) -> list[dict[str, Any]]:
    """Phòng kẹt ở RUNNING quá hạn (crash giữa lúc quay) để vòng nền dọn."""

    def inner(con: sqlite3.Connection) -> list[dict[str, Any]]:
        cutoff = now() - STALE_RUNNING_SECONDS
        return rows(
            con.execute(
                "SELECT * FROM battles WHERE status = 'RUNNING' AND COALESCE(started_at, 0) < ? ORDER BY id ASC LIMIT ?",
                (cutoff, limit),
            )
        )

    return run(inner)


def leave_battle_player(battle_id: int, player: str) -> dict[str, Any]:
    """Rời phòng khi còn WAITING. Trả về tiền ghế đã trả để caller hoàn.

    - Host out -> chuyển host cho người còn lại (slot nhỏ nhất).
    - Người cuối cùng out -> xóa phòng cho gọn lobby.
    """

    def inner(con: sqlite3.Connection) -> dict[str, Any]:
        battle = row_dict(con.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone())
        if not battle:
            raise ValueError("Không có trận này.")
        if battle["status"] != "WAITING":
            raise ValueError("Trận đã bắt đầu, không thể rời.")
        row = con.execute(
            "SELECT * FROM battle_players WHERE battle_id = ? AND player = ?",
            (battle_id, player),
        ).fetchone()
        if not row:
            raise ValueError("Bạn không ở trong phòng này.")
        paid = int(row["paid"])
        con.execute("DELETE FROM battle_players WHERE battle_id = ? AND player = ?", (battle_id, player))
        rest = rows(con.execute("SELECT * FROM battle_players WHERE battle_id = ? ORDER BY slot", (battle_id,)))
        if not rest:
            con.execute("DELETE FROM battles WHERE id = ?", (battle_id,))
            return {"paid": paid, "battle_deleted": True, "new_host": None}
        # Dồn slot cho gọn + chuyển host nếu cần.
        for idx, member in enumerate(rest):
            con.execute(
                "UPDATE battle_players SET slot = ? WHERE battle_id = ? AND player = ?",
                (idx, battle_id, member["player"]),
            )
        new_host = battle["host"]
        if battle["host"] == player:
            new_host = rest[0]["player"]
            con.execute("UPDATE battles SET host = ? WHERE id = ?", (new_host, battle_id))
        return {"paid": paid, "battle_deleted": False, "new_host": new_host}

    return run(inner)


def cancel_battle_room(battle_id: int, host: str) -> list[dict[str, Any]]:
    """Host hủy phòng WAITING. Trả về danh sách người cần hoàn tiền."""

    def inner(con: sqlite3.Connection) -> list[dict[str, Any]]:
        battle = row_dict(con.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone())
        if not battle:
            raise ValueError("Không có trận này.")
        if battle["status"] != "WAITING":
            raise ValueError("Trận đã bắt đầu, không thể hủy.")
        if battle["host"] != host:
            raise ValueError("Chỉ chủ phòng mới được hủy.")
        members = rows(con.execute("SELECT player, paid, is_bot FROM battle_players WHERE battle_id = ?", (battle_id,)))
        con.execute("UPDATE battles SET status = 'CANCELLED', finished_at = ? WHERE id = ?", (now(), battle_id))
        return members

    return run(inner)


def update_battle_config(
    battle_id: int, host: str, case_id: str, rounds: int, slots: int, mode: str, new_paid: int,
    lines: str = "", entry_price: int = 0,
) -> dict[str, Any]:
    """Host đổi rương / vòng / ghế / chế độ khi phòng còn WAITING và chưa full."""
    import json as _json

    if not lines:
        try:
            lines = _json.dumps([{"case_id": case_id, "count": int(rounds)}], ensure_ascii=False)
        except Exception:
            lines = ""
    if not entry_price:
        entry_price = int(new_paid)

    def inner(con: sqlite3.Connection) -> dict[str, Any]:
        battle = row_dict(con.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone())
        if not battle:
            raise ValueError("Không có trận này.")
        if battle["status"] != "WAITING":
            raise ValueError("Trận đã bắt đầu, không đổi được cấu hình.")
        if battle["host"] != host:
            raise ValueError("Chỉ chủ phòng mới đổi được cấu hình.")
        seated = con.execute(
            "SELECT COUNT(*) AS n FROM battle_players WHERE battle_id = ?", (battle_id,)
        ).fetchone()["n"]
        if slots < seated:
            raise ValueError(f"Đang có {seated} người, không giảm ghế xuống {slots} được.")
        old_paid_rows = rows(con.execute("SELECT player, paid FROM battle_players WHERE battle_id = ?", (battle_id,)))
        con.execute(
            "UPDATE battles SET case_id = ?, rounds = ?, slots = ?, mode = ?, lines = ?, entry_price = ? WHERE id = ?",
            (case_id, rounds, slots, mode, lines, int(entry_price), battle_id),
        )
        con.execute("UPDATE battle_players SET paid = ? WHERE battle_id = ?", (new_paid, battle_id))
        return {"old": old_paid_rows, "new_paid": new_paid}

    return run(inner)


def save_battle_result(battle_id: int, totals: dict[str, int], drops: list[dict[str, Any]], winner: str) -> None:
    stamp = now()

    def inner(con: sqlite3.Connection) -> None:
        for player, total in totals.items():
            con.execute(
                "UPDATE battle_players SET total = ? WHERE battle_id = ? AND player = ?",
                (total, battle_id, player),
            )
        # Tương thích DB cũ chưa có cột case_id: chèn kèm cột nếu có.
        try:
            cols = {row[1] for row in con.execute("PRAGMA table_info(battle_drops)")}
        except Exception:
            cols = {"case_id"}
        if "case_id" in cols:
            con.executemany(
                """
                INSERT INTO battle_drops (
                    battle_id, player, round, item_id, name, rarity, value, image, color, case_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        battle_id,
                        drop["player"],
                        drop["round"],
                        drop["id"],
                        drop["name"],
                        drop["rarity"],
                        drop["value"],
                        drop["image"],
                        drop["color"],
                        drop.get("case_id") or "",
                    )
                    for drop in drops
                ],
            )
        else:
            con.executemany(
                """
                INSERT INTO battle_drops (
                    battle_id, player, round, item_id, name, rarity, value, image, color
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        battle_id,
                        drop["player"],
                        drop["round"],
                        drop["id"],
                        drop["name"],
                        drop["rarity"],
                        drop["value"],
                        drop["image"],
                        drop["color"],
                    )
                    for drop in drops
                ],
            )
        con.execute(
            "UPDATE battles SET status = 'FINISHED', winner = ?, started_at = COALESCE(started_at, ?), finished_at = ? WHERE id = ?",
            (winner, stamp, stamp, battle_id),
        )

    run(inner)


def waiting_battles() -> list[dict[str, Any]]:
    def inner(con: sqlite3.Connection) -> list[dict[str, Any]]:
        return rows(
            con.execute(
                """
                SELECT b.*, COUNT(p.player) AS seated
                FROM battles b
                JOIN battle_players p ON p.battle_id = b.id
                WHERE b.status = 'WAITING'
                GROUP BY b.id
                ORDER BY b.id ASC
                """
            )
        )

    return run(inner)


def battle_player_names(battle_id: int) -> set[str]:
    def inner(con: sqlite3.Connection) -> set[str]:
        return {
            row["player"]
            for row in con.execute(
                "SELECT player FROM battle_players WHERE battle_id = ?",
                (battle_id,),
            )
        }

    return run(inner)


def recent_tx(player: str, limit: int = 20) -> list[dict[str, Any]]:
    return run(
        lambda con: rows(
            con.execute(
                "SELECT * FROM tx WHERE player = ? ORDER BY id DESC LIMIT ?",
                (player, limit),
            )
        )
    )


def stats() -> dict[str, Any]:
    def inner(con: sqlite3.Connection) -> dict[str, Any]:
        total = con.execute(
            """
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(cost),0) AS spent,
                   COALESCE(SUM(prize_coin),0) AS paid
            FROM pulls
            """
        ).fetchone()
        by_rarity = rows(
            con.execute(
                """
                SELECT rarity, COUNT(*) AS n, COALESCE(SUM(prize_coin),0) AS paid
                FROM pulls GROUP BY rarity ORDER BY n DESC
                """
            )
        )
        recent = rows(
            con.execute(
                """
                SELECT player, cost, prize_name, rarity, prize_coin, created_at, case_id, dry_run
                FROM pulls ORDER BY id DESC LIMIT 40
                """
            )
        )
        top = rows(
            con.execute(
                """
                SELECT player, COUNT(*) AS n, COALESCE(SUM(cost),0) AS spent
                FROM pulls GROUP BY player ORDER BY n DESC LIMIT 15
                """
            )
        )
        battles_n = con.execute("SELECT COUNT(*) AS n FROM battles WHERE status = 'FINISHED'").fetchone()["n"]
        sells = con.execute("SELECT COUNT(*) AS n FROM inventory WHERE status = 'sold'").fetchone()["n"]
        held = con.execute("SELECT COUNT(*) AS n FROM inventory WHERE status = 'held'").fetchone()["n"]
        upgrades = con.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(won),0) AS wins FROM upgrades"
        ).fetchone()
        users_n = con.execute("SELECT COUNT(*) AS n FROM wallets WHERE is_bot = 0").fetchone()["n"]
        return {
            "pulls": total["n"],
            "spent": total["spent"],
            "paid": total["paid"],
            "net": total["spent"] - total["paid"],
            "by_rarity": by_rarity,
            "recent": recent,
            "top": top,
            "battles": battles_n,
            "sells": sells,
            "held": held,
            "upgrades": upgrades["n"],
            "upgrade_wins": upgrades["wins"],
            "users": users_n,
        }

    return run(inner)
