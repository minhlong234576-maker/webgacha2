"""Quản lý sản phẩm (item) của catalogue gacha cho admin.

Nguồn sự thật là file `gacha.json` ở thư mục gốc. Mọi thay đổi (thêm /
sửa / xoá item, cùng ảnh đi kèm) đều ghi lại file này.

Nguyên tắc:
- Ghi file **atomic**: ghi file tạm -> `os.replace` sang file thật. Nếu app
  chết giữa lúc ghi, `gacha.json` cũ vẫn nguyên vẹn.
- **Backup** mỗi lần ghi: giữ `gacha.json.bak` để admin có thể quay lại.
- **Khoá** (lock) để hai request admin song song không ghi đè nhau.
- Validate nghiêm ngặt trước khi ghi: id hợp lệ, tỉ lệ trúng > 0, giá >= 0,
  tổng tỉ lệ của mỗi rương > 0. Rương rỗng là không quay được.
- Ảnh nằm trong `app/static/items/` (và `app/static/cases/` cho rương).
  Tên file luôn sinh từ id + extension thật, không lấy từ tên file người
  dùng tải lên -> chống path traversal.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from .config import ROOT, STATIC_DIR, dry_run

# Path cua file gacha.json. Cho phep tro sang file tam trong test de khong
# cham du lieu that cua production.
GACHA_FILE = Path(os.getenv("GACHA_FILE") or (ROOT / "gacha.json"))

ITEMS_DIR = STATIC_DIR / "items"
CASES_DIR = STATIC_DIR / "cases"

# Id sản phẩm: chữ thường/số/gạch dưới/gạch ngang. Dùng chung cho
# `nexo_id` nên chặn thêm ký tự lạ.
ITEM_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
CASE_ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")

RARITIES = (
    "consumer",
    "industrial",
    "milspec",
    "restricted",
    "classified",
    "covert",
    "extraordinary",
)

IMAGE_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".svg")

# Kich thuoc toi da cho 1 file anh (5 MB).
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Khoa ghi file — tranh hai request admin cung ghi file mot luc.
_write_lock = threading.Lock()

# File gacha.json THAT cua du lieu production. Moi thay doi tren file nay
# deu anh huong truc tiep toi nguoi choi (item mat khoi ruong -> khong quay
# duoc nua).
REAL_GACHA_FILE = ROOT / "gacha.json"


class CatalogError(ValueError):
    """Lỗi nghiệp vụ khi admin sửa catalogue. Thông điệp hiển thị cho user."""


class CatalogReadOnlyError(CatalogError):
    """Catalogue dang o che do chi-doc (server test / dry-run)."""


def _guard_write() -> None:
    """Chặn ghi vao `gacha.json` that khi dang o che do dry-run.

    Server test va moi truong `GACHA_DRY_RUN=true` tro sang mot ban sao tam
    cua `gacha.json`. Nếu quen truyền `GACHA_FILE`, route admin san pham se
    ghi thang vao file that cua production — xoa item that khi test chay.

    Voi `GACHA_DRY_RUN=false` (production that) moi cho phep ghi vao file
    that; dung cho dev server de admin thu nghiem tren du lieu that.
    """
    if GACHA_FILE.resolve() != REAL_GACHA_FILE.resolve():
        return  # dang tro toi ban sao tam -> ghi thoai
    if dry_run():
        raise CatalogReadOnlyError(
            "Đang ở chế độ dry-run — không sửa được danh mục thật. "
            "Hãy đặt GACHA_DRY_RUN=false để quản trị sản phẩm."
        )


# ---------------------------------------------------------------------------
#  Doc
# ---------------------------------------------------------------------------


def load_raw() -> dict[str, Any]:
    """Đọc nguyên file `gacha.json` (chưa chuẩn hoá)."""
    if not GACHA_FILE.exists():
        return {"cases": []}
    try:
        data = json.loads(GACHA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"Không đọc được gacha.json: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogError("gacha.json không phải object.")
    return data


def _atomic_write(data: dict[str, Any]) -> None:
    """Ghi `gacha.json` atomic, có backup file cũ."""
    GACHA_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Backup ban goc truoc khi ghi de.
    if GACHA_FILE.exists():
        shutil.copy2(GACHA_FILE, GACHA_FILE.with_suffix(".json.bak"))
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = GACHA_FILE.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    # os.replace la atomic tren cung filesystem: file cu hoac file moi, khong
    # bao gio la file nua.
    os.replace(tmp, GACHA_FILE)


def list_items(case_id: str | None = None) -> list[dict[str, Any]]:
    """Danh sach item phang (kem thong tin rương cha).

    Moi item tra ve them `case_id` de admin biet item thuoc rương nao.
    """
    data = load_raw()
    out: list[dict[str, Any]] = []
    for case in data.get("cases", []) or []:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("id") or "")
        if case_id and cid != case_id:
            continue
        for index, item in enumerate(case.get("items", []) or []):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["case_id"] = cid
            row["case_name"] = str(case.get("name") or "")
            row["_index"] = index
            out.append(row)
    return out


def get_item(item_id: str, case_id: str | None = None) -> dict[str, Any] | None:
    for row in list_items(case_id):
        if str(row.get("id")) == item_id:
            return row
    return None


def list_cases() -> list[dict[str, Any]]:
    data = load_raw()
    out = []
    for case in data.get("cases", []) or []:
        if not isinstance(case, dict):
            continue
        items = case.get("items", []) or []
        out.append(
            {
                "id": str(case.get("id") or ""),
                "name": str(case.get("name") or ""),
                "description": str(case.get("description") or ""),
                "pull_cost": int(case.get("pull_cost") or 0),
                "item_count": len(items),
                "total_weight": sum(
                    max(0.0, float(i.get("weight") or 0))
                    for i in items
                    if isinstance(i, dict)
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
#  Validate
# ---------------------------------------------------------------------------


def _clean_text(value: Any, field: str, *, max_len: int = 120) -> str:
    text = str(value or "").strip()
    if not text:
        raise CatalogError(f"{field} không được để trống.")
    if len(text) > max_len:
        raise CatalogError(f"{field} quá dài (tối đa {max_len} ký tự).")
    return text


def validate_item(raw: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Chuẩn hoá + kiem tra mot item. Tra ve item da chuan hoa.

    `existing` la item goc (dung khi sua) — cac truong khong doi giu nguyen.
    """
    if not isinstance(raw, dict):
        raise CatalogError("Item phải là object.")

    item_id = _clean_text(raw.get("id") or (existing or {}).get("id"), "Id", max_len=64).lower()
    if not ITEM_ID_RE.fullmatch(item_id):
        raise CatalogError(
            "Id chỉ gồm chữ thường, số, gạch dưới và gạch ngang (tối đa 64 ký tự)."
        )

    name = _clean_text(raw.get("name") or (existing or {}).get("name"), "Tên", max_len=120)

    rarity = str(raw.get("rarity") or (existing or {}).get("rarity") or "consumer").strip().lower()
    if rarity not in RARITIES:
        raise CatalogError(f"Rarity không hợp lệ. Chọn một trong: {', '.join(RARITIES)}.")

    try:
        weight = float(raw.get("weight") if raw.get("weight") not in (None, "") else (existing or {}).get("weight"))
    except (TypeError, ValueError):
        raise CatalogError("Tỉ lệ trúng phải là số.") from None
    if weight <= 0:
        raise CatalogError("Tỉ lệ trúng phải lớn hơn 0.")
    if weight > 1_000_000:
        raise CatalogError("Tỉ lệ trúng quá lớn.")

    try:
        coin = int(raw.get("coin") if raw.get("coin") not in (None, "") else (existing or {}).get("coin"))
    except (TypeError, ValueError):
        raise CatalogError("Giá trị phải là số nguyên.") from None
    if coin < 0:
        raise CatalogError("Giá trị không được âm.")

    nexo_id = str(raw.get("nexo_id") or (existing or {}).get("nexo_id") or "").strip()
    if nexo_id and not re.fullmatch(r"^[A-Za-z0-9_:-]{1,64}$", nexo_id):
        raise CatalogError("nexo_id chỉ gồm chữ, số, gạch dưới, gạch ngang và dấu hai chấm.")

    try:
        nexo_amount = int(
            raw.get("nexo_amount")
            if raw.get("nexo_amount") not in (None, "")
            else (existing or {}).get("nexo_amount", 1)
        )
    except (TypeError, ValueError):
        raise CatalogError("nexo_amount phải là số nguyên.") from None
    if nexo_amount < 1:
        raise CatalogError("nexo_amount phải từ 1 trở lên.")

    out: dict[str, Any] = {
        "id": item_id,
        "name": name,
        "rarity": rarity,
        "weight": weight,
        "coin": coin,
    }
    if nexo_id:
        out["nexo_id"] = nexo_id
    out["nexo_amount"] = nexo_amount

    image = str(raw.get("image") or (existing or {}).get("image") or "").strip()
    if image:
        # Chi chap nhan duong dan tuong doi trong static hoac duong dan /
        # pika/tex/... (proxy noi bo). Chan duong dan absolute/URL ngoai.
        if image.startswith("/static/") or image.startswith("/pika/tex/"):
            out["image"] = image
        elif image == "":
            out.pop("image", None)
        else:
            raise CatalogError("Ảnh phải là đường dẫn nội bộ (dạng /static/...).")
    return out


def _validate_case_weights(case: dict[str, Any]) -> None:
    total = sum(
        max(0.0, float(i.get("weight") or 0)) for i in case.get("items", []) or []
    )
    if total <= 0:
        raise CatalogError(
            f"Rương '{case.get('name') or case.get('id')}' phải có ít nhất một item với tỉ lệ trúng > 0."
        )


# ---------------------------------------------------------------------------
#  Ghi
# ---------------------------------------------------------------------------


def _find_case(data: dict[str, Any], case_id: str) -> dict[str, Any] | None:
    for case in data.get("cases", []) or []:
        if isinstance(case, dict) and str(case.get("id")) == case_id:
            return case
    return None


def create_item(case_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Them item moi vao mot ruong."""
    item = validate_item(raw)
    with _write_lock:
        _guard_write()
        data = load_raw()
        case = _find_case(data, case_id)
        if not case:
            raise CatalogError(f"Không tìm thấy rương '{case_id}'.")
        items = case.setdefault("items", [])
        if any(isinstance(i, dict) and str(i.get("id")) == item["id"] for i in items):
            raise CatalogError(f"Id '{item['id']}' đã tồn tại trong rương này.")
        items.append(item)
        _validate_case_weights(case)
        _atomic_write(data)
    return item


def update_item(case_id: str, item_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Sua item trong ruong."""
    with _write_lock:
        _guard_write()
        data = load_raw()
        case = _find_case(data, case_id)
        if not case:
            raise CatalogError(f"Không tìm thấy rương '{case_id}'.")
        items = case.get("items", []) or []
        for index, item in enumerate(items):
            if isinstance(item, dict) and str(item.get("id")) == item_id:
                merged = validate_item(raw, existing=item)
                # Neu doi id -> phai dam bao khong trung id khac trong ruong.
                if merged["id"] != item_id and any(
                    isinstance(i, dict) and str(i.get("id")) == merged["id"]
                    for i in items
                ):
                    raise CatalogError(f"Id '{merged['id']}' đã tồn tại trong rương này.")
                items[index] = merged
                _validate_case_weights(case)
                _atomic_write(data)
                return merged
    raise CatalogError(f"Không tìm thấy item '{item_id}' trong rương '{case_id}'.")


def delete_item(case_id: str, item_id: str) -> None:
    """Xoa item khoi ruong.

    Cho phep xoa ca item cuoi cung — ruong se rong. Truong hop nay ruong khong
    quay duoc (khong co gi de trung), nen UI can canh bao admin truoc khi xoa.
    """
    with _write_lock:
        _guard_write()
        data = load_raw()
        case = _find_case(data, case_id)
        if not case:
            raise CatalogError(f"Không tìm thấy rương '{case_id}'.")
        items = case.get("items", []) or []
        remaining = [i for i in items if not (isinstance(i, dict) and str(i.get("id")) == item_id)]
        if len(remaining) == len(items):
            raise CatalogError(f"Không tìm thấy item '{item_id}' trong rương.")
        case["items"] = remaining
        _atomic_write(data)


def update_case(case_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Sua thong tin rương (ten, mo ta, gia quay)."""
    with _write_lock:
        _guard_write()
        data = load_raw()
        case = _find_case(data, case_id)
        if not case:
            raise CatalogError(f"Không tìm thấy rương '{case_id}'.")
        if "name" in raw:
            case["name"] = _clean_text(raw.get("name"), "Tên rương", max_len=120)
        if "description" in raw:
            case["description"] = str(raw.get("description") or "").strip()[:400]
        if "pull_cost" in raw:
            try:
                cost = int(raw.get("pull_cost"))
            except (TypeError, ValueError):
                raise CatalogError("Giá quay phải là số nguyên.") from None
            if cost < 0:
                raise CatalogError("Giá quay không được âm.")
            case["pull_cost"] = cost
        _atomic_write(data)
        return case


# ---------------------------------------------------------------------------
#  Anh
# ---------------------------------------------------------------------------


def _safe_image_name(item_id: str, filename: str) -> str:
    """Sinh ten file an toan tu id + extension cua file tai len."""
    ext = Path(filename or "").suffix.lower()
    if ext not in IMAGE_EXTS:
        raise CatalogError(f"Định dạng ảnh không hợp lệ. Chỉ nhận: {', '.join(IMAGE_EXTS)}.")
    return f"{item_id}{ext}"


def save_item_image(item_id: str, filename: str, content: bytes) -> str:
    """Luu anh san pham vao static/items. Tra ve duong dan web.

    Ten file luon sinh tu `item_id` + extension -> khong bao gio dung ten file
    nguoi dung tai len (chong path traversal / chong ghi de file khac).
    """
    if not ITEM_ID_RE.fullmatch(item_id):
        raise CatalogError("Id sản phẩm không hợp lệ.")
    if not content:
        raise CatalogError("File ảnh rỗng.")
    if len(content) > MAX_IMAGE_BYTES:
        raise CatalogError(
            f"Ảnh vượt quá {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
        )
    # Kiem tra magic bytes: chi nhan anh that, khong nhan file .exe/.html
    if not _looks_like_image(content):
        raise CatalogError("File không phải ảnh hợp lệ (PNG/JPG/WebP/SVG).")

    name = _safe_image_name(item_id, filename)
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    target = ITEMS_DIR / name
    # Xoa anh cu cua item (khac duoi) de tranh ton tai 2 anh cho 1 item.
    for old in ITEMS_DIR.glob(f"{item_id}.*"):
        if old.name != name and old.is_file():
            try:
                old.unlink()
            except OSError:
                pass
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, target)
    return f"/static/items/{name}"


def _looks_like_image(content: bytes) -> bool:
    """Kiem tra magic bytes cua anh. SVG la text nen check rieng."""
    head = content[:512].lstrip()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in content[:2048]):
        return True
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if content.startswith(b"\xff\xd8\xff"):
        return True
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return True
    return False


def delete_item_image(item_id: str) -> None:
    """Xoa file anh cua item (neu co)."""
    if not ITEM_ID_RE.fullmatch(item_id):
        raise CatalogError("Id sản phẩm không hợp lệ.")
    for path in ITEMS_DIR.glob(f"{item_id}.*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            try:
                path.unlink()
            except OSError:
                pass


def backup() -> Path | None:
    """Duong dan file backup (neu co)."""
    bak = GACHA_FILE.with_suffix(".json.bak")
    return bak if bak.exists() else None


def restore_backup() -> None:
    """Khoi phuc `gacha.json` tu file backup."""
    bak = GACHA_FILE.with_suffix(".json.bak")
    if not bak.exists():
        raise CatalogError("Không có file backup để khôi phục.")
    with _write_lock:
        _guard_write()
        # Backup ban hien tai truoc khi ghi de, de khong mat du lieu dang sai.
        shutil.copy2(GACHA_FILE, GACHA_FILE.with_suffix(".json.broken"))
        shutil.copy2(bak, GACHA_FILE)
