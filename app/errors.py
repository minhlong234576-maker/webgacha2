from __future__ import annotations


class MoneyError(Exception):
    """Lỗi liên quan Coin: không đủ tiền, hoặc thao tác với Coin in-game thất bại.

    Tách riêng khỏi HTTPException để tầng game xử lý được, và để tầng web
    trả về đúng mã lỗi (402 = thiếu tiền) cho trình duyệt.
    """
