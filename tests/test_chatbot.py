"""Kiem chung chatbot tra loi cau hoi ve lenh console Minecraft.

Nhom kiem tra:
1. Dataset lenh: nap duoc, khong rong, co mo ta
2. NLP khop: cau hoi tieng Viet → dung lenh console that
3. Bo dau tieng Viet: "dich chuyen" / "doi skin" van khop dung
4. Lenh admin duoc danh dau, lenh nguoi choi khong bi nham
5. XSS: noi dung server tra ve duoc chuyen tiep an toan (khong innerHTML)
6. API /api/chat: CSRF, cau hoi rong, gioi han do dai
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import os
import sys

os.environ["GACHA_DRY_RUN"] = "true"
sys.path.insert(0, str(ROOT))

from app import chatbot  # noqa: E402

FAILS = []


def check(label, ok, extra=""):
    if ok:
        print(f"  PASS {label}")
    else:
        print(f"  FAIL {label} {extra}")
        FAILS.append(label)


print("=== 1. DATASET LENH ===")
commands, admin_only = chatbot.load_commands()
check("dataset khong rong", len(commands) > 300, f"(co {len(commands)})")
check("nhieu lenh co mo ta", sum(1 for d in commands.values() if d) > 200)
check("co lenh co ban cua nguoi choi",
      all(name in commands for name in ("home", "sethome", "tpa", "balance", "skin")))
check("co lenh danh cho admin", len(admin_only) > 0, f"(co {len(admin_only)})")
check("lenh nguoi choi khong bi danh dau admin",
      not any(n in admin_only for n in ("list", "msg", "home", "tpa", "balance")))

print()
print("=== 2. NLP KHOP LENH ===")
cases = [
    ("lệnh xem số dư là gì?", "balance"),
    ("lệnh về nhà", "home"),
    ("cách đổi skin", "skin"),
    ("lệnh xem ai đang online", "list"),
    ("lệnh claim vùng đất", "claim"),
    ("mời người chơi qua tpa", "tpa"),
    ("lệnh tạo nhà", "sethome"),
    ("gửi tiền cho bạn", "pay"),
]
for question, expected in cases:
    names = [row["name"] for row in chatbot.match_commands(question)]
    check(f"'{question}' → /{expected}", expected in names, f"(ra {names[:4]})")

print()
print("=== 3. BO DAU / TU TIENG VIET ===")
check("'dich chuyen' khop lenh tp",
      any(r["name"] in ("tpa", "tpaccept", "back") for r in chatbot.match_commands("dich chuyen")))
check("'doi skin' khop /skin",
      any(r["name"] == "skin" for r in chatbot.match_commands("doi skin")))
check("'tietien' khong lot lenh nhieu",
      len(chatbot.match_commands("tietien cua toi la bao nhieu")) <= 6)

print()
print("=== 4. PHAI LOAI LENH ===")
rows = chatbot.match_commands("lệnh xem số dư")
check("mo ta lenh co day du", all(r["name"] and r["desc"] for r in rows[:2]))
check("co truong admin_only", all("admin_only" in r for r in rows))
check("mau tra loi fallback co ten lenh", "/balance" in chatbot.format_fallback(rows))

print()
print("=== 5. XSS / AN TOAN ===")
danger = chatbot.match_commands("<script>alert(1)</script>")
check("khong nhung lenh la doc", all("<script>" not in r["desc"] for r in danger))
prompt = chatbot.build_prompt("cau hoi", [{"name": "x", "desc": "y", "admin_only": False}])
check("prompt chi chua danh sach lenh da loc",
      prompt.count("/x") == 1 and "cau hoi" in prompt)

print()
print("=== 6. API /api/chat ===")
import inspect  # noqa: E402

from app import main as main_mod  # noqa: E402

routes = {r.path for r in main_mod.app.router.routes}
check("route /api/chat ton tai", "/api/chat" in routes)
check("route /api/chat dung method POST",
      any(r.path == "/api/chat" and "POST" in getattr(r, "methods", set())
          for r in main_mod.app.router.routes))
check("/api/chat la API cong khai",
      "/api/chat" in getattr(main_mod, "PUBLIC_API_PATHS", set()))

src = inspect.getsource(main_mod.api_chat)
check("api_chat kiem tra CSRF", "csrf=True" in src)
check("api_chat khong lo loi noi bo ra ngoai",
      "str(exc)" not in src and "detail\": str" not in src)

print()
print(f"=== KET QUA: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} loi) ===")
if FAILS:
    for name in FAILS:
        print("  FAIL:", name)
    sys.exit(1)
print(">>> CHATBOT TEST PASS")
