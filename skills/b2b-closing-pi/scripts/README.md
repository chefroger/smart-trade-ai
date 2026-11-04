# scripts/

本 skill 为纯提示词技能，不需要脚本。

若后续加入脚本，遵循：
- 每个脚本必须有 `if __name__ == "__main__":` 入口
- 参数通过 argparse / 环境变量传递
- 输出到 stdout（不写文件除非显式指定）
