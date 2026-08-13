#!/usr/bin/env python3
"""给所有 37 个 skill 加 scripts/ references/ assets/ examples/ 骨架目录。
每个骨架含 README.md（约定说明）+ .gitkeep（保留空目录）。
"""
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

SKELETON_DIRS = ["scripts", "references", "assets", "examples"]

DIR_READMES = {
    "scripts": """# scripts/

可执行代码（Python / Shell）。

## 约定
- 每个脚本必须有 `if __name__ == "__main__":` 入口
- 参数通过 argparse / 环境变量传递
- 输出到 stdout（不写文件除非显式指定）
- 配套的 README 写在本目录（如 `scripts/README.md`）说明调用方式
""",
    "references": """# references/

长文档 / 模板 / Schema / 配置样例。

## 约定
- Markdown / JSON / YAML 格式
- 单一职责：每个文件聚焦一个主题（如 `checklist.md`、`email-template.md`）
- SKILL.md 通过相对路径引用：`references/checklist.md`
""",
    "assets": """# assets/

静态资源：图片、HTML/Excel 模板、CSV 样例、Logo。

## 约定
- 命名规范：`<purpose>.<ext>`
  - 例：`cold-email-template.eml`、`vat-form.docx`
- 大文件（>1MB）走 Git LFS 或外部 URL
""",
    "examples": """# examples/

调用样例（input → output 对照）。

## 约定
- 文件名：`<NN>-<scenario>.<ext>`（如 `01-simple-osquery.md`）
- 每个样例独立可运行（包含完整输入与预期输出）
- 用于回归测试或 Agent 自学
""",
}


def main():
    created = 0
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name in {"STANDARDS.md",} or skill_dir.name.startswith("."):
            continue
        # 跳过文件（如 STANDARDS.md 不在 skills/<skill>/ 下就不处理）
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue

        for sub in SKELETON_DIRS:
            sub_path = skill_dir / sub
            if sub_path.exists():
                continue
            sub_path.mkdir(parents=True)
            (sub_path / "README.md").write_text(DIR_READMES[sub], encoding="utf-8")
            (sub_path / ".gitkeep").touch()
            created += 1

    print(f"✅ 创建了 {created} 个骨架项（{len(SKELETON_DIRS)} 目录 × 37 skills = {37 * len(SKELETON_DIRS)}，部分已存在会跳过）")


if __name__ == "__main__":
    main()
