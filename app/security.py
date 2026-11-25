from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import Request

# App có nằm sau reverse proxy (Nginx/Cloudflare) mà ta kiểm soát không?
# Bật chỉ khi CÓ — xem `client_ip` để hiểu vì sao.
TRUST_PROXY = False

_MAX_ATTEMPTS = 8
_WINDOW_SECONDS = 10 * 60
_attempts: dict[str, deque[float]] = defaultdict(deque)


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
    _attempts[ip].append(time.time())


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
