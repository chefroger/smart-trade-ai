"""仓库级卫生检查 —— 钉住那些「本地全绿、CI 全红」的常见坑。

这些不是业务逻辑测试，而是**跨文件的静态不变量**：违反了不一定逻辑错，
但一定会在别人的机器/CI 上炸。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 扫描范围：仓库里我们自己的源码（跳过依赖、构建产物、缓存）
_SCAN_DIRS = ("trade", "tests", "scripts")
_SKIP_PARTS = {"__pycache__", "build", "dist", ".git", "node_modules"}
# 守卫文件自身必须跳过 —— 它为了说明"什么是坏的"而**故意**写着那个写法
# （docstring 里的反面例子 + test_guard_itself_catches_the_bug_shape 的样本字符串），
# 不跳过就会自己抓自己。这是这类静态守卫的常规做法。
_SKIP_FILES = {Path(__file__).name}


def _iter_source_files(suffix: str = ".py"):
    for d in _SCAN_DIRS:
        base = REPO_ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob(f"*{suffix}"):
            if any(part in _SKIP_PARTS for part in p.parts):
                continue
            if p.name in _SKIP_FILES:
                continue
            yield p


# 文件系统调用里出现「绝对的家目录路径」——这种值在本机是对的、在别人机器上必然找不到。
#
# 为什么只匹配 Path(...)/open(...) 这类**文件系统调用**而不是裸字符串：
# 测试数据里合法地会出现家目录路径（例如把 "识别图片 '/Users/x/截屏.png'" 当作
# **用户输入**喂给 prompt 构造，断言的是生成的提示词，不碰磁盘）。
# 那种写法在 CI 上照常通过，不是 bug；裸字符串扫描会把它误报成 bug。
_HARDCODED_FS_CALL = re.compile(
    r"""\b(?:Path|open|Path\.|os\.path\.\w+|shutil\.\w+)\s*\(\s*["']"""
    r"""(?:/Users/|/home/|/root/|[A-Za-z]:\\\\?Users\\\\?)""",
)


class TestNoHardcodedHomePaths:
    """文件系统调用里不得写死开发机的家目录路径。

    2026-10-16 实测教训：`tests/test_chat_memory_plugin.py` 第一版把插件目录写成了
    `Path("/Users/rogerlau/Desktop/Foreign Trade Assistant/trade/...")` ——
    本机 35 个用例全绿，**CI 上 6 个用例全挂在 FileNotFoundError**（仓库不在那个路径下）。
    这类 bug 本地永远发现不了，只能靠静态守卫。
    """

    def test_no_absolute_home_path_in_filesystem_calls(self):
        offenders: list[str] = []
        for path in _iter_source_files(".py"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _HARDCODED_FS_CALL.search(line):
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")

        assert not offenders, (
            "文件系统调用里写死了家目录路径（本机绿、CI 红）：\n  "
            + "\n  ".join(offenders)
            + "\n  改用 Path(__file__).resolve().parent... 从文件位置推导。"
        )

    def test_guard_itself_catches_the_bug_shape(self):
        """守卫自身的回归：确认它真的能匹配到当初那个 bug 写法。

        防止将来有人把正则改松（改到匹配不到任何东西）而守卫静默失效 ——
        一个永远通过的守卫比没有守卫更糟，因为它给人虚假的安全感。
        """
        bug = 'plugin_path = Path("/Users/rogerlau/Desktop/x/trade/hermes_chat_memory_plugin")'
        assert _HARDCODED_FS_CALL.search(bug), "守卫匹配不到当初的 bug 写法，已失效"

        # 反例：把家目录路径当**测试数据**（不碰磁盘）不该被误报
        data_only = 'prompt, _ = self._build(env, "识别图片 \'/Users/rogerlau/Desktop/a.png\'")'
        assert not _HARDCODED_FS_CALL.search(data_only), "把测试数据误报成 bug"


class TestRepoLayoutAssumptions:
    """测试必须能**从文件位置**找到仓库资源，而不是靠 CWD 或写死路径。

    CI 用 `python -m pytest tests/`（CWD 被加进 sys.path），本地可能用别的方式跑；
    依赖 CWD 的写法在两种环境下行为不同。
    """

    @pytest.mark.parametrize("rel", ["trade", "trade/hermes_chat_memory_plugin"])
    def test_repo_root_resolution_works(self, rel):
        assert (REPO_ROOT / rel).is_dir(), f"从 __file__ 推不出 {rel}，仓库布局假设失效"
