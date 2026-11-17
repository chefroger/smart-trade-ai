"""单公司数据打包导出 / 导入（跨电脑迁移）。

交换格式是一个 ZIP：
  manifest.json / checksums.sha256 / db/*.json / company_data/ / libraries/ / memory/

设计约束：
- 只按 company_id 导出，不整库拷贝；导入时重映射主键与外键。
- 同名匹配只看公司名称，不看 slug / company_id；目标机同名不同 slug 时复用目标。
- 包内不包含 license、machine_id、PID、向量索引、Hermes 定时任务等机器级数据。
"""

from __future__ import annotations

PACKAGE_FORMAT = "trade-company-pack"
FORMAT_VERSION = 1

# 压缩包上限：超过 1 GiB 不自动打包，提示用户手动拷贝。
MAX_PACKAGE_BYTES = 1 << 30
# 解压后总大小上限（防 zip bomb）。
MAX_UNCOMPRESSED_BYTES = 2 << 30
MAX_ENTRIES = 50000


class TransferError(Exception):
    """导出/导入的可预期错误基类。"""


class PackageTooLargeError(TransferError):
    """打包结果超过上限。"""

    def __init__(self, measured_bytes: int, limit_bytes: int, paths: list[str]):
        self.measured_bytes = measured_bytes
        self.limit_bytes = limit_bytes
        self.paths = paths
        super().__init__(
            f"package is {measured_bytes} bytes, limit is {limit_bytes} bytes"
        )


class InvalidPackageError(TransferError):
    """包格式/内容校验失败。"""


class AmbiguousCompanyError(TransferError):
    """目标机存在多个同名公司，需调用方指定 target_company_id。"""

    def __init__(self, candidates: list[dict]):
        self.candidates = candidates
        super().__init__(f"multiple companies share this name: {candidates}")
