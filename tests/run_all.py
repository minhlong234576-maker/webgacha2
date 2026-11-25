"""Chay TOAN BO bo test va tom tat ket qua.

Usage: python tests/run_all.py
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent

# (ten, file, can server chay khong)
SUITES = [
    ("Logic + bao mat he thong", "test_system.py", False),
    ("Tat ca chuc nang web (can server 8101)", "test_all_features.py", True),
    ("Bao mat HTTP (CSRF/session/quyen)", "test_http_security.py", True),
    ("Tien that - don gian", "test_money.py", False),
    ("Tien that - end to end", "test_e2e_money.py", False),
    ("Tien that - race condition", "test_money_race.py", False),
    ("Roulette", "test_roulette.py", False),
    ("Realtime - kho", "test_realtime_balance.py", False),
    ("Realtime - thuc (can server 8099)", "test_realtime_live.py", True),
    ("Realtime - UI (can server 8099)", "test_realtime_ui.py", True),
    ("UI - menu (can server 8101)", "test_ui_menu.py", True),
    ("Quyen admin realtime (doc OP tu PikaMC)", "test_admin_realtime.py", False),
    ("Quyen admin realtime - HTTP (can server 8101)", "test_admin_http.py", True),
    ("Dang nhap thuc (can server 8080)", "test_login_browser.py", True),
]


def main():
    results = []
    total_pass = 0
    for name, script, needs_server in SUITES:
        path = HERE / script
        if not path.exists():
            results.append((name, "KHONG CO", 0))
            continue
        print(f"\n{'=' * 70}")
        print(f"  {name}  ({script})")
        print("=" * 70)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(path),
             *(["8080"] if script == "test_login_browser.py"
               else ["8101"] if script in ("test_all_features.py", "test_ui_menu.py",
                                          "test_admin_http.py")
               else [])],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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

        # Dem so dong PASS/FAIL
        n_pass = out.count("  PASS ") + out.count("PASS ")
        n_fail = out.count("  FAIL ") + out.count("FAIL:")
        total_pass += n_pass
        ok = proc.returncode == 0
        results.append((name, "PASS" if ok else "FAIL", dt))
        print(f"  --> {'PASS' if ok else 'FAIL'}  ({dt:.1f}s, {n_pass} assertions)")

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
