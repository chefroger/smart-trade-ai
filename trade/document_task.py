"""Trade 文档分析任务的范围和完成度状态，不读取文件内容。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_STRICT_FILE_PATTERNS = (
    r"逐个",
    r"完整读取",
    r"读到末尾",
    r"不要遗漏",
    r"全部文件",
    r"所有文件",
    r"every file",
    r"all files",
    r"read.*(entire|complete|all)",
)


@dataclass(frozen=True)
class DocumentFile:
    """一个待分析文件的只读元数据。"""

    path: Path
    relative_path: str
    size: int
    mtime_ns: int
    version: str


@dataclass(frozen=True)
class GateResult:
    """文档读取完成度门禁结果。"""

    status: str
    complete: list[str]
    missing: list[str]
    errors: list[str]


@dataclass
class DocumentTask:
    """一次请求内的文件范围和 Hermes 读取证据映射。"""

    root: Path
    files: list[DocumentFile]

    @classmethod
    def from_root(cls, root: str | Path) -> DocumentTask:
        """枚举根目录下的普通文件；不读取文件内容。"""
        root_path = Path(root).resolve()
        files: list[DocumentFile] = []
        for path in sorted(root_path.rglob("*"), key=lambda item: item.relative_to(root_path).as_posix()):
            if not path.is_file() or path.is_symlink():
                continue
            stat = path.stat()
            version = hashlib.sha256(
                f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}".encode()
            ).hexdigest()
            files.append(DocumentFile(
                path=path,
                relative_path=path.relative_to(root_path).as_posix(),
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                version=version,
            ))
        return cls(root=root_path, files=files)

    def evaluate(self, evidence: dict[str, dict[str, Any]]) -> GateResult:
        """只接受 Hermes 明确报告 complete 的每个文件；缺证据时 fail-closed。"""
        complete: list[str] = []
        missing: list[str] = []
        errors: list[str] = []
        for item in self.files:
            record = evidence.get(str(item.path), {})
            if record.get("complete") is True:
                metadata = record.get("document_metadata") or {}
                if metadata.get("kind") == "xlsx" and not metadata.get("sheets"):
                    missing.append(item.relative_path)
                    errors.append(f"{item.relative_path}: no sheet coverage metadata")
                elif metadata.get("kind") == "pdf" and not metadata.get("pages"):
                    missing.append(item.relative_path)
                    errors.append(f"{item.relative_path}: no page coverage metadata")
                else:
                    complete.append(item.relative_path)
            else:
                missing.append(item.relative_path)
                if record.get("error"):
                    errors.append(f"{item.relative_path}: {record['error']}")
        status = "complete" if not missing and not errors else "incomplete"
        return GateResult(status, complete, missing, errors)


def should_enforce_document_gate(query: str, *, has_library: bool = False) -> bool:
    """判断是否明确要求完整文件分析；普通聊天保持原有行为。"""
    text = str(query or "").strip().lower()
    if not has_library:
        return False
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in _STRICT_FILE_PATTERNS)
