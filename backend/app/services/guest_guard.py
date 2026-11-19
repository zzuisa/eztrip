"""游客流量保护：按客户端 IP 的滚动 24 小时配额 + 站长身份判定。

站长身份：请求携带的 HTTP Basic 凭据与 htpasswd（EZTRIP_OWNER_HTPASSWD，apr1 哈希）
匹配即为站长，可以和反向代理共用同一个 htpasswd 文件。不信任任何客户端自报的身份头。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List

from fastapi import HTTPException, Request

WINDOW_SECONDS = 24 * 3600


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def limits() -> Dict[str, int]:
    return {
        "gen": _int_env("EZTRIP_GUEST_GEN_PER_DAY", 3),
        "nlq": _int_env("EZTRIP_GUEST_NLQ_PER_DAY", 20),
        "img": _int_env("EZTRIP_GUEST_IMG_PER_DAY", 60),
        "chat": _int_env("EZTRIP_GUEST_CHAT_PER_DAY", 20),
        "route": _int_env("EZTRIP_GUEST_ROUTE_PER_DAY", 120),
        "story": _int_env("EZTRIP_GUEST_STORY_PER_DAY", 5),
        "edit": _int_env("EZTRIP_GUEST_EDIT_PER_DAY", 300),
        "aiedit": _int_env("EZTRIP_GUEST_AIEDIT_PER_DAY", 10),
        "psearch": _int_env("EZTRIP_GUEST_PSEARCH_PER_DAY", 80),
        "fork": _int_env("EZTRIP_GUEST_FORK_PER_DAY", 10),
        "stay": _int_env("EZTRIP_GUEST_STAY_PER_DAY", 3),
        "stay_all": _int_env("EZTRIP_STAY_GLOBAL_PER_DAY", 30),
        "xhsplace": _int_env("EZTRIP_GUEST_XHS_PLACE_PER_DAY", 24),
        "xhsplace_all": _int_env("EZTRIP_XHS_PLACE_GLOBAL_PER_DAY", 120),
        "pdetail": _int_env("EZTRIP_GUEST_PDETAIL_PER_DAY", 40),
        "pdetail_all": _int_env("EZTRIP_PDETAIL_GLOBAL_PER_DAY", 120),
        "geo": _int_env("EZTRIP_GUEST_GEO_PER_DAY", 200),
        # 路线对比：每次对比会调 Google Routes（付费），游客每天 6 次 + 全站 40 次的总闸
        "rcmp": _int_env("EZTRIP_GUEST_RCMP_PER_DAY", 6),
        "rcmp_all": _int_env("EZTRIP_RCMP_GLOBAL_PER_DAY", 40),
        # 地点对话里的“近期活动”检索（走 MCP 搜索 + 抓页，较慢较贵）：游客每天 8 次，全站 60 次
        "pevt": _int_env("EZTRIP_GUEST_PEVT_PER_DAY", 8),
        "pevt_all": _int_env("EZTRIP_PEVT_GLOBAL_PER_DAY", 60),
        "fun": _int_env("EZTRIP_GUEST_FUN_PER_DAY", 30),
        "fun_all": _int_env("EZTRIP_FUN_GLOBAL_PER_DAY", 150),
        "funchat": _int_env("EZTRIP_GUEST_FUNCHAT_PER_DAY", 15),
        "funchat_all": _int_env("EZTRIP_FUNCHAT_GLOBAL_PER_DAY", 120),
        "funphoto": _int_env("EZTRIP_GUEST_FUNPHOTO_PER_DAY", 400),
        # 主题引导里“未知目的地”的识别（一次小模型调用 + 一次网页搜索）：游客每天 12 次，全站 80 次；命中内置表 / 缓存不占额度
        "disc": _int_env("EZTRIP_GUEST_DISC_PER_DAY", 12),
        "disc_all": _int_env("EZTRIP_DISC_GLOBAL_PER_DAY", 80),
        # 全站每日上限：不论谁访问，Google 照片/详情的付费调用都有总闸（超额只降级成兜底图，不报错）
        "img_all": _int_env("EZTRIP_IMG_GLOBAL_PER_DAY", 800),
        "funphoto_all": _int_env("EZTRIP_FUNPHOTO_GLOBAL_PER_DAY", 1500),
        "feedback": _int_env("EZTRIP_GUEST_FEEDBACK_PER_DAY", 60),
        "running": _int_env("EZTRIP_MAX_RUNNING_JOBS", 3),
    }


def _normalize_ip(raw: str) -> str:
    """IPv6 访客按 /64 归并（同一用户可轻易轮换 /64 内地址），IPv4 原样。"""
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return "unknown"
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False).network_address) + "/64"
    return str(addr)


def client_ip(request: Request) -> str:
    # 前置 Nginx（A）写入 X-Real-IP；B 的 web 容器已通过 realip 还原为真实访客地址
    real = request.headers.get("x-real-ip", "").split(",")[0].strip()
    if real:
        return _normalize_ip(real)
    return _normalize_ip(request.client.host) if request.client else "unknown"


# ---------------------------------------------------------------------------
# 站长身份：后端直接校验请求自带的 HTTP Basic 凭据（与反向代理共用的 htpasswd）
# ---------------------------------------------------------------------------
_APR1_ALPHABET = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _to64(value: int, count: int) -> str:
    out = []
    for _ in range(count):
        out.append(_APR1_ALPHABET[value & 0x3F])
        value >>= 6
    return "".join(out)


def apr1_hash(password: str, salt: str) -> str:
    """Apache apr1（MD5-crypt）。与 openssl passwd -apr1 / htpasswd -m 兼容。"""
    pw = password.encode("utf-8")
    sl = salt.encode("ascii")[:8]
    magic = b"$apr1$"
    final = hashlib.md5(pw + sl + pw).digest()
    ctx = pw + magic + sl
    remaining = len(pw)
    while remaining > 0:
        ctx += final[: min(16, remaining)]
        remaining -= 16
    i = len(pw)
    while i:
        ctx += b"\x00" if i & 1 else pw[:1]
        i >>= 1
    final = hashlib.md5(ctx).digest()
    for i in range(1000):
        data = pw if i & 1 else final
        if i % 3:
            data += sl
        if i % 7:
            data += pw
        data += final if i & 1 else pw
        final = hashlib.md5(data).digest()
    enc = ""
    for a, b, c in ((0, 6, 12), (1, 7, 13), (2, 8, 14), (3, 9, 15), (4, 10, 5)):
        enc += _to64((final[a] << 16) | (final[b] << 8) | final[c], 4)
    enc += _to64(final[11], 2)
    return "$apr1$" + sl.decode("ascii") + "$" + enc


def _owner_htpasswd_path() -> Path:
    return Path(os.getenv("EZTRIP_OWNER_HTPASSWD", "/app/owner.htpasswd"))


class _OwnerAuth:
    """读取 htpasswd（仅 apr1），校验 Basic 凭据；成功结果短时缓存，失败按 IP 限速防爆破。"""

    CACHE_SECONDS = 300
    MAX_FAILS = 10
    FAIL_WINDOW = 600

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._users: Dict[str, str] = {}
        self._mtime = -1.0
        self._path: Path | None = None
        self._ok: Dict[str, float] = {}
        self._fails: Dict[str, List[float]] = {}

    def _load(self) -> None:
        path = _owner_htpasswd_path()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._users, self._mtime, self._path = {}, -1.0, path
            return
        if path == self._path and mtime == self._mtime:
            return
        users: Dict[str, str] = {}
        try:
            for line in path.read_text().splitlines():
                name, sep, hashed = line.strip().partition(":")
                if sep and name and hashed.startswith("$apr1$"):
                    users[name] = hashed
        except OSError:
            users = {}
        self._users, self._mtime, self._path = users, mtime, path
        self._ok.clear()

    def throttled(self, ip: str) -> bool:
        now = time.time()
        recent = [t for t in self._fails.get(ip, []) if now - t < self.FAIL_WINDOW]
        self._fails[ip] = recent
        return len(recent) >= self.MAX_FAILS

    def verify(self, header: str, ip: str) -> bool:
        scheme, _, token = header.strip().partition(" ")
        if scheme.lower() != "basic" or not token:
            return False
        key = hashlib.sha256(token.strip().encode()).hexdigest()
        with self._lock:
            self._load()
            now = time.time()
            if self._ok.get(key, 0) > now:
                return True
            if not self._users or self.throttled(ip):
                return False
            try:
                user, _, password = base64.b64decode(token.strip(), validate=True).decode("utf-8").partition(":")
            except Exception:
                self._fails.setdefault(ip, []).append(now)
                return False
            stored = self._users.get(user)
            ok = False
            if stored:
                parts = stored.split("$")  # ['', 'apr1', salt, hash]
                if len(parts) == 4:
                    ok = hmac.compare_digest(apr1_hash(password, parts[2]), stored)
            if ok:
                self._ok = {k: v for k, v in self._ok.items() if v > now}
                self._ok[key] = now + self.CACHE_SECONDS
                return True
            self._fails.setdefault(ip, []).append(now)
            return False


_owner_auth = _OwnerAuth()


def is_owner(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    if not header:
        return False
    return _owner_auth.verify(header, client_ip(request))


def require_owner(request: Request) -> None:
    if not is_owner(request):
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_required", "message": "需要访问口令"},
        )


class GuestQuota:
    """线程安全、可持久化的滚动窗口计数器（JSON 文件，量很小）。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path(__file__).resolve().parents[2] / "storage" / "guest_quota.json"
        self._lock = threading.Lock()
        self._hits: Dict[str, List[float]] = {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._hits = {k: [float(t) for t in v] for k, v in raw.items() if isinstance(v, list)}
        except Exception:
            self._hits = {}

    def _prune(self, key: str, now: float) -> List[float]:
        hits = [t for t in self._hits.get(key, []) if now - t < WINDOW_SECONDS]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._hits), encoding="utf-8")
            tmp.replace(self._path)
        except Exception:
            pass  # 配额持久化失败不应影响业务

    def status(self, kind: str, ip: str, limit: int) -> Dict[str, int]:
        now = time.time()
        with self._lock:
            hits = self._prune(f"{kind}:{ip}", now)
        used = len(hits)
        retry = int(WINDOW_SECONDS - (now - min(hits))) if hits and used >= limit else 0
        return {"limit": limit, "used": used, "remaining": max(0, limit - used), "retry_after_seconds": retry}

    def consume(self, kind: str, ip: str, limit: int) -> None:
        """占用一次额度；超限抛 429。"""
        now = time.time()
        key = f"{kind}:{ip}"
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) >= limit:
                retry = int(WINDOW_SECONDS - (now - min(hits)))
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "quota_exceeded",
                        "kind": kind,
                        "limit": limit,
                        "retry_after_seconds": max(retry, 1),
                        "message": "游客今日额度已用完，输入访问口令可继续使用",
                    },
                    headers={"Retry-After": str(max(retry, 1))},
                )
            hits.append(now)
            self._hits[key] = hits
            self._save()

    def refund(self, kind: str, ip: str) -> None:
        key = f"{kind}:{ip}"
        with self._lock:
            hits = self._hits.get(key)
            if hits:
                hits.pop()
                if not hits:
                    self._hits.pop(key, None)
                self._save()


_quota: GuestQuota | None = None


def get_quota() -> GuestQuota:
    global _quota
    if _quota is None:
        _quota = GuestQuota()
    return _quota


def guest_quota_dependency(kind: str):
    """FastAPI 依赖：站长放行；游客占用 kind 额度。"""

    def dep(request: Request) -> None:
        if is_owner(request):
            return
        get_quota().consume(kind, client_ip(request), limits()[kind])

    return dep

