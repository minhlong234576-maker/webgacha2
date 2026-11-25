from __future__ import annotations

import json
import random
from dataclasses import dataclass

from .gacha import (
    get_case,
    is_dry_run,
    load_cases,
    market_listings,
    roll,
)
from . import store

BATTLE_MAX_ROUNDS = 30
BATTLE_MAX_LINES = 6
BATTLE_MIN_ROUNDS = 1

UPGRADE_RTP = 0.9
UPGRADE_MIN_CHANCE = 0.005
UPGRADE_MAX_CHANCE = 0.85
UPGRADE_MIN_MULTIPLIER = 1.05
DRY_SEED = 250_000
BONUS_SLICES = (
    (500, 28),
    (1500, 24),
    (3000, 18),
    (5000, 14),
    (10000, 10),
    (25000, 5),
    (50000, 1),
)


class GameError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class OpenResult:
    winner: dict
    pool: list[dict]
    inventory_id: int
    balance: int
    dry_run: bool


@dataclass
class OpenBatchResult:
    openings: list[dict]
    pool: list[dict]
    total_cost: int
    balance: int
    dry_run: bool


def seed_wallet(player: str, pika_coin: float = 0, is_bot: bool = False) -> int:
    """Đảm bảo ví web có dòng, và ở chế độ thật thì mirror đúng số dư server.

    - Bot: luôn là ví ảo (chỉ tồn tại trong web), seed 1.000.000.
    - Dry-run: seed 250.000 như thiết kế.
    - Tiền thật: KHÔNG seed — số dư phải bằng đúng Coin in-game, nếu không
      người chơi có thể mở rương miễn phí ngay lần đầu.
    """
    if is_bot:
        return store.ensure_wallet(player, seed=max(int(pika_coin), 1_000_000), is_bot=True)
    if is_dry_run():
        return store.ensure_wallet(player, seed=DRY_SEED, is_bot=False)
    return store.set_wallet(player, int(pika_coin))


def balance(player: str) -> int:
    return store.get_balance(player)


def open_case_batch(player: str, slug: str, count: int = 1, is_bot: bool = False) -> OpenBatchResult:
    if count not in (1, 2, 3, 4, 5):
        raise GameError("Số lượng mở không hợp lệ (1-5).")
    case = get_case(slug)
    if not case:
        raise GameError("Không có rương này.", 404)
    total_cost = case.pull_cost * count
    if store.get_balance(player) < total_cost:
        raise GameError(f"Không đủ Coin. Cần {total_cost:,} Coin.")

    store.debit(player, total_cost, "open", f"{case.id} x{count}")
    openings = []
    pool = [item.as_public() for item in case.items]
    for _ in range(count):
        prize = roll(case)
        inv_id = store.add_inventory(player, prize, "case", case.id)
        store.record_drop(player, prize, case.id, is_bot=is_bot)
        store.record_pull(player, case.pull_cost, prize, case_id=case.id, dry=is_dry_run())
        openings.append({
            "winner": prize.as_public(),
            "inventory_id": inv_id,
            "winner_coin": prize.coin,
        })
    return OpenBatchResult(
        openings=openings,
        pool=pool,
        total_cost=total_cost,
        balance=store.get_balance(player),
        dry_run=is_dry_run(),
    )


def open_case(player: str, slug: str, is_bot: bool = False) -> OpenResult:
    res = open_case_batch(player, slug, count=1, is_bot=is_bot)
    first = res.openings[0]
    return OpenResult(
        winner=first["winner"],
        pool=res.pool,
        inventory_id=first["inventory_id"],
        balance=res.balance,
        dry_run=res.dry_run,
    )


def sell_preview(player: str, item_pks: list[int]) -> int:
    """Tính tổng giá trị sẽ bán, KHÔNG thay đổi gì.

    Dùng để cộng Coin in-game TRƯỚC khi đánh dấu đồ là đã bán — nếu cộng
    tiền thật thất bại thì đồ vẫn còn trong túi, người chơi không mất gì.
    """
    if not item_pks:
        raise GameError("Chưa chọn món nào.")
    items = store.get_inventory_items(item_pks)
    total = 0
    for pk in item_pks:
        row = items.get(pk)
        if not row or row["player"] != player:
            raise GameError("Không phải đồ của bạn.")
        if row["status"] != "held":
            raise GameError(f"{row['name']} không còn trong túi.")
        total += int(row["value"])
    return total


def sell_items(player: str, item_pks: list[int]) -> dict:
    if not item_pks:
        raise GameError("Chưa chọn món nào.")
    items = store.get_inventory_items(item_pks)
    total = 0
    sold = []
    for pk in item_pks:
        row = items.get(pk)
        if not row or row["player"] != player:
            raise GameError("Không phải đồ của bạn.")
        if row["status"] != "held":
            raise GameError(f"{row['name']} không còn trong túi.")
        total += int(row["value"])
        sold.append(row)
    store.set_inventory_status(item_pks, "sold")
    store.credit(player, total, "sell", f"{len(item_pks)} món")
    return {
        "sold": len(item_pks),
        "amount": total,
        "balance": store.get_balance(player),
        "items": sold,
    }


def sell_all(player: str) -> dict:
    held = store.list_inventory(player, "held")
    return sell_items(player, [row["id"] for row in held])


def upgrade_odds(source: int, target: int) -> dict:
    if source <= 0 or target <= 0:
        return {"ok": False, "reason": "Giá không hợp lệ."}
    multiplier = target / source
    if multiplier < UPGRADE_MIN_MULTIPLIER:
        return {"ok": False, "reason": "Món đích phải đắt hơn ít nhất 5%."}
    raw = (source / target) * UPGRADE_RTP
    if raw < UPGRADE_MIN_CHANCE:
        return {"ok": False, "reason": "Khoảng giá quá xa, tỉ lệ dưới 0.5%."}
    chance = min(UPGRADE_MAX_CHANCE, raw)
    return {"ok": True, "chance": chance, "multiplier": multiplier}


def upgrade_targets(stake_value: int) -> list[dict]:
    low = int(stake_value * UPGRADE_MIN_MULTIPLIER)
    high = int((stake_value * UPGRADE_RTP) / UPGRADE_MIN_CHANCE)
    out = []
    for item in market_listings():
        if low <= item.coin <= high:
            odds = upgrade_odds(stake_value, item.coin)
            if odds["ok"]:
                public = item.as_public()
                public["chance"] = round(odds["chance"] * 100, 2)
                public["multiplier"] = round(odds["multiplier"], 2)
                out.append(public)
    return out


def do_upgrade(player: str, inventory_id: int, target_id: str, target_coin: int) -> dict:
    stake = store.get_inventory_item(inventory_id)
    if not stake or stake["player"] != player or stake["status"] != "held":
        raise GameError("Không dùng được món này.")
    target = None
    for item in market_listings():
        if item.id == target_id and item.coin == target_coin:
            target = item
            break
    if not target:
        raise GameError("Không có món đích này.")
    odds = upgrade_odds(int(stake["value"]), target.coin)
    if not odds["ok"]:
        raise GameError(odds["reason"])
    roll_v = random.random()
    won = roll_v < odds["chance"]
    store.set_inventory_status([inventory_id], "upgraded")
    reward_id = None
    if won:
        reward_id = store.add_inventory(player, target, "upgrade")
        store.record_drop(player, target, "upgrade", is_bot=False)
    store.record_upgrade(player, {"name": stake["name"], "coin": stake["value"]}, target.as_public(), odds["chance"], roll_v, won)
    return {
        "won": won,
        "chance": round(odds["chance"] * 100, 2),
        "roll": round(roll_v * 100, 2),
        "stake": stake,
        "target": target.as_public(),
        "reward_id": reward_id,
        "balance": store.get_balance(player),
    }


def battle_lines_normalize(raw_lines=None, slug: str = "", rounds: int = 1) -> list[dict]:
    """Chuẩn web gốc: battle là playlist [{case_id, count}]."""
    lines: list[dict] = []
    if raw_lines:
        seen: set[str] = set()
        for entry in raw_lines:
            if not isinstance(entry, dict):
                continue
            cid = str(entry.get("case_id") or entry.get("id") or entry.get("slug") or "").strip()
            try:
                cnt = int(entry.get("count") or entry.get("rounds") or 1)
            except (TypeError, ValueError):
                cnt = 1
            if not cid or cid in seen:
                continue
            case = get_case(cid)
            if not case:
                raise GameError(f"Không có rương {cid}.", 404)
            cnt = max(1, min(BATTLE_MAX_ROUNDS, cnt))
            seen.add(cid)
            lines.append({"case_id": cid, "count": cnt})
    if not lines:
        if not slug:
            raise GameError("Chưa chọn rương.", 400)
        case = get_case(slug)
        if not case:
            raise GameError("Không có rương này.", 404)
        lines = [{"case_id": slug, "count": max(1, min(BATTLE_MAX_ROUNDS, int(rounds or 1)))}]
    if len(lines) > BATTLE_MAX_LINES:
        raise GameError(f"Tối đa {BATTLE_MAX_LINES} loại rương / trận.", 400)
    total = sum(int(line["count"]) for line in lines)
    if total < BATTLE_MIN_ROUNDS or total > BATTLE_MAX_ROUNDS:
        raise GameError(f"Số vòng 1–{BATTLE_MAX_ROUNDS}.", 400)
    return lines


def battle_lines_of(battle: dict) -> list[dict]:
    raw = (battle or {}).get("lines") or ""
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return [{"case_id": str(e.get("case_id")), "count": int(e.get("count") or 1)} for e in parsed if e.get("case_id")]
        except Exception:
            pass
    cid = str((battle or {}).get("case_id") or "")
    try:
        cnt = int((battle or {}).get("rounds") or 1)
    except (TypeError, ValueError):
        cnt = 1
    return [{"case_id": cid, "count": max(1, cnt)}] if cid else []


def battle_order_of(battle: dict) -> list[str]:
    order: list[str] = []
    for line in battle_lines_of(battle):
        order.extend([line["case_id"]] * int(line["count"]))
    return order


def battle_entry_price(lines: list[dict]) -> int:
    total = 0
    for line in lines:
        case = get_case(line["case_id"])
        if not case:
            raise GameError(f"Không có rương {line['case_id']}.", 404)
        total += case.pull_cost * int(line["count"])
    return total


def battle_case_at(battle: dict, round_i: int):
    order = battle_order_of(battle)
    if 1 <= round_i <= len(order):
        return get_case(order[round_i - 1])
    return get_case(battle.get("case_id"))


def battle_price(slug: str, rounds: int) -> int:
    case = get_case(slug)
    if not case:
        raise GameError("Không có rương này.", 404)
    if rounds < 1 or rounds > BATTLE_MAX_ROUNDS:
        raise GameError(f"Số vòng 1–{BATTLE_MAX_ROUNDS}.")
    return case.pull_cost * rounds


def battle_paid_of(battle: dict) -> int:
    """Giá 1 ghế: ưu tiên entry_price đã chốt, fallback tính lại."""
    try:
        locked = int((battle or {}).get("entry_price") or 0)
    except (TypeError, ValueError):
        locked = 0
    if locked > 0:
        return locked
    try:
        return battle_entry_price(battle_lines_of(battle))
    except GameError:
        return battle_price(battle.get("case_id"), int(battle.get("rounds") or 1))


def create_battle(player: str, slug: str, slots: int, rounds: int, mode: str, is_bot: bool = False, lines: list[dict] | None = None) -> dict:
    if slots not in (2, 3, 4):
        raise GameError("Số chỗ 2, 3 hoặc 4.")
    mode = mode if mode in ("STANDARD", "CRAZY") else "STANDARD"
    norm = battle_lines_normalize(lines, slug, rounds)
    paid = battle_entry_price(norm)
    if store.get_balance(player) < paid:
        raise GameError("Không đủ Coin.")
    note = norm[0]["case_id"] if len(norm) == 1 else f"{len(norm)} rương x{sum(int(l['count']) for l in norm)} vòng"
    store.debit(player, paid, "battle_pay", note)
    lines_json = json.dumps(norm, ensure_ascii=False)
    total_rounds = sum(int(line["count"]) for line in norm)
    battle_id = store.create_battle(player, norm[0]["case_id"], total_rounds, slots, mode, paid, is_bot, lines_json, paid)
    return store.get_battle(battle_id)


def join_existing_battle(player: str, battle_id: int, is_bot: bool = False) -> dict:
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Không có trận này.", 404)
    if battle["status"] != "WAITING":
        raise GameError("Trận đã bắt đầu.")
    paid = battle_paid_of(battle)
    if store.get_balance(player) < paid:
        raise GameError("Không đủ Coin.")
    order = battle_order_of(battle)
    store.debit(player, paid, "battle_pay", order[0] if len(order) and len(set(order)) == 1 else f"{len(battle_lines_of(battle))} rương x{len(order)} vòng")
    try:
        store.join_battle(battle_id, player, is_bot, paid)
    except ValueError as exc:
        store.credit(player, paid, "refund", "join thất bại")
        raise GameError(str(exc)) from exc
    fresh = store.get_battle(battle_id) or {}
    # Chuẩn web gốc: đủ ghế -> tự quay luôn, không cần chờ host bấm Start.
    try:
        if fresh and fresh.get("status") == "WAITING" and len(fresh.get("players") or []) >= int(fresh.get("slots") or 0):
            return start_battle(battle_id, None)
    except GameError:
        pass
    return store.get_battle(battle_id)


def fill_bots(battle_id: int, requester: str | None = None) -> dict:
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Không có trận này.", 404)
    if battle["status"] != "WAITING":
        return battle
    # Chỉ người trong phòng mới được gọi bot (tránh người ngoài lấp full
    # phòng người khác để ép ván). Host / người đã ngồi đều được gọi.
    if requester is not None:
        seated_names = {row["player"] for row in battle["players"]}
        if requester not in seated_names:
            raise GameError("Vào phòng rồi mới được gọi bot.")
    seated = {row["player"] for row in battle["players"]}
    paid = battle_paid_of(battle)
    order = battle_order_of(battle)
    note = order[0] if len(order) and len(set(order)) == 1 else f"{len(battle_lines_of(battle))} rương x{len(order)} vòng"
    for name in store.BOT_NAMES:
        if len(seated) >= battle["slots"]:
            break
        if name in seated:
            continue
        seed_wallet(name, is_bot=True)
        if store.get_balance(name) < paid:
            store.credit(name, paid * 4, "seed", "bot nạp")
        store.debit(name, paid, "battle_pay", note)
        try:
            store.join_battle(battle_id, name, True, paid)
        except ValueError:
            store.credit(name, paid, "refund", "ghế đầy")
            break
        seated.add(name)
    fresh = store.get_battle(battle_id) or battle
    # Chuẩn web gốc: full ghế -> tự quay luôn.
    try:
        if fresh.get("status") == "WAITING" and len(fresh.get("players") or []) >= int(fresh.get("slots") or 0):
            return start_battle(battle_id, None)
    except GameError:
        pass
    return store.get_battle(battle_id)


def leave_battle(player: str, battle_id: int) -> dict:
    """Rời phòng khi còn WAITING + hoàn tiền ghế web."""
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Không có trận này.", 404)
    if battle["status"] != "WAITING":
        raise GameError("Trận đã bắt đầu, không thể rời.")
    try:
        info = store.leave_battle_player(battle_id, player)
    except ValueError as exc:
        raise GameError(str(exc)) from exc
    paid = int(info.get("paid") or 0)
    if paid > 0:
        # Người thật + bot đều hoàn ví web ở đây. Tiền thật (Coin in-game)
        # do tầng web (main.py) hoàn qua bank.give sau.
        store.credit(player, paid, "refund", f"rời phòng #{battle_id}")
    if info.get("battle_deleted"):
        return {"deleted": True, "id": battle_id, "balance": store.get_balance(player)}
    fresh = store.get_battle(battle_id)
    return {"deleted": False, "balance": store.get_balance(player), "battle": fresh}


def cancel_battle(host: str, battle_id: int) -> dict:
    """Host hủy phòng WAITING + hoàn tiền ghế cho mọi người (ví web)."""
    try:
        members = store.cancel_battle_room(battle_id, host)
    except ValueError as exc:
        raise GameError(str(exc)) from exc
    for member in members:
        paid = int(member.get("paid") or 0)
        if paid > 0:
            store.credit(member["player"], paid, "refund", f"hủy phòng #{battle_id}")
    return {"cancelled": True, "id": battle_id, "refunded": members, "balance": store.get_balance(host)}


def kick_battle_bot(host: str, battle_id: int, target: str) -> dict:
    """Host đá bot khỏi phòng WAITING + hoàn tiền ghế cho bot."""
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Không có trận này.", 404)
    if battle["status"] != "WAITING":
        raise GameError("Trận đã bắt đầu, không đá được.")
    if battle["host"] != host:
        raise GameError("Chỉ chủ phòng mới đá được bot.")
    row = next((r for r in battle["players"] if r["player"] == target), None)
    if not row:
        raise GameError("Bot không ở trong phòng này.")
    if not row["is_bot"]:
        raise GameError("Chỉ đá được bot, người thật phải tự rời.")
    if target == battle["host"]:
        raise GameError("Không đá được chủ phòng.")
    try:
        info = store.leave_battle_player(battle_id, target)
    except ValueError as exc:
        raise GameError(str(exc)) from exc
    paid = int(info.get("paid") or 0)
    if paid > 0:
        store.credit(target, paid, "refund", f"bị đá khỏi phòng #{battle_id}")
    return store.get_battle(battle_id) or {}


def update_battle_setup(
    host: str, battle_id: int, slug: str, rounds: int, slots: int, mode: str,
    lines: list[dict] | None = None,
) -> dict:
    """Host đổi rương / vòng / ghế / chế độ khi phòng còn WAITING.

    Chuẩn web gốc: `lines` là playlist [{case_id, count}]. Nếu không truyền
    lines thì dùng cấu hình 1 rương cũ (slug + rounds).
    Chênh lệch tiền ghế xử lý ở ví web tại đây:
    - Đắt hơn: trừ thêm (thiếu tiền thì báo lỗi, không đổi gì).
    - Rẻ hơn: hoàn phần chênh.
    Tầng web (main.py) tự đối chiếu Coin in-game qua bank trước khi gọi.
    """
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Không có trận này.", 404)
    if battle["status"] != "WAITING":
        raise GameError("Trận đã bắt đầu, không đổi được cấu hình.")
    if battle["host"] != host:
        raise GameError("Chỉ chủ phòng mới đổi được cấu hình.")
    if slots not in (2, 3, 4):
        raise GameError("Số chỗ 2, 3 hoặc 4.")
    mode = mode if mode in ("STANDARD", "CRAZY") else "STANDARD"
    norm = battle_lines_normalize(lines, slug, rounds)
    if len(battle["players"]) > slots:
        raise GameError(f"Đang có {len(battle['players'])} người, không giảm ghế xuống {slots} được.")
    new_paid = battle_entry_price(norm)
    total_rounds = sum(int(line["count"]) for line in norm)
    # Tính chênh lệch trước khi đụng DB.
    diffs: dict[str, int] = {}
    for row in battle["players"]:
        diff = new_paid - int(row["paid"])
        if diff > 0 and store.get_balance(row["player"]) < diff:
            raise GameError(f"{row['player']} không đủ Coin để đổi sang rương này.")
        diffs[row["player"]] = diff
    try:
        store.update_battle_config(
            battle_id, host, norm[0]["case_id"], total_rounds, slots, mode, new_paid,
            json.dumps(norm, ensure_ascii=False), new_paid,
        )
    except ValueError as exc:
        raise GameError(str(exc)) from exc
    for player_name, diff in diffs.items():
        if diff > 0:
            try:
                store.debit(player_name, diff, "battle_pay", f"đổi rương phòng #{battle_id}")
            except ValueError:
                pass
        elif diff < 0:
            store.credit(player_name, -diff, "refund", f"đổi rương phòng #{battle_id}")
    return store.get_battle(battle_id) or {}


def rematch_battle(player: str, battle_id: int, slug: str, rounds: int, mode: str, lines: list[dict] | None = None) -> dict:
    """Đánh tiếp ván mới sau khi trận cũ FINISHED/CANCELLED.

    Tạo phòng WAITING mới giữ nguyên số ghế, host là người bấm.
    Chuẩn web gốc: cho phép chọn lại playlist rương.
    Người này trả tiền ghế ngay; người khác / bot vào sau như phòng thường.
    """
    old = store.get_battle(battle_id)
    if not old:
        raise GameError("Không có trận này.", 404)
    if old["status"] not in ("FINISHED", "CANCELLED"):
        raise GameError("Trận chưa xong, chưa đánh tiếp được.")
    norm = battle_lines_normalize(lines, slug, rounds)
    mode = mode if mode in ("STANDARD", "CRAZY") else "STANDARD"
    old_players = [r["player"] for r in old.get("players") or []]
    if player not in old_players:
        raise GameError("Chỉ người trong trận cũ mới đánh tiếp được.")
    paid = battle_entry_price(norm)
    if store.get_balance(player) < paid:
        raise GameError("Không đủ Coin.")
    note = norm[0]["case_id"] if len(norm) == 1 else f"{len(norm)} rương x{sum(int(l['count']) for l in norm)} vòng"
    store.debit(player, paid, "battle_pay", note)
    new_id = store.create_battle(
        player, norm[0]["case_id"], sum(int(l["count"]) for l in norm),
        int(old["slots"]), mode, paid, False,
        json.dumps(norm, ensure_ascii=False), paid,
    )
    return store.get_battle(new_id) or {}


def start_battle(battle_id: int, player: str | None = None) -> dict:
    battle = store.get_battle(battle_id)
    if not battle:
        raise GameError("Không có trận này.", 404)
    if battle["status"] == "FINISHED":
        raise GameError("Trận đã xong.")
    if battle["status"] == "CANCELLED":
        raise GameError("Phòng đã bị hủy.")
    if battle["status"] == "RUNNING":
        # Ai bấm Start lúc đang quay thì trả về trạng thái hiện tại,
        # không roll lại (chống double-claim khi double-click).
        fresh = store.get_battle(battle_id)
        if fresh and fresh["status"] == "FINISHED":
            return fresh
        raise GameError("Trận đang quay, chờ chút.")
    if len(battle["players"]) < 2:
        raise GameError("Cần ít nhất 2 người mới bắt đầu.")
    if player is not None and battle["host"] != player:
        raise GameError("Chỉ chủ phòng mới bấm Bắt đầu.")
    return settle_battle(battle_id, expected_host=player)


def settle_battle(battle_id: int, expected_host: str | None = None) -> dict:
    # Giành quyền quay nguyên tử: chỉ 1 request thắng, còn lại không roll lại.
    # Nếu crash kẹt RUNNING quá 90s thì tự phục hồi về WAITING rồi quay tiếp.
    claim = store.try_claim_battle_start(battle_id)
    if not claim["claimed"]:
        reason = claim.get("reason") or ""
        fresh = store.get_battle(battle_id)
        if fresh and fresh["status"] == "FINISHED":
            return fresh
        if reason == "running":
            raise GameError("Trận đang quay, chờ chút.")
        if reason == "missing":
            raise GameError("Không có trận này.", 404)
        # race-lost / finished: trả trạng thái mới nhất để client tự refresh.
        if fresh:
            return fresh
        raise GameError("Trận đã bắt đầu hoặc đã xong.")
    battle = claim["battle"]
    assert battle is not None
    if len(battle["players"]) < 2:
        store.reset_battle_to_waiting(battle_id)
        raise GameError("Cần ít nhất 2 người.")
    if expected_host is not None and battle["host"] != expected_host:
        store.reset_battle_to_waiting(battle_id)
        raise GameError("Chỉ chủ phòng mới bấm Bắt đầu.")
    case = get_case(battle["case_id"])
    order = battle_order_of(battle)
    if not order and case:
        order = [case.id] * int(battle.get("rounds") or 1)
    if not order or not case:
        store.reset_battle_to_waiting(battle_id)
        raise GameError("Rương trận không còn.")
    # Chuẩn web gốc: mỗi vòng mở đúng rương của vòng đó, pool reel khác nhau.
    case_by_id: dict[str, object] = {}
    for cid in dict.fromkeys(order):
        c = get_case(cid)
        if not c:
            store.reset_battle_to_waiting(battle_id)
            raise GameError("Rương trận không còn.")
        case_by_id[cid] = c
    try:
        drops = []
        totals: dict[str, int] = {}
        best: dict[str, int] = {}
        worst: dict[str, int] = {}
        for player_row in battle["players"]:
            player = player_row["player"]
            totals[player] = 0
            best[player] = 0
            worst[player] = 10**12
            for round_i, cid in enumerate(order, start=1):
                round_case = case_by_id[cid]
                assert round_case is not None
                prize = roll(round_case)  # type: ignore[arg-type]
                public = prize.as_public()
                totals[player] += prize.coin
                best[player] = max(best[player], prize.coin)
                worst[player] = min(worst[player], prize.coin)
                drops.append(
                    {
                        "player": player,
                        "round": round_i,
                        "id": public["id"],
                        "name": public["name"],
                        "rarity": public["rarity"],
                        "value": public["coin"],
                        "image": public["image"],
                        "color": public["color"],
                        "case_id": cid,
                    }
                )
                store.record_drop(player, prize, cid, is_bot=bool(player_row["is_bot"]))
        crazy = battle["mode"] == "CRAZY"
        ranked = sorted(
            battle["players"],
            key=lambda row: (
                totals[row["player"]] if crazy else -totals[row["player"]],
                worst[row["player"]] if crazy else -best[row["player"]],
                row["slot"],
            ),
        )
        winner = ranked[0]["player"]
        store.save_battle_result(battle_id, totals, drops, winner)
        for drop in drops:
            store.add_inventory(winner, _drop_as_item(drop), "battle", drop.get("case_id") or battle["case_id"])
        return store.get_battle(battle_id) or {}
    except Exception:
        # Roll / ghi DB lỗi giữa chừng: trả về WAITING để bấm lại được,
        # tiền ghế giữ nguyên (không mất, không thưởng 2 lần).
        store.reset_battle_to_waiting(battle_id)
        raise


class _DropItem:
    def __init__(self, drop: dict):
        self.id = drop["id"]
        self.name = drop["name"]
        self.rarity = drop["rarity"]
        self.coin = drop["value"]
        self.image = drop["image"]
        self.color = drop["color"]

    def as_public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "rarity": self.rarity,
            "weight": 1,
            "coin": self.coin,
            "image": self.image,
            "color": self.color,
        }


def _drop_as_item(drop: dict) -> _DropItem:
    return _DropItem(drop)


def bonus_preview(player: str) -> int:
    """Kiểm tra đủ điều kiện và roll giải bonus, KHÔNG ghi nhận lần nhận.

    Tách khỏi `claim_bonus` để tầng web có thể cộng Coin in-game trước rồi mới
    commit. Nếu không, lệnh console fail sẽ mất lượt bonus của người chơi.
    """
    last = store.last_bonus(player)
    elapsed = store.now() - last
    if last and elapsed < 24 * 3600:
        remain = 24 * 3600 - elapsed
        raise GameError(f"Bonus còn {remain // 3600} giờ {(remain % 3600) // 60} phút.")
    slices, weights = zip(*BONUS_SLICES)
    return int(random.choices(list(slices), weights=list(weights), k=1)[0])


def claim_bonus(player: str, prize: int | None = None) -> dict:
    last = store.last_bonus(player)
    elapsed = store.now() - last
    if last and elapsed < 24 * 3600:
        remain = 24 * 3600 - elapsed
        raise GameError(f"Bonus còn {remain // 3600} giờ {(remain % 3600) // 60} phút.")
    if prize is None:
        slices, weights = zip(*BONUS_SLICES)
        prize = int(random.choices(list(slices), weights=list(weights), k=1)[0])
    store.set_bonus(player)
    store.credit(player, prize, "bonus", "vòng bonus ngày")
    return {"amount": prize, "balance": store.get_balance(player), "slices": list(BONUS_SLICES)}


def site_stats_bar() -> dict:
    cases = load_cases()
    items = market_listings()
    data = store.stats()
    return {
        "cases": len(cases),
        "item_count": len(items),
        "pulls": data["pulls"],
        "battles": data["battles"],
        "upgrades": data.get("upgrades", 0),
        "users": data.get("users", 0),
        "online": len(store.BOT_NAMES),
        "online_bots": len(store.BOT_NAMES),
        "rtp": "90%",
    }
