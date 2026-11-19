"""访客身份：站长（Basic 校验通过）= "owner"；游客 = 浏览器持有的匿名 ez_uid Cookie（无账号体系）。

用途：对话记忆/历史按“人”隔离。限流仍按 IP（guest_guard），二者互不影响。
Cookie 丢失（清缓存/换设备）等于一个新游客，历史不可找回；站长凭据同源，历史可跨设备。
"""

from __future__ import annotations

import re
import uuid
from typing import Optional, Tuple

from fastapi import Request, Response

from .guest_guard import is_owner

COOKIE = "ez_uid"
_UID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_AGE = 400 * 24 * 3600


def user_key(request: Request) -> Tuple[str, Optional[str]]:
    """返回 (user_key, 需要下发的新 uid)。站长恒为 "owner"。"""
    if is_owner(request):
        return "owner", None
    uid = request.cookies.get(COOKIE, "")
    if _UID_RE.match(uid):
        return f"g:{uid}", None
    new_uid = uuid.uuid4().hex
    return f"g:{new_uid}", new_uid


def peek_user_key(request: Request) -> Optional[str]:
    """只读取当前身份，不生成新 uid：站长 "owner"；有合法 Cookie 的游客 "g:<uid>"；否则 None。"""
    if is_owner(request):
        return "owner"
    uid = request.cookies.get(COOKIE, "")
    return f"g:{uid}" if _UID_RE.match(uid) else None


def can_edit(request: Request, record: dict) -> bool:
    """站长可改任何行程；游客只能改记录里 editor 与自己 uid 一致的行程。"""
    if is_owner(request):
        return True
    editor = record.get("editor")
    return bool(editor) and editor == peek_user_key(request)


def set_cookie(response: Response, request: Request, new_uid: Optional[str]) -> None:
    if not new_uid:
        return
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        COOKIE,
        new_uid,
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )

