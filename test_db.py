import sqlite3
conn = sqlite3.connect("data/gacha.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Check cases
c.execute("SELECT COUNT(*) as cnt FROM cases")
cases_count = c.fetchone()["cnt"]
print(f"Cases: {cases_count}")

# Check items in first case
c.execute("SELECT id, name FROM cases LIMIT 1")
case = c.fetchone()
if case:
    c.execute(f"SELECT COUNT(*) as cnt FROM items WHERE case_id = ?", (case["id"],))
    items_count = c.fetchone()["cnt"]
    print(f"Items in '{case['name']}': {items_count}")
    
    # Show first 3 items
    c.execute(f"SELECT id, name, coin FROM items WHERE case_id = ? LIMIT 3", (case["id"],))
    for row in c.fetchall():
        print(f"  - {row['id']}: {row['name']} ({row['coin']} Coin)")
