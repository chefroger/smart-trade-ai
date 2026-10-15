#!/bin/bash
# ==============================================================================
# Foreign Trade Assistant — 一键安装脚本 (macOS / Linux / WSL2)
# ==============================================================================
# 使用方式:
#   curl -fsSL https://raw.githubusercontent.com/chefroger/smart-trade-ai/main/scripts/install.sh | bash
#
# 全程使用 venv，不碰系统 Python site-packages，兼容 Homebrew PEP 668。
# ==============================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log_info()  { echo -e "${CYAN}→${NC} $*"; }
log_ok()    { echo -e "${GREEN}✓${NC} $*"; }
log_warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
log_err()   { echo -e "${RED}✗${NC} $*"; }
log_step()  { echo -e "\n${BOLD}════════════════════════════════════════${NC}"; echo -e "${BOLD}$*${NC}"; }

# 克隆或更新一个 git 仓库（失败返回 1，由调用方决定是否中止）。
#
# 为什么要这些判断（都是实测踩出来的）：
#   1. 只有目录**是有效的 git 仓库**（.git 且 HEAD 可解析）才算「已安装」。
#      克隆被网络中断时 git 会留下空目录，旧逻辑 `[ -d ... ]` 会把它当成已装，
#      随后 `git pull` 静默失败、`pip install -e .` 在残缺树里报出误导性错误，
#      而且**重试永远无法恢复**，用户只能手动删目录。
#   2. 用浅克隆 `--depth 1`：全历史克隆在弱网下最慢、最易失败（README 本身就提醒
#      用户要有稳定网络）。跟 main 时本地没有 tag，Hermes 版本推导会退化为「未知」，
#      Trade 会打印警告并继续启动，不影响使用；固定版本模式（`--branch <tag>`）
#      会把该 tag 一并带上，版本可正常解出。
#   3. 不吞 git 的 stderr：README 让用户按网络问题排查，看不到真实报错就没法排查。
_clone_or_update() {
    local name="$1" repo="$2" dest="$3" ref="${4:-main}"
    # 目录存在且是有效仓库 → 拉取更新
    if [ -d "$dest/.git" ] && git -C "$dest" rev-parse --verify HEAD >/dev/null 2>&1; then
        # 固定版本模式（ref != main，Hermes 用）：不 pull —— 在 tag 检出上 pull main
        # 会把它拖到 main 尖端，固定就失去意义。已有检出保持原样。
        if [ "$ref" != "main" ]; then
            log_info "已有 $name 检出，保持现状（固定版本 $ref，不跟随 main）"
            return 0
        fi
        log_info "更新已有仓库..."
        git -C "$dest" pull --ff-only origin main || log_warn "git pull 失败，继续使用现有代码"
        return 0
    fi
    # 目录存在但不是有效仓库 → 多为上次克隆的残留，重克隆（否则重试永远失败）
    if [ -e "$dest" ]; then
        log_warn "已存在的目录不是有效的代码仓库（上次克隆中断的残留），重新克隆：$dest"
        rm -rf "$dest"
    fi
    mkdir -p "$(dirname "$dest")"
    git clone --depth 1 --branch "$ref" "$repo" "$dest" || {
        log_err "无法克隆 $name（git 的报错见上）。请确认网络/VPN 后重新运行本脚本。"
        return 1
    }
    return 0
}

echo ""
echo -e "${BOLD}${CYAN}  Foreign Trade Assistant — 安装向导${NC}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: 检查 Python
# ─────────────────────────────────────────────────────────────────────────────
log_step "Step 1/5: 检查 Python 环境"

# Trade 必须跑在 **Python 3.14** 上：Hermes 从 v0.21.6 起只提供 3.14 的依赖集
# （requires-python 里那个 `>=3.11` 只是留给旧安装「跑完自己的升级步骤」的过渡桥），
# 而 Trade 是**进程内**嵌 Hermes 的，解释器必须与 Hermes 的托管环境同 ABI。
# 在 3.11~3.13 上会变成「装得上、起不来」，所以这里不再接受 3.11~3.13。
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

_find_python314() {
    local cmd cand
    # 1) PATH 上的解释器（版本号必须正好是 3.14）
    for cmd in python3.14 python3; do
        if command -v "$cmd" &>/dev/null \
           && "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)' 2>/dev/null; then
            command -v "$cmd"
            return 0
        fi
    done
    # 2) Hermes 自带的托管 Python（上游安装器放在数据目录的 tools/ 下）——
    #    优先用它：与 Hermes 的托管环境 ABI 完全一致，省掉一类难查的崩
    for cand in "$HERMES_HOME"/tools/*/bin/python3.14 \
                "$HERMES_HOME"/tools/*/*/bin/python3.14; do
        if [ -x "$cand" ] \
           && "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)' 2>/dev/null; then
            echo "$cand"
            return 0
        fi
    done
    # 3) Homebrew 常见位置（Intel / Apple Silicon）
    for cand in /opt/homebrew/bin/python3.14 /usr/local/bin/python3.14; do
        if [ -x "$cand" ]; then
            echo "$cand"
            return 0
        fi
    done
    return 1
}

PYTHON="$(_find_python314 || true)"

if [ -z "$PYTHON" ]; then
    log_err "需要 Python 3.14，但未找到。"
    echo ""
    echo "  Trade 必须与 Hermes 用同一个 Python 大版本（3.14）。任选一种方式："
    echo ""
    echo "  1) 让 Hermes 自带（推荐）—— 先安装 Hermes，它会自带 3.14，本脚本能自动找到："
    echo "       curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
    echo ""
    echo "  2) 自己装 3.14："
    echo "       macOS:  brew install python@3.14"
    echo "       Ubuntu: sudo apt install python3.14 python3.14-venv"
    exit 1
fi
log_ok "Python $("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')（$PYTHON）"

# ── 架构检测 + 自动修正（Apple Silicon 兼容性）────────────────────────────
ARCH=$(uname -m)
PY_ARCH=$("$PYTHON" -c "import platform; print(platform.machine())")
if [ "$ARCH" = "arm64" ] && [ "$PY_ARCH" = "x86_64" ]; then
    log_warn "检测到 CPU 是 arm64 (Apple Silicon)，但 Python 是 x86_64 (Rosetta)。"
    log_info "正在搜索原生 arm64 Python ..."

    # 主动搜索原生 arm64 Homebrew Python
    NATIVE_PYTHON=""
    for candidate in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11; do
        if [ -x "$candidate" ]; then
            _arch=$("$candidate" -c "import platform; print(platform.machine())" 2>/dev/null)
            if [ "$_arch" = "arm64" ]; then
                NATIVE_PYTHON="$candidate"
                break
            fi
        fi
    done

    if [ -n "$NATIVE_PYTHON" ]; then
        log_ok "找到原生 arm64 Python: $NATIVE_PYTHON ($("$NATIVE_PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"))"
        PYTHON="$NATIVE_PYTHON"
    else
        log_err "未找到原生 arm64 Python。Rosetta Python 会导致 Hermes 不可用。"
        echo ""
        echo "  修复方法："
        echo "    1. 安装原生 Homebrew（如果当前是 Rosetta 版）："
        echo "       /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "    2. 安装原生 Python："
        echo "       brew install python@3.12"
        echo "    3. 重新运行此安装脚本："
        echo "       curl -fsSL https://raw.githubusercontent.com/chefroger/smart-trade-ai/main/scripts/install.sh | bash"
        exit 1
    fi
fi

# 反向检查：Intel CPU + arm64 Python（极罕见）
if [ "$ARCH" = "x86_64" ] && [ "$PY_ARCH" = "arm64" ]; then
    log_err "架构不匹配：CPU 是 x86_64 (Intel)，但 Python 是 arm64。"
    echo "  请安装与 CPU 匹配的 Python 版本。"
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# 创建 venv（所有后续安装都在 venv 内，不碰系统 Python）
# ─────────────────────────────────────────────────────────────────────────────
VENV_DIR="$HOME/.trade/venv"
if [ ! -f "$VENV_DIR/bin/python" ]; then
    log_info "创建虚拟环境..."
    "$PYTHON" -m venv "$VENV_DIR"
fi
PIP="$VENV_DIR/bin/pip"
PY="$VENV_DIR/bin/python"
log_ok "虚拟环境就绪 ($VENV_DIR)"

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: 检查 Hermes Agent
# ─────────────────────────────────────────────────────────────────────────────
log_step "Step 2/5: 检查 Hermes Agent"

# **不再把 Hermes 克隆/安装进 Trade 的 venv**（旧的固定 tag 方案已废除）。
# 现在机器上只有**一份** Hermes：用户自己装的那份。Trade 通过 sys.path 指向它，
# 并让它的 pm 托管环境提供 Hermes 的依赖（见 trade/bootstrap.py 与 COMPATIBILITY.md）。
#
# 这样做的理由（两条都是实测出来的）：
#   1. 上游从 v0.21.6 起把核心依赖标成 `python_version >= '3.14'`，Hermes 与它的
#      依赖是一个 3.14 的整体；Trade 进程必须是 3.14 才能加载它（Step 1 已保证）。
#   2. 旧方案把 Hermes 装进 Trade 的 venv，会和用户自己那份抢同一个 checkout 目录，
#      导致「pin 失效 + 把用户的 Hermes 降级」—— 见 COMPATIBILITY.md 的跟进记录。
#
# 版本是否够新由 Trade 启动时判定；过旧会在界面里自动升级（trade/hermes_upgrade.py），
# 所以这里只确认它存在，不在这里改动用户的 Hermes。
if command -v hermes &>/dev/null; then
    log_ok "已找到 hermes 命令（$(command -v hermes)）"
elif [ -x "$HOME/.local/bin/hermes" ]; then
    log_ok "已找到 hermes 命令（$HOME/.local/bin/hermes）"
else
    log_err "未找到 hermes 命令 —— 请先安装 Hermes Agent。"
    echo ""
    echo "  复制下面这一行，粘贴到终端后回车："
    echo "    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
    echo ""
    echo "  装好后重新运行本安装脚本。"
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: 安装 foreign-trade-assistant + 全部依赖
# ─────────────────────────────────────────────────────────────────────────────
log_step "Step 3/5: 安装 Foreign Trade Assistant"

TRADE_REPO="https://github.com/chefroger/smart-trade-ai.git"
TRADE_DIR="$HOME/.trade/foreign-trade-assistant"

_clone_or_update "foreign-trade-assistant" "$TRADE_REPO" "$TRADE_DIR" || exit 1

cd "$TRADE_DIR"
# 装依赖（不含 hermes-agent，它在 Step 2 已装进 venv）+ trade 自身
"$PIP" install -r requirements.txt
"$PIP" install -e "." --no-deps

# 可选依赖：客户语义检索用的向量扩展（sqlite-vec）。
# **单独装、失败只警告** —— 它不是主链依赖：不装则语义检索自动降级关键词，
# 其余功能零影响；而个别平台（如 Windows ARM）没有对应 wheel，
# 不能因为一个可选能力让整台机器的安装失败。
if "$PY" -c "import sqlite_vec" 2>/dev/null; then
    log_ok "sqlite-vec 已安装（客户语义检索可用）"
elif "$PIP" install "sqlite-vec>=0.1.6" >/dev/null 2>&1; then
    log_ok "sqlite-vec 安装完成（客户语义检索可用）"
else
    log_warn "sqlite-vec 未安装：客户语义检索将降级为关键词检索（其余功能不受影响）"
fi
cd - >/dev/null

log_ok "Foreign Trade Assistant 安装完成"

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: 安装 B2B skills
# ─────────────────────────────────────────────────────────────────────────────
log_step "Step 4/5: 安装 B2B skills"

# 必须用真实存在的入口：此前写的是 `python -m trade.post_install install`，
# 但该包**没有 __main__.py** → 这一步从未生效过（报错被 2>/dev/null 吞掉，
# 只打印下面那句警告）。实测新装后 ~/.hermes/skills 里 0 个 skill。
if "$PY" -c "from trade.post_install import install_skills; install_skills()"; then
    log_ok "B2B skills 安装完成"
else
    log_warn "B2B skills 安装可能不完整（首次启动时会自动同步）"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 5: 初始化数据目录
# ─────────────────────────────────────────────────────────────────────────────
log_step "Step 5/5: 初始化数据目录"

TRADE_HOME="${TRADE_HOME:-$HOME/.trade}"
mkdir -p "$TRADE_HOME/data"
mkdir -p "$TRADE_HOME/companies"

"$PY" -c "from trade.database import init_db; init_db()" 2>/dev/null && \
    log_ok "数据库初始化完成 ($TRADE_HOME/data/trade.db)" || \
    log_info "数据库将在首次启动时自动初始化"

# ─────────────────────────────────────────────────────────────────────────────
# 导出 trade 命令到 ~/.local/bin（放 PATH 里）
# ─────────────────────────────────────────────────────────────────────────────
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/trade" << LAUNCHER
#!/bin/bash
export HERMES_HOME="\${HERMES_HOME:-$HOME/.hermes}"
# 禁用 Hermes 懒加载重启：否则 agent 创建时会被 exec 到 Hermes 自带的 store python
# （那里没有 trade 包），agent 线程以 RelaunchExit(SystemExit) 静默死亡，
# 前端只会看到「Agent 未返回有效回复」。bootstrap.py 里也设了一处，这里是双保险。
export HERMES_DISABLE_LAZY_INSTALLS="1"
exec "$VENV_DIR/bin/python" "$TRADE_DIR/server.py" "\$@"
LAUNCHER
chmod +x "$HOME/.local/bin/trade"

# ─────────────────────────────────────────────────────────────────────────────
# 检查 PATH 中是否有 ~/.local/bin
# ─────────────────────────────────────────────────────────────────────────────
if ! echo "$PATH" | tr ':' '\n' | grep -qxF "$HOME/.local/bin"; then
    SHELL_NAME=$(basename "${SHELL:-$SHELL}")
    case "$SHELL_NAME" in
        zsh)  RC_FILE="$HOME/.zshrc" ;;
        bash) RC_FILE="$HOME/.bashrc" ;;
        *)    RC_FILE="$HOME/.profile" ;;
    esac

    if ! grep -qF 'export PATH="$HOME/.local/bin:$PATH"' "$RC_FILE" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$RC_FILE"
    fi
    export PATH="$HOME/.local/bin:$PATH"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 安装后自检（快检：零 token，不发真实请求）
#
# 端到端验活（真发一次对话 / 一张图 / 一次搜索）在**首次启动时**跑 —— 那时服务与
# 配置都已就位，结果会落盘并在界面提示。这里只做能立刻发现「装坏了」的快检，
# 避免安装因为网络波动误报失败而挡住用户。
# ─────────────────────────────────────────────────────────────────────────────
# 两处都必须在调 doctor 之前处理：
#   1. `prepare_hermes_import_paths()` —— Hermes 不再装进 Trade 的 venv，不先准备
#      sys.path 就直接 import doctor 会报 `No module named 'run_agent'`（干净机器实测）。
#   2. doctor 自己会 import Hermes，会触发 pm 激活剥离 venv 的 site-packages；
#      那一步的恢复也在这个函数里，漏了会让后面 holehe/sqlite-vec 误报「未安装」。
# 「Hermes 版本」这一项刻意不计入致命项：版本过旧不需要在这里解决 —— Trade 启动后
# 会在界面里自动升级 Hermes（见 trade/hermes_upgrade.py）。若这里判失败并 exit 1，
# 用户就永远看不到那个升级界面了。
if ! "$PY" -c "import sys; from trade.bootstrap import prepare_hermes_import_paths; prepare_hermes_import_paths(); from trade.doctor import run_doctor, format_report, has_fatal_failure; r = run_doctor(deep=False); print(format_report(r)); sys.exit(1 if has_fatal_failure(r, ignore_names=('Hermes 版本',)) else 0)"; then
    log_err "自检发现致命问题，安装不完整。请把上面的输出发给技术支持。"
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# 完成
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══ 安装完成 ══${NC}"
echo ""
echo -e "  启动方式:"
echo -e "    新终端: ${BOLD}trade${NC}"
echo -e "    当前终端: ${BOLD}$HOME/.local/bin/trade${NC}"
echo ""
echo -e "  启动后打开: ${CYAN}http://127.0.0.1:9119/trade${NC}"
echo ""
echo -e "  数据位置:"
echo -e "    用户数据: ${CYAN}$TRADE_HOME/${NC}"
echo -e "    Hermes 配置: ${CYAN}$HERMES_HOME/${NC}"
echo ""
echo -e "  帮助: ${CYAN}trade --help${NC}"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 配置 macOS 开机自启动（launchd，后台静默运行，无终端窗口）
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$(uname -s)" == "Darwin" ]]; then
    PLIST_DIR="$HOME/Library/LaunchAgents"
    PLIST_FILE="$PLIST_DIR/com.trade.assistant.plist"
    mkdir -p "$PLIST_DIR"

    if [ ! -f "$PLIST_FILE" ]; then
        cat > "$PLIST_FILE" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trade.assistant</string>
    <key>ProgramArguments</key>
    <array>
        <string>$HOME/.local/bin/trade</string>
        <string>--no-browser</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$TRADE_HOME/logs/launchd-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$TRADE_HOME/logs/launchd-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HERMES_HOME</key>
        <string>$HERMES_HOME</string>
        <key>TRADE_HOME</key>
        <string>$TRADE_HOME</string>
        <key>PATH</key>
        <string>$VENV_DIR/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST
        # 确保日志目录存在
        mkdir -p "$TRADE_HOME/logs"
        # 加载到当前会话（用户级，无需 sudo）
        launchctl bootstrap gui/$(id -u) "$PLIST_FILE" 2>/dev/null || \
        launchctl load "$PLIST_FILE" 2>/dev/null || true
        echo -e "  ${GREEN}✓${NC} macOS 开机自启动已配置（后台运行，无终端窗口）"
        echo -e "    管理命令:"
        echo -e "      停止:  ${CYAN}launchctl unload $PLIST_FILE${NC}"
        echo -e "      重启:  ${CYAN}launchctl unload $PLIST_FILE && launchctl load $PLIST_FILE${NC}"
        echo -e "      查看日志: ${CYAN}tail -f $TRADE_HOME/logs/launchd-stdout.log${NC}"
    else
        echo -e "  ${GREEN}✓${NC} macOS 开机自启动已配置"
    fi

# ─────────────────────────────────────────────────────────────────────────────
# 配置 Linux 开机自启动（systemd user unit）
# ─────────────────────────────────────────────────────────────────────────────
elif [[ "$(uname -s)" == "Linux" ]]; then
    UNIT_DIR="$HOME/.config/systemd/user"
    UNIT_FILE="$UNIT_DIR/trade.service"
    mkdir -p "$UNIT_DIR"

    if [ ! -f "$UNIT_FILE" ]; then
        cat > "$UNIT_FILE" << UNIT
[Unit]
Description=Smart Trade AI
After=network.target

[Service]
Type=simple
ExecStart=$HOME/.local/bin/trade --no-browser
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
UNIT
        systemctl --user daemon-reload
        systemctl --user enable trade.service
        systemctl --user start trade.service
        echo -e "  ${GREEN}✓${NC} Linux 开机自启动已配置（systemd user unit）"
    else
        echo -e "  ${GREEN}✓${NC} Linux 开机自启动已配置"
    fi
fi
echo ""
