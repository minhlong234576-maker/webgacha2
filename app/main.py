from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match
from fastapi.templating import Jinja2Templates

from . import admins, bank, bots, catalog_admin, chatbot, game, liveplayers, pika, store
from .roulette import roulette_manager
from .config import PIKA_SERVER_UUID, SESSION_SECRET, pika_ready, session_https_only
from .errors import MoneyError
from .gacha import (
    find_listing,
    get_case,
    is_dry_run,
    is_nexo_withdraw_enabled,
    load_cases,
    pull_cost,
)
from .pika import (
    coin_amount,
    find_authme_user,
    find_economy_user,
    get_server,
    list_servers,
    nexo_give_item,
)
from .security import (
    SafeSessionMiddleware,
    clear_failed_logins,
    client_ip,
    is_same_origin,
    login_allowed,
    new_csrf_token,
    record_failed_login,
    verify_authme_sha256,
)

log = logging.getLogger("jellyvale.web")
_bonus_locks: dict[str, asyncio.Lock] = {}
_inventory_locks: dict[str, asyncio.Lock] = {}

# --- Gioi han cau hoi chatbot ------------------------------------------------
# Endpoint /api/chat cong khai. Khi bat Claude API, moi cau hoi la mot request
# co tien -> phai gioi han de mot nguoi spam khong lam hao chi phi.
_CHAT_MAX_PER_WINDOW = 20
_CHAT_WINDOW_SECONDS = 60
_chat_hits: dict[str, deque[float]] = defaultdict(deque)


def chat_rate_allowed(ip: str) -> bool:
    """True neu IP nay chua vuot gioi han cau hoi trong cua so thoi gian."""
    now = time.time()
    bucket = _chat_hits[ip]
    while bucket and now - bucket[0] > _CHAT_WINDOW_SECONDS:
        bucket.popleft()
    return len(bucket) < _CHAT_MAX_PER_WINDOW


def record_chat_request(ip: str) -> None:
    """Ghi nhan mot cau hoi chatbot vua duoc gui."""
    if len(_chat_hits) >= 4096 and ip not in _chat_hits:
        now = time.time()
        for key, hits in list(_chat_hits.items()):
            if not hits or now - hits[-1] > _CHAT_WINDOW_SECONDS:
                del _chat_hits[key]
    _chat_hits[ip].append(time.time())

VN_TZ = timezone(timedelta(hours=7))
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Timeout cho viec resolve texture NexoMC (giay). Khi server Minecraft khong
# phan hoi, viec quet resource pack se treo -> chan trai anh cho nguoi choi.
PIKA_TEX_TIMEOUT = 6.0

KIND_LABELS = {
    "seed": "Nạp ví",
    "open": "Mở rương",
    "sell": "Bán đồ",
    "withdraw": "Rút Nexo",
    "battle_pay": "Vào battle",
    "refund": "Hoàn Coin",
    "bonus": "Bonus ngày",
    "roulette_bet": "Cược Roulette",
    "roulette_win": "Thắng Roulette",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    # Nap danh sach OP TRUOC khi phuc vu request. Neu khong nap, admin
    # cua phai doi toi vong nen 60s moi thay link "Admin" trong menu.
    try:
        await admins.refresh()
    except Exception:
        pass
    bots.start(app)
    bank.start(app)
    roulette_manager.start_loop()
    admins.start(app)
    liveplayers.start(app)
    yield
    task = getattr(app.state, "bot_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    bank_task = getattr(app.state, "bank_task", None)
    if bank_task:
        bank_task.cancel()
        try:
            await bank_task
        except asyncio.CancelledError:
            pass
    admins_task = getattr(app.state, "admins_task", None)
    if admins_task:
        admins_task.cancel()
        try:
            await admins_task
        except asyncio.CancelledError:
            pass
    live_task = getattr(app.state, "liveplayers_task", None)
    if live_task:
        live_task.cancel()
        try:
            await live_task
        except asyncio.CancelledError:
            pass
    await pika.close_client()
    store.close_all()


app = FastAPI(title="JellyVale Gacha", docs_url=None, redoc_url=None, lifespan=lifespan)


# API doc cong khai (khong can dang nhap): dung o header cho ca khach.
PUBLIC_API_PATHS = frozenset({
    "/api/drops",     # dai "drop truc tiep" tren header
    "/api/admins",    # danh sach nguoi quan tri (doc tu OP tren server)
    "/api/online",    # so nguoi dang online tren server Minecraft
    "/api/chat",      # tro ly tra loi ve lenh console (khong chua du lieu nguoi choi)
})


def api_route_exists(path: str, method: str) -> bool:
    """True neu `path` khop mot route API da dang ky (bat ke method).

    Route da bi XOA phai tra 404 (khong phai 401) — nguoi goi can biet
    "tinh nang khong con" thi moi dung, con 401 se lam ho nghi la "sai mat
    khau". Middleware nen kiem tra route truoc khi chan.

    `route.matches(scope)` la bo khop cua Starlette — no xu ly ca duong dan
    co tham so nhu `/api/battles/{battle_id}`.

    `Match.PARTIAL` duoc chap nhan o day: duong dan co that route (chi sai
    method) van la "tinh nang co that" -> khach van phai dang nhap, thay vi
    nhan 405 "Method Not Allowed" lo mong.
    """
    scope = {"type": "http", "path": path, "method": method, "headers": []}
    for route in app.router.routes:
        route_path = getattr(route, "path", "")
        if not route_path.startswith("/api/"):
            continue
        try:
            match, _ = route.matches(scope)
        except Exception:
            continue
        if match in (Match.FULL, Match.PARTIAL):
            return True
    return False

@app.middleware("http")
async def require_login_for_api(request: Request, call_next):
    """Chac moi API (tru API cong khai) yeu cau dang nhap.

    Lop phong thu thu hai: tung route van tu goi `api_auth()` de kiem tra
    CSRF, nhung middleware nay dam bao route API MOI theo sau deu khong
    the quen mat `api_auth` va khong lo du lieu nguoi choi cho khach.

    Route API da bi xoa van tra 404 de "tinh nang khong con" khong bi
    hieu nham la "ban chua dang nhap".
    """
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
        if not request.session.get("user") and api_route_exists(path, request.method):
            return JSONResponse(
                {"detail": "Chưa đăng nhập.", "redirect": "/login?next="
                 + quote(path, safe="")},
                status_code=401,
            )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "media-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'",
    )
    return response


app.add_middleware(
    SafeSessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="jv_session",
    same_site="lax",
    https_only=session_https_only(),
    max_age=60 * 60 * 12,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def format_coin(value: float | str | None) -> str:
    try:
        amount = 0.0 if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        amount = 0.0
    if amount.is_integer():
        return f"{int(amount):,}".replace(",", ".")
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_last_seen(ms: float | str | None) -> str:
    try:
        stamp = float(ms) if ms not in (None, "") else 0
    except (TypeError, ValueError):
        stamp = 0
    if stamp <= 0:
        return "Chưa có"
    if stamp > 10_000_000_000:
        stamp = stamp / 1000
    dt = datetime.fromtimestamp(stamp, tz=VN_TZ)
    return dt.strftime("%d/%m/%Y %H:%M")


def is_admin(name: str | None) -> bool:
    """Quyen admin: dung du lieu da cache tu server (OP) + .env.

    Dung ham nay trong `render` de khong block moi request bang viec goi
    PikaMC. Cache duoc lam moi moi 60 giay boi `admins.loop`.
    """
    return admins.is_admin_now(name)


def require_admin(request: Request) -> bool:
    """Kiem tra quyen admin cho request, chap ca ten hien thi va ten login.

    Ten trong `ops.json` la ten Minecraft (username). Session luu ca
    `login_name` (username that) va `user` (realname hoac username) — nen
    phai so sanh ca hai de khong bo sot OP khi realname khac username.
    """
    session = request.session
    for key in ("login_name", "user"):
        if admins.is_admin_now(session.get(key)):
            return True
    return False


def require_admin_api(request: Request, *, csrf: bool = True) -> JSONResponse | None:
    """Chac quyen admin + CSRF cho API quan tri san pham.

    Tra ve `JSONResponse` loi neu khong du quyen, nguoc lai `None` (cho phep
    tiep tuc xu ly). Dung chung cho moi route `/api/admin/*`.
    """
    if not request.session.get("user"):
        return JSONResponse({"detail": "Chưa đăng nhập."}, status_code=401)
    if not require_admin(request):
        return JSONResponse({"detail": "Chỉ quản trị viên mới dùng được."}, status_code=403)
    if csrf and not require_csrf(request):
        return JSONResponse({"detail": "Phiên hết hạn, tải lại trang."}, status_code=403)
    return None


def require_login(request: Request) -> tuple[str, str] | RedirectResponse:
    user = request.session.get("user")
    login_name = request.session.get("login_name")
    if not user or not login_name:
        return RedirectResponse("/login", status_code=303)
    return user, login_name


# Cac duong dan duoc phep quay lai sau khi dang nhap. Chi nhan path noi bo
# (bat dau bang "/") va khong chua "//" — chong open-redirect.
_SAFE_NEXT_PREFIXES = ("/gacha", "/case/", "/battles", "/battle/", "/bonus",
                        "/roulette", "/upgrade", "/inventory", "/vi", "/admin")


def safe_next(raw: str | None) -> str:
    """Chuan hoa `next` ve duong dan trong he thong (khong phai domain ngoai)."""
    if not raw:
        return "/gacha"
    target = raw.strip()
    if not target.startswith("/") or target.startswith("//") or ":" in target.split("/")[0]:
        return "/gacha"
    if not any(target == p or target.startswith(p) for p in _SAFE_NEXT_PREFIXES):
        return "/gacha"
    return target


def login_redirect(request: Request) -> RedirectResponse:
    """Chuyen khach ve trang dang nhap, giu lai trang ho dich dang muon vao."""
    nxt = request.url.path
    if request.url.query:
        nxt = f"{nxt}?{request.url.query}"
    return RedirectResponse(f"/login?next={quote(nxt, safe='')}", status_code=303)


async def require_player(request: Request):
    """Context nguoi choi cho TRANG game — khach chua dang nhap bi day ve /login.

    Moi trang co chuc nang (mo ruong, quay roulette, bonus, battle, nang cap)
    deu di qua day. Landing page (`/`) van mo cho khach xem gioi thieu.
    """
    ctx = await player_ctx(request)
    if isinstance(ctx, RedirectResponse):
        return login_redirect(request)
    return ctx


def render(request: Request, name: str, **context) -> HTMLResponse:
    context.setdefault("is_admin", require_admin(request))
    context.setdefault("dry_run", is_dry_run())
    token = request.session.get("csrf") or new_csrf_token()
    request.session["csrf"] = token
    context.setdefault("csrf", token)
    context.setdefault("csp_nonce", getattr(request.state, "csp_nonce", ""))
    context.setdefault("player", None)
    # Trang landing riêng CSS riêng -> khong nap thua vao moi trang.
    context.setdefault("landing", name == "landing.html")
    return templates.TemplateResponse(request, name, context)


def json_error(exc: game.GameError | Exception, status: int = 400) -> JSONResponse:
    if isinstance(exc, game.GameError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)
    return JSONResponse({"detail": str(exc)}, status_code=status)


async def read_json_dict(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception as exc:
        raise game.GameError("Dữ liệu JSON không hợp lệ.", 400) from exc
    if not isinstance(body, dict):
        raise game.GameError("Dữ liệu JSON phải là object.", 400)
    return body


def parse_int(value, default: int = 0, *, field: str = "giá trị") -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise game.GameError(f"{field} không hợp lệ.", 400) from exc


def case_view(case) -> dict:
    total = sum(max(0, item.weight) for item in case.items) or 1
    return {
        "id": case.id,
        "name": case.name,
        "description": case.description,
        "image": case.image,
        "glow": case.glow,
        "pull_cost": case.pull_cost,
        "cost_fmt": format_coin(case.pull_cost),
        "loot": [
            {
                **item.as_public(),
                "weight": ("%.5f" % (100 * item.weight / total)).rstrip("0").rstrip("."),
                "coin_fmt": format_coin(item.coin),
            }
            for item in case.items
        ],
    }


def inv_view(row: dict) -> dict:
    out = dict(row)
    out["value_fmt"] = format_coin(row["value"])
    return out


def battle_view(battle: dict) -> dict:
    # Chuẩn web gốc: battle là playlist lines [{case_id, count}], giá ghế chốt
    # theo tổng mọi vòng, thứ tự vòng giữ nguyên như host xếp.
    lines = game.battle_lines_of(battle)
    order = game.battle_order_of(battle)
    try:
        price = game.battle_paid_of(battle)
    except game.GameError:
        case0 = get_case(battle.get("case_id"))
        price = case0.pull_cost * int(battle.get("rounds") or 1) if case0 else 0
    seated = battle.get("seated") or len(battle.get("players") or [])
    case0 = get_case(battle.get("case_id"))
    out = dict(battle)
    line_views = []
    pools: list[list[dict]] = []
    for line in lines:
        c = get_case(line["case_id"])
        if not c:
            continue
        line_views.append({
            "case_id": c.id, "name": c.name, "image": c.image,
            "count": int(line["count"]), "cost": c.pull_cost,
            "cost_fmt": format_coin(c.pull_cost),
        })
        pools.append([item.as_public() for item in c.items])
    # Pool từng vòng theo đúng thứ tự playlist (reel mỗi vòng khác nhau).
    round_pools: list[list[dict]] = []
    by_id = {lv["case_id"]: pool for lv, pool in zip(line_views, pools)}
    # Map lại theo order (order chứa case_id lặp theo count).
    case_pool_cache: dict[str, list[dict]] = {}
    for cid in order:
        if cid not in case_pool_cache:
            c = get_case(cid)
            case_pool_cache[cid] = [item.as_public() for item in c.items] if c else []
        round_pools.append(case_pool_cache[cid])
    if len(line_views) <= 1:
        out["case_name"] = case0.name if case0 else battle.get("case_id")
        out["case_image"] = case0.image if case0 else ""
        out["case_cost"] = case0.pull_cost if case0 else 0
    else:
        names = " + ".join(lv["name"] for lv in line_views[:3])
        if len(line_views) > 3:
            names += f" +{len(line_views) - 3}"
        out["case_name"] = f"Mix {len(line_views)} rương · {len(order)} vòng ({names})"
        out["case_image"] = line_views[0]["image"] if line_views else ""
        out["case_cost"] = 0
    out["lines"] = line_views
    out["order"] = order
    out["rounds"] = len(order) or int(battle.get("rounds") or 1)
    out["price"] = price
    out["price_fmt"] = format_coin(price)
    out["seated"] = seated
    out["slots"] = int(battle["slots"])
    out["mode_label"] = "Crazy" if battle["mode"] == "CRAZY" else "Standard"
    out["full"] = seated >= int(battle["slots"])
    out["pool"] = round_pools[0] if round_pools else []
    out["pools"] = round_pools
    for player in out.get("players") or []:
        player["total_fmt"] = format_coin(player.get("total") or 0)
    case_name_by_id = {lv["case_id"]: lv["name"] for lv in line_views}
    for drop in out.get("drops") or []:
        drop["value_fmt"] = format_coin(drop.get("value") or 0)
        cid = drop.get("case_id") or ""
        drop["case_name"] = case_name_by_id.get(cid, "")
    return out


GUEST = {
    "player": None,
    "user": None,
    "login_name": None,
    "eco": None,
    "pika": 0,
    "pika_fmt": "0",
    "money": 0,
    "money_fmt": None,
    "held": 0,
    "last_seen": "Chưa có",
}


async def optional_ctx(request: Request) -> dict:
    if not request.session.get("user"):
        return dict(GUEST)
    ctx = await player_ctx(request)
    if isinstance(ctx, RedirectResponse):
        return dict(GUEST)
    return ctx


async def player_ctx(request: Request):
    auth = require_login(request)
    if isinstance(auth, RedirectResponse):
        return auth
    user, login_name = auth
    try:
        eco = await find_economy_user(login_name)
    except HTTPException:
        eco = None
    player = (eco or {}).get("name") or user
    if is_dry_run():
        game.seed_wallet(player, pika_coin=coin_amount(eco))
    else:
        # Tiền thật: Coin in-game là nguồn sự thật — mirror số dư server xuống ví web.
        # `eco` đã mang sẵn số dư nên không cần hỏi server lần thứ hai; chỉ khi
        # không tìm được bản ghi economy mới phải tra cứu theo tên thật.
        # Lỗi mạng không được biến thành 0 (sẽ khóa nhầm người chơi), nên giữ số dư
        # cache và báo lỗi riêng.
        try:
            if eco is not None:
                store.set_wallet(player, round(coin_amount(eco)))
                bank.mark_synced(player)
            else:
                await bank.sync(player)
        except (HTTPException, MoneyError):
            pass
    money = game.balance(player)
    return {
        "user": user,
        "login_name": login_name,
        "player": player,
        "eco": eco,
        "pika": coin_amount(eco),
        "pika_fmt": format_coin(coin_amount(eco)),
        "money": money,
        "money_fmt": format_coin(money),
        "held": len(store.list_inventory(player, "held")),
        "last_seen": format_last_seen((eco or {}).get("last_seen")),
    }


def require_csrf(request: Request) -> bool:
    sent = request.headers.get("x-csrf")
    expected = request.session.get("csrf")
    if not isinstance(sent, str) or not isinstance(expected, str) or not sent or not expected:
        return False
    return hmac.compare_digest(sent, expected)


def api_auth(request: Request, *, csrf: bool = False) -> str | JSONResponse:
    user = request.session.get("user")
    if not user:
        return JSONResponse({"detail": "Chưa đăng nhập."}, status_code=401)
    if csrf and not require_csrf(request):
        return JSONResponse({"detail": "Phiên hết hạn, tải lại trang."}, status_code=403)
    return user


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Trang chủ (landing page) — giới thiệu dự án cho khách chưa đăng nhập."""
    ctx = await optional_ctx(request)
    live = await liveplayers.snapshot()
    return render(
        request,
        "landing.html",
        **ctx,
        cases=[case_view(item) for item in load_cases()],
        site=game.site_stats_bar(online=live["online"]),
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None, next: str | None = None):
    if request.session.get("user"):
        return RedirectResponse(safe_next(next), status_code=303)
    token = new_csrf_token()
    request.session["csrf"] = token
    return render(
        request,
        "login.html",
        csrf=token,
        error=error,
        pika_ready=pika_ready(),
        next_url=safe_next(next),
        need_login=bool(next),
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(...),
    next: str = Form(""),
):
    if not pika_ready():
        return RedirectResponse("/login?error=setup", status_code=303)
    ip = client_ip(request)
    if csrf != request.session.get("csrf"):
        return RedirectResponse("/login?error=phien", status_code=303)
    if not login_allowed(ip):
        return RedirectResponse("/login?error=rate", status_code=303)
    username = username.strip()
    if not username or not password:
        record_failed_login(ip)
        return RedirectResponse("/login?error=sai", status_code=303)
    try:
        row = await find_authme_user(username)
    except HTTPException:
        return RedirectResponse("/login?error=pika", status_code=303)
    stored = (row or {}).get("password")
    if row is None or not verify_authme_sha256(password, str(stored or "")):
        record_failed_login(ip)
        return RedirectResponse("/login?error=sai", status_code=303)
    request.session.clear()
    request.session["user"] = row.get("realname") or row.get("username")
    request.session["login_name"] = row.get("username")
    request.session["csrf"] = new_csrf_token()
    # Dang nhap thanh cong -> xoa gioi han so lan that bai cua IP nay.
    clear_failed_logins(ip)
    return RedirectResponse(safe_next(next), status_code=303)


@app.post("/logout")
async def logout(request: Request):
    if not is_same_origin(request):
        return JSONResponse({"detail": "Nguồn yêu cầu không hợp lệ."}, status_code=403)
    request.session.clear()
    return RedirectResponse("/gacha", status_code=303)


@app.get("/gacha", response_class=HTMLResponse)
async def catalogue(request: Request):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    last_bonus = store.last_bonus(ctx["player"])
    bonus_ready = (not last_bonus) or (store.now() - last_bonus >= 24 * 3600)
    live = await liveplayers.snapshot()
    return render(
        request,
        "catalogue.html",
        **ctx,
        cases=[case_view(item) for item in load_cases()],
        site=game.site_stats_bar(online=live["online"]),
        bonus_ready=bonus_ready,
    )


@app.get("/case/{slug}", response_class=HTMLResponse)
async def case_page(request: Request, slug: str):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    case = get_case(slug)
    if not case:
        return RedirectResponse("/gacha", status_code=303)
    view = case_view(case)
    return render(
        request,
        "case.html",
        **ctx,
        case=view,
        pool_json=json.dumps([item.as_public() for item in case.items], ensure_ascii=False),
    )


@app.post("/api/case/{slug}/open")
async def open_case(request: Request, slug: str):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    count = 1
    try:
        body = await read_json_dict(request)
        if "count" in body:
            # `parse_int` -> `count` sai (chuỗi, số thực...) trả 400 thay vì
            # bị nuốt âm thầm thành 1 (người chơi tưởng mở 5 lượt, thực ra
            # chỉ mở 1 và vẫn bị tính tiền).
            count = parse_int(body.get("count"), 1, field="Số lượng mở")
    except game.GameError as exc:
        return json_error(exc)
    case = get_case(slug)
    if not case:
        return JSONResponse({"detail": "Không có rương này."}, status_code=404)
    if count not in (1, 2, 3, 4, 5):
        return JSONResponse({"detail": "Số lượng mở không hợp lệ (1-5)."}, status_code=400)
    total_cost = case.pull_cost * count

    # --- Tiền thật: trừ Coin in-game TRƯỚC, xong mới trao đồ -------------
    # Thứ tự này đảm bảo người chơi không bao giờ nhận đồ khi tiền chưa bị trừ.
    # Nếu trừ tiền thất bại thì dừng luôn, không roll đồ.
    if not is_dry_run():
        try:
            await bank.take(user, total_cost)
        except MoneyError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=402)
        except HTTPException as exc:
            return JSONResponse({"detail": str(exc.detail)}, status_code=503)

    try:
        batch = game.open_case_batch(user, slug, count=count)
    except game.GameError as exc:
        # Đã trừ tiền thật nhưng không mở được → hoàn lại ngay.
        if not is_dry_run():
            try:
                await bank.give(user, total_cost)
            except (MoneyError, HTTPException):
                pass
        return json_error(exc)
    except Exception as exc:
        log.exception("open_case loi bat ngo cho %s", user)
        if not is_dry_run():
            try:
                await bank.give(user, total_cost)
            except (MoneyError, HTTPException):
                pass
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thử lại."}, status_code=500)

    openings_resp = []
    for op in batch.openings:
        openings_resp.append({
            "winner": op["winner"],
            "inventory_id": op["inventory_id"],
            "winner_coin": op["winner_coin"],
            "winner_coin_fmt": format_coin(op["winner_coin"]),
        })
    first = openings_resp[0]
    if not is_dry_run():
        await bank.sync(user)
    return {
        "winner": first["winner"],
        "inventory_id": first["inventory_id"],
        "winner_coin_fmt": first["winner_coin_fmt"],
        "openings": openings_resp,
        "count": count,
        "total_cost": batch.total_cost,
        "total_cost_fmt": format_coin(batch.total_cost),
        "pool": batch.pool,
        "dry_run": batch.dry_run,
        "balance_fmt": format_coin(batch.balance),
        "balance": batch.balance,
    }


@app.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    held = [inv_view(row) for row in store.list_inventory(ctx["player"], "held")]
    for row in held:
        meta = find_listing(row.get("item_id", ""), int(row.get("value") or 0))
        row["nexo_id"] = meta.nexo_id if meta else ""
    worth = sum(row["value"] for row in held)
    return render(
        request,
        "inventory.html",
        **ctx,
        items=held,
        worth_fmt=format_coin(worth),
        nexo_withdraw_enabled=is_nexo_withdraw_enabled(),
    )


@app.post("/api/inventory/sell")
async def inventory_sell(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    lock = _inventory_locks.setdefault(user, asyncio.Lock())
    async with lock:
        try:
            body = await read_json_dict(request)
            raw_ids = body.get("ids") or []
            if not isinstance(raw_ids, list):
                raise game.GameError("Danh sách món không hợp lệ.", 400)
            ids = [parse_int(x, field="ID món") for x in raw_ids]
            # Tiền thật: cộng Coin in-game TRƯỚC, xong mới đánh dấu đồ đã bán.
            # Nếu cộng tiền thất bại thì đồ vẫn còn trong túi — người chơi không mất gì.
            amount = game.sell_preview(user, ids)
            if not is_dry_run():
                try:
                    await bank.give(user, amount)
                except MoneyError as exc:
                    return JSONResponse({"detail": str(exc)}, status_code=503)
                except HTTPException as exc:
                    return JSONResponse({"detail": str(exc.detail)}, status_code=503)
            result = game.sell_items(user, ids)
            if not is_dry_run():
                await bank.sync(user)
                result["balance"] = store.get_balance(user)
            return {
                **result,
                "amount_fmt": format_coin(result["amount"]),
                "balance_fmt": format_coin(result["balance"]),
            }
        except game.GameError as exc:
            return json_error(exc)


@app.post("/api/inventory/sell-all")
async def inventory_sell_all(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    lock = _inventory_locks.setdefault(user, asyncio.Lock())
    async with lock:
        try:
            held = store.list_inventory(user, "held")
            ids = [row["id"] for row in held]
            amount = game.sell_preview(user, ids)
            if not is_dry_run() and amount > 0:
                try:
                    await bank.give(user, amount)
                except (MoneyError, HTTPException):
                    raise
            result = game.sell_items(user, ids)
            if not is_dry_run():
                await bank.sync(user)
                result["balance"] = store.get_balance(user)
            return {
                **result,
                "amount_fmt": format_coin(result["amount"]),
                "balance_fmt": format_coin(result["balance"]),
            }
        except game.GameError as exc:
            return json_error(exc)
        except MoneyError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=503)
        except HTTPException as exc:
            return JSONResponse({"detail": str(exc.detail)}, status_code=503)


@app.post("/api/inventory/withdraw")
async def inventory_withdraw(request: Request):
    """Rút vật phẩm trong túi vào server Minecraft qua lệnh `nexo give`."""
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    if not is_nexo_withdraw_enabled():
        return JSONResponse({"detail": "Tính năng rút đồ Nexo chưa bật."}, status_code=503)
    if is_dry_run():
        return JSONResponse({"detail": "Không thể rút đồ khi đang bật chế độ dry-run."}, status_code=400)
    lock = _inventory_locks.setdefault(user, asyncio.Lock())
    async with lock:
        try:
            body = await read_json_dict(request)
            item_pk = parse_int(body.get("id"), field="ID món")
            row = store.get_inventory_item(item_pk)
            if not row or row["player"] != user:
                raise game.GameError("Không phải đồ của bạn.", 403)
            if row["status"] != "held":
                raise game.GameError(f"{row['name']} không còn trong túi.", 400)
            meta = find_listing(row["item_id"], int(row["value"]))
            if not meta or not meta.nexo_id:
                raise game.GameError("Món này chưa gắn nexo_id trong gacha.json.", 400)
            await nexo_give_item(user, meta.nexo_id, meta.nexo_amount)
            try:
                store.claim_inventory_status(user, [item_pk], "withdrawn")
            except ValueError as exc:
                raise game.GameError(str(exc), 409) from exc
            return {
                "withdrawn": True,
                "id": item_pk,
                "nexo_id": meta.nexo_id,
                "amount": meta.nexo_amount,
            }
        except game.GameError as exc:
            return json_error(exc)
        except MoneyError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        except HTTPException as exc:
            return JSONResponse({"detail": str(exc.detail)}, status_code=503)


@app.get("/upgrade", response_class=HTMLResponse)
async def upgrade_page(request: Request):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    held = [inv_view(row) for row in store.list_inventory(ctx["player"], "held")]
    return render(request, "upgrade.html", **ctx, items=held)


@app.get("/api/upgrade/targets")
async def upgrade_targets(request: Request, value: int = 0):
    user = api_auth(request)
    if isinstance(user, JSONResponse):
        return user
    targets = game.upgrade_targets(value)
    for row in targets:
        row["coin_fmt"] = format_coin(row["coin"])
    return {"targets": targets}


@app.post("/api/upgrade")
async def upgrade_run(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        body = await read_json_dict(request)
        # Hỗ trợ cả 1 món (`inventory_id`) và nhiều món (`inventory_ids` —
        # cơ chế 2 món lên 1 món). Ưu tiên `inventory_ids` khi có mặt.
        raw_ids = body.get("inventory_ids")
        if raw_ids is None:
            inv_id = body.get("inventory_id")
            if inv_id is None:
                raise game.GameError("Chưa chọn món nào.", 400)
            inv_ids = [parse_int(inv_id, field="inventory_id")]
        else:
            if not isinstance(raw_ids, list):
                raise game.GameError("inventory_ids không hợp lệ.", 400)
            if not raw_ids:
                raise game.GameError("Chọn ít nhất 1 món cược.", 400)
            if len(raw_ids) > game.UPGRADE_MAX_STAKES:
                raise game.GameError(
                    f"Chỉ nâng cấp tối đa {game.UPGRADE_MAX_STAKES} món cược mỗi lần.", 400
                )
            inv_ids = [parse_int(x, field="inventory_id") for x in raw_ids]

        result = game.do_upgrade(
            user,
            inv_ids,
            str(body.get("target_id") or ""),
            parse_int(body.get("target_coin"), 0, field="target_coin"),
        )
        result["balance_fmt"] = format_coin(result["balance"])
        result["target"]["coin_fmt"] = format_coin(result["target"]["coin"])
        return result
    except game.GameError as exc:
        return json_error(exc)
    except Exception:
        # Không trả raw `str(exc)` cho client — log server-side rồi trả lỗi
        # chung. Nâng cấp là luồng tiền/đồ nên lỗi 500 phải an toàn.
        log.exception("api_upgrade loi bat ngo cho %s", user)
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thử lại."}, status_code=500)


@app.get("/battles", response_class=HTMLResponse)
async def battles_page(request: Request):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    lobby = store.list_battles()
    return render(
        request,
        "battles.html",
        **ctx,
        cases=[case_view(item) for item in load_cases()],
        open_battles=[battle_view(row) for row in lobby["open"]],
        finished=[battle_view(row) for row in lobby["finished"]],
    )


@app.get("/battles/{battle_id}", response_class=HTMLResponse)
async def battle_page(request: Request, battle_id: int):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    battle = store.get_battle(battle_id)
    if not battle:
        return RedirectResponse("/battles", status_code=303)
    return render(
        request,
        "battle.html",
        **ctx,
        battle=battle_view(battle),
        battle_json=json.dumps(battle_view(battle), ensure_ascii=False),
        cases=[case_view(item) for item in load_cases()],
    )


@app.get("/api/battles")
async def battles_list():
    lobby = store.list_battles()
    return {
        "open": [battle_view(row) for row in lobby["open"]],
        "finished": [battle_view(row) for row in lobby["finished"]],
    }


@app.post("/api/battles")
async def battles_create(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        body = await read_json_dict(request)
        case_id = str(body.get("case_id") or "")
        rounds = parse_int(body.get("rounds"), 1, field="rounds")
        slots = parse_int(body.get("slots"), 2, field="slots")
        # Chuẩn web gốc: cho phép gửi playlist lines [{case_id, count}].
        raw_lines = body.get("lines") or body.get("cases")
        norm = game.battle_lines_normalize(raw_lines, case_id, rounds)
        paid = game.battle_entry_price(norm)
    except game.GameError as exc:
        return json_error(exc)
    try:
        # Tiền thật: trừ Coin in-game TRƯỚC khi tạo trận.
        if not is_dry_run():
            try:
                await bank.take(user, paid)
            except MoneyError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=402)
            except HTTPException as exc:
                return JSONResponse({"detail": str(exc.detail)}, status_code=503)
        try:
            battle = game.create_battle(
                user,
                norm[0]["case_id"],
                slots,
                sum(int(line["count"]) for line in norm),
                str(body.get("mode") or "STANDARD"),
                lines=norm,
            )
        except game.GameError as exc:
            if not is_dry_run():
                try:
                    await bank.give(user, paid)
                except (MoneyError, HTTPException):
                    pass
            return json_error(exc)
        if body.get("fill_bots"):
            battle = game.fill_bots(battle["id"], user)
        if not is_dry_run():
            await bank.sync(user)
        return battle_view(battle)
    except game.GameError as exc:
        return json_error(exc)


@app.post("/api/battles/{battle_id}/leave")
async def battles_leave(request: Request, battle_id: int):
    """Rời phòng khi còn WAITING + hoàn tiền ghế (vấn đề 2)."""
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    battle = store.get_battle(battle_id)
    if not battle:
        return JSONResponse({"detail": "Không có trận này."}, status_code=404)
    row = next((r for r in battle.get("players") or [] if r["player"] == user), None)
    if not row:
        return JSONResponse({"detail": "Bạn không ở trong phòng này."}, status_code=400)
    paid = int(row.get("paid") or 0)
    try:
        result = game.leave_battle(user, battle_id)
    except game.GameError as exc:
        return json_error(exc)
    # Tiền thật: hoàn Coin in-game cho người rời.
    if not is_dry_run() and paid > 0:
        try:
            await bank.give(user, paid)
        except (MoneyError, HTTPException):
            pass
        await bank.sync(user)
        result["balance"] = store.get_balance(user)
    if result.get("deleted"):
        return {"deleted": True, "id": battle_id, "balance": result.get("balance", 0)}
    return battle_view(result.get("battle") or {})


@app.post("/api/battles/{battle_id}/cancel")
async def battles_cancel(request: Request, battle_id: int):
    """Host hủy phòng WAITING + hoàn tiền cho mọi người (vấn đề 2)."""
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    battle = store.get_battle(battle_id)
    if not battle:
        return JSONResponse({"detail": "Không có trận này."}, status_code=404)
    try:
        result = game.cancel_battle(user, battle_id)
    except game.GameError as exc:
        return json_error(exc)
    if not is_dry_run():
        for member in result.get("refunded") or []:
            if member.get("is_bot"):
                continue
            amount = int(member.get("paid") or 0)
            if amount > 0:
                try:
                    await bank.give(member["player"], amount)
                except (MoneyError, HTTPException):
                    pass
        await bank.sync(user)
    return {"cancelled": True, "id": battle_id}


@app.post("/api/battles/{battle_id}/kick")
async def battles_kick(request: Request, battle_id: int):
    """Host đá bot khỏi phòng WAITING (vấn đề 2)."""
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        body = await request.json()
    except Exception:
        body = {}
    target = str((body or {}).get("player") or "")
    try:
        battle = game.kick_battle_bot(user, battle_id, target)
    except game.GameError as exc:
        return json_error(exc)
    return battle_view(battle)


@app.post("/api/battles/{battle_id}/config")
async def battles_config(request: Request, battle_id: int):
    """Host đổi rương / vòng / ghế / chế độ khi phòng còn WAITING (vấn đề 2).

    Web gốc: tạo phòng trước, vào phòng mới chọn rương + số người.
    Chuẩn mới: nhận thêm `lines` [{case_id, count}] để ghép nhiều rương.
    """
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        body = await read_json_dict(request)
        slug = str(body.get("case_id") or "")
        rounds = parse_int(body.get("rounds"), 1, field="rounds")
        slots = parse_int(body.get("slots"), 2, field="slots")
        mode = str(body.get("mode") or "STANDARD")
        raw_lines = body.get("lines") or body.get("cases")
    except game.GameError as exc:
        return json_error(exc)
    battle = store.get_battle(battle_id)
    if not battle:
        return JSONResponse({"detail": "Không có trận này."}, status_code=404)
    if battle["status"] != "WAITING":
        return JSONResponse({"detail": "Trận đã bắt đầu, không đổi được cấu hình."}, status_code=400)
    if battle.get("host") != user:
        return JSONResponse({"detail": "Chỉ chủ phòng mới đổi được cấu hình."}, status_code=403)
    try:
        norm = game.battle_lines_normalize(raw_lines, slug, rounds)
        new_paid = game.battle_entry_price(norm)
    except game.GameError as exc:
        return json_error(exc)
    others = [r for r in battle.get("players") or [] if r["player"] != user]
    host_row = next((r for r in battle.get("players") or [] if r["player"] == user), None)
    host_old = int((host_row or {}).get("paid") or 0)
    host_diff = new_paid - host_old
    # Tiền thật: không tự trừ thêm tiền của người khác khi chưa đồng ý.
    # Đã có người ngồi thì chỉ được đổi sang cấu hình rẻ hơn hoặc bằng.
    if others and new_paid > min(int(r.get("paid") or 0) for r in others):
        return JSONResponse(
            {"detail": "Đã có người ngồi, chỉ đổi sang rương rẻ hơn hoặc bằng để không trừ thêm tiền họ."},
            status_code=400,
        )
    if not is_dry_run() and host_diff > 0:
        try:
            await bank.take(user, host_diff)
        except MoneyError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=402)
        except HTTPException as exc:
            return JSONResponse({"detail": str(exc.detail)}, status_code=503)
    try:
        updated = game.update_battle_setup(
            user, battle_id, norm[0]["case_id"],
            sum(int(line["count"]) for line in norm), slots, mode, lines=norm,
        )
    except game.GameError as exc:
        if not is_dry_run() and host_diff > 0:
            try:
                await bank.give(user, host_diff)
            except (MoneyError, HTTPException):
                pass
        return json_error(exc)
    if not is_dry_run():
        # Hoàn chênh lệch cho host (nếu rẻ hơn) + mọi người ngồi cùng.
        for r in others:
            refund = int(r.get("paid") or 0) - new_paid
            if refund > 0:
                try:
                    await bank.give(r["player"], refund)
                except (MoneyError, HTTPException):
                    pass
        if host_diff < 0:
            try:
                await bank.give(user, -host_diff)
            except (MoneyError, HTTPException):
                pass
        await bank.sync(user)
    return battle_view(updated)


@app.post("/api/battles/{battle_id}/rematch")
async def battles_rematch(request: Request, battle_id: int):
    """Đánh tiếp ván mới sau khi trận cũ xong (vấn đề 2).

    Tạo phòng WAITING mới giữ nguyên số ghế, cho phép chọn lại rương.
    """
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        body = await read_json_dict(request)
        slug = str(body.get("case_id") or "")
        rounds = parse_int(body.get("rounds"), 1, field="rounds")
        mode = str(body.get("mode") or "STANDARD")
        raw_lines = body.get("lines") or body.get("cases")
    except game.GameError as exc:
        return json_error(exc)
    old = store.get_battle(battle_id)
    if not old:
        return JSONResponse({"detail": "Không có trận này."}, status_code=404)
    try:
        norm = game.battle_lines_normalize(raw_lines, slug, rounds)
        paid = game.battle_entry_price(norm)
    except game.GameError as exc:
        return json_error(exc)
    if not is_dry_run():
        try:
            await bank.take(user, paid)
        except MoneyError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=402)
        except HTTPException as exc:
            return JSONResponse({"detail": str(exc.detail)}, status_code=503)
    try:
        new_battle = game.rematch_battle(
            user, battle_id, norm[0]["case_id"],
            sum(int(line["count"]) for line in norm), mode, lines=norm,
        )
    except game.GameError as exc:
        if not is_dry_run():
            try:
                await bank.give(user, paid)
            except (MoneyError, HTTPException):
                pass
        return json_error(exc)
    if body.get("fill_bots"):
        new_battle = game.fill_bots(new_battle["id"], user)
    if not is_dry_run():
        await bank.sync(user)
    return battle_view(new_battle)


@app.post("/api/battles/{battle_id}/join")
async def battles_join(request: Request, battle_id: int):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        battle = store.get_battle(battle_id)
        if not battle:
            return JSONResponse({"detail": "Không có trận này."}, status_code=404)
        if battle["status"] != "WAITING":
            return JSONResponse({"detail": "Trận đã bắt đầu."}, status_code=400)
        paid = game.battle_paid_of(battle)

        # Tiền thật: trừ Coin in-game TRƯỚC khi ngồi vào trận.
        if not is_dry_run():
            try:
                await bank.take(user, paid)
            except MoneyError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=402)
            except HTTPException as exc:
                return JSONResponse({"detail": str(exc.detail)}, status_code=503)
        try:
            battle = game.join_existing_battle(user, battle_id)
        except game.GameError as exc:
            if not is_dry_run():
                try:
                    await bank.give(user, paid)
                except (MoneyError, HTTPException):
                    pass
            return json_error(exc)
        if not is_dry_run():
            await bank.sync(user)
        return battle_view(battle)
    except game.GameError as exc:
        return json_error(exc)


@app.post("/api/battles/{battle_id}/bots")
async def battles_bots(request: Request, battle_id: int):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        return battle_view(game.fill_bots(battle_id, user))
    except game.GameError as exc:
        return json_error(exc)


@app.post("/api/battles/{battle_id}/start")
async def battles_start(request: Request, battle_id: int):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        return battle_view(game.start_battle(battle_id, user))
    except game.GameError as exc:
        return json_error(exc)


@app.get("/api/battles/{battle_id}")
async def battles_get(request: Request, battle_id: int):
    battle = store.get_battle(battle_id)
    if not battle:
        return JSONResponse({"detail": "Không có trận này."}, status_code=404)
    return battle_view(battle)


@app.get("/api/drops")
async def api_drops():
    drops = store.recent_drops(30)
    for row in drops:
        row["value_fmt"] = format_coin(row["value"])
    best = max(drops, key=lambda row: row["value"]) if drops else None
    return {"drops": drops, "best": best}


@app.get("/api/admins")
async def api_admins():
    """Danh sách quản trị viên, đọc realtime từ OP trên server PikaMC."""
    return {"admins": await admins.admin_list()}


@app.get("/api/online")
async def api_online():
    """Số người đang online trên server Minecraft, đọc từ PikaMC.

    Công khai (không cần đăng nhập) vì đây là số liệu server, không phải dữ
    liệu người chơi. Có cache TTL ngắn phía server nên poll nhiều tab không
    bắn mỗi tab một request ra hosting.
    """
    live = await liveplayers.snapshot()
    return {
        "online": live["online"],
        "max": live["max"],
        "players": live["players"],
    }


@app.post("/api/chat")
async def api_chat(request: Request):
    """Tro ly tra loi cau hoi ve lenh console cua nguoi choi.

    Công khai vì chỉ tra lời về lệnh console (dữ liệu công khai của server),
    không đụng tới dữ liệu người chơi. Nhưng vẫn nhận CSRF token để chặn
    việc site khác lén gọi từ trình duyệt của người dùng.

    Trả về: `{"reply", "commands": [{name, desc, admin_only}], "source"}`.
    """
    try:
        payload = await read_json_dict(request)
    except game.GameError:
        return JSONResponse({"detail": "Dữ liệu gửi lên không hợp lệ."}, status_code=400)
    question = str(payload.get("q") or payload.get("question") or "").strip()
    if not question:
        return JSONResponse({"detail": "Câu hỏi trống."}, status_code=400)
    if len(question) > 500:
        question = question[:500]

    auth = api_auth(request, csrf=True)
    if isinstance(auth, JSONResponse):
        return auth

    # Gioi han so cau hoi theo IP: endpoint cong khai, va khi bat Claude API
    # moi cau hoi deu ton tien. Khong gioi han -> mot nguoi spam se lam hao
    # chi phi API cho ca may chu.
    ip = client_ip(request)
    if not chat_rate_allowed(ip):
        return JSONResponse(
            {"detail": "Bạn hỏi hơi nhiều. Chờ một chút rồi thử lại nhé."},
            status_code=429,
        )
    record_chat_request(ip)

    try:
        result = await chatbot.answer(question)
    except Exception:
        # Không trả lỗi nội bộ ra ngoài — chỉ log.
        log.exception("chatbot loi")
        return JSONResponse({"detail": "Trợ lý đang bận, thử lại sau."}, status_code=503)
    return result


@app.get("/api/balance")
async def api_balance(request: Request):
    """Số dư Coin realtime của người đang đăng nhập.

    Frontend gọi định kỳ để chip số dư trên header cập nhật theo Coin in-game.
    Dùng `sync_fresh` nên poll nhiều người cùng lúc không dồn request ra server.
    """
    user = request.session.get("user")
    if not user:
        return JSONResponse({"detail": "Chưa đăng nhập."}, status_code=401)
    balance = await bank.sync_fresh(user)
    return {
        "balance": round(balance),
        "balance_fmt": format_coin(balance),
        "player": user,
    }


@app.get("/bonus", response_class=HTMLResponse)
async def bonus_page(request: Request):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    last_bonus = store.last_bonus(ctx["player"])
    bonus_ready = (not last_bonus) or (store.now() - last_bonus >= 24 * 3600)
    slices = [{"amount": amount, "weight": weight} for amount, weight in game.BONUS_SLICES]
    return render(
        request,
        "bonus.html",
        **ctx,
        bonus_ready=bonus_ready,
        slices_json=json.dumps(slices),
    )


@app.post("/api/bonus")
async def api_bonus(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    lock = _bonus_locks.setdefault(user, asyncio.Lock())
    async with lock:
        try:
            # Tiền thật: roll giải + cộng Coin in-game TRƯỚC, xong mới commit
            # lần nhận. Nếu lệnh console fail thì lượt bonus chưa bị dùng.
            prize = game.bonus_preview(user)
            if not is_dry_run():
                try:
                    await bank.give(user, prize)
                except (MoneyError, HTTPException) as exc:
                    return JSONResponse({"detail": f"Cộng bonus thất bại: {exc}"}, status_code=503)
            result = game.claim_bonus(user, prize)
            if not is_dry_run():
                await bank.sync(user)
                result["balance"] = store.get_balance(user)
            return {
                **result,
                "amount_fmt": format_coin(result["amount"]),
                "balance_fmt": format_coin(result["balance"]),
            }
        except game.GameError as exc:
            return json_error(exc)


@app.get("/roulette", response_class=HTMLResponse)
async def roulette_page(request: Request):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    state = roulette_manager.get_state(ctx.get("player"))
    return render(
        request,
        "roulette.html",
        **ctx,
        roulette_state=state,
        state_json=json.dumps(state, ensure_ascii=False),
    )


@app.get("/api/roulette/state")
async def api_roulette_state(request: Request):
    user = api_auth(request)
    if isinstance(user, JSONResponse):
        return user
    state = roulette_manager.get_state(user)
    return state


@app.post("/api/roulette/bet")
async def api_roulette_bet(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        body = await read_json_dict(request)
        side = str(body.get("side") or "").strip().lower()
        amount = parse_int(body.get("amount"), 0, field="amount")

        # Tiền thật: trừ Coin in-game TRƯỚC khi chốt cược.
        # `place_bet` chỉ ghi sổ ví web, nên nếu trừ tiền thật sau thì lệnh
        # console fail sẽ để lại cược "ảo" trong vòng quay.
        if not is_dry_run():
            try:
                await bank.take(user, amount)
            except MoneyError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=402)
            except HTTPException as exc:
                return JSONResponse({"detail": str(exc.detail)}, status_code=503)
        try:
            res = roulette_manager.place_bet(user, side, amount, is_bot=False)
        except Exception:
            if not is_dry_run():
                try:
                    await bank.give(user, amount)
                except (MoneyError, HTTPException):
                    pass
            raise
        if not is_dry_run():
            await bank.sync(user)
            res["balance"] = store.get_balance(user)
        return {
            **res,
            "amount_fmt": format_coin(res["amount"]),
            "balance_fmt": format_coin(res["balance"]),
        }
    except game.GameError as exc:
        return json_error(exc)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("api_roulette_bet loi bat ngo cho %s", user)
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thử lại."}, status_code=500)


@app.get("/vi", response_class=HTMLResponse)
async def wallet(request: Request):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    txs = store.recent_tx(ctx["player"], 20)
    for row in txs:
        row["when"] = datetime.fromtimestamp(row["created_at"], tz=VN_TZ).strftime("%d/%m %H:%M")
        row["amount_fmt"] = format_coin(row["amount"])
        row["kind_label"] = KIND_LABELS.get(row["kind"], row["kind"])
    return render(request, "wallet.html", **ctx, txs=txs)


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    if not require_admin(request):
        return RedirectResponse("/gacha", status_code=303)
    data = store.stats()
    for row in data["recent"]:
        row["when"] = datetime.fromtimestamp(row["created_at"], tz=VN_TZ).strftime("%d/%m %H:%M")
        row["prize_fmt"] = format_coin(row["prize_coin"])
    for row in data["by_rarity"]:
        row["paid_fmt"] = format_coin(row["paid"])
    for row in data["top"]:
        row["spent_fmt"] = format_coin(row["spent"])
    return render(
        request,
        "admin.html",
        **ctx,
        cost=format_coin(pull_cost()),
        stats=data,
        spent=format_coin(data["spent"]),
        paid=format_coin(data["paid"]),
        net=format_coin(data["net"]),
        admins=await admins.admin_list(),
    )


# ---------------------------------------------------------------------------
#  Admin — quan tri san pham (item) cua catalogue
# ---------------------------------------------------------------------------


@app.get("/pika/tex/{encoded}")
async def pika_texture(encoded: str):
    """Proxy texture NexoMC tu server Minecraft.

    `encoded` la `nexo_id` duoc base64url hoa (khong co padding). Server tu
    trai ten voi duong dan that cua texture, nen web khong can biet cau truc
    thu muc `assets/` cua resource pack.

    Neu texture khong ton tai tren server -> tra ve anh placeholder thay vi
    404. Ly do: trinh duyet se bao loi "Failed to load resource" trong console
    khi anh khong tai duoc, va do la loi JS console (bi test chan).
    """
    from base64 import urlsafe_b64decode

    from . import pika_textures

    if len(encoded) > 256:
        return JSONResponse({"detail": "Mã texture không hợp lệ."}, status_code=400)
    try:
        padding = "=" * (-len(encoded) % 4)
        nexo_id = urlsafe_b64decode(encoded + padding).decode("utf-8")
    except Exception:
        return JSONResponse({"detail": "Mã texture không hợp lệ."}, status_code=400)
    if not re.fullmatch(r"^[A-Za-z0-9_:/.-]{1,128}$", nexo_id) or ".." in nexo_id:
        return JSONResponse({"detail": "Mã texture không hợp lệ."}, status_code=400)

    try:
        # Timeout ngan: khi server Minecraft khong phan hoi, `resolve_nexo_id`
        # se treo rat lau -> chan trai anh cho nguoi choi. Sau timeout tra ve
        # placeholder thay vi doi request.
        path = await asyncio.wait_for(
            pika_textures.resolve_nexo_id(nexo_id), timeout=PIKA_TEX_TIMEOUT
        )
    except asyncio.TimeoutError:
        log.warning("timeout khi resolve texture %s", nexo_id)
        path = None
    except Exception:
        log.warning("khong resolve duoc texture %s", nexo_id, exc_info=True)
        path = None
    if not path:
        # Fallback: thu doi duong dan theo thu muc pack.
        return _placeholder_texture()
    try:
        result = await asyncio.wait_for(
            pika.read_binary(path), timeout=PIKA_TEX_TIMEOUT
        )
    except asyncio.TimeoutError:
        log.warning("timeout khi tai texture %s", path)
        return _placeholder_texture()
    except HTTPException:
        raise
    except Exception:
        log.warning("khong tai duoc texture %s", path, exc_info=True)
        return _placeholder_texture()
    if not result:
        return _placeholder_texture()
    content, content_type = result
    ct = (content_type or "").split(";")[0].strip().lower()
    safe_media_type = ct if ct in {"image/png", "image/webp", "image/jpeg"} else "image/png"
    return Response(
        content=content,
        media_type=safe_media_type,
        headers={"Cache-Control": "public, max-age=300"},
    )


def _placeholder_texture() -> Response:
    """Anh placeholder khi texture tren server khong ton tai."""
    path = STATIC_DIR / "items" / "_placeholder.svg"
    try:
        content = path.read_bytes()
    except OSError:
        content = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
            b'<rect width="64" height="64" fill="#2a2f3a"/></svg>'
        )
    return Response(
        content=content,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/admin/products", response_class=HTMLResponse)
async def admin_products_page(request: Request):
    """Trang quan tri san pham: danh sach item, them / sua / xoa, upload anh."""
    ctx = await require_player(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    if not require_admin(request):
        return RedirectResponse("/gacha", status_code=303)
    try:
        cases = catalog_admin.list_cases()
        items = catalog_admin.list_items()
    except catalog_admin.CatalogError as exc:
        cases, items = [], []
        catalog_error = str(exc)
        log.warning("khong doc duoc catalogue: %s", exc)
    else:
        catalog_error = ""
    for row in items:
        row["image_url"] = _item_image_url(row)
        row["coin_fmt"] = format_coin(row.get("coin"))
        row["weight_pct"] = row.get("_pct")
    return render(
        request,
        "admin_products.html",
        **ctx,
        cases=cases,
        items=items,
        rarities=catalog_admin.RARITIES,
        catalog_error=catalog_error,
    )


def _item_image_url(row: dict) -> str:
    """Duong dan anh hien thi cua item.

    Uu tien `image` explicit (duong dan noi bo). Neu khong co, dung proxy
    `/pika/tex/<base64 nexo_id>` de web tu tai texture tu server.
    """
    explicit = str(row.get("image") or "").strip()
    if explicit.startswith("/static/") or explicit.startswith("/pika/tex/"):
        return explicit
    nexo_id = str(row.get("nexo_id") or "").strip()
    if nexo_id:
        from base64 import urlsafe_b64encode
        encoded = urlsafe_b64encode(nexo_id.encode()).decode().rstrip("=")
        return f"/pika/tex/{encoded}"
    return "/static/items/_placeholder.svg"


@app.get("/api/admin/products")
async def api_admin_products(request: Request):
    """Danh sach item (loc theo `case` neu co)."""
    err = require_admin_api(request, csrf=False)
    if err:
        return err
    try:
        case_id = request.query_params.get("case") or None
        items = catalog_admin.list_items(case_id)
        for row in items:
            row["image_url"] = _item_image_url(row)
        return {"items": items, "cases": catalog_admin.list_cases()}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@app.post("/api/admin/products")
async def api_admin_product_create(request: Request):
    """Them san pham moi vao ruong."""
    err = require_admin_api(request)
    if err:
        return err
    try:
        body = await read_json_dict(request)
        case_id = str(body.get("case_id") or "").strip()
        if not case_id:
            raise catalog_admin.CatalogError("Thiếu rương đích.")
        item = catalog_admin.create_item(case_id, body)
        item["image_url"] = _item_image_url(item)
        return {"ok": True, "item": item}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("tao san pham that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thử lại."}, status_code=500)


@app.put("/api/admin/products/{case_id}/{item_id}")
async def api_admin_product_update(request: Request, case_id: str, item_id: str):
    """Sua san pham."""
    err = require_admin_api(request)
    if err:
        return err
    try:
        body = await read_json_dict(request)
        item = catalog_admin.update_item(case_id, item_id, body)
        item["image_url"] = _item_image_url(item)
        return {"ok": True, "item": item}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("sua san pham that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thử lại."}, status_code=500)


@app.delete("/api/admin/products/{case_id}/{item_id}")
async def api_admin_product_delete(request: Request, case_id: str, item_id: str):
    """Xoa san pham khoi ruong."""
    err = require_admin_api(request)
    if err:
        return err
    try:
        catalog_admin.delete_item(case_id, item_id)
        return {"ok": True}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("xoa san pham that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thử lại."}, status_code=500)


@app.put("/api/admin/cases/{case_id}")
async def api_admin_case_update(request: Request, case_id: str):
    """Sua thong tin ruong (ten, mo ta, gia quay)."""
    err = require_admin_api(request)
    if err:
        return err
    try:
        body = await read_json_dict(request)
        case = catalog_admin.update_case(case_id, body)
        return {"ok": True, "case": case}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("sua ruong that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thử lại."}, status_code=500)


@app.post("/api/admin/cases")
async def api_admin_case_create(request: Request):
    """Tao ruong moi."""
    err = require_admin_api(request)
    if err:
        return err
    try:
        body = await read_json_dict(request)
        new_case = catalog_admin.create_case(body)
        return {"ok": True, "case": new_case}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("tao ruong that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thự lại."}, status_code=500)


@app.delete("/api/admin/cases/{case_id}")
async def api_admin_case_delete(request: Request, case_id: str):
    """Xoa ruong (kem toan bo san pham ben trong)."""
    err = require_admin_api(request)
    if err:
        return err
    try:
        result = catalog_admin.delete_case(case_id)
        return {"ok": True, **result}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("xoa ruong that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thự lại."}, status_code=500)


@app.post("/api/admin/cases/{case_id}/image")
async def api_admin_case_image(request: Request, case_id: str):
    """Upload anh cho ruong (multipart/form-data)."""
    err = require_admin_api(request)
    if err:
        return err
    try:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise catalog_admin.CatalogError("Chưa chọn file ảnh.")
        content = await upload.read()
        path = catalog_admin.save_case_image(
            case_id, getattr(upload, "filename", "") or "", content
        )
        # Luu duong dan moi vao ruong neu ruong ton tai.
        try:
            case = catalog_admin._find_case(catalog_admin.load_raw(), case_id)
            if case:
                catalog_admin.update_case(case_id, {**case, "image": path})
        except catalog_admin.CatalogError:
            pass
        return {"ok": True, "image": path, "image_url": path}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("upload anh ruong that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thự lại."}, status_code=500)


@app.post("/api/admin/cases/{case_id}/image/delete")
async def api_admin_case_image_delete(request: Request, case_id: str):
    """Xoa file anh cua ruong."""
    err = require_admin_api(request)
    if err:
        return err
    try:
        catalog_admin.delete_case_image(case_id)
        try:
            case = catalog_admin._find_case(catalog_admin.load_raw(), case_id)
            if case:
                catalog_admin.update_case(case_id, {**case, "image": ""})
        except catalog_admin.CatalogError:
            pass
        return {"ok": True}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("xoa anh ruong that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thự lại."}, status_code=500)


@app.post("/api/admin/products/{case_id}/{item_id}/image")
async def api_admin_product_image(request: Request, case_id: str, item_id: str):
    """Upload anh cho san pham (multipart/form-data).

    File luu vao `app/static/items/<id>.<ext>`. Ten file sinh tu id + extension
    thật nen khong dung ten file nguoi tai len -> chong path traversal.
    """
    err = require_admin_api(request)
    if err:
        return err
    try:
        # `python-multipart` cho phep FastAPI parse multipart.
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise catalog_admin.CatalogError("Chưa chọn file ảnh.")
        content = await upload.read()
        path = catalog_admin.save_item_image(item_id, getattr(upload, "filename", "") or "", content)
        # Luu duong dan moi vao item neu item ton tai trong ruong.
        try:
            item = catalog_admin.get_item(item_id, case_id)
            if item:
                catalog_admin.update_item(case_id, item_id, {**item, "image": path})
        except catalog_admin.CatalogError:
            # Anh da luu thanh cong; item khong tim thay -> van tra ve path.
            pass
        return {"ok": True, "image": path, "image_url": path}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("upload anh that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thử lại."}, status_code=500)


@app.post("/api/admin/products/{case_id}/{item_id}/image/delete")
async def api_admin_product_image_delete(request: Request, case_id: str, item_id: str):
    """Xoa file anh cua san pham."""
    err = require_admin_api(request)
    if err:
        return err
    try:
        catalog_admin.delete_item_image(item_id)
        item = catalog_admin.get_item(item_id, case_id)
        if item:
            catalog_admin.update_item(case_id, item_id, {**item, "image": ""})
        return {"ok": True}
    except catalog_admin.CatalogError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        log.exception("xoa anh that bai")
        return JSONResponse({"detail": "Lỗi hệ thống, vui lòng thử lại."}, status_code=500)


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    token = new_csrf_token()
    request.session["csrf"] = token
    show_admins = pika_ready() and require_admin(request)
    return render(
        request,
        "setup.html",
        csrf=token,
        pika_ready=pika_ready(),
        servers=None,
        admins=await admins.admin_list() if show_admins else [],
        error=None,
    )


@app.get("/setup/test")
async def setup_test_get():
    return RedirectResponse("/setup", status_code=303)


@app.post("/setup/test")
async def setup_test(request: Request, csrf: str = Form(...)):
    if csrf != request.session.get("csrf"):
        return RedirectResponse("/setup", status_code=303)
    token = new_csrf_token()
    request.session["csrf"] = token
    if not pika_ready():
        return render(
            request,
            "setup.html",
            csrf=token,
            pika_ready=False,
            servers=None,
            error="Chưa có PIKA_API_KEY trong file .env",
        )
    if not require_admin(request):
        resp = render(
            request,
            "setup.html",
            csrf=token,
            pika_ready=True,
            servers=None,
            admins=[],
            error="Chỉ quản trị viên mới được test kết nối khi hệ thống đã cấu hình.",
        )
        resp.status_code = 403
        return resp
    try:
        servers = [await get_server(PIKA_SERVER_UUID)] if PIKA_SERVER_UUID else await list_servers()
        return render(
            request,
            "setup.html",
            csrf=token,
            pika_ready=True,
            servers=servers,
            admins=await admins.admin_list(),
            error=None,
        )
    except HTTPException as exc:
        return render(
            request,
            "setup.html",
            csrf=token,
            pika_ready=True,
            servers=None,
            admins=await admins.admin_list(),
            error=exc.detail,
        )
