#!/usr/bin/env python3
"""按招标清单匹配本地文件库并归档。

用法：
    python match_archive.py --items items.json --library <文件库目录> --dest <归档目录> [--apply] [--move]

`items.json`：

    {
      "items": [
        {"no": 1, "name": "<清单名称>", "number": "<图号/编号>",
         "files": ["<本地文件名>"], "is_set": false}
      ]
    }

匹配策略（按序，**不放宽造假**）：
    1. 编号精确匹配（规范化后相等）**且**名称相关；
    2. 名称相等；
    3. 名称互含；
    4. 皆无 → 输出候选清单，不归档。

编号规范化（关键）：统一分隔符、统一大小写、纯数字段去前导零。
**禁止「删光所有非字母数字」再比较** —— 那会把 `A-1` 和 `A1` 判成相等，
造成大面积误报；规范化后还必须过「名称相关」校验（词交集至少 1 个）。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import _i18n_docmatch as _i18n

#: 分隔符与大小写归一时匹配的「非字母数字」字符段。
_SEP_RE = re.compile(r"[^a-z0-9]+")
#: 名称分词：英文/数字串，或单个中文字。
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")

_ILLEGAL = r'[<>:"/\\|?*\x00-\x1f]'


def normalize_number(value: str) -> str:
    """规范化编号：分隔符统一成 `-`、转小写、纯数字段去前导零。

    `A-0012-00` 与 `a_12_000` 都归一为 `a-12-0`。
    **保留分隔符**（不删光），这样 `A-1` 与 `A1` 仍是两个不同的编号。
    """
    text = _SEP_RE.sub("-", str(value or "").strip().lower()).strip("-")
    if not text:
        return ""
    parts = []
    for seg in text.split("-"):
        if seg.isdigit():
            seg = str(int(seg))  # 前导零去掉；全零段 → "0"
        parts.append(seg)
    return "-".join(parts)


def numbers_equal(a: str, b: str) -> bool:
    """两个编号规范化后是否相等（探针 7：末段 00 与 000 视为相等）。"""
    na, nb = normalize_number(a), normalize_number(b)
    return bool(na) and na == nb


def name_tokens(name: str) -> set[str]:
    """名称分词：英文/数字按串、中文按字。用于「名称相关」校验。"""
    return set(_TOKEN_RE.findall(str(name or "").lower()))


def name_related(a: str, b: str) -> bool:
    """两份名称是否相关（词交集至少 1 个）—— 防止编号巧合造成误匹配。"""
    return bool(name_tokens(a) & name_tokens(b))


def _norm_name(name: str) -> str:
    """名称比较用的归一：折叠空白、转小写。"""
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


@dataclass
class Match:
    """一个清单项与它匹配到的文件。"""

    item: dict
    files: list[Path]
    strategy: str


@dataclass
class PlanItem:
    """归档动作：单文件平放，或成套项整夹打包。"""

    no: object
    name: str
    files: list[Path]
    is_set: bool


def match_items(items: list[dict], library: list[Path]) -> tuple[list[Match], list[dict], list[Path]]:
    """按三档策略匹配；返回 (匹配, 未匹配清单项, 未匹配文件)。

    匹配上的文件会从候选池里移除，避免一个文件被多个清单项重复认领。
    """
    remaining = list(library)
    matches: list[Match] = []
    unmatched_items: list[dict] = []

    # 第零档：清单里直接点名的文件（成套项常这么给）—— 文件名精确匹配
    by_name = {f.name: f for f in remaining}
    for item in items:
        wanted = [str(n) for n in (item.get("files") or [])]
        hit = [by_name[n] for n in wanted if n in by_name]
        if hit:
            matches.append(Match(item=item, files=hit, strategy="strategy.specified"))
            remaining = [f for f in remaining if f not in hit]

    specified = {id(m.item) for m in matches}

    # 第一档：编号精确（规范化后）+ 名称相关
    for item in items:
        if id(item) in specified:
            continue
        hit: list[Path] = []
        for f in remaining:
            if numbers_equal(item.get("number", ""), f.stem) and name_related(
                item.get("name", ""), f.stem
            ):
                hit.append(f)
        if hit:
            matches.append(Match(item=item, files=hit, strategy="strategy.number"))
            remaining = [f for f in remaining if f not in hit]

    matched_ids = {id(m.item) for m in matches}

    # 第二档：名称相等
    for item in items:
        if id(item) in matched_ids:
            continue
        target = _norm_name(item.get("name", ""))
        hit = [f for f in remaining if _norm_name(f.stem) == target]
        if hit:
            matches.append(Match(item=item, files=hit, strategy="strategy.name_equal"))
            remaining = [f for f in remaining if f not in hit]
            matched_ids.add(id(item))

    # 第三档：名称互含
    for item in items:
        if id(item) in matched_ids:
            continue
        target = _norm_name(item.get("name", ""))
        if not target:
            continue
        hit = [
            f for f in remaining
            if target in _norm_name(f.stem) or _norm_name(f.stem) in target
        ]
        if hit:
            matches.append(Match(item=item, files=hit, strategy="strategy.name_contains"))
            remaining = [f for f in remaining if f not in hit]
            matched_ids.add(id(item))

    unmatched_items = [i for i in items if id(i) not in matched_ids]
    return matches, unmatched_items, remaining


def plan_archive(matches: list[Match]) -> list[PlanItem]:
    """把匹配结果转成归档动作；成套项（is_set）整夹打包。"""
    plan: list[PlanItem] = []
    for m in matches:
        plan.append(
            PlanItem(
                no=m.item.get("no"),
                name=str(m.item.get("name") or ""),
                files=list(m.files),
                is_set=bool(m.item.get("is_set")),
            )
        )
    return plan


def _safe(name: str) -> str:
    """替换文件名非法字符。"""
    return re.sub(_ILLEGAL, "_", str(name or "")).strip(" .") or "未命名"


def apply_archive(plan: list[PlanItem], dest: Path, *, move: bool = False) -> dict:
    """执行归档：单文件平放到根目录，成套项放进 `<序号>/` 子文件夹。

    默认**复制**（源文件保留）；``move=True`` 才移动。返回动作清单。
    """
    dest.mkdir(parents=True, exist_ok=True)
    actions: list[dict] = []
    for p in plan:
        if p.is_set:
            folder = dest / _safe(str(p.no))
            folder.mkdir(parents=True, exist_ok=True)
            for f in p.files:
                target = folder / f.name
                _transfer(f, target, move)
                actions.append({"kind": "set", "folder": str(folder), "file": str(target)})
        else:
            for f in p.files:
                target = _unique(dest / f"{_safe(str(p.no))}-{f.name}")
                _transfer(f, target, move)
                actions.append({"kind": "single", "file": str(target)})
    return {"actions": actions}


def _transfer(src: Path, dst: Path, move: bool) -> None:
    """复制或移动单个文件。"""
    if move:
        shutil.move(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))


def _unique(path: Path) -> Path:
    """目标已存在时加序号，避免覆盖。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 2
    while True:
        candidate = path.with_name(f"{stem}({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def verify_archive(dest: Path, plan: list[PlanItem]) -> tuple[bool, str]:
    """回读验证：根目录文件数 = 单文件项数；总文件数 = 计划文件数。"""
    singles = [p for p in plan if not p.is_set]
    expected_root = sum(len(p.files) for p in singles)
    expected_total = sum(len(p.files) for p in plan)

    root_files = [f for f in dest.iterdir() if f.is_file()]
    total_files = [f for f in dest.rglob("*") if f.is_file()]

    if len(root_files) != expected_root:
        return False, _i18n.t("verify_root_count", expected=expected_root,
                              actual=len(root_files))
    if len(total_files) != expected_total:
        return False, _i18n.t("verify_total_count", expected=expected_total,
                              actual=len(total_files))
    return True, ""


def load_items(path: str | Path) -> list[dict]:
    """读清单 JSON。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [i for i in raw.get("items", []) if isinstance(i, dict)]


def library_files(root: Path) -> list[Path]:
    """文件库里所有文件（递归、排序稳定）。"""
    return sorted(p for p in root.rglob("*") if p.is_file())


def main() -> int:
    """入口：匹配 → 出计划 → （可选）执行 → 验证 → 汇报。"""
    parser = argparse.ArgumentParser(description="按清单匹配并归档招标文件")
    parser.add_argument("--items", required=True, help="清单 JSON")
    parser.add_argument("--library", required=True, help="本地文件库目录")
    parser.add_argument("--dest", required=True, help="归档根目录")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只出计划）")
    parser.add_argument("--move", action="store_true", help="移动而非复制")
    parser.add_argument("--lang", choices=("zh", "en"), default=None,
                        help="Output language (default: TRADE_LANG or zh)")
    args = parser.parse_args()
    _i18n.set_language(args.lang)

    items = load_items(args.items)
    library = library_files(Path(args.library).expanduser())
    matches, unmatched_items, unmatched_files = match_items(items, library)

    print(_i18n.t("summary", items=len(items), files=len(library),
                  matched=len(matches), unmatched=len(unmatched_items)))
    for m in matches:
        print(_i18n.t("match_line", strategy=_i18n.t(m.strategy),
                      no=m.item.get("no"), name=m.item.get("name"),
                      files=", ".join(f.name for f in m.files)))
    for i in unmatched_items:
        print(_i18n.t("unmatched_line", no=i.get("no"), name=i.get("name"),
                      candidates=len(unmatched_files)))

    if not args.apply:
        print(_i18n.t("plan_only"))
        return 0

    plan = plan_archive(matches)
    apply_archive(plan, Path(args.dest).expanduser(), move=args.move)
    ok, why = verify_archive(Path(args.dest).expanduser(), plan)
    print(_i18n.t("verify_ok") if ok else _i18n.t("verify_fail", why=why))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
