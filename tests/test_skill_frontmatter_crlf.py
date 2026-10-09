"""SKILL.md 的 frontmatter 解析必须与换行符无关。

## 为什么（Windows 客户机上是致命的）

`_parse_frontmatter` 用 `content.startswith("---\\n")` 与 `content.find("\\n---\\n", 4)`
定位分隔线。CRLF 文件里首行是 `---\\r\\n`、结束标记是 `\\r\\n---\\r\\n` —— 两个判断
**全部失配**，函数直接返回 `({}, content)`：frontmatter 解析成空字典。

后果链：
  - `triggers` 读不到 → 该技能注册失效
  - `injection_prompt` 读不到 → 降级到 `skill_registry` 的 `augment_prompt`
  - 而 **19/38 个技能的 augment_prompt 是空串** → 匹配到了但**零指令注入**，
    AI 完全自由发挥

macOS 开发机看不出（仓库检出是 LF）；CI 的 windows-latest 只跑 pytest，
不校验 frontmatter 解析结果。而两条 Windows 产生 CRLF 的路径都不需要用户改配置：
  1. `.gitattributes` 没有 `*.md` 的 eol 规则，Git for Windows 默认 core.autocrlf=true
  2. `trade/post_install/skills.py` 用 `write_text(content)` 写入 —— Windows 上
     `newline=None` 会把 `\\n` 翻译成 `\\r\\n`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trade.skill_router import _parse_frontmatter

SKILL = Path(__file__).resolve().parent.parent / "skills" / "b2b-short-video" / "SKILL.md"


def _crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


class TestCrlfFrontmatter:
    """CRLF 与 LF 必须解析出相同结果（实测前：LF 8 个 key / CRLF 0 个）。"""

    def test_lf_baseline(self):
        """前置条件：LF 能正常解析（否则这个测试文件本身失效）。"""
        fm, _ = _parse_frontmatter(SKILL.read_text(encoding="utf-8"))

        assert fm.get("name") == "b2b-short-video"
        assert fm.get("injection_prompt"), "LF 下应当能拿到 injection_prompt"

    def test_crlf_parses_same_keys(self):
        lf = SKILL.read_text(encoding="utf-8")
        fm_lf, _ = _parse_frontmatter(lf)
        fm_crlf, _ = _parse_frontmatter(_crlf(lf))

        assert fm_crlf, (
            "CRLF 下 frontmatter 解析为空 —— Windows 客户机上技能会退化为零指令注入"
        )
        assert set(fm_crlf.keys()) == set(fm_lf.keys())

    def test_crlf_injection_prompt_matches(self):
        lf = SKILL.read_text(encoding="utf-8")
        _, body_lf = _parse_frontmatter(lf)
        fm_crlf, body_crlf = _parse_frontmatter(_crlf(lf))
        fm_lf, _ = _parse_frontmatter(lf)

        assert fm_crlf.get("injection_prompt") == fm_lf.get("injection_prompt")
        # body 也要一致（去掉换行差异后）
        assert body_crlf.replace("\r\n", "\n") == body_lf.replace("\r\n", "\n")

    def test_crlf_triggers_present(self):
        """triggers 是 Hermes 注册技能的依据，绝不能因换行符丢失。"""
        fm, _ = _parse_frontmatter(_crlf(SKILL.read_text(encoding="utf-8")))

        assert fm.get("triggers"), "CRLF 下 triggers 丢失 → 技能注册失败"

    def test_real_skill_files_have_parseable_frontmatter(self):
        """守卫：仓库里所有 SKILL.md 用 LF 与 CRLF 都应可解析。"""
        import glob

        broken = []
        for path in glob.glob(str(SKILL.parent.parent / "*" / "SKILL.md")):
            text = Path(path).read_text(encoding="utf-8")
            fm_lf, _ = _parse_frontmatter(text)
            fm_crlf, _ = _parse_frontmatter(_crlf(text))
            if not fm_lf.get("name") or not fm_crlf.get("name"):
                broken.append(Path(path).parent.name)

        assert not broken, f"以下技能的 frontmatter 在某种换行符下解析失败：{broken}"
