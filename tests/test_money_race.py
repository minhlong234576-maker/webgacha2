"""Kiem chung race condition tren TIEN THAT (console PikaMC).

`eco take` tren server clamp ve 0 khi khong du tien (khong bao loi). Neu 2
request cung chay, ca hai deu co the doc duoc so du cu va ca hai deu chay
`eco take` -> mat tien nguoi choi.

Kiem tra: 5 request dong thoi, moi request 2000 Coin, so du 5000.
Ket qua dung: chi 2 request thanh cong (2 x 2000 = 4000), 3 request that bai.
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio
import os
import sys

os.environ["GACHA_DRY_RUN"] = "false"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.errors import MoneyError  # noqa: E402
from app.pika import eco_give, eco_take, economy_balance  # noqa: E402

ME = "Trez1724"
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (f"   {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


async def main():
    before = await economy_balance(ME)
    print(f"  so du ban dau: {before:,.0f}")
    try:
        # Nap 5.000. 5 request x 2.000 = 10.000 > 5.000 -> chi 2 duoc thanh
        # cong (4.000), 3 phai that bai. Neu co race, ca 5 deu doc duoc so du
        # cu 5.000 va deu thay du tien -> mat 5.000.
        await eco_give(ME, 5_000)
        await asyncio.sleep(1.5)
        start = await economy_balance(ME)
        print(f"  nap 5.000 -> {start:,.0f}")

        print()
        print("=== 5 request dong thoi, moi request 2.000 Coin (chi du cho 2) ===")
        results = await asyncio.gather(
            *[eco_take(ME, 2000) for _ in range(5)],
            return_exceptions=True,
        )
        ok = sum(1 for r in results if not isinstance(r, Exception))
        failed = [type(r).__name__ for r in results if isinstance(r, Exception)]
        after = await economy_balance(ME)

        print(f"  thanh cong: {ok}/5 | that bai: {failed}")
        print(f"  so du sau: {after:,.0f} (tru {start - after:,.0f})")

        check("khong tru qua so du (con tien)", after >= 0, f"{after}")
        # So du thuc te cua nguoi choi co the lon hon 5.000 (test chay tren
        # tai khoan that), nen khong the gan cung 'chi 2 request duoc tru'.
        # Bat buoc phai la: so du bi tru DUNG BANG so request thanh cong x 2.000
        # -> khong duoc tru thua (khong mat tien ngoai y muon).
        deducted = int(round(start - after))
        check("tru dung so tien theo so request thanh cong",
              deducted == ok * 2000,
              f"tru {deducted:,} | ok={ok} (mong doi {ok * 2000:,})")
        check("so du cuoi >= 1.000 (khong mat tien)",
              after >= 1000, f"{after} (tru {start - after})")
        check("request that bai phai la MoneyError",
              all(f == "MoneyError" for f in failed) if failed else True,
              str(failed))
    finally:
        # Tra lai so du ban dau
        now = await economy_balance(ME)
        delta = int(round(now - before))
        if delta > 0:
            await eco_take(ME, delta)
            await asyncio.sleep(1.5)
        print()
        print(f"  so du sau khi don dep: {await economy_balance(ME):,.0f} "
              f"(ban dau {before:,.0f})")

    print()
    if FAILS:
        print(f"!!! {len(FAILS)} FAIL: {FAILS}")
        sys.exit(1)
    print(">>> MONEY RACE TEST PASS")


asyncio.run(main())
