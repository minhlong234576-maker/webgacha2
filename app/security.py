from __future__ import annotations

import binascii
import hashlib
import hmac
import json
import secrets
import time
from base64 import b64decode, b64encode
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import Request
from itsdangerous.exc import BadSignature
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import HTTPConnection
from starlette.types import Message, Receive, Scope, Send

# App có nằm sau reverse proxy (Nginx/Cloudflare) mà ta kiểm soát không?
# Bật chỉ khi CÓ — xem `client_ip` để hiểu vì sao.
TRUST_PROXY = False

_MAX_ATTEMPTS = 8
_WINDOW_SECONDS = 10 * 60
_MAX_TRACKED_IPS = 4096
_attempts: dict[str, deque[float]] = defaultdict(deque)


class SafeSessionMiddleware(SessionMiddleware):
    """SessionMiddleware an toàn trước cookie hỏng / lệch SECRET.

    Starlette mặc định chỉ bắt `BadSignature`. Nếu cookie `jv_session` giải mã
    base64 lỗi (`binascii.Error`) hoặc JSON hỏng (`ValueError`) hoặc không phải
    dict, mọi request đều văng 500 Internal Server Error. Middleware này reset
    phiên về `{}` và xóa cookie hỏng trên trình duyệt người dùng.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        initial_session_was_empty = True

        if self.session_cookie in connection.cookies:
            raw_cookie = connection.cookies[self.session_cookie].encode("utf-8")
            try:
                unsigned = self.signer.unsign(raw_cookie, max_age=self.max_age)
                parsed = json.loads(b64decode(unsigned))
                if not isinstance(parsed, dict):
                    raise ValueError("session payload is not a dict")
                scope["session"] = parsed
                initial_session_was_empty = False
            except (BadSignature, binascii.Error, ValueError, UnicodeDecodeError, TypeError):
                scope["session"] = {}
                # Đánh dấu non-empty để send_wrapper xóa cookie hỏng nếu route
                # không ghi session mới.
                initial_session_was_empty = False
        else:
            scope["session"] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                if scope["session"]:
                    data = b64encode(json.dumps(scope["session"]).encode("utf-8"))
                    data = self.signer.sign(data)
                    headers = MutableHeaders(scope=message)
                    header_value = "{session_cookie}={data}; path={path}; {max_age}{security_flags}".format(
                        session_cookie=self.session_cookie,
                        data=data.decode("utf-8"),
                        path=self.path,
                        max_age=f"Max-Age={self.max_age}; " if self.max_age else "",
                        security_flags=self.security_flags,
                    )
                    headers.append("Set-Cookie", header_value)
                elif not initial_session_was_empty:
                    headers = MutableHeaders(scope=message)
                    header_value = "{session_cookie}={data}; path={path}; {expires}{security_flags}".format(
                        session_cookie=self.session_cookie,
                        data="null",
                        path=self.path,
                        expires="expires=Thu, 01 Jan 1970 00:00:00 GMT; ",
                        security_flags=self.security_flags,
                    )
                    headers.append("Set-Cookie", header_value)
            await send(message)

        await self.app(scope, receive, send_wrapper)


def is_same_origin(request: Request) -> bool:
    """Chặn form POST cross-origin nếu trình duyệt gửi header Origin."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host")
    if not host:
        return False
    return urlparse(origin).netloc.lower() == host.lower()


def verify_authme_sha256(password: str, stored: str) -> bool:
    if not stored or not stored.startswith("$SHA$"):
        return False
    parts = stored.split("$")
    if len(parts) < 4:
        return False
    salt, expected = parts[2], parts[3]
    inner = hashlib.sha256(password.encode("utf-8")).hexdigest()
    actual = hashlib.sha256((inner + salt).encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual.lower(), expected.lower())


def client_ip(request: Request) -> str:
    """IP thật của người gửi, để giới hạn đăng nhập.

    `X-Forwarded-For` chỉ đáng tin khi app nằm sau reverse proxy mà ta kiểm
    soát. Nếu lấy nó vô điều kiện, kẻ xấu tự đặt header này thành IP bất kỳ
    là vượt qua được giới hạn đăng nhập — mỗi lần thử lại là một IP mới.

    Vì vậy: chỉ dùng `X-Forwarded-For` khi `TRUST_PROXY` bật (deploy sau
    Nginx/Cloudflare của chính bạn). Còn lại dùng IP kết nối thật.
    """
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def login_allowed(ip: str) -> bool:
    now = time.time()
    bucket = _attempts[ip]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    return len(bucket) < _MAX_ATTEMPTS


def record_failed_login(ip: str) -> None:
    if len(_attempts) >= _MAX_TRACKED_IPS and ip not in _attempts:
        now = time.time()
        stale = [k for k, q in _attempts.items() if not q or now - q[-1] > _WINDOW_SECONDS]
        for k in stale:
            del _attempts[k]
    _attempts[ip].append(time.time())


def clear_failed_logins(ip: str) -> None:
    """Xoa lich su login that bai cua IP (sau khi dang nhap THANH CONG).

    Khong xoa thi mot nguoi choi go sai mat khau vai lan roi dang nhap dung
    van bi chan `error=rate` trong 10 phut -> dang nhap that bi khoa o bat
    thuong.
    """
    _attempts.pop(ip, None)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
