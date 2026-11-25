"""Kiem tra moi file test: ROOT phai duoc define TRUOC khi dung, va
khong con hardcode duong dan repo (jellyvale-gacha-dev §4)."""
import ast
import re
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent

# Khu vuc "duong dan repo cu" — regex bat ca kieu escape.
HARDCODED = re.compile(r"[A-Za-z]:[\\/]+code[\\/]+web", re.IGNORECASE)

bad = []
for path in sorted(TESTS.glob("*.py")):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # dong define ROOT
    root_def = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "ROOT":
                    root_def = node.lineno
                    break
        if root_def:
            break

    uses = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id == "ROOT" and isinstance(n.ctx, ast.Load)
    ]
    if uses and root_def is None:
        bad.append(f"{path.name}: dung ROOT nhung khong define")
    elif uses and root_def and min(uses) < root_def:
        bad.append(
            f"{path.name}: dung ROOT tai dong {min(uses)} truoc khi define dong {root_def}"
        )

    if HARDCODED.search(src):
        bad.append(f"{path.name}: van con hardcode path")

print("Kiem tra", len(list(TESTS.glob('*.py'))), "file")
if bad:
    print("FAIL:")
    for b in bad:
        print("  -", b)
    sys.exit(1)
print(">>> ALL PATH CHECKS PASS")
