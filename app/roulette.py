from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from . import bank, store
from .errors import MoneyError
from .gacha import is_dry_run

log = logging.getLogger("jellyvale.roulette")

# Cấu trúc 15 ô chuẩn CSGOEmpire:
# 7 ô Village (Làng) - Hệ số x2 (Tương đương Terrorist/T-coin vàng)
# 7 ô Pillager (Kẻ cướp) - Hệ số x2 (Tương đương Counter-Terrorist/CT-coin đen)
# 1 ô Steve (Đặc biệt) - Hệ số x14 (Tương đương Empire Bonus Dice xanh)
#
# Thứ tự 15 slot được xếp so le hoàn hảo:
# [Steve, Pillager, Village, Pillager, Village, Pillager, Village, Pillager, Village, Pillager, Village, Pillager, Village, Pillager, Village]
# Trong đó Steve ở index 0, sau đó xen kẽ Pillager và Village.

SIDE_VILLAGE = "village"
SIDE_PILLAGER = "pillager"
SIDE_STEVE = "steve"

MULTIPLIERS = {
    SIDE_VILLAGE: 2,
    SIDE_PILLAGER: 2,
    SIDE_STEVE: 14,
}

SIDE_META = {
    SIDE_VILLAGE: {
        "id": "village",
        "name": "Ngôi Làng",
        "multiplier": 2,
        "color": "#10b981",
        "bg": "rgba(16, 185, 129, 0.15)",
        "icon": "/static/items/coin_village.svg",
    },
    SIDE_PILLAGER: {
        "id": "pillager",
        "name": "Pillager",
        "multiplier": 2,
        "color": "#ef4444",
        "bg": "rgba(239, 68, 68, 0.15)",
        "icon": "/static/items/coin_pillager.svg",
    },
    SIDE_STEVE: {
        "id": "steve",
        "name": "Steve Đặc Biệt",
        "multiplier": 14,
        "color": "#06b6d4",
        "bg": "rgba(6, 182, 212, 0.2)",
        "icon": "/static/items/coin_steve.svg",
    },
}

# 15 vị trí bánh xe (0-14):
# Index 0: Steve (14x)
# Index 1, 3, 5, 7, 9, 11, 13: Pillager (2x) (7 ô)
# Index 2, 4, 6, 8, 10, 12, 14: Village (2x) (7 ô)
WHEEL_SLOTS = [
    {"slot": 0, "side": SIDE_STEVE, **SIDE_META[SIDE_STEVE]},
    {"slot": 1, "side": SIDE_PILLAGER, **SIDE_META[SIDE_PILLAGER]},
    {"slot": 2, "side": SIDE_VILLAGE, **SIDE_META[SIDE_VILLAGE]},
    {"slot": 3, "side": SIDE_PILLAGER, **SIDE_META[SIDE_PILLAGER]},
    {"slot": 4, "side": SIDE_VILLAGE, **SIDE_META[SIDE_VILLAGE]},
    {"slot": 5, "side": SIDE_PILLAGER, **SIDE_META[SIDE_PILLAGER]},
    {"slot": 6, "side": SIDE_VILLAGE, **SIDE_META[SIDE_VILLAGE]},
    {"slot": 7, "side": SIDE_PILLAGER, **SIDE_META[SIDE_PILLAGER]},
    {"slot": 8, "side": SIDE_VILLAGE, **SIDE_META[SIDE_VILLAGE]},
    {"slot": 9, "side": SIDE_PILLAGER, **SIDE_META[SIDE_PILLAGER]},
    {"slot": 10, "side": SIDE_VILLAGE, **SIDE_META[SIDE_VILLAGE]},
    {"slot": 11, "side": SIDE_PILLAGER, **SIDE_META[SIDE_PILLAGER]},
    {"slot": 12, "side": SIDE_VILLAGE, **SIDE_META[SIDE_VILLAGE]},
    {"slot": 13, "side": SIDE_PILLAGER, **SIDE_META[SIDE_PILLAGER]},
    {"slot": 14, "side": SIDE_VILLAGE, **SIDE_META[SIDE_VILLAGE]},
]

STATUS_BETTING = "BETTING"
STATUS_ROLLING = "ROLLING"
STATUS_SETTLED = "SETTLED"

BETTING_SECONDS = 50.0  # 50s nhận cược + 6s quay + 4s trả thưởng = tròn chu kỳ 60s
ROLLING_SECONDS = 6.0   # 6s hiệu ứng dải roulette xoay trượt
SETTLED_SECONDS = 4.0   # 4s hiển thị kết quả và thưởng

class RouletteManager:
    def __init__(self):
        self.round_id = 1
        self.status = STATUS_BETTING
        self.phase_start_time = time.time()
        self.phase_end_time = self.phase_start_time + BETTING_SECONDS
        
        # Bets hiện tại: { "village": [...], "steve": [...], "pillager": [...] }
        self.bets: dict[str, list[dict]] = {
            SIDE_VILLAGE: [],
            SIDE_STEVE: [],
            SIDE_PILLAGER: [],
        }
        
        # Outcome của vòng quay hiện tại
        self.winning_slot = 0
        self.winning_side = SIDE_STEVE
        self.server_seed = hashlib.sha256(f"seed_{time.time()}".encode()).hexdigest()
        self.hash_commit = hashlib.sha256(self.server_seed.encode()).hexdigest()
        
        # Lịch sử 100 vòng gần nhất
        self.history: list[dict] = []
        self._init_mock_history()
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def _init_mock_history(self):
        """Khởi tạo một số kết quả lịch sử ban đầu cho đẹp mắt."""
        for i in range(25):
            slot_idx = random.choices(
                [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
                weights=[1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
                k=1
            )[0]
            slot_info = WHEEL_SLOTS[slot_idx]
            self.history.append({
                "round_id": i + 1,
                "slot": slot_idx,
                "side": slot_info["side"],
                "color": slot_info["color"],
                "icon": slot_info["icon"],
                "multiplier": slot_info["multiplier"],
            })
        self.round_id = 26

    def start_loop(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        log.info("Khởi động vòng lặp Roulette CSGOEmpire...")
        while True:
            try:
                # 1. PHA CƯỢC (BETTING)
                async with self._lock:
                    self.status = STATUS_BETTING
                    self.phase_start_time = time.time()
                    self.phase_end_time = self.phase_start_time + BETTING_SECONDS
                    self.bets = {SIDE_VILLAGE: [], SIDE_STEVE: [], SIDE_PILLAGER: []}
                    self.server_seed = hashlib.sha256(f"seed_{self.round_id}_{time.time()}".encode()).hexdigest()
                    self.hash_commit = hashlib.sha256(self.server_seed.encode()).hexdigest()
                    # Quyết định trước slot thắng bằng xác suất chuẩn
                    self.winning_slot = random.randint(0, 14)
                    self.winning_side = WHEEL_SLOTS[self.winning_slot]["side"]

                # Trong lúc đếm ngược, Bot ngẫu nhiên đặt cược
                await self._bot_betting_phase()

                # 2. PHA QUAY (ROLLING)
                async with self._lock:
                    self.status = STATUS_ROLLING
                    self.phase_start_time = time.time()
                    self.phase_end_time = self.phase_start_time + ROLLING_SECONDS
                
                await asyncio.sleep(ROLLING_SECONDS)

                # 3. PHA KẾT TOÁN (SETTLED)
                async with self._lock:
                    self.status = STATUS_SETTLED
                    self.phase_start_time = time.time()
                    self.phase_end_time = self.phase_start_time + SETTLED_SECONDS
                    self._settle_payouts()
                    # Lưu vào lịch sử
                    win_info = WHEEL_SLOTS[self.winning_slot]
                    self.history.append({
                        "round_id": self.round_id,
                        "slot": self.winning_slot,
                        "side": self.winning_side,
                        "color": win_info["color"],
                        "icon": win_info["icon"],
                        "multiplier": win_info["multiplier"],
                    })
                    if len(self.history) > 100:
                        self.history.pop(0)
                    self.round_id += 1

                # Cộng Coin in-game thật cho người chơi thắng (ngoài khóa để
                # không chặn vòng quay trong lúc chờ console).
                await self.payout_real_bets()

                await asyncio.sleep(SETTLED_SECONDS)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception(f"Lỗi trong roulette loop: {e}")
                await asyncio.sleep(2)

    async def _bot_betting_phase(self):
        """Mô phỏng các bot JellyVale vào đặt cược sôi động trong 15s."""
        total_steps = 15
        step_duration = BETTING_SECONDS / total_steps
        bot_pool = list(store.BOT_NAMES)

        for step in range(total_steps):
            await asyncio.sleep(step_duration)
            if self.status != STATUS_BETTING:
                break

            # 60% cơ hội có 1-2 bot cược ở mỗi nhịp
            if random.random() < 0.65:
                bot_name = random.choice(bot_pool)
                # Đảm bảo bot có tiền
                store.ensure_wallet(bot_name, seed=500_000, is_bot=True)
                
                # Chọn phe (Village 46%, Pillager 46%, Steve 8%)
                target_side = random.choices(
                    [SIDE_VILLAGE, SIDE_PILLAGER, SIDE_STEVE],
                    weights=[46, 46, 8],
                    k=1
                )[0]
                
                # Số tiền cược ngẫu nhiên phù hợp
                bet_amounts = [1000, 2000, 5000, 10000, 20000, 50000]
                bet_amount = random.choice(bet_amounts)
                
                async with self._lock:
                    try:
                        self.place_bet(bot_name, target_side, bet_amount, is_bot=True)
                    except Exception:
                        pass

    def place_bet(self, player: str, side: str, amount: int, is_bot: bool = False) -> dict:
        if self.status != STATUS_BETTING:
            raise ValueError("Đã hết thời gian đặt cược, hãy chờ vòng tiếp theo!")
        if side not in (SIDE_VILLAGE, SIDE_PILLAGER, SIDE_STEVE):
            raise ValueError("Cửa cược không hợp lệ.")
        if amount < 100:
            raise ValueError("Mức cược tối thiểu là 100 Coin.")
        if amount > 10_000_000:
            raise ValueError("Mức cược tối đa là 10.000.000 Coin.")

        # Trừ tiền
        balance = store.get_balance(player)
        if balance < amount:
            raise ValueError(f"Không đủ Coin. Bạn chỉ còn {balance:,} Coin.")
        
        store.debit(player, amount, "roulette_bet", f"Cược Roulette {side}")

        bet_entry = {
            "player": player,
            "side": side,
            "amount": amount,
            "is_bot": is_bot,
            "timestamp": time.time(),
        }
        self.bets[side].append(bet_entry)
        return {
            "player": player,
            "side": side,
            "amount": amount,
            "balance": store.get_balance(player),
        }

    def _settle_payouts(self):
        """Trả thưởng cho những người cược trúng cửa thắng.

        Chỉ ghi sổ ví web. Việc cộng Coin in-game thật do `app.bank` đảm nhiệm
        (xem `payout_real_bets`) vì hàm này chạy đồng bộ trong vòng quay.
        """
        winning_bets = self.bets.get(self.winning_side, [])
        multiplier = MULTIPLIERS[self.winning_side]

        for b in winning_bets:
            payout = b["amount"] * multiplier
            store.credit(b["player"], payout, "roulette_win", f"Thắng Roulette x{multiplier}")

    async def payout_real_bets(self) -> None:
        """Cộng Coin in-game cho người chơi thật vừa thắng roulette.

        Bot không có ví in-game nên bị bỏ qua. Lỗi cộng tiền được nuốt và ghi log
        vì không thể hoàn tác vòng quay đã quay; người chơi có thể báo admin.
        """
        if is_dry_run():
            return
        winning_bets = self.bets.get(self.winning_side, [])
        multiplier = MULTIPLIERS[self.winning_side]
        for b in winning_bets:
            if b.get("is_bot"):
                continue
            payout = int(b["amount"] * multiplier)
            if payout <= 0:
                continue
            try:
                await bank.give(b["player"], payout)
            except (MoneyError, HTTPException) as exc:
                log.warning("Roulette payout lỗi cho %s: %s", b["player"], exc)

    def get_state(self, current_player: str | None = None) -> dict[str, Any]:
        """Trả về toàn bộ trạng thái hiện tại phục vụ client polling hoặc render."""
        now = time.time()
        time_left = max(0.0, self.phase_end_time - now)

        # Tính tổng cược từng bên
        totals = {}
        for s in (SIDE_VILLAGE, SIDE_STEVE, SIDE_PILLAGER):
            side_bets = self.bets.get(s, [])
            totals[s] = {
                "count": len(side_bets),
                "total_amount": sum(b["amount"] for b in side_bets),
                "bets": side_bets[-20:],  # 20 cược mới nhất của mỗi bên
            }

        my_bets = []
        if current_player:
            for s in (SIDE_VILLAGE, SIDE_STEVE, SIDE_PILLAGER):
                for b in self.bets.get(s, []):
                    if b["player"].lower() == current_player.lower():
                        my_bets.append(b)

        return {
            "round_id": self.round_id,
            "status": self.status,
            "time_left": round(time_left, 1),
            "total_phase_time": (
                BETTING_SECONDS if self.status == STATUS_BETTING
                else ROLLING_SECONDS if self.status == STATUS_ROLLING
                else SETTLED_SECONDS
            ),
            "hash_commit": self.hash_commit,
            "winning_slot": self.winning_slot if self.status in (STATUS_ROLLING, STATUS_SETTLED) else None,
            "winning_side": self.winning_side if self.status in (STATUS_ROLLING, STATUS_SETTLED) else None,
            "wheel_slots": WHEEL_SLOTS,
            "totals": totals,
            "my_bets": my_bets,
            "recent_history": self.history[-15:],
            "server_time": now,
        }

# Global singleton
roulette_manager = RouletteManager()
