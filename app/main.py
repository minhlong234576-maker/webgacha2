from __future__ import annotations

import json
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import admins, bank, bots, game, pika, store
from .roulette import roulette_manager
from .config import PIKA_SERVER_UUID, SESSION_SECRET, pika_ready
from .errors import MoneyError
from .gacha import get_case, is_dry_run, load_cases, pull_cost
from .pika import (
    coin_amount,
    find_authme_user,
    find_economy_user,
    get_server,
    list_servers,
)
from .security import (
    client_ip,
    login_allowed,
    new_csrf_token,
    record_failed_login,
    verify_authme_sha256,
)

VN_TZ = timezone(timedelta(hours=7))
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
KIND_LABELS = {
    "seed": "Nạp ví",
    "open": "Mở rương",
    "sell": "Bán đồ",
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
    await pika.close_client()


app = FastAPI(title="JellyVale Gacha", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="jv_session",
    same_site="lax",
    https_only=False,
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


def require_login(request: Request) -> tuple[str, str] | RedirectResponse:
    user = request.session.get("user")
    login_name = request.session.get("login_name")
    if not user or not login_name:
        return RedirectResponse("/login", status_code=303)
    return user, login_name


def render(request: Request, name: str, **context) -> HTMLResponse:
    context.setdefault("is_admin", require_admin(request))
    context.setdefault("dry_run", is_dry_run())
    token = request.session.get("csrf") or new_csrf_token()
    request.session["csrf"] = token
    context.setdefault("csrf", token)
    context.setdefault("player", None)
    return templates.TemplateResponse(request, name, context)


def json_error(exc: game.GameError | Exception, status: int = 400) -> JSONResponse:
    if isinstance(exc, game.GameError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)
    return JSONResponse({"detail": str(exc)}, status_code=status)


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
    return request.headers.get("x-csrf") == request.session.get("csrf")


def api_auth(request: Request, *, csrf: bool = False) -> str | JSONResponse:
    user = request.session.get("user")
    if not user:
        return JSONResponse({"detail": "Chưa đăng nhập."}, status_code=401)
    if csrf and not require_csrf(request):
        return JSONResponse({"detail": "Phiên hết hạn, tải lại trang."}, status_code=403)
    return user


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse("/gacha", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    if request.session.get("user"):
        return RedirectResponse("/gacha", status_code=303)
    token = new_csrf_token()
    request.session["csrf"] = token
    return render(request, "login.html", csrf=token, error=error, pika_ready=pika_ready())


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: str = Form(...),
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
    return RedirectResponse("/gacha", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/gacha", status_code=303)


@app.get("/gacha", response_class=HTMLResponse)
async def catalogue(request: Request):
    ctx = await optional_ctx(request)
    last_bonus = store.last_bonus(ctx["player"]) if ctx["player"] else 0
    bonus_ready = bool(ctx["player"]) and ((not last_bonus) or (store.now() - last_bonus >= 24 * 3600))
    return render(
        request,
        "catalogue.html",
        **ctx,
        cases=[case_view(item) for item in load_cases()],
        site=game.site_stats_bar(),
        bonus_ready=bonus_ready,
    )


@app.get("/case/{slug}", response_class=HTMLResponse)
async def case_page(request: Request, slug: str):
    ctx = await optional_ctx(request)
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
        body = await request.json()
        if isinstance(body, dict) and "count" in body:
            count = int(body["count"])
    except Exception:
        count = 1
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
        if not is_dry_run():
            try:
                await bank.give(user, total_cost)
            except (MoneyError, HTTPException):
                pass
        return JSONResponse({"detail": str(exc)}, status_code=500)

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
    ctx = await player_ctx(request)
    if isinstance(ctx, RedirectResponse):
        return ctx
    held = [inv_view(row) for row in store.list_inventory(ctx["player"], "held")]
    worth = sum(row["value"] for row in held)
    return render(
        request,
        "inventory.html",
        **ctx,
        items=held,
        worth_fmt=format_coin(worth),
    )


@app.post("/api/inventory/sell")
async def inventory_sell(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    body = await request.json()
    ids = [int(x) for x in body.get("ids") or []]
    try:
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
    try:
        held = store.list_inventory(user, "held")
        ids = [row["id"] for row in held]
        amount = game.sell_preview(user, ids)
        if not is_dry_run() and amount > 0:
            try:
                await bank.give(user, amount)
            except (MoneyError, HTTPException):
                raise
        result = game.sell_all(user)
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


@app.get("/upgrade", response_class=HTMLResponse)
async def upgrade_page(request: Request):
    ctx = await player_ctx(request)
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
    body = await request.json()
    try:
        result = game.do_upgrade(
            user,
            int(body.get("inventory_id") or 0),
            str(body.get("target_id") or ""),
            int(body.get("target_coin") or 0),
        )
        result["balance_fmt"] = format_coin(result["balance"])
        result["target"]["coin_fmt"] = format_coin(result["target"]["coin"])
        return result
    except game.GameError as exc:
        return json_error(exc)


@app.get("/battles", response_class=HTMLResponse)
async def battles_page(request: Request):
    ctx = await optional_ctx(request)
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
    ctx = await optional_ctx(request)
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
    body = await request.json()
    case_id = str(body.get("case_id") or "")
    rounds = int(body.get("rounds") or 1)
    # Chuẩn web gốc: cho phép gửi playlist lines [{case_id, count}].
    raw_lines = body.get("lines") or body.get("cases")
    try:
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
                int(body.get("slots") or 2),
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
        body = await request.json()
    except Exception:
        body = {}
    slug = str((body or {}).get("case_id") or "")
    rounds = int((body or {}).get("rounds") or 1)
    slots = int((body or {}).get("slots") or 2)
    mode = str((body or {}).get("mode") or "STANDARD")
    raw_lines = (body or {}).get("lines") or (body or {}).get("cases")
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
        body = await request.json()
    except Exception:
        body = {}
    slug = str((body or {}).get("case_id") or "")
    rounds = int((body or {}).get("rounds") or 1)
    mode = str((body or {}).get("mode") or "STANDARD")
    raw_lines = (body or {}).get("lines") or (body or {}).get("cases")
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
    ctx = await optional_ctx(request)
    last_bonus = store.last_bonus(ctx["player"]) if ctx["player"] else 0
    bonus_ready = bool(ctx["player"]) and ((not last_bonus) or (store.now() - last_bonus >= 24 * 3600))
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
    ctx = await optional_ctx(request)
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
    user = request.session.get("user")
    state = roulette_manager.get_state(user)
    return state


@app.post("/api/roulette/bet")
async def api_roulette_bet(request: Request):
    user = api_auth(request, csrf=True)
    if isinstance(user, JSONResponse):
        return user
    try:
        body = await request.json()
        side = str(body.get("side") or "").strip().lower()
        amount = int(body.get("amount") or 0)

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
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=500)


@app.get("/vi", response_class=HTMLResponse)
async def wallet(request: Request):
    ctx = await player_ctx(request)
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
    ctx = await player_ctx(request)
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


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    token = new_csrf_token()
    request.session["csrf"] = token
    return render(
        request,
        "setup.html",
        csrf=token,
        pika_ready=pika_ready(),
        servers=None,
        admins=await admins.admin_list() if pika_ready() else [],
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
