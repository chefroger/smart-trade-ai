"""私密备忘录（2026-11-23 审计 P1-F）。

家庭类 facts 与「客户索要」礼物**绝不进** AI 上下文、打印件、长图、导出包；
需要查阅时输入本机固定密语，单独看一页。这里只做存取与密语校验，不参与
任何自动注入路径 —— 调用方只有 memo 专用端点。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

PBKDF2_ITERATIONS = 200_000
_MIN_PASSPHRASE = 4
_MAX_PASSPHRASE = 128

# 密语策略（W13）：每次输入（默认）或本会话内有效
UNLOCK_MODES = frozenset({"always", "session"})
DEFAULT_UNLOCK_MODE = "always"

# 后端节流（O-新6 / S8 / O-新28）：前端锁定刷新即清零，这里补一层后端保护。
# S8：状态持久化，重启不清零。
# O-新28：① 计时用 monotonic 缓存，磁盘只存墙钟截止时间 —— 系统时钟跳变
# 不拉长/缩短正在进行的 60 秒锁；② 状态按公司分桶，A 公司锁住不影响 B 公司。
MAX_FAILURES = 5
LOCK_SECONDS = 60
_throttle_lock = threading.Lock()
# (磁盘路径, 公司键) → (失败计数, monotonic 截止时间)；命中后不再读盘，
# 因此运行中的锁不受墙钟跳变影响。
_throttle_cache: dict[tuple[str, str], tuple[int, float]] = {}


def throttle_path() -> Path:
    """节流状态文件（独立于 memo.json，避免改密语策略时覆盖锁定）。"""
    return _trade_home() / "data" / "memo_throttle.json"


def _throttle_key(company_id: int | None) -> str:
    return str(company_id) if company_id is not None else "global"


def _cache_key(company_id: int | None) -> tuple[str, str]:
    return str(throttle_path()), _throttle_key(company_id)


def _load_throttle_file() -> dict:
    try:
        data = json.loads(throttle_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_throttle_file(data: dict) -> None:
    """原子写 memo_throttle.json；写失败不阻断请求（可用性优先）。"""
    try:
        path = throttle_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
        if os.name != "nt":
            path.chmod(0o600)
    except OSError:
        pass


def _throttle_state(company_id: int | None = None) -> tuple[int, float]:
    """返回 (失败计数, monotonic 截止时间)；首次访问从磁盘水合。

    水合时把墙钟剩余夹到 [0, LOCK_SECONDS]：时钟回拨最多锁 60 秒，
    时钟前拨直接解锁，不会出现「重启后锁一年」。
    """
    ckey = _cache_key(company_id)
    cached = _throttle_cache.get(ckey)
    if cached is not None:
        return cached
    entry = _load_throttle_file().get(_throttle_key(company_id)) or {}
    try:
        failures = max(0, int(entry.get("failures") or 0))
    except (TypeError, ValueError):
        failures = 0
    try:
        until_epoch = float(entry.get("until") or 0)
    except (TypeError, ValueError):
        until_epoch = 0.0
    remaining = max(0.0, min(float(LOCK_SECONDS), until_epoch - time.time()))
    mono_until = (time.monotonic() + remaining) if remaining > 0 else 0.0
    state = (failures, mono_until)
    _throttle_cache[ckey] = state
    return state


def _persist_throttle(
    failures: int, mono_until: float, company_id: int | None = None,
) -> None:
    remaining = max(0.0, mono_until - time.monotonic()) if mono_until else 0.0
    data = _load_throttle_file()
    data[_throttle_key(company_id)] = {
        "failures": int(failures),
        "until": round(time.time() + remaining, 3) if remaining > 0 else 0.0,
    }
    _write_throttle_file(data)


def lock_remaining(company_id: int | None = None) -> int:
    """密语锁定剩余秒数（0 = 未锁定；按公司独立）。"""
    with _throttle_lock:
        _, mono_until = _throttle_state(company_id)
        if not mono_until:
            return 0
        return max(0, int(round(mono_until - time.monotonic())))


def register_failure(company_id: int | None = None) -> None:
    """记录一次密语失败；连续 MAX_FAILURES 次后锁定 LOCK_SECONDS。"""
    with _throttle_lock:
        failures, mono_until = _throttle_state(company_id)
        failures += 1
        if failures >= MAX_FAILURES:
            mono_until = time.monotonic() + LOCK_SECONDS
            failures = 0
        _throttle_cache[_cache_key(company_id)] = (failures, mono_until)
        _persist_throttle(failures, mono_until, company_id)


def register_success(company_id: int | None = None) -> None:
    """成功校验后清零失败计数（锁定期内不允许调用，由端点先拦截）。"""
    with _throttle_lock:
        _throttle_cache[_cache_key(company_id)] = (0, 0.0)
        _persist_throttle(0, 0.0, company_id)


def reset_throttle(company_id: int | None = None) -> None:
    """测试/维护用：清空锁定状态。

    `company_id=None` 清空**全部公司**（兼容既有测试与维护脚本的调用习惯）；
    指定公司时只清那一桶。
    """
    with _throttle_lock:
        path_key = str(throttle_path())
        if company_id is None:
            for ckey in [k for k in _throttle_cache if k[0] == path_key]:
                del _throttle_cache[ckey]
            _write_throttle_file({})
            return
        _throttle_cache[_cache_key(company_id)] = (0, 0.0)
        _persist_throttle(0, 0.0, company_id)


class MemoError(ValueError):
    """密语缺失/过短/不正确。"""


def _trade_home() -> Path:
    value = os.environ.get("TRADE_HOME", "").strip()
    if value:
        return Path(value)
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(local) / "trade"
    return Path.home() / ".trade"


def memo_config_path() -> Path:
    return _trade_home() / "data" / "memo.json"


def _load_config() -> dict:
    try:
        data = json.loads(memo_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_configured() -> bool:
    data = _load_config()
    return bool(data.get("salt") and data.get("hash"))


def unlock_mode() -> str:
    """当前密语策略：always（每次输入，默认）/ session（本会话内有效）。"""
    mode = str(_load_config().get("unlock_mode") or DEFAULT_UNLOCK_MODE)
    return mode if mode in UNLOCK_MODES else DEFAULT_UNLOCK_MODE


def set_unlock_mode(mode: str) -> str:
    """更新策略（写 memo.json，保留已有密语盐/哈希）。"""
    value = str(mode or "").strip().lower()
    if value not in UNLOCK_MODES:
        raise MemoError("策略只能是 always 或 session")
    data = _load_config()
    data["unlock_mode"] = value
    _write_config(data)
    return value


def _write_config(data: dict) -> None:
    """原子写 memo.json（W15 O-19）：临时文件 + os.replace，避免半截 JSON。

    Windows 没有 POSIX 0600 权限位；POSIX 上仍收紧为 0600。
    """
    path = memo_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)
    if os.name != "nt":
        path.chmod(0o600)


def _hash(passphrase: str, salt_hex: str, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), bytes.fromhex(salt_hex), iterations,
    )
    return digest.hex()


def configure(passphrase: str) -> None:
    """首次设置密语（已配置时必须走 verify，不允许静默覆盖）。"""
    value = str(passphrase or "")
    if len(value) < _MIN_PASSPHRASE:
        raise MemoError(f"密语至少 {_MIN_PASSPHRASE} 位")
    if len(value) > _MAX_PASSPHRASE:
        raise MemoError("密语过长")
    if is_configured():
        raise MemoError("密语已设置")
    salt = secrets.token_hex(16)
    payload = {
        "salt": salt,
        "hash": _hash(value, salt, PBKDF2_ITERATIONS),
        "iterations": PBKDF2_ITERATIONS,
        # 保留用户已选的策略（配置密语不应重置为默认）
        "unlock_mode": unlock_mode(),
    }
    _write_config(payload)


def verify(passphrase: str) -> bool:
    """校验密语；配置缺失或损坏返回 False（fail-closed，不泄露原因）。"""
    data = _load_config()
    salt = str(data.get("salt") or "")
    expected = str(data.get("hash") or "")
    try:
        iterations = int(data.get("iterations") or PBKDF2_ITERATIONS)
    except (TypeError, ValueError):
        iterations = PBKDF2_ITERATIONS
    if not salt or not expected:
        return False
    try:
        actual = _hash(str(passphrase or ""), salt, iterations)
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def memo_items(company_id: int, customer_id: int) -> dict:
    """家庭类 facts + 「客户索要」礼物（调用方必须先 verify）。

    分类由用户/模型决定，不可靠；写了家庭称谓的条目即使分类是「重要日期」
    也一并收进来。
    """
    from trade.database import get_connection
    from trade.profile import contains_family_terms

    conn = get_connection()
    try:
        facts = conn.execute(
            "SELECT id, category, subject, content, status FROM customer_facts "
            "WHERE company_id = ? AND customer_id = ? AND status != '已作废' "
            "ORDER BY category, id DESC",
            (company_id, customer_id),
        ).fetchall()
        gifts = conn.execute(
            "SELECT id, item, approx_value, currency, occasion, status, gift_date "
            "FROM customer_gifts "
            "WHERE company_id = ? AND customer_id = ? AND direction = '客户索要' "
            "AND status != '已作废' ORDER BY id DESC",
            (company_id, customer_id),
        ).fetchall()
    finally:
        conn.close()
    fact_rows = []
    for row in facts:
        item = dict(row)
        if (item.get("category") == "家庭"
                or contains_family_terms(f"{item.get('subject') or ''} {item.get('content') or ''}")):
            fact_rows.append(item)
    return {
        "customer_id": customer_id,
        "facts": fact_rows,
        "gift_requests": [dict(row) for row in gifts],
    }
