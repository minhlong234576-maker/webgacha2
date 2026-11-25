"""Kiem tra quyen admin realtime doc tu OP tren server PikaMC.

- Doc `ops.json` qua API PikaMC.
- Moi OP tren server phai co quyen admin tren web.
- Nguoi khong phai OP phai bi chan.
- Cache TTL va fallback khi API loi.
"""
import asyncio
import os
import sys

sys.path.insert(0, r"c:\code\web\webgacha-main")
from dotenv import load_dotenv  # noqa: E402

load_dotenv(r"c:\code\web\webgacha-main\.env")

from app import admins  # noqa: E402
from app.pika import server_ops  # noqa: E402

FAILS = []
PASSES = 0


def check(name, cond, detail=""):
    global PASSES
    if cond:
        PASSES += 1
        print(f"  PASS {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"   {detail}" if detail else ""))


async def main():
    print("=== 1. DOC OPS.JSON TU SERVER ===")
    ops = await server_ops()
    check("doc duoc danh sach OP", len(ops) > 0, f"{len(ops)} OP")
    names = {op["name"].lower() for op in ops}
    server_ops_names_list = sorted(names)
    print(f"  OP: {sorted(names)}")

    print()
    print("=== 2. MOI OP CO QUYEN ADMIN ===")
    for op in ops:
        ok = await admins.is_admin(op["name"])
        check(f"OP '{op['name']}' la admin", ok)

    print()
    print("=== 3. NGUOI KHONG PHAI OP BI CHAN ===")
    for fake in ["nguoi_thuong_xyz", "Trez1725", "admin_gi_ma", ""]:
        ok = not await admins.is_admin(fake)
        check(f"'{fake}' khong phai admin", ok)

    print()
    print("=== 4. PHAI SO KHOP TU TEN DANG NHAP (khong phan biet HOA/THUONG) ===")
    for op in ops:
        ok = await admins.is_admin(op["name"].upper())
        check(f"'{op['name'].upper()}' van la admin", ok)

    print()
    print("=== 5. ADMIN_LIST GOP CA OP VA ENV ===")
    lst = await admins.admin_list()
    check("admin_list khong rong", len(lst) > 0, f"{len(lst)}")
    check("co truong 'source' cho moi dong",
          all("source" in row and "name" in row for row in lst))
    env_only = {name.lower() for name in os.getenv("ADMIN_USERS", "").split(",") if name.strip()}
    server_ops_names = names
    for row in lst:
        expected = "server-op" if row["name"] in server_ops_names else "env"
        check(f"'{row['name']}' nguon = {expected}", row["source"] == expected,
              f"thuc te {row['source']}")
    print(f"  ENV: {sorted(env_only)} | server: {sorted(server_ops_names)}")

    print()
    print("=== 6. CACHE: LAN 2 KHONG GOI LAI SERVER ===")
    calls = {"n": 0}
    orig = admins.server_op_names

    async def counted():
        calls["n"] += 1
        return await orig()

    admins.server_op_names = counted
    try:
        await admins.refresh()
        await admins.op_names()
        await admins.op_names()
        check("cache hoat dong (chi goi server 1 lan)", calls["n"] == 1,
              f"{calls['n']} lan")
    finally:
        admins.server_op_names = orig

    print()
    print("=== 7. FALLBACK KHI API LOI (khong khoa admin) ===")
    from fastapi import HTTPException

    async def boom():
        raise HTTPException(status_code=503, detail="PikaMC down")

    admins.server_op_names = boom
    try:
        # Cache cu van con nen ket qua phai dung
        got = await admins.op_names()
        check("API loi -> dung cache cu", len(got) > 0, f"{len(got)}")
    finally:
        admins.server_op_names = orig

    print()
    print("=== 8. ADMIN KHAI BAO TRONG .env (khong bat buoc) ===")
    # Mac dinh ADMIN_USERS rong — quyen admin lay tu OP server.
    # Neu co khai bao them trong .env thi ho cung la admin.
    local = admins.local_admin_users()
    print(f"  ADMIN_USERS tu .env: {sorted(local) if local else '(rong)'}")
    for name in local:
        check(f"'{name}' (tu .env) la admin", await admins.is_admin(name))
    if not local:
        check("khong can ADMIN_USERS trong .env — OP server la du",
              await admins.is_admin(server_ops_names_list[0]))

    print()
    print("=== 9. TAT CA OP TREN SERVER DEU LA ADMIN (khong thieu) ===")
    for op in ops:
        check(f"'{op['name']}' co quyen admin",
              await admins.is_admin(op["name"]))

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> ADMIN REALTIME TEST PASS")


asyncio.run(main())
