#!/usr/bin/env python3
"""文档提取缓存手工基准脚本（路线 A：走完整聊天）。

跑法（必须在 Trade 的运行 venv 里，python-docx / openpyxl 才在）：

    ~/.trade/venv/bin/python scripts/benchmark-doc-cache.py \
        --rounds 2 --out reports/benchmark-doc-cache-2026-11-12.json

脚本做四件事：

1. **隔离**：自建临时 TRADE_HOME（全新 trade.db）→ 冷轮缓存必空，
   且不碰用户真实数据（`~/.trade`）。文档集复制进临时文档库目录
   （复制不改字节内容 → SHA256 与原文件一致，缓存键仍可比）。
2. **预热与命中**：走生产路径 `doc_extract.warm_cache` / `doc_cache.get`，
   抽取模型走 `resolve_extraction_model()` 的默认配置（不换小模型、不 mock）。
3. **两轮问答**：每轮每题调生产同步聊天端点 `trade.api.chat.trade_chat`
   （进程内调用，跳过 HTTP 层；走的仍是同一个生产实现）。
4. **改数验证**：改报价单里一个金额 → 重问同一数字题 → 答案必须跟着变
   → 再改回来。

记录口径（报告里必须原样写明）：

- **token**：`usage_ledger`（按 company_id 切片）。该表只记 agent 主流程
  用量（`trade/usage.py:record_agent_usage`），**不含 aux 抽取通道的
  token** —— 抽取侧调用次数单独记（见下），不与主流程 token 混算。
- **模型调用次数**：agent 调用 = `usage_ledger` 行数增量（重试也记）；
  抽取调用 = `doc_extractions.attempts` 增量。
- **是否全文读**：scope=summary 且该文件命中缓存 → 未全文读；其余一律
  全文读（locate 命中缓存也仍全文读，见 `trade/api/chat.py:479`）。
- **答案是否一致**：数字题抽数字集合逐字比对；summary/locate 记
  identical/differs + 差异点（人工判）。

脚本只做基准，不进产品逻辑。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── 文档集（真实业务文档，不进仓库；只记文件名/分类/哈希）──────────────

DOC_SOURCE_ROOT = Path.home() / "Desktop" / "外贸业务资料包" / "外贸业务资料包"

DOCUMENTS = [
    {
        "key": "quotation",
        "name": "产品报价单（外贸协议订单版本，含打版等复杂信息）1.xlsx",
        "rel": "01-外贸报价模板/产品报价单（外贸协议订单版本，含打版等复杂信息）1.xlsx",
        "role": "money 典型（金额结构）；改数验证对象",
        "expect_kind": "money",
        "parse": "ok",
    },
    {
        "key": "ces_table",
        "name": "万腾CES展产品表(最终确定版本-2018.12.22）.xlsx",
        "rel": "06-更多销售技巧，模板拿下客户/有效沟通细节图工具/"
               "万腾CES展产品表(最终确定版本-2018.12.22）.xlsx",
        "role": "产品表：11-09 被金额兜底误判 money 的那类，分类观察点",
        "expect_kind": "info",
        "parse": "ok",
    },
    {
        "key": "crm_big",
        "name": "客户跟进管理系统-外贸.xlsx",
        "rel": "03-客户盘点管理表/客户跟进管理系统-外贸.xlsx",
        "role": "Excel 超大表（2.5MB）：截断口径观察点",
        "expect_kind": None,
        "parse": "truncated",
    },
    {
        "key": "perf_stats",
        "name": "个人业绩统计表.xlsx",
        "rel": "07-外贸业务工作管理表格/个人业绩统计表.xlsx",
        "role": "Excel 统计表：数字题主力",
        "expect_kind": None,
        "parse": "ok",
    },
    {
        "key": "cold_email_docx",
        "name": "高效开发信的全方位建议.docx",
        "rel": "02-客户开发与订单管理/高效开发信的全方位建议.docx",
        "role": "Word prose（无表格）：Word 抽取观察点",
        "expect_kind": "info",
        "parse": "ok",
    },
    {
        "key": "negotiation_docx",
        "name": "业务转化提升分享第二篇.docx",
        "rel": "06-更多销售技巧，模板拿下客户/业务转化提升分享第二篇.docx",
        "role": "Word 含数值（7000USD）：Word 数字题",
        "expect_kind": None,
        "parse": "ok",
    },
]

# 报价单里用于改数验证的字面数值（M6 = 报价单号 2018123），改后核对答案。
QUOTATION_ORIGINAL_TOTAL = 2018123
QUOTATION_MUTATED_TOTAL = 2018999

# ── 问题集（全文进报告）─────────────────────────────────────────────────
#
# 提问一律对**整个文档库**（6 个文件），这是产品设计的用法：缓存只服务
# 概览/定位两类请求，针对单个文件的具体事实按规则一律全文读
# （`trade/doc_scope.py`）。每道题的 scope 由 `detect_request_scope` 判定，
# 脚本会实测并写进结果，不靠这里的标注。
#
# summary/locate 题刻意避开 doc_scope 的 full_read 触发词（数字、价格、
# 金额、客户、统计、比较……），否则会被判成 full_read、缓存根本不参与，
# 测不出收益。数字题含具体数值 → 必然 full_read。

QUESTIONS = [
    # ── summary 类（库级概览）：6 道，覆盖全部 6 个文件 ──
    {"id": "s1", "kind": "summary", "covers": "all",
     "query": "请介绍一下这批文件"},
    {"id": "s2", "kind": "summary", "covers": "all",
     "query": "概述一下这些文件"},
    {"id": "s3", "kind": "summary", "covers": "all",
     "query": "请总结这批文件"},
    {"id": "s4", "kind": "summary", "covers": "all",
     "query": "介绍一下这批文件讲了什么"},
    {"id": "s5", "kind": "summary", "covers": "all",
     "query": "请介绍一下这些文件的内容"},
    {"id": "s6", "kind": "summary", "covers": "all",
     "query": "概览这批文件"},

    # ── locate 类（库级定位，每道指向一个文件的独有内容）：6 道 ──
    {"id": "l1", "kind": "locate", "covers": ["quotation"],
     "query": "哪些文件里有打版相关的内容"},
    {"id": "l2", "kind": "locate", "covers": ["ces_table"],
     "query": "哪些文件里谈到了 CES 展会"},
    {"id": "l3", "kind": "locate", "covers": ["crm_big"],
     "query": "哪些文件里有首页和基本设置表"},
    {"id": "l4", "kind": "locate", "covers": ["perf_stats"],
     "query": "哪些文件里记录了季度合计"},
    {"id": "l5", "kind": "locate", "covers": ["cold_email_docx"],
     "query": "哪些文件里谈到了开发信"},
    {"id": "l6", "kind": "locate", "covers": ["negotiation_docx"],
     "query": "哪些文件里谈到了商务谈判"},

    # ── 具体数字题：每文件 1 道，必然 full_read ──
    {"id": "n1", "kind": "number", "covers": ["quotation"],
     "query": "这份报价单的总计金额是多少元？", "expect_number": "39703"},
    {"id": "n2", "kind": "number", "covers": ["ces_table"],
     "query": "产品表里曝光 198070 的那行，点击率是多少？"},
    {"id": "n3", "kind": "number", "covers": ["crm_big"],
     "query": "客户跟进管理系统里的合计客户数是多少？"},
    {"id": "n4", "kind": "number", "covers": ["perf_stats"],
     "query": "个人业绩统计表里一月份的实际业绩是多少美元？"},
    {"id": "n5", "kind": "number", "covers": ["cold_email_docx"],
     "query": "文档里提到一个月可以发多少封开发信？"},
    {"id": "n6", "kind": "number", "covers": ["negotiation_docx"],
     "query": "文档里提到当场给了多少美元的现场打样和小批试单？"},
]

# 改数验证用的题目（问的正是被改的那个字面值）
MUTATION_QUESTION = "这份报价单的报价单号是多少？"

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# 沙箱配置改动说明（写进结果 JSON 与报告）
_SANDBOX_NOTES: dict = {}


def _extract_numbers(text: str) -> list[str]:
    """从答案里抽出数字（去千分位逗号），用于数字题逐字比对。"""
    return [m.group(0).replace(",", "") for m in _NUMBER_RE.finditer(text or "")]


def _numbers_equal(left: str, right: str) -> bool:
    """两个答案的数字集合是否一致（顺序不敏感）。"""
    return sorted(_extract_numbers(left)) == sorted(_extract_numbers(right))


def _digest(path: Path) -> str:
    """计算文件 SHA-256（与 trade/doc_cache.py 的 file_sha256 同口径）。"""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_isolated_home() -> Path:
    """建临时 TRADE_HOME 并返回其路径。

    必须在 import trade.* 之前设好，否则 trade.database 会连到真实 trade.db。
    """
    import tempfile

    base = Path(tempfile.mkdtemp(prefix="bench-trade-home-"))
    (base / "data").mkdir(parents=True, exist_ok=True)
    os.environ["TRADE_HOME"] = str(base)
    # 明确关闭懒加载重启（bootstrap 内部也会设，这里双保险）
    os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
    return base


def _patch_real_hermes_config() -> tuple[Path, dict]:
    """临时改 `~/.hermes/config.yaml` 的三处开关，返回 (备份路径, 改动说明)。

    为什么不隔离整个 HERMES_HOME：pm 的托管环境定位依赖真实的安装状态标记，
    换 HERMES_HOME 会让 `import hermes_bootstrap` 的激活静默失效（实测
    `ModuleNotFoundError: ruamel`）。改配置开关是最小侵入的做法。

    三处开关：

    1. `auxiliary.background_review.enabled = false` —— 关 self-improvement。
       实测试跑时 Hermes 的 curator 把 `~/.hermes/skills/b2b-document/SKILL.md`
       改了 3 次：既污染用户环境，也让「第一轮 vs 第二轮」的 skill 内容不同，
       两轮数字不可比。关掉它，skill 根本不会被写。
    2. `moa.enabled = false` —— MOA 每轮多调 3 个参考模型 + 1 个聚合模型，
       token 与耗时是主模型的 4~5 倍。它与文档缓存无关，关掉才测得出缓存
       本身的收益（两轮同配置，不影响可比性）。
    3. `mcp_servers.*.enabled = false` —— MCP 走 npx 拉包，每次 agent 启动
       都要联网装包，基准里没有意义。

    原文件按字节备份，基准结束（或异常退出）时用 `_restore_hermes_config`
    原样还原。
    """
    import yaml

    real = Path.home() / ".hermes" / "config.yaml"
    if not real.is_file():
        raise FileNotFoundError(f"找不到 Hermes 配置：{real}")
    backup = real.with_name("config.yaml.bench-backup")
    lock = real.with_name("config.yaml.bench-lock")
    # 并发保护：另一个基准正在跑（配置已被它改过），此时再打补丁并把它的
    # 备份当遗物还原，会直接毁掉对方那一轮。必须先检查锁里的 pid 是否还活着。
    if lock.is_file():
        try:
            other_pid = int(lock.read_text(encoding="utf-8").strip() or 0)
        except ValueError:
            other_pid = 0
        if other_pid:
            try:
                os.kill(other_pid, 0)  # 只探活，不发信号
                raise RuntimeError(
                    f"另一个基准进程（pid={other_pid}）正在运行，配置已被它改过。"
                    "请等它结束再跑。"
                )
            except ProcessLookupError:
                lock.unlink(missing_ok=True)  # 上个进程已死，锁是遗物
            except PermissionError:
                raise RuntimeError(
                    f"另一个基准进程（pid={other_pid}）可能仍在运行，拒绝并发。"
                ) from None
    # 自愈：上次跑基准被强杀（SIGKILL 不走 atexit）会留下备份文件。
    # 先把备份还原，再重新打补丁 —— 否则会把「已改过的配置」当成原始配置备份。
    if backup.is_file():
        shutil.copy2(backup, real)
        backup.unlink()
        print("[bench] 检测到上次遗留的配置备份，已先还原", flush=True)
    shutil.copy2(real, backup)
    lock.write_text(str(os.getpid()), encoding="utf-8")

    data = yaml.safe_load(real.read_text(encoding="utf-8")) or {}
    notes = {}

    auxiliary = data.setdefault("auxiliary", {})
    auxiliary.setdefault("background_review", {})["enabled"] = False
    notes["auxiliary.background_review.enabled"] = False

    data.setdefault("moa", {})["enabled"] = False
    notes["moa.enabled"] = False

    # 4. `agent.max_turns` 150 → 30：agent 读二进制 xlsx 时会反复重试
    #    （实测单题 40+ 轮工具调用、prompt token 40 万~128 万）。降到 30 截断
    #    无效重试，两轮同设置，不影响冷热可比。
    agent = data.setdefault("agent", {})
    original_turns = agent.get("max_turns")
    agent["max_turns"] = 30
    notes["agent.max_turns"] = f"{original_turns} → 30"

    for name, block in (data.get("mcp_servers") or {}).items():
        if isinstance(block, dict):
            block["enabled"] = False
            notes[f"mcp_servers.{name}.enabled"] = False

    real.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    _start_config_watchdog(backup, real)
    _SANDBOX_NOTES.update(notes)
    return backup, notes


def _start_config_watchdog(backup: Path, real: Path) -> None:
    """起一个脱离进程组的看门狗：本进程死掉（含 SIGKILL）后 2 秒内还原配置。

    atexit / 信号处理挡不住 SIGKILL，而基准单跑一轮要一两小时，中途被杀的
    概率不低 —— 不能把用户的 config.yaml 留在「已关掉 MOA / 缩减 max_turns」
    的状态。看门狗用 `start_new_session=True` 脱离会话，poll 本进程 pid。
    """
    import subprocess

    script = (
        f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 2; done; "
        f"cp -p '{backup}' '{real}' 2>/dev/null; rm -f '{backup}'"
    )
    try:
        subprocess.Popen(
            ["sh", "-c", script],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001 — 看门狗起不来不该阻断基准
        print(f"[bench] 警告：配置看门狗启动失败（{exc}）", flush=True)


def _restore_hermes_config(backup: Path) -> bool:
    """把 ~/.hermes/config.yaml 按字节还原（备份不在则不动）。"""
    real = Path.home() / ".hermes" / "config.yaml"
    lock = real.with_name("config.yaml.bench-lock")
    if not backup.is_file():
        return False
    # 只有持锁的进程才有权还原（防止两个基准互相踩）
    if lock.is_file():
        try:
            if int(lock.read_text(encoding="utf-8").strip() or 0) != os.getpid():
                return False
        except ValueError:
            pass
    shutil.copy2(backup, real)
    backup.unlink()
    lock.unlink(missing_ok=True)
    return True


def _bootstrap_runtime() -> None:
    """准备 Hermes 运行环境（与生产启动同一顺序）。

    顺序不能换：先 prepare_hermes_import_paths（sys.path + pm 激活恢复），
    再 load_env_and_set_yolo（要 import hermes_cli）。
    """
    sys.path.insert(0, str(REPO_ROOT))
    from trade import bootstrap

    bootstrap.prepare_hermes_import_paths()
    bootstrap.load_env_and_set_yolo()


def _copy_document_set(target_dir: Path) -> list[dict]:
    """把文档集复制进临时文档库目录（内容不变 → SHA256 不变）。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for doc in DOCUMENTS:
        source = DOC_SOURCE_ROOT / doc["rel"]
        if not source.is_file():
            raise FileNotFoundError(f"文档集缺文件：{source}")
        target = target_dir / doc["name"]
        shutil.copy2(source, target)
        copied.append({**doc, "path": str(target), "sha256": _digest(target)})
    return copied


def _read_usage(conn, company_id: int) -> list[tuple]:
    """读 usage_ledger 的全部行（按时间排序）。"""
    try:
        return list(conn.execute(
            "SELECT ts, prompt_tokens, completion_tokens, model FROM usage_ledger "
            "WHERE company_id = ? ORDER BY ts", (company_id,)
        ))
    except Exception:
        return []


def _read_cache_rows(conn, tenant: str) -> dict:
    """读该租户的文档缓存行（键 = sha256）。"""
    try:
        rows = conn.execute(
            "SELECT sha256, extraction_status, doc_kind, attempts, extracted_at, "
            "error_code, summary_text FROM doc_extractions WHERE tenant_id = ?",
            (tenant,),
        ).fetchall()
    except Exception:
        return {}
    return {
        row[0]: {
            "extraction_status": row[1],
            "doc_kind": row[2],
            "attempts": row[3],
            "extracted_at": row[4],
            "error_code": row[5],
            "summary_text": row[6] or "",
        }
        for row in rows
    }


def _usage_delta(before: list, after: list) -> dict:
    """usage_ledger 的增量统计。"""
    new_rows = after[len(before):]
    return {
        "agent_calls": len(new_rows),
        "prompt_tokens": sum(int(r[1] or 0) for r in new_rows),
        "completion_tokens": sum(int(r[2] or 0) for r in new_rows),
        "models": sorted({str(r[3]) for r in new_rows if r[3]}),
    }


def _cache_delta(before: dict, after: dict) -> dict:
    """文档缓存的增量统计：抽取调用次数（attempts 增量）与各文件分类。"""
    attempts = 0
    per_file = {}
    for sha, row in after.items():
        old = before.get(sha)
        old_attempts = int(old["attempts"]) if old else 0
        delta = int(row["attempts"]) - old_attempts
        if delta > 0:
            attempts += delta
        per_file[sha] = {
            "extraction_status": row["extraction_status"],
            "doc_kind": row["doc_kind"],
            "attempts": row["attempts"],
            "attempts_delta": delta,
            "extracted_at": row["extracted_at"],
            "error_code": row["error_code"],
            "summary_chars": len(row["summary_text"]),
        }
    return {"extraction_calls": attempts, "files": per_file}


async def _ask(trade_chat, chat_request_cls, query: str, library_id: int, company_id: int) -> dict:
    """调生产同步聊天端点一次，返回 {ok, response, cache_context, error}。

    429（每分钟 20 次限流）→ 退避重试；其余异常如实记录，不中断基准。
    """
    from fastapi import HTTPException

    for attempt in range(4):
        try:
            payload = chat_request_cls(query=query, library_id=library_id)
            result = await trade_chat(payload=payload, cid=company_id)
            return {
                "ok": True,
                "response": result.get("response", ""),
                "cache_context": result.get("analysis_cache_context") or [],
                "analysis_incomplete": bool(result.get("analysis_incomplete")),
                "error": "",
            }
        except HTTPException as exc:
            if exc.status_code == 429 and attempt < 3:
                # 限流：等一个窗口再问
                await asyncio.sleep(62)
                continue
            return {"ok": False, "response": "", "cache_context": [],
                    "analysis_incomplete": False,
                    "error": f"HTTP {exc.status_code}: {exc.detail}"}
        except Exception as exc:  # noqa: BLE001 — 基准要如实记下失败原因
            return {"ok": False, "response": "", "cache_context": [],
                    "analysis_incomplete": False,
                    "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": False, "response": "", "cache_context": [],
            "analysis_incomplete": False, "error": "retries exhausted"}


def _append_jsonl(path: Path, payload: dict) -> None:
    """追加一行 JSON（增量落盘：跑一半被打断也不丢已跑的结果）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()


async def _run_questions(trade_chat, chat_request_cls, questions, library_id, company_id,
                         documents, rounds, pause, jsonl_path: Path | None = None,
                         phase: str = "", skip: set | None = None) -> list[dict]:
    """跑若干轮问题，返回每题每轮的记录（同时增量写 JSONL）。"""
    from trade.database import get_connection
    from trade.doc_scope import detect_request_scope

    results = []
    skip = skip or set()
    for round_index in range(1, rounds + 1):
        for question in questions:
            if (phase or f"round{round_index}", round_index, question["id"]) in skip:
                print(f"  [{phase or round_index}] {question['id']} 已完成，跳过", flush=True)
                continue
            conn = get_connection()
            try:
                usage_before = _read_usage(conn, company_id)
                cache_before = _read_cache_rows(conn, str(company_id))
            finally:
                conn.close()

            scope = detect_request_scope(question["query"])
            started = time.time()
            answer = await _ask(trade_chat, chat_request_cls, question["query"],
                                library_id, company_id)
            elapsed = round(time.time() - started, 2)

            conn = get_connection()
            try:
                usage_after = _read_usage(conn, company_id)
                cache_after = _read_cache_rows(conn, str(company_id))
            finally:
                conn.close()

            hit_names = list(answer["cache_context"])
            # 缓存旁路只对 summary 生效：locate 命中缓存后仍全文读
            # （trade/api/chat.py:479 会把 skip_paths 清空）。
            full_read = not (scope == "summary" and hit_names)
            record = {
                "phase": phase or f"round{round_index}",
                "round": round_index,
                "id": question["id"],
                "kind": question["kind"],
                "covers": question["covers"],
                "query": question["query"],
                "scope_detected": scope,
                "ok": answer["ok"],
                "error": answer["error"],
                "elapsed_sec": elapsed,
                "response": answer["response"],
                "cache_context": hit_names,
                "used_cache": bool(hit_names),
                "full_read": full_read,
                "analysis_incomplete": answer["analysis_incomplete"],
                "usage": _usage_delta(usage_before, usage_after),
                "cache": _cache_delta(cache_before, cache_after),
            }
            results.append(record)
            # 增量落盘：跑一半被超时打断，已跑的结果仍然可用
            if jsonl_path is not None:
                _append_jsonl(jsonl_path, record)
            print(f"  [{record['phase']}] {question['id']} scope={scope} "
                  f"full_read={full_read} hit={len(hit_names)} "
                  f"tokens={record['usage']['prompt_tokens']}"
                  f"/{record['usage']['completion_tokens']} "
                  f"{elapsed}s", flush=True)
            # 题间留间隔，别把每分钟 20 次的限流打满
            await asyncio.sleep(pause)
    return results


def _mutate_quotation(path: Path, old_value: int, new_value: int) -> bool:
    """改掉报价单里的一个**字面数值单元格**（zip 层改 XML）。

    选 `M6`（报价单号 2018123）：它是普通字面值，不是公式结果。
    改它不会让文档自相矛盾 —— 若改合计（`M30` 是 `=SUM(M20:M29)`），
    只改缓存值会让明细与合计对不上，模型会先指出矛盾再复算，
    那验证的就不是「答案跟着内容变」而是「模型怎么处理矛盾」。

    为什么不用 openpyxl：**用它保存会把整册的公式缓存值全部丢掉**，
    之后 `doc_extract`（`data_only=True`）读到的合计数会变成 None。

    改完用 `parse_document` 复核：旧值必须消失、新值必须出现。
    """
    import re
    import zipfile

    target = "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(path) as src:
        items = [(info, src.read(info.filename)) for info in src.infolist()]

    changed = False
    rewritten = []
    for info, data in items:
        if info.filename == target:
            text = data.decode("utf-8")
            # 只改 M6 单元格内的字面值，避免误伤别处同样的数字
            pattern = re.compile(
                r'(<c r="M6"[^>]*>\s*)<v>' + str(old_value) + r"(</v>)"
            )
            text, count = pattern.subn(rf"\g<1><v>{new_value}\g<2>", text)
            if count:
                changed = True
            data = text.encode("utf-8")
        rewritten.append((info, data))

    if not changed:
        return False

    # 重建 zip（保持原有条目顺序）
    tmp = path.with_suffix(".mutated")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info, data in rewritten:
            dst.writestr(info, data)
    tmp.replace(path)
    return True


def _restore_quotation(original_path: Path, work_path: Path) -> bool:
    """把报价单恢复成原文件（改数验证后必须还原）。"""
    shutil.copy2(original_path, work_path)
    return True


def _reuse_home(path: str) -> Path:
    """复用上次的临时 TRADE_HOME（断点续跑：缓存状态与数据库都保留）。"""
    home = Path(path)
    if not (home / "data").is_dir():
        raise FileNotFoundError(f"续跑目录不存在或不是基准目录：{home}")
    os.environ["TRADE_HOME"] = str(home)
    os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
    return home


def _reuse_state(home: Path) -> dict | None:
    """读断点续跑状态（公司/库/文档集都复用，避免重建导致缓存键全变）。"""
    state_path = home / "bench-state.json"
    if not state_path.is_file():
        return None
    return json.loads(state_path.read_text(encoding="utf-8"))


def _save_state(home: Path, payload: dict) -> None:
    """写断点续跑状态。"""
    (home / "bench-state.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _done_keys(jsonl_path: Path) -> set[tuple]:
    """已完成的 (phase, round, id) 三元组，用于跳过。"""
    done: set[tuple] = set()
    if not jsonl_path.is_file():
        return done
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        done.add((record.get("phase"), record.get("round"), record.get("id")))
    return done


async def _amain(args) -> dict:
    """基准主流程。"""
    home = _reuse_home(args.home) if args.home else _prepare_isolated_home()
    print(f"[bench] 隔离 TRADE_HOME: {home}", flush=True)

    # 临时改 Hermes 配置（关 self-improvement / MOA / MCP）。
    # 用 atexit + 信号处理保证「无论怎么退出都还原」——SIGTERM（timeout）也还原。
    config_backup, sandbox_notes = _patch_real_hermes_config()
    print(f"[bench] 已临时关闭 Hermes 开关：{sandbox_notes}", flush=True)

    import atexit
    import signal

    def _restore_on_exit(*_args) -> None:
        """退出时还原 Hermes 配置（幂等）。"""
        if _restore_hermes_config(config_backup):
            print("[bench] 已还原 ~/.hermes/config.yaml", flush=True)

    atexit.register(_restore_on_exit)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, lambda *_: (_restore_on_exit(), sys.exit(1)))
        except (ValueError, OSError):
            pass

    _bootstrap_runtime()

    from trade import company as company_module
    from trade import database
    from trade import library as library_module
    from trade.api.chat import trade_chat
    from trade.api.models import ChatRequest
    from trade.doc_cache import EXTRACTOR_VERSION
    from trade.doc_scope import detect_request_scope

    database.init_db()
    chat_request_cls = ChatRequest

    # 断点续跑：复用上次的公司/库/文档集（重建会让缓存键与进度全部作废）
    state = _reuse_state(home) if args.home else None
    if state:
        company_id = int(state["company_id"])
        library_id = int(state["library_id"])
        documents = state["documents"]
        print(f"[bench] 断点续跑：复用公司 {company_id} / 库 {library_id}", flush=True)
    else:
        company = company_module.create("基准测试公司", slug="bench-doc-cache")
        company_id = int(company["id"])
        docs_dir = home / "bench-docs"
        documents = _copy_document_set(docs_dir)
        library = library_module.create("基准文档库", str(docs_dir),
                                        "手工基准用", company_id=company_id)
        library_id = int(library["id"])

    selected = [d for d in documents
                if not args.only or d["key"] in set(args.only)]
    questions = [q for q in QUESTIONS
                 if not args.only or q["covers"] == "all"
                 or set(q["covers"]) & set(args.only)]

    print(f"[bench] 文档 {len(selected)} 个 / 问题 {len(questions)} 道 / "
          f"EXTRACTOR_VERSION={EXTRACTOR_VERSION}", flush=True)

    scope_preview = {q["id"]: detect_request_scope(q["query"]) for q in questions}

    # 落状态文件（续跑用）
    _save_state(home, {
        "company_id": company_id,
        "library_id": library_id,
        "documents": documents,
    })

    jsonl_path = Path(args.out).with_suffix(".jsonl")
    done = _done_keys(jsonl_path) if args.home else set()
    if args.mutation_only:
        # 只补跑改数验证（正文两轮已完成）
        rounds = []
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("phase") == "main":
                rounds.append(record)
    else:
        rounds = await _run_questions(trade_chat, chat_request_cls, questions, library_id,
                                      company_id, documents, args.rounds, args.pause,
                                      jsonl_path=jsonl_path, phase="main", skip=done)

    # ── 改数验证：问同一题 → 改数字 → 再问 → 改回 → 再问 ──
    mutation = {"question": MUTATION_QUESTION}
    quotation = next(d for d in documents if d["key"] == "quotation")
    original_path = DOC_SOURCE_ROOT / quotation["rel"]
    work_path = Path(quotation["path"])
    mutation_q = [{"id": "m1", "kind": "number", "covers": ["quotation"],
                   "query": MUTATION_QUESTION}]

    if args.mutation_only:
        baseline = []
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("phase") == "before" and record.get("id") == "m1":
                baseline = [record]
                break
    else:
        baseline = []

    if not baseline:
        baseline = await _run_questions(
            trade_chat, chat_request_cls, mutation_q, library_id, company_id,
            documents, 1, args.pause, jsonl_path=jsonl_path, phase="before")

    mutation["answer_before"] = baseline[0]["response"] if baseline else ""
    mutation["numbers_before"] = _extract_numbers(mutation["answer_before"])
    mutation["sha256_before"] = _digest(work_path)
    mutation["mutated_to"] = QUOTATION_MUTATED_TOTAL
    changed = _mutate_quotation(work_path, QUOTATION_ORIGINAL_TOTAL,
                                 QUOTATION_MUTATED_TOTAL)
    mutation["mutated"] = changed
    mutation["sha256_after_mutate"] = _digest(work_path) if changed else ""

    if changed:
        mutated_rounds = await _run_questions(
            trade_chat, chat_request_cls, mutation_q, library_id, company_id,
            documents, 1, args.pause, jsonl_path=jsonl_path, phase="mutate")
        mutation["answer_after"] = mutated_rounds[0]["response"]
        mutation["numbers_after"] = _extract_numbers(mutation["answer_after"])
        mutation["round_after"] = mutated_rounds[0]
        _restore_quotation(original_path, work_path)
        restored_rounds = await _run_questions(
            trade_chat, chat_request_cls, mutation_q, library_id, company_id,
            documents, 1, args.pause, jsonl_path=jsonl_path, phase="restore")
        mutation["answer_restored"] = restored_rounds[0]["response"]
        mutation["numbers_restored"] = _extract_numbers(mutation["answer_restored"])
        mutation["round_restored"] = restored_rounds[0]
        mutation["sha256_after_restore"] = _digest(work_path)
        mutation["answer_followed_change"] = (
            str(QUOTATION_MUTATED_TOTAL) in mutation["numbers_after"]
            and str(QUOTATION_MUTATED_TOTAL) not in mutation["numbers_before"]
        )
        mutation["answer_reverted"] = (
            str(QUOTATION_ORIGINAL_TOTAL) in mutation["numbers_restored"]
            and str(QUOTATION_MUTATED_TOTAL) not in mutation["numbers_restored"]
        )
    else:
        mutation["mutated"] = False
        mutation["answer_after"] = ""
        mutation["answer_restored"] = ""
        mutation["answer_followed_change"] = False
        mutation["answer_reverted"] = False

    # ── 最终缓存表快照（分类判定结果）──
    from trade.database import get_connection

    conn = get_connection()
    try:
        final_cache = _read_cache_rows(conn, str(company_id))
        final_usage = _read_usage(conn, company_id)
    finally:
        conn.close()

    by_sha = {d["sha256"]: d for d in documents}
    classification = []
    for sha, row in final_cache.items():
        doc = by_sha.get(sha)
        classification.append({
            "file": doc["name"] if doc else sha[:12],
            "sha256": sha,
            "expect_kind": doc.get("expect_kind") if doc else None,
            "doc_kind": row["doc_kind"],
            "extraction_status": row["extraction_status"],
            "error_code": row["error_code"],
            "attempts": row["attempts"],
            "summary_chars": len(row["summary_text"]),
        })
    classification.sort(key=lambda x: x["file"])

    return {
        "meta": {
            "repo": str(REPO_ROOT),
            "trade_home": str(home),
            "hermes_home_sandbox": "未隔离（临时改 ~/.hermes/config.yaml，结束还原）",
            "sandbox_config_notes": _SANDBOX_NOTES,
            "extractor_version": EXTRACTOR_VERSION,
            "rounds": args.rounds,
            "run_started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "documents": [
                {"key": d["key"], "name": d["name"], "sha256": d["sha256"],
                 "expect_kind": d["expect_kind"], "parse": d["parse"], "role": d["role"]}
                for d in documents
            ],
            "questions": [
                {**q, "scope_detected": scope_preview.get(q["id"])}
                for q in questions
            ],
        },
        "rounds": rounds,
        "mutation": mutation,
        "classification": classification,
        "usage_total": {
            "rows": len(final_usage),
            "prompt_tokens": sum(int(r[1] or 0) for r in final_usage),
            "completion_tokens": sum(int(r[2] or 0) for r in final_usage),
        },
    }


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="文档提取缓存手工基准")
    parser.add_argument("--rounds", type=int, default=2, help="问答轮数（默认 2）")
    parser.add_argument("--only", nargs="*", default=None,
                        help="只跑指定文档 key（默认全部）")
    parser.add_argument("--pause", type=float, default=3.0,
                        help="题间间隔秒数（默认 3，避开每分钟 20 次限流）")
    parser.add_argument("--out", default="reports/benchmark-doc-cache.json",
                        help="结果 JSON 输出路径")
    parser.add_argument("--home", default="",
                        help="断点续跑：复用上次的临时 TRADE_HOME 目录")
    parser.add_argument("--mutation-only", action="store_true",
                        help="只补跑改数验证（复用已有两轮结果）")
    args = parser.parse_args()

    result = asyncio.run(_amain(args))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[bench] 结果已写入 {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
