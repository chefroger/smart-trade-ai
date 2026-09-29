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
#      用户要有稳定网络）。代价是本地没有 tag，Hermes 版本推导会退化为「未知」，
#      Trade 会打印警告并继续启动，不影响使用。
#   3. 不吞 git 的 stderr：README 让用户按网络问题排查，看不到真实报错就没法排查。
_clone_or_update() {
    local name="$1" repo="$2" dest="$3"
    # 目录存在且是有效仓库 → 拉取更新
    if [ -d "$dest/.git" ] && git -C "$dest" rev-parse --verify HEAD >/dev/null 2>&1; then
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
    git clone --depth 1 --branch main "$repo" "$dest" || {
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

PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$("$cmd" -c "import sys; print(sys.version_info.major)")
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)")
        if [ "$major" -gt 3 ] || ([ "$major" -eq 3 ] && [ "$minor" -ge 11 ]); then
            PYTHON="$cmd"
            log_ok "Python $ver ($(which "$PYTHON"))"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    log_err "需要 Python >= 3.11，但未找到。"
    echo ""
    echo "  请先安装 Python："
    echo "    macOS:  brew install python@3.12"
    echo "    Ubuntu: sudo apt install python3.12 python3.12-venv"
    exit 1
fi

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
# Step 2: 安装 hermes-agent 
# ─────────────────────────────────────────────────────────────────────────────
log_step "Step 2/5: 安装 hermes-agent"

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

if "$PY" -c "import hermes_cli" 2>/dev/null; then
    hermes_ver=$("$PY" -c "import hermes_cli; print(hermes_cli.__version__)" 2>/dev/null || echo "unknown")
    log_ok "hermes-agent 已安装 (v$hermes_ver)"
else
    log_info "正在安装 hermes-agent..."
    HERMES_REPO="https://github.com/NousResearch/hermes-agent.git"
    HERMES_DIR="$HERMES_HOME/hermes-agent"

    _clone_or_update "hermes-agent" "$HERMES_REPO" "$HERMES_DIR" || exit 1

    cd "$HERMES_DIR"
    "$PIP" install -e "."
    cd - >/dev/null

    if "$PY" -c "import hermes_cli" 2>/dev/null; then
        log_ok "hermes-agent 安装完成"
    else
        log_err "hermes-agent 安装失败"
        exit 1
    fi
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
