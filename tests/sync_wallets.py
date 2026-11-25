"""Đồng bộ ví web với Coin in-game cho toàn bộ người chơi thật."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import os, sys, sqlite3
os.environ['GACHA_DRY_RUN'] = 'false'
sys.path.insert(0, str(ROOT))

import httpx
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app import store

base = os.getenv('PIKA_BASE_URL').rstrip('/')
key = os.getenv('PIKA_API_KEY')
uuid = os.getenv('PIKA_SERVER_UUID')
H = {'Authorization': f'Bearer {key}', 'Accept': 'application/json', 'Content-Type': 'application/json'}


def sql(db, q, rows=500):
    r = httpx.post(f'{base}/api/client/servers/{uuid}/files/sqlite-query', headers=H, json={
        'file': db, 'query': q, 'rows': rows, 'read_only': True}, timeout=40)
    res = (r.json().get('results') or [{}])[0]
    cols = [c['name'] for c in (res.get('columns') or [])]
    return [{c: (v.get('value') if v else None) for c, v in zip(cols, row)}
            for row in (res.get('rows') or [])]


authme = sql('/plugins/AuthMe/authme.db', 'select username, realname from authme')
eco = sql('/plugins/ExcellentEconomy/data.db', 'select name, money from excellenteconomy_users')
eco_by = {r['name'].lower(): float(r['money'] or 0) for r in eco}

synced = 0
for u in authme:
    real = u['realname']
    if real.lower() in eco_by:
        store.set_wallet(real, round(eco_by[real.lower()]))
        synced += 1

print(f'synced {synced}/{len(authme)} wallets')

con = sqlite3.connect(store.DB_PATH)
con.row_factory = sqlite3.Row
rows = con.execute('select player, balance from wallets order by balance desc').fetchall()
print(f'total wallets: {len(rows)} | total balance: {sum(r["balance"] for r in rows):,}')
for r in rows[:10]:
    print(f"  {r['player']:22} {r['balance']:>12,}")

# so khớp với server
server_total = sum(float(r['money'] or 0) for r in eco
                   if r['name'].lower() in {u['realname'].lower() for u in authme})
web_total = sum(r['balance'] for r in rows)
print(f'\nserver total (41 users) = {server_total:,.0f}')
print(f'web    total             = {web_total:,}')
print('MATCH' if abs(server_total - web_total) < 50 else 'MISMATCH')
