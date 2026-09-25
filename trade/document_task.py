"""Trade 文档分析任务的范围和完成度状态，不读取文件内容。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Trade 认为「需要完整读取」的文档类型。Hermes 负责实际读取与解析，
# 这里只决定哪些文件纳入强制范围。
_ANALYZABLE_EXTENSIONS = frozenset({
    # 纯文本
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".log", ".ini", ".cfg", ".conf", ".sql",
    # 办公文档
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".epub",
    # 代码/笔记本（技术资料场景）
    ".ipynb",
})

# 临时文件与办公软件锁文件：可能随时消失，不纳入强制范围。
_TEMP_EXTENSIONS = frozenset({".tmp", ".temp", ".swp", ".swo", ".bak", ".crdownload", ".part"})

# manifest 文件数上限。超过即放弃强制：这么大的目录几乎不可能被完整读取，
# 强行判定只会把正常问答变成失败，同时枚举本身也会拖慢请求。
_MAX_MANIFEST_FILES = 200

# 用户明确要求「整个目录/全部文件」的范围词。
_DIRECTORY_SCOPE_PATTERNS = (
    r"所有(的)?(文件|文档|资料|附件)",
    r"全部(的)?(文件|文档|资料|附件)",
    r"每(一)?(个|份|张)(文件|文档|资料)",
    r"各(个)?(文件|文档)",
    r"整个?(目录|文件夹)",
    r"目录(里|中|下)的?(所有|全部|每)",
    r"文件夹(里|中|下)的?(所有|全部|每)",
    r"every\s+file",
    r"all\s+(the\s+)?(files|documents)",
    r"each\s+file",
    r"entire\s+(folder|directory)",
)

# 用户明确要求「完整读完、不跳过」的意图词。
_COMPLETENESS_INTENT_PATTERNS = (
    r"逐个",
    r"逐份",
    r"逐一",
    r"完整(读取|读完|阅读|查看|分析|扫描)",
    r"完全(读取|读完|阅读|查看|分析)",
    r"读到(末尾|结尾|最后)",
    r"读到底",
    r"(不要|不得|不能|别)(遗漏|跳过|漏掉)",
    r"read\s+(them\s+|it\s+)?(all|fully|completely|entirely)",
    r"read\s+to\s+the\s+end",
    r"completely",
    r"thoroughly",
    r"entirely",
)


@dataclass(frozen=True)
class DocumentFile:
    """一个必须完整读取的文件。"""

    path: Path
    relative_path: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class SkippedFile:
    """一个不纳入强制范围的文件及其原因。"""

    relative_path: str
    reason: str


@dataclass(frozen=True)
class GateResult:
    """文档读取完成度门禁结果。"""

    status: str
    complete: list[str]
    missing: list[str]
    errors: list[str]
    skipped: list[dict] = field(default_factory=list)


@dataclass
class DocumentTask:
    """一次请求内的文件范围和 Hermes 读取证据映射。"""

    root: Path
    files: list[DocumentFile]
    skipped: list[SkippedFile]
    truncated: bool = False

    @classmethod
    def from_root(cls, root: str | Path) -> DocumentTask:
        """枚举根目录下的文件并按可读性分类；不读取文件内容。"""
        root_path = Path(root).resolve()
        analyzable: list[DocumentFile] = []
        skipped: list[SkippedFile] = []
        truncated = False
        for path in sorted(root_path.rglob("*"), key=lambda item: item.relative_to(root_path).as_posix()):
            if len(analyzable) + len(skipped) >= _MAX_MANIFEST_FILES:
                truncated = True
                break
            try:
                relative = path.relative_to(root_path).as_posix()
            except ValueError:
                # rglob 理论上不会给出越界路径，出现即跳过，避免相对路径计算崩溃。
                continue
            reason = cls._skip_reason(path)
            if reason is not None:
                skipped.append(SkippedFile(relative, reason))
                continue
            try:
                stat = path.stat()
            except OSError:
                # 枚举与 stat 之间文件被删除/无权限：记为跳过，不让请求失败。
                skipped.append(SkippedFile(relative, "stat_failed"))
                continue
            analyzable.append(DocumentFile(
                path=path,
                relative_path=relative,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            ))
        return cls(root=root_path, files=analyzable, skipped=skipped, truncated=truncated)

    @staticmethod
    def _skip_reason(path: Path) -> str | None:
        """返回跳过原因；None 表示该文件必须完整读取。"""
        if path.is_symlink():
            return "symlink"
        if not path.is_file():
            return "not_regular_file"
        name = path.name
        if name.startswith("."):
            return "hidden_file"
        if name.startswith("~$"):
            return "office_lock_file"
        suffix = path.suffix.lower()
        if suffix in _TEMP_EXTENSIONS:
            return "temp_file"
        if suffix not in _ANALYZABLE_EXTENSIONS:
            return "unsupported_type"
        return None

    def _fingerprint_changed(self, item: DocumentFile) -> bool:
        """文件在分析期间被改动或删除时返回 True。"""
        try:
            stat = item.path.stat()
        except OSError:
            return True
        return stat.st_size != item.size or stat.st_mtime_ns != item.mtime_ns

    def evaluate(self, evidence: dict[str, dict[str, Any]]) -> GateResult:
        """只接受 Hermes 明确报告 complete 的可分析文件；缺证据时 fail-closed。"""
        # 证据键先归一化，避免同一文件的不同书写形式被误判为未读取。
        normalized: dict[str, dict[str, Any]] = {}
        for key, value in evidence.items():
            try:
                resolved = str(Path(key).resolve())
            except (OSError, ValueError):
                continue
            normalized.setdefault(resolved, value)

        complete: list[str] = []
        missing: list[str] = []
        errors: list[str] = []
        for item in self.files:
            if self._fingerprint_changed(item):
                missing.append(item.relative_path)
                errors.append(f"{item.relative_path}: changed_during_analysis")
                continue
            record = normalized.get(str(item.path), {})
            if record.get("complete") is not True:
                missing.append(item.relative_path)
                if record.get("error"):
                    errors.append(f"{item.relative_path}: {record['error']}")
                continue
            metadata = record.get("document_metadata") or {}
            if metadata.get("kind") == "xlsx" and not metadata.get("sheets"):
                missing.append(item.relative_path)
                errors.append(f"{item.relative_path}: no sheet coverage metadata")
            elif metadata.get("kind") == "pdf" and not metadata.get("pages"):
                missing.append(item.relative_path)
                errors.append(f"{item.relative_path}: no page coverage metadata")
            else:
                complete.append(item.relative_path)

        if not missing and not errors:
            status = "complete"
        elif not normalized:
            # 完全没有读取证据：无法区分「没读文件」和「用别的方式读了」，
            # 判为不可追踪，避免把正常问答误判成失败。
            status = "untracked"
        else:
            status = "incomplete"
        return GateResult(
            status=status,
            complete=complete,
            missing=missing,
            errors=errors,
            skipped=[{"file": item.relative_path, "reason": item.reason} for item in self.skipped],
        )


# 门禁原因的中文说明，用于把不通过原因直接呈现给用户。
_REASON_LABELS = {
    "hidden_file": "隐藏文件",
    "office_lock_file": "办公软件临时锁文件",
    "temp_file": "临时文件",
    "symlink": "符号链接",
    "not_regular_file": "非普通文件",
    "unsupported_type": "格式不支持完整读取",
    "stat_failed": "文件无法访问",
    "changed_during_analysis": "分析期间被修改或删除",
    "no sheet coverage metadata": "未能确认全部工作表已读取",
    "no page coverage metadata": "未能确认全部页面已读取",
}


def _label(reason: str) -> str:
    """把内部原因码翻成用户可读说明，未知原因原样返回。"""
    return _REASON_LABELS.get(reason, reason)


def format_incomplete_report(result: GateResult) -> str:
    """把门禁结果转成用户可读的说明文本，作为本次回答返回。"""
    detail = {}
    for entry in result.errors:
        name, _, reason = entry.partition(":")
        detail[name.strip()] = reason.strip()

    lines = ["⚠️ 本次没有完成完整读取，因此不给出分析结论。", ""]
    if result.missing:
        lines.append("未读完的文件：")
        for name in result.missing:
            lines.append(f"- {name}（{_label(detail.get(name, '未读取完整'))}）")
        lines.append("")
    if result.skipped:
        lines.append("未纳入本次完整分析的文件：")
        for item in result.skipped:
            lines.append(f"- {item['file']}（{_label(item['reason'])}）")
        lines.append("")
    lines.append("请让助手补齐上述文件，或改为只分析指定文件的提问方式后重试。")
    return "\n".join(lines)


def should_enforce_document_gate(query: str) -> bool:
    """判断用户是否明确要求读完整目录；普通聊天保持原有行为。

    必须同时出现「目录范围」和「完整读取意图」，避免「逐个介绍产品」这类
    普通提问被误判为全量文件分析。
    """
    text = str(query or "").strip().lower()
    if not text:
        return False
    has_scope = any(re.search(p, text, re.IGNORECASE) for p in _DIRECTORY_SCOPE_PATTERNS)
    has_intent = any(re.search(p, text, re.IGNORECASE) for p in _COMPLETENESS_INTENT_PATTERNS)
    return has_scope and has_intent
