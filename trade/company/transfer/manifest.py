"""包 manifest 与校验和。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
    company = data.get("company") or {}
    if not company.get("name"):
        raise InvalidPackageError("manifest.company.name is missing")
    for key in ("tables", "paths"):
        if key not in data:
            raise InvalidPackageError(f"manifest.{key} is missing")
