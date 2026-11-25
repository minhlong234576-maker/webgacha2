"""Quan tri san pham cho admin: them / sua / xoa + upload anh.

Kiem tra:
- Khach / nguoi thuong bi tu choi (401/403) tren moi route /api/admin/*.
- CSRF bat buoc cho thao tac ghi.
- Them / sua / xoa item hoat dong tren file gacha.json tam (khong cham file that).
- Upload anh tao file dung ten, kiem tra magic bytes, chan dinh dang sai.
- Rương khong duoc mat item cuoi cung.

Usage: python tests/test_admin_products.py [port]
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import asyncio
import base64
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, str(ROOT))

# Server test (tests/run_test_server.py) tro `GACHA_FILE` toi mot ban sao tam
# trong thu muc tam — de khong bao gio ghi vao `gacha.json` that cua du lieu
# production. File do duoc tao boi `run_test_server.py`; neu chay test doc
# lap (khong co env) thi tu tao file tam rieng.
def _find_server_gacha_file() -> Path | None:
    """Tim `gacha.json` tam cua server test (qua marker file)."""
    import glob

    # `run_all.py` tao thu muc ten `jvcfg<port>_`; `run_test_server.py` tao
    # `jvcfg_` khi chay doc lap.
    patterns = [
        os.path.join(tempfile.gettempdir(), "jvcfg*_", "gacha_file_path.txt"),
        os.path.join(tempfile.gettempdir(), "jvcfg_*", "gacha_file_path.txt"),
    ]
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(glob.glob(pattern))
    hits.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for hit in hits:
        try:
            path = Path(hit).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if path and Path(path).exists():
            return Path(path)
    return None


_server_gacha = None
if "GACHA_FILE" in os.environ:
    _server_gacha = Path(os.environ["GACHA_FILE"])
else:
    _server_gacha = _find_server_gacha_file()

if _server_gacha and _server_gacha.exists():
    TMP = _server_gacha.parent
    os.environ["GACHA_FILE"] = str(_server_gacha)
else:
    TMP = Path(tempfile.mkdtemp(prefix="jvadmin_"))
    shutil.copy(ROOT / "gacha.json", TMP / "gacha.json")
    os.environ["GACHA_FILE"] = str(TMP / "gacha.json")

os.environ["GACHA_DRY_RUN"] = "true"

from app import catalog_admin  # noqa: E402

catalog_admin.GACHA_FILE = Path(os.environ["GACHA_FILE"])

# Thu muc anh tam — khong ghi vao `app/static/items` that.
catalog_admin.ITEMS_DIR = TMP / "items"
catalog_admin.ITEMS_DIR.mkdir(parents=True, exist_ok=True)

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main as web_main  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8101"
BASE = f"http://127.0.0.1:{PORT}"

FAILS: list[str] = []
PASSES = 0


def check(name, cond, detail=""):
    global PASSES
    if cond:
        PASSES += 1
        print(f"  PASS {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"   {detail}" if detail else ""))


# Cookie gia da ky bang secret thuoc app.
def make_cookie(user: str) -> str:
    import itsdangerous
    from app.config import SESSION_SECRET

    raw = base64.b64encode(
        json.dumps({"user": user, "login_name": user, "csrf": "test-csrf"}).encode()
    )
    return itsdangerous.TimestampSigner(SESSION_SECRET).sign(raw).decode()


ADMIN = "Trez1724"
QA = "QA_Tester_01"

# 1x1 PNG trong suot.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def main():
    # ---------------------------------------------------------------- API
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        print("=== 1. PHAI DANG NHAP ===")
        r = await c.get("/api/admin/products")
        check("GET /api/admin/products (khach) -> 401", r.status_code == 401,
              str(r.status_code))

        print()
        print("=== 2. NGUOI THUONG -> 403 ===")
        c.cookies.set("jv_session", make_cookie(QA), domain="127.0.0.1")
        r = await c.get("/api/admin/products")
        check("GET /api/admin/products (nguoi thuong) -> 403", r.status_code == 403,
              str(r.status_code))

        print()
        print("=== 3. ADMIN -> 200 ===")
        c.cookies.set("jv_session", make_cookie(ADMIN), domain="127.0.0.1")
        r = await c.get("/api/admin/products")
        check("GET /api/admin/products (admin) -> 200", r.status_code == 200,
              str(r.status_code))
        if r.status_code == 200:
            data = r.json()
            check("co danh sach items", len(data["items"]) > 0, str(len(data["items"])))
            check("co danh sach cases", len(data["cases"]) > 0, str(len(data["cases"])))
            first = data["items"][0]
            check("item co image_url", bool(first.get("image_url")),
                  first.get("image_url", ""))
            check("item co case_id", bool(first.get("case_id")))
            check("item co weight_pct hoac tinh duoc",
                  "weight" in first, str(first.get("weight")))

        print()
        print("=== 4. CSRF BAT BUOC KHI GHI ===")
        c.cookies.set("jv_session", make_cookie(ADMIN), domain="127.0.0.1")
        r = await c.post("/api/admin/products", json={"case_id": "jelly-starter",
                                                       "id": "csrf_test", "name": "X",
                                                       "rarity": "consumer",
                                                       "weight": 1, "coin": 1})
        check("POST /api/admin/products thieu CSRF -> 403", r.status_code == 403,
              str(r.status_code))

        print()
        print("=== 5. THEM SAN PHAM (co CSRF) ===")
        new_item = {
            "case_id": "jelly-starter",
            "id": "zz_test_item",
            "name": "Món Thử Nghiệm",
            "rarity": "milspec",
            "weight": 3.5,
            "coin": 1234,
            "nexo_id": "test_nexo_item",
            "nexo_amount": 2,
        }
        r = await c.post("/api/admin/products", json=new_item,
                         headers={"X-CSRF": "test-csrf"})
        check("POST tao item -> 200", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        if r.status_code == 200:
            created = r.json()["item"]
            check("item id dung", created["id"] == "zz_test_item", created.get("id", ""))
            check("item rarity dung", created["rarity"] == "milspec")
            check("item weight dung", abs(float(created["weight"]) - 3.5) < 0.001)
            check("item coin dung", int(created["coin"]) == 1234)
            check("item nexo_amount dung", int(created["nexo_amount"]) == 2)
            # Da ghi vao file that?
            saved = json.loads((TMP / "gacha.json").read_text(encoding="utf-8"))
            found = False
            for case in saved["cases"]:
                for it in case["items"]:
                    if it["id"] == "zz_test_item":
                        found = True
            check("item da ghi vao gacha.json", found)

        print()
        print("=== 6. TRUNG ID -> 400 ===")
        r = await c.post("/api/admin/products", json=new_item,
                         headers={"X-CSRF": "test-csrf"})
        check("POST trung id -> 400", r.status_code == 400, str(r.status_code))
        check("thong bao loai id", "đã tồn tại" in r.text.lower(), r.text[:120])

        print()
        print("=== 7. VALIDATE: ID SAI DINH DANG ===")
        bad = {**new_item, "id": "Bad ID!"}
        r = await c.post("/api/admin/products", json=bad,
                         headers={"X-CSRF": "test-csrf"})
        check("POST id sai -> 400", r.status_code == 400, str(r.status_code))

        print()
        print("=== 8. VALIDATE: WEIGHT = 0 / COIN AM ===")
        r = await c.post("/api/admin/products",
                         json={**new_item, "id": "w0", "weight": 0},
                         headers={"X-CSRF": "test-csrf"})
        check("POST weight=0 -> 400", r.status_code == 400, str(r.status_code))
        r = await c.post("/api/admin/products",
                         json={**new_item, "id": "cm", "coin": -5},
                         headers={"X-CSRF": "test-csrf"})
        check("POST coin=-5 -> 400", r.status_code == 400, str(r.status_code))
        r = await c.post("/api/admin/products",
                         json={**new_item, "id": "rr", "rarity": "khong_co"},
                         headers={"X-CSRF": "test-csrf"})
        check("POST rarity sai -> 400", r.status_code == 400, str(r.status_code))

        print()
        print("=== 9. SUA SAN PHAM ===")
        r = await c.put("/api/admin/products/jelly-starter/zz_test_item",
                        json={"name": "Đã Sửa", "coin": 9999},
                        headers={"X-CSRF": "test-csrf"})
        check("PUT sua item -> 200", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        if r.status_code == 200:
            it = r.json()["item"]
            check("ten da doi", it["name"] == "Đã Sửa", it.get("name", ""))
            check("gia da doi", int(it["coin"]) == 9999, str(it.get("coin")))
            check("id giu nguyen", it["id"] == "zz_test_item")
            check("rarity giu nguyen", it["rarity"] == "milspec")

        print()
        print("=== 10. XOA SAN PHAM ===")
        r = await c.delete("/api/admin/products/jelly-starter/zz_test_item",
                           headers={"X-CSRF": "test-csrf"})
        check("DELETE item -> 200", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        r = await c.get("/api/admin/products")
        ids = [i["id"] for i in r.json()["items"]]
        check("item da khoi danh sach", "zz_test_item" not in ids)

        print()
        print("=== 11. XOA ITEM CUOI CUNG -> 200 (RUONG RONG) ===")
        # Tao 1 ruong chi co 1 item roi xoa — rương rỗng là hợp lệ.
        saved = json.loads((TMP / "gacha.json").read_text(encoding="utf-8"))
        saved["cases"].append({
            "id": "zz-solo", "name": "Rương Một Món", "description": "",
            "pull_cost": 100, "items": [{
                "id": "solo_item", "name": "Duy Nhat", "rarity": "consumer",
                "weight": 1, "coin": 10,
            }],
        })
        (TMP / "gacha.json").write_text(
            json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        r = await c.delete("/api/admin/products/zz-solo/solo_item",
                           headers={"X-CSRF": "test-csrf"})
        check("DELETE item cuoi -> 200 (cho phep ruong rong)",
              r.status_code == 200, f"{r.status_code} {r.text[:140]}")
        saved2 = json.loads((TMP / "gacha.json").read_text(encoding="utf-8"))
        solo = next((x for x in saved2["cases"] if x["id"] == "zz-solo"), None)
        check("ruong da rong (items = [])",
              solo is not None and solo["items"] == [],
              str(solo["items"]) if solo else "khong tim thay ruong")

        print()
        print("=== 12. SUA RUONG ===")
        r = await c.put("/api/admin/cases/jelly-starter",
                        json={"name": "Rương Starter Đã Đổi Tên", "pull_cost": 3600},
                        headers={"X-CSRF": "test-csrf"})
        check("PUT sua ruong -> 200", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        if r.status_code == 200:
            case = r.json()["case"]
            check("ten ruong da doi", case["name"] == "Rương Starter Đã Đổi Tên")
            check("gia quay da doi", int(case["pull_cost"]) == 3600)

    # ------------------------------------------------------------- Upload
    print()
    print("=== 13. UPLOAD ANH ===")
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        c.cookies.set("jv_session", make_cookie(ADMIN), domain="127.0.0.1")
        files = {"file": ("anh.png", PNG_1PX, "image/png")}
        r = await c.post("/api/admin/products/jelly-starter/zz_up/image",
                         files=files, headers={"X-CSRF": "test-csrf"})
        check("POST upload -> 200", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        if r.status_code == 200:
            path = r.json()["image"]
            check("duong dan /static/items/", path.startswith("/static/items/"), path)
            check("ten file tu id item",
                  path == "/static/items/zz_up.png", path)

        print()
        print("=== 14. UPLOAD FILE KHONG PHAI ANH -> 400 ===")
        bad = {"file": ("hack.html", b"<script>alert(1)</script>", "text/html")}
        r = await c.post("/api/admin/products/jelly-starter/zz_up/image",
                         files=bad, headers={"X-CSRF": "test-csrf"})
        check("upload file html -> 400", r.status_code == 400, str(r.status_code))

        print()
        print("=== 15. UPLOAD DINH DANG KHONG HO TRO -> 400 ===")
        bad = {"file": ("x.gif", PNG_1PX, "image/gif")}
        r = await c.post("/api/admin/products/jelly-starter/zz_up/image",
                         files=bad, headers={"X-CSRF": "test-csrf"})
        check("upload .gif -> 400", r.status_code == 400, str(r.status_code))

        print()
        print("=== 16. UPLOAD TEN FILE DUONG DAN -> KHONG GHI RA NGOAI ===")
        evil = {"file": ("../../evil.png", PNG_1PX, "image/png")}
        r = await c.post("/api/admin/products/jelly-starter/zz_up/image",
                         files=evil, headers={"X-CSRF": "test-csrf"})
        check("upload ten duong dan -> 200 hoac 400", r.status_code in (200, 400),
              str(r.status_code))
        if r.status_code == 200:
            path = r.json()["image"]
            check("duong dan van nam trong items/",
                  path.startswith("/static/items/") and ".." not in path, path)
        # Khong duoc co file nao lot ra ngoai thu muc items.
        outside = list(TMP.glob("*.png")) + list(ROOT.glob("evil.png"))
        check("khong ghi file ra ngoai items/", not outside, str(outside))

        print()
        print("=== 17. XOA ANH ===")
        r = await c.post(
            "/api/admin/products/jelly-starter/zz_up/image/delete",
            headers={"X-CSRF": "test-csrf"},
        )
        check("POST xoa anh -> 200", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        check("file anh da xoa",
              not (catalog_admin.ITEMS_DIR / "zz_up.png").exists())

    # ------------------------------------------------------- Trang HTML
    print()
    print("=== 18. TRANG /admin/products ===")
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        c.cookies.set("jv_session", make_cookie(ADMIN), domain="127.0.0.1")
        r = await c.get("/admin/products")
        check("GET /admin/products (admin) -> 200", r.status_code == 200,
              str(r.status_code))
        check("co bang san pham", 'id="product-rows"' in r.text)
        check("co nut them san pham", 'id="btn-new"' in r.text)
        check("co o upload anh", 'id="f-file"' in r.text)

        print()
        print("=== 19. TRANG /admin/products CHO NGUOI THUONG -> 303 ===")
        c.cookies.set("jv_session", make_cookie(QA), domain="127.0.0.1")
        r = await c.get("/admin/products", follow_redirects=False)
        check("GET /admin/products (nguoi thuong) -> 303",
              r.status_code == 303, str(r.status_code))

    # ------------------------------------------- Lưới an toàn ghi file thật
    print()
    print("=== 20. DRY-RUN KHONG DUOC GHI VAO gacha.json THAT ===")
    # `catalog_admin` tro toi file tam -> ghi thoai. Nhung khi tro ve file
    # THAT cua production + GACHA_DRY_RUN=true -> phai bi chan.
    real_file = ROOT / "gacha.json"
    before = real_file.read_bytes()
    original_gacha_file = catalog_admin.GACHA_FILE
    original_dry = os.environ.get("GACHA_DRY_RUN")
    try:
        # `dry_run()` doc env moi lan goi -> doi env la du.
        catalog_admin.GACHA_FILE = real_file
        os.environ["GACHA_DRY_RUN"] = "true"

        try:
            catalog_admin.delete_item("jelly-starter", "starter_dust_1")
            check("dry-run chan xoa item that", False, "KHONG bi chan!")
        except catalog_admin.CatalogReadOnlyError:
            check("dry-run chan xoa item that", True)
        except catalog_admin.CatalogError as exc:
            check("dry-run chan xoa item that (loai CatalogError)", True, type(exc).__name__)
        else:
            check("dry-run chan xoa item that", False, "khong nem loi")

        try:
            catalog_admin.create_item("jelly-starter", {
                "id": "zz_should_not_exist", "name": "X", "rarity": "consumer",
                "weight": 1, "coin": 1,
            })
            check("dry-run chan tao item that", False, "KHONG bi chan!")
        except catalog_admin.CatalogError:
            check("dry-run chan tao item that", True)
        else:
            check("dry-run chan tao item that", False, "khong nem loi")
    finally:
        catalog_admin.GACHA_FILE = original_gacha_file
        if original_dry is None:
            os.environ.pop("GACHA_DRY_RUN", None)
        else:
            os.environ["GACHA_DRY_RUN"] = original_dry

    after = real_file.read_bytes()
    check("gacha.json that KHONG bi thay doi", before == after,
          f"{len(before)} -> {len(after)} bytes")

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> ADMIN PRODUCTS TEST PASS")


asyncio.run(main())
