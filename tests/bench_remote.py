"""So sanh: query truc tiep vs dung client chung + cache."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio, os, sys, time
os.environ['GACHA_DRY_RUN'] = 'false'
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app import pika

async def main():
    print('=== 6 lan economy_balances() lien tie (client chung + cache 5s) ===')
    times = []
    for i in range(6):
        t0 = time.perf_counter()
        bal = await pika.economy_balances()
        ms = (time.perf_counter() - t0) * 1000
        times.append(ms)
        print(f'  lan {i+1}: {ms:.0f} ms  ({len(bal)} nguoi)')
    print(f'  tong: {sum(times):.0f} ms | TB: {sum(times)/len(times):.0f} ms')

    print()
    print('=== 6 lan economy_balance() lien tie (1 nguoi, moi lan 1 query) ===')
    times2 = []
    for i in range(6):
        t0 = time.perf_counter()
        await pika.economy_balance('Trez1724')
        ms = (time.perf_counter() - t0) * 1000
        times2.append(ms)
        print(f'  lan {i+1}: {ms:.0f} ms')
    print(f'  tong: {sum(times2):.0f} ms | TB: {sum(times2)/len(times2):.0f} ms')

    await pika.close_client()

asyncio.run(main())
