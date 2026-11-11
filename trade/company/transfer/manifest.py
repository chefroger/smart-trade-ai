"""包 manifest 与校验和。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from trade.company.transfer import FORMAT_VERSION, PACKAGE_FORMAT, InvalidPackageError

EXCLUDED_FROM_CHECKSUMS = {"manifest.json", "checksums.sha256"}


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(root: Path) -> None:
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in EXCLUDED_FROM_CHECKSUMS:
            continue
        lines.append(f"{sha256_file(path)}  {rel}")
    (root / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_checksums(root: Path) -> None:
    checksum_file = root / "checksums.sha256"
    if not checksum_file.is_file():
        raise InvalidPackageError("checksums.sha256 is missing")
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        expected, _, rel = line.partition("  ")
        # checksums 同样是包内可篡改的输入：只读哈希也要挡路径逃逸（纵深防御）
        pure = PurePosixPath(rel)
        if (not rel or "\x00" in rel or "\\" in rel
                or pure.is_absolute() or ".." in pure.parts):
            raise InvalidPackageError(f"unsafe path in checksums: {rel!r}")
        target = root / rel
        if not target.is_file():
            raise InvalidPackageError(f"file listed in checksums is missing: {rel}")
        actual = sha256_file(target)
        if actual != expected:
            raise InvalidPackageError(f"checksum mismatch: {rel}")


def load_manifest(root: Path) -> dict:
    path = root / "manifest.json"
    if not path.is_file():
        raise InvalidPackageError("manifest.json is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidPackageError(f"manifest.json is unreadable: {exc}") from exc
    validate_manifest(data)
    return data


def validate_manifest(data: dict) -> None:
    if not isinstance(data, dict):
        raise InvalidPackageError("manifest must be an object")
    if data.get("format") != PACKAGE_FORMAT:
        raise InvalidPackageError("unknown package format")
    if data.get("format_version") != FORMAT_VERSION:
        raise InvalidPackageError(
            f"unsupported format_version: {data.get('format_version')!r}"
        )
    company = data.get("company")
    if not isinstance(company, dict) or not isinstance(company.get("name"), str) \
            or not company.get("name", "").strip():
        raise InvalidPackageError("manifest.company.name is missing")
    for key in ("slug", "logo_url", "website", "contact_name", "contact_email", "address"):
        if key in company and not isinstance(company.get(key), str):
            raise InvalidPackageError(f"manifest.company.{key} must be a string")
    for key in ("tables", "paths"):
        if key not in data:
            raise InvalidPackageError(f"manifest.{key} is missing")
    paths = data.get("paths")
    if not isinstance(paths, dict):
        raise InvalidPackageError("manifest.paths must be an object")
    for key in ("data_dir", "work_dir"):
        if key in paths and not isinstance(paths.get(key), str):
            raise InvalidPackageError(f"manifest.paths.{key} must be a string")
    _validate_library_entries(paths)


def _validate_library_entries(paths: dict) -> None:
    """校验资料库条目，重点是 export_id —— 它会拼进 staging 下的路径。

    ZIP 本身的 zip-slip 防御只覆盖条目名；manifest 是**包里另一个可被篡改的
    输入**，导入端会用它拼 ``staging/libraries/<export_id>``。不校验就等于留了
    一条从包外读文件的路（2026-11-11 审计 P2-1）。写侧只生成 ``L<id>``，这里
    按同一字符集收窄。
    """
    libraries = paths.get("libraries") or []
    if not isinstance(libraries, list):
        raise InvalidPackageError("manifest.paths.libraries must be a list")
    for entry in libraries:
        if not isinstance(entry, dict):
            raise InvalidPackageError("manifest.paths.libraries[] must be objects")
        export_id = entry.get("export_id")
        if not isinstance(export_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", export_id):
            raise InvalidPackageError(
                f"unsafe manifest.paths.libraries[].export_id: {export_id!r}"
            )
        for key in ("name", "root_path", "description"):
            if key in entry and not isinstance(entry.get(key), str):
                raise InvalidPackageError(
                    f"manifest.paths.libraries[].{key} must be a string"
                )
