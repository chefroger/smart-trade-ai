# scripts/

可执行代码（Python / Shell）。

## 约定
- 每个脚本必须有 `if __name__ == "__main__":` 入口
- 参数通过 argparse / 环境变量传递
- 输出到 stdout（不写文件除非显式指定）
- 配套的 README 写在本目录（如 `scripts/README.md`）说明调用方式
