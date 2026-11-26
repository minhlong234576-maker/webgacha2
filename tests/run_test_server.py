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

# `gacha.json` cung vay danh sach san pham. Server test KHONG bao gio ghi vao
# file that — dung DANH MUC MAU (tests/fixture_catalog.py) trong thu muc tam.
# Cac route admin san pham (`/admin/products`) se ghi vao ban sao nay.
#
# Dung mau thay vi ban sao cua file that: admin co the xoa het san pham / ca
# ruong, nen file that co the rong va test se khong co gi de mo ruong.
if "GACHA_FILE" not in os.environ:
    _cfg_tmp = Path(tempfile.mkdtemp(prefix="jvcfg_"))
    os.environ["GACHA_FILE"] = str(_cfg_tmp / "gacha.json")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fixture_catalog

    fixture_catalog.write_fixture(Path(os.environ["GACHA_FILE"]))
    # Ghi duong dan ra file de test process tu tim thay (khong do duong dan
    # qua bien moi truong).
    (_cfg_tmp / "gacha_file_path.txt").write_text(
        os.environ["GACHA_FILE"], encoding="utf-8"
    )

import uvicorn  # noqa: E402

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8101
uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")
