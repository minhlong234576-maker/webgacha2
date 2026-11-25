"""Chay TOAN BO bo test va tom tat ket qua.

Tu dong bat/tat cac server test ( tren ban sao tam cua data/gacha.db, KHONG
cham vao du lieu that) truoc khi chay tung suite.

Usage: python tests/run_all.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent

# DB test dung chung cho server + test client (UI test them mon cho
# QA_Tester_01 truoc khi chay -> can cung mot file DB).
TEST_DIR = Path(tempfile.mkdtemp(prefix="jvtestdb_"))
TEST_DB = TEST_DIR / "gacha.db"

# (ten, file, can server chay khong, port can dung)
SUITES = [
    ("Logic + bao mat he thong", "test_system.py", False, None),
    ("Bao mat + regression (cookie 500, Nexo, input)", "test_security_and_fixes.py", False, None),
    ("Duong dan test (khong hardcode)", "test_paths_static.py", False, None),
    ("Battle - chi winner nhan do", "test_battle_winner_only.py", False, None),
    ("Battle - chay song song (race)", "test_concurrent_battles.py", False, None),
    ("Upgrade - 2 mon len 1 mon", "test_upgrade_two_to_one.py", False, None),
    ("Tat ca chuc nang web", "test_all_features.py", True, 8101),
    ("Bao mat HTTP (CSRF/session/quyen)", "test_http_security.py", True, 8098),
    ("Tien that - don gian", "test_money.py", False, None),
    ("Tien that - end to end", "test_e2e_money.py", False, None),
    ("Tien that - race condition", "test_money_race.py", False, None),
    ("Roulette", "test_roulette.py", False, None),
    ("Realtime - kho", "test_realtime_balance.py", False, None),
    ("Realtime - thuc", "test_realtime_live.py", True, 8099),
    ("Realtime - UI", "test_realtime_ui.py", True, 8099),
    ("UI - menu", "test_ui_menu.py", True, 8101),
    ("UI - nang cap 2 mon len 1 mon", "test_upgrade_ui.py", True, 8101),
    ("Quyen admin realtime (doc OP tu PikaMC)", "test_admin_realtime.py", False, None),
    ("Quyen admin realtime - HTTP", "test_admin_http.py", True, 8101),
    ("Dang nhap thuc", "test_login_browser.py", True, 8080),
]

# Port -> (dry_run, arg) cho server test.
# 8080 chay o che do THAT (GACHA_DRY_RUN=false) vi test dang nhap that can
# AuthMe/PikaMC; 8099 cung vay cho test realtime.
SERVERS = {
    8080: ("false", ["--live"]),
    8098: ("true", []),
    8099: ("false", ["--live"]),
    8101: ("true", []),
}


def prepare_db() -> None:
    # Moi lan chay dung thu muc rieng: file DB cu con process server cu bi khoa
    # tren Windows (WinError 32) -> khong xoa duoc, va se lam DB "malformed"
    # khi hai process cung ghi vao cung mot file.
    shutil.copy(ROOT / "data" / "gacha.db", TEST_DB)


def kill_port(port: int) -> None:
    """Ket thuc moi process dang giu port (server test cu con lai tu lan chay truoc).

    Neu con server cu, `wait_ready` se thay port da mo -> test se goi nham
    server cu voi DB cu (khong dung DB tam) -> FAIL lung tung.
    """
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-Command",
               f"Get-NetTCPConnection -LocalPort {port} -State Listen "
               f"-ErrorAction SilentlyContinue | ForEach-Object "
               f"{{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"]
    else:
        cmd = ["sh", "-c",
               f"lsof -ti tcp:{port} | xargs -r kill -9 2>/dev/null || true"]
    subprocess.run(cmd, capture_output=True)


def start_servers(ports: set[int]) -> list[subprocess.Popen]:
    procs = []
    for port in sorted(ports):
        kill_port(port)
    time.sleep(1.5)
    for port in sorted(ports):
        dry_run, extra = SERVERS.get(port, ("true", []))
        env = dict(os.environ)
        env["GACHA_DB_PATH"] = str(TEST_DB)
        env["GACHA_DRY_RUN"] = dry_run
        out = open(ROOT / f"srv{port}.out", "w", encoding="utf-8")
        err = open(ROOT / f"srv{port}.err", "w", encoding="utf-8")
        procs.append(subprocess.Popen(
            [sys.executable, str(HERE / "run_test_server.py"), str(port), *extra],
            cwd=str(ROOT), env=env, stdout=out, stderr=err,
        ))
    return procs


def wait_ready(ports: set[int], timeout: float = 40.0) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    pending = set(ports)
    while pending and time.time() < deadline:
        for port in list(pending):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=2)
                pending.discard(port)
            except urllib.error.HTTPError:
                pending.discard(port)
            except Exception:
                pass
        if pending:
            time.sleep(0.5)
    return not pending


def main():
    results = []
    total_pass = 0
    prepare_db()

    needed_ports = {port for _, _, needs, port in SUITES if needs and port}
    procs = start_servers(needed_ports)
    try:
        if not wait_ready(needed_ports):
            print("!! Khong khoi dong duoc server test — bo qua cac suite can server.")
            needed_ports = set()

        for name, script, needs_server, port in SUITES:
            path = HERE / script
            if not path.exists():
                results.append((name, "KHONG CO", 0))
                continue
            if needs_server and port and port not in needed_ports:
                results.append((name, "SKIP", 0))
                continue
            print(f"\n{'=' * 70}")
            print(f"  {name}  ({script})")
            print("=" * 70)
            t0 = time.perf_counter()
            proc = subprocess.run(
                [sys.executable, str(path),
                 *(["8080"] if script == "test_login_browser.py"
                   else [str(port)] if script in ("test_all_features.py",
                                                 "test_ui_menu.py",
                                                 "test_admin_http.py",
                                                 "test_upgrade_ui.py")
                   else [])],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "GACHA_DB_PATH": str(TEST_DB)},
            )
            dt = time.perf_counter() - t0
            out = proc.stdout or ""
            tail = [line for line in out.strip().splitlines() if line.strip()]
            for line in tail[-4:]:
                print("  " + line)
            if proc.returncode != 0:
                for line in tail[-12:]:
                    print("  " + line)
                err = (proc.stderr or "").strip().splitlines()
                if err:
                    for line in err[-6:]:
                        print("  ERR " + line)

            n_pass = out.count("  PASS ") + out.count("PASS ")
            n_fail = out.count("  FAIL ") + out.count("FAIL:")
            total_pass += n_pass
            ok = proc.returncode == 0
            results.append((name, "PASS" if ok else "FAIL", dt))
            print(f"  --> {'PASS' if ok else 'FAIL'}  ({dt:.1f}s, {n_pass} assertions)")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
        if TEST_DB.exists():
            try:
                TEST_DB.unlink()
            except Exception:
                pass
        for suffix in ("-wal", "-shm"):
            p = Path(str(TEST_DB) + suffix)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        # Don thu muc DB tam (co the con file khoa -> bo qua loi).
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    print()
    print("=" * 70)
    print("  TONG KET")
    print("=" * 70)
    for name, status, dt in results:
        mark = "OK " if status == "PASS" else "XX "
        print(f"  [{mark}] {name:<34} {status:<10} {dt:>5.1f}s")
    failed = [r for r in results if r[1] != "PASS"]
    print()
    if failed:
        print(f"  !!! {len(failed)} suite FAIL: {[f[0] for f in failed]}")
        sys.exit(1)
    print(f"  >>> TAT CA {len(results)} SUITE PASS ({total_pass} assertions)")


if __name__ == "__main__":
    main()
