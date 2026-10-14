"""`python -m trade.osint <目标>` 的入口（见 cli.py 的模块说明）。

存在的意义：skill 提示词需要一个**确定的、跨平台可执行的命令**来跑 6 层背调
（而不是"调用 domain_whois(域名)"这种没有对应工具的函数名）。
"""

import sys

from trade.osint.cli import main

if __name__ == "__main__":
    sys.exit(main())
