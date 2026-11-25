"""Chay server test tren BAN SAO tam cua data/gacha.db (khong mutate DB that).

Moi server test deu tro toi mot ban sao tam cua `data/gacha.db` nen khong
bao gio chan vao du lieu nguoi choi that (jellyvale-gacha-dev §4).

Usage:
    python tests/run_test_server.py <port> [--live]

    --live  : chay voi GACHA_DRY_RUN=false (dung cho test realtime / tien that,
              vi du port 8099).

Vi du:
    python tests/run_test_server.py 8101            # dry-run
    python tests/run_test_server.py 8099 --live     # tien that
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LIVE = "--live" in sys.argv
os.environ["GACHA_DRY_RUN"] = "false" if LIVE else "true"

# DB test dung DUNG mot file co dinh de server va test process tro ve cung
# mot noi dung (UI test can them mon cho QA_Tester_01 truoc khi chay).
# File nay KHONG bao gio la du lieu that — luon la ban sao tam.
#
# `run_all.py` chuan bi san file nay roi truyen `GACHA_DB_PATH` qua env.
# Khi chay doc lap (khong co env) thi tu tao ban sao tam trong thu muc tam.
if "GACHA_DB_PATH" not in os.environ:
    tmp_dir = Path(tempfile.mkdtemp(prefix="jvsrv_"))
    os.environ["GACHA_DB_PATH"] = str(tmp_dir / "gacha.db")
    shutil.copy(ROOT / "data" / "gacha.db", tmp_dir / "gacha.db")

import uvicorn  # noqa: E402

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8101
uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")
