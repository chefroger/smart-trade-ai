"""
Trade AI Assistant — 文档库管理.

B2B 文档库（PDF/XLSX/DOCX 文件目录）的 CRUD 操作。
每个文档库对应一个文件系统目录，AI 智能体可以扫描并读取其中的文件。

所有操作都限定在公司范围内，实现多租户隔离。
"""

import os
from pathlib import Path

from trade.database import get_connection

# 禁止作为 root_path 的敏感数据目录（含 Windows 路径）
# 注意：这些目录连同其子目录都会被禁止（如 .ssh/known_hosts）。
# 只列真正含敏感数据的目录（密钥/配置/业务数据），
# 不列 /tmp /var 等共享临时目录——它们不敏感且会误伤正常路径。
_LOCAL_APP = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
_FORBIDDEN_DIRS = [
    (Path.home() / ".hermes").resolve(),
    (Path.home() / ".trade").resolve(),
    (Path.home() / ".ssh").resolve(),
    (Path(_LOCAL_APP) / "hermes").resolve(),    # Windows Hermes 路径
    (Path(_LOCAL_APP) / "trade").resolve(),     # Windows Trade 路径
    Path("/etc").resolve(),
    Path("/root").resolve(),
]


def _validate_root_path(rp: str) -> str:
    """验证 root_path 合法：不包含 .. , 是绝对路径, 不在禁止目录列表中。

    家目录和根目录本身禁止（精确匹配），但其下非敏感子目录允许
    （如 ~/Documents/client-files 合法，~/ 或 / 本身非法）。
    """
    if ".." in rp:
        raise ValueError("root_path 不能包含 '..'")
    rp_path = Path(rp).resolve()
    if not rp_path.is_absolute():
        raise ValueError(f"root_path 必须是绝对路径: {rp}")

    # 禁止指向根目录或家目录本身（精确匹配）
    # 根目录跨平台判断：父目录等于自身（Unix: / 的 parent 是 /；Windows: C:\ 的 parent 是 C:\）
    if rp_path.parent == rp_path or rp_path == Path.home():
        raise ValueError("root_path 不能指向根目录或家目录本身")

    # 禁止指向敏感数据目录及其所有子目录
    for forbidden in _FORBIDDEN_DIRS:
        try:
            rp_path.relative_to(forbidden)
        except ValueError:
            continue  # 不在该禁止目录下，检查下一个
        # relative_to 成功 → rp_path 位于 forbidden 之内（含本身）
        raise ValueError(f"root_path 不能指向系统敏感目录: {forbidden}")
    return rp


def create(
    name: str,
    root_path: str,
    description: str = "",
    company_id: int | None = None,
) -> dict:
    """创建归属于指定公司的文档库，返回新记录行的字典。"""
    # 路径穿越防护
    root_path = _validate_root_path(root_path)
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO libraries (company_id, name, root_path, description) VALUES (?, ?, ?, ?)",
            (company_id, name, root_path, description),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM libraries WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_by_company(company_id: int | None = None) -> list[dict]:
    """返回某个公司的所有文档库，按 id 降序排列（最新的在前）。company_id=None 表示未分配。"""
    conn = get_connection()
    try:
        if company_id is None:
            # 未指定公司，查询所有未分配公司的文档库
            rows = conn.execute(
                "SELECT * FROM libraries WHERE company_id IS NULL ORDER BY id DESC"
            ).fetchall()
        else:
            # 按指定公司 ID 查询文档库
            rows = conn.execute(
                "SELECT * FROM libraries WHERE company_id = ? ORDER BY id DESC",
                (company_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get(library_id: int, company_id: int | None = None) -> dict | None:
    """根据 id 获取单个文档库，可选地按公司范围限定。"""
    conn = get_connection()
    try:
        if company_id is not None:
            # 指定了公司，需同时校验公司 ID 以隔离多租户数据
            row = conn.execute(
                "SELECT * FROM libraries WHERE id = ? AND company_id = ?",
                (library_id, company_id),
            ).fetchone()
        else:
            # 未指定公司，仅按 id 查询
            row = conn.execute("SELECT * FROM libraries WHERE id = ?", (library_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def update(
    library_id: int,
    company_id: int | None = None,
    **kwargs,
) -> dict | None:
    """更新文档库字段（name, root_path, description）。"""
    allowed = {"name", "root_path", "description"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    # 路径穿越防护：校验 ..  / 绝对路径 / 禁止目录
    if "root_path" in updates:
        updates["root_path"] = _validate_root_path(updates["root_path"])
    if not updates:
        # 没有可更新的字段时，直接返回当前记录
        return get(library_id, company_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [library_id]

    conn = get_connection()
    try:
        if company_id is not None:
            # 指定了公司，需同时校验公司 ID 以隔离多租户数据
            n = conn.execute(
                f"UPDATE libraries SET {set_clause}, updated_at = datetime('now','localtime') "
                "WHERE id = ? AND company_id = ?",
                values + [company_id],
            ).rowcount
        else:
            # 未指定公司，仅按 id 更新
            n = conn.execute(
                f"UPDATE libraries SET {set_clause}, updated_at = datetime('now','localtime') "
                "WHERE id = ?",
                values,
            ).rowcount
        conn.commit()
        if n == 0:
            # 没有行被更新，说明指定的 id 不存在或不属于该公司
            return None
        return get(library_id, company_id)
    finally:
        conn.close()


def delete(library_id: int, company_id: int | None = None) -> bool:
    """删除归属于指定公司的文档库。如果确实删除了某行则返回 True。"""
    conn = get_connection()
    try:
        if company_id is not None:
            # 指定了公司，需同时校验公司 ID 以确保只能删除本公司文档库
            cur = conn.execute(
                "DELETE FROM libraries WHERE id = ? AND company_id = ?",
                (library_id, company_id),
            )
        else:
            # 未指定公司，仅按 id 删除
            cur = conn.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def count_files(library_id: int, company_id: int | None = None, max_count: int = 10_000) -> int:
    """统计文档库根目录中的文件数量（非递归）。

    company_id 参数为向后兼容而设为可选，但 API 调用方应始终传入
    以确保多租户隔离。
    使用 os.scandir 比 Path.iterdir 快 3-5 倍；超过 max_count 时提前返回。
    """
    lib = get(library_id, company_id=company_id)
    if not lib:
        return 0
    root = Path(lib["root_path"])
    if not root.is_dir():
        return 0
    count = 0
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    count += 1
                    if count >= max_count:
                        break
    except OSError:
        # 权限或 IO 错误：返回已统计数
        return count
    return count


# ── helpers ──────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "company_id": row["company_id"],
        "name": row["name"],
        "root_path": row["root_path"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
