#!/bin/bash
# ==============================================================================
# Hermes Agent 前置软件安装脚本 — macOS / Linux / Termux
# ==============================================================================
# 安装 hermes-agent（NousResearch/hermes-agent）所需的全部前置软件。
# 仅安装必需的系统依赖，不包含 hermes-agent 自身（由 hermes install.sh 处理）。
#
# 使用方式：
#   chmod +x install_prereqs.sh
#   ./install_prereqs.sh          # 交互式（有终端）
#   curl -fsSL ... | bash         # 非交互式（curl | bash）
# ==============================================================================

set -e

# ─────────────────────────────────────────────────────────────────────────────
# 颜色输出
# ─────────────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

log_info()  { echo -e "${CYAN}→${NC} $*"; }
log_ok()    { echo -e "${GREEN}✓${NC} $*"; }
log_warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
log_err()   { echo -e "${RED}✗${NC} $*"; }
log_step()  { echo -e "\n${BOLD}[$1]${NC} $*"; }

# ─────────────────────────────────────────────────────────────────────────────
# 检测操作系统
# ─────────────────────────────────────────────────────────────────────────────
detect_os() {
    if [ "$(uname)" = "Darwin" ]; then
        OS="macos"
    elif [ -f /etc/os-release ]; then
        . /etc/os-release
        case "$ID" in
            ubuntu|debian)  OS="debian" ;;
            fedora|rhel|centos) OS="fedora" ;;
            arch|manjaro)   OS="arch" ;;
            termux)         OS="termux" ;;
            *)              OS="unknown" ;;
        esac
    elif [ -n "$ANDROID_ROOT" ]; then
        OS="termux"
    else
        OS="unknown"
    fi
    echo "Detected OS: $OS"
}

# ─────────────────────────────────────────────────────────────────────────────
# 检测是否为交互式终端
# ─────────────────────────────────────────────────────────────────────────────
is_interactive() {
    [ -t 0 ] || [ -n "$CI" ]
}

# ─────────────────────────────────────────────────────────────────────────────
# 前置软件包列表（按操作系统分组）
# ─────────────────────────────────────────────────────────────────────────────

# 必需（hermes-agent 无法运行的核心依赖）
REQUIRED_DEPS=()

# 可选（缺少时 Hermes 部分功能降级，但不阻塞运行）
OPTIONAL_DEPS=()

# macOS
install_macos() {
    log_step "1" "检查 macOS 核心依赖"

    # Xcode Command Line Tools（提供 git, make, clang）
    if ! command -v git &>/dev/null; then
        log_info "Git 未找到，正在安装 Xcode Command Line Tools..."
        if is_interactive; then
            xcode-select --install 2>/dev/null || true
        fi
        log_warn "请在弹出的对话框中点击「安装」"
        log_info "或者手动运行: xcode-select --install"
    else
        log_ok "Git 已安装: $(git --version)"
    fi

    # Homebrew（可选，但能简化后续安装）
    if ! command -v brew &>/dev/null; then
        log_warn "Homebrew 未安装（可选，不影响 Hermes 运行）"
        log_info "安装 Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/installHEAD/install.sh)\""
    else
        log_ok "Homebrew 已安装"
    fi

    # Python（由 hermes install.sh 通过 uv 自动处理，这里仅检查）
    log_step "2" "Python（由 Hermes 安装器通过 uv 管理，跳过手动安装）"

    # Node.js（可选，浏览器工具需要）
    log_step "3" "Node.js 22 LTS（可选，浏览器工具需要）"
    if ! command -v node &>/dev/null; then
        log_warn "Node.js 未安装（可选： Hermes 浏览器工具需要）"
        log_info "使用 Homebrew 安装: brew install node@22"
        log_info "或手动下载: https://nodejs.org/en/download/"
    else
        log_ok "Node.js 已安装: $(node --version)"
    fi

    # ripgrep（可选，加快文件搜索）
    log_step "4" "ripgrep（可选，加快 Hermse 文件搜索速度）"
    if ! command -v rg &>/dev/null; then
        log_warn "ripgrep 未安装（可选：文件搜索会使用 find 替代）"
        log_info "使用 Homebrew 安装: brew install ripgrep"
    else
        log_ok "ripgrep 已安装: $(rg --version | head -1)"
    fi

    # ffmpeg（可选，TTS 语音消息需要）
    log_step "5" "ffmpeg（可选，TTS 语音消息需要）"
    if ! command -v ffmpeg &>/dev/null; then
        log_warn "ffmpeg 未安装（可选：TTS 语音功能不可用）"
        log_info "使用 Homebrew 安装: brew install ffmpeg"
    else
        log_ok "ffmpeg 已安装: $(ffmpeg -version | head -1)"
    fi

    # 扫描件识别走 vision（由模型完成），无需安装 tesseract
    log_step "6" "扫描件识别：由 vision 处理（无需额外安装）"
    log_info "推荐模型 DeepSeek V4 Flash 自带看图能力；扫描件/图片直接走 vision"

    log_step "7" "Playwright Chromium（可选，浏览器自动化工具需要）"
    log_info "如有需要，运行: npx playwright install --with-deps chromium"
    log_info "（Playwright 和 Node.js 一起安装，单独运行此命令即可）"
}

# Debian/Ubuntu
install_debian() {
    log_step "1" "安装 Debian/Ubuntu 核心依赖"

    local pkgs=(curl git ca-certificates)
    log_info "检查基础工具: ${pkgs[*]}"
    for pkg in "${pkgs[@]}"; do
        if dpkg -s "$pkg" &>/dev/null 2>&1; then
            log_ok "$pkg 已安装"
        else
            log_info "安装 $pkg..."
            sudo apt-get update -qq && sudo apt-get install -y -qq "$pkg" || \
                log_warn "$pkg 安装失败，请手动安装"
        fi
    done

    log_step "2" "Python 3.11+（由 Hermes 安装器通过 uv 管理，跳过）"

    log_step "3" "Node.js 22 LTS（可选）"
    if ! command -v node &>/dev/null; then
        log_warn "Node.js 未安装"
        log_info "安装 Node.js: https://nodejs.org/en/download/"
    else
        log_ok "Node.js 已安装: $(node --version)"
    fi

    log_step "4" "build-essential（编译 Python C 扩展需要）"
    if dpkg -s build-essential &>/dev/null; then
        log_ok "build-essential 已安装"
    else
        log_info "安装 build-essential..."
        sudo apt-get update -qq && sudo apt-get install -y -qq build-essential || \
            log_warn "build-essential 安装失败"
    fi

    log_step "5" "ripgrep（可选）"
    if command -v rg &>/dev/null; then
        log_ok "ripgrep 已安装"
    else
        log_info "安装 ripgrep: sudo apt install ripgrep"
        sudo apt-get install -y -qq ripgrep || log_warn "ripgrep 安装失败"
    fi

    log_step "6" "ffmpeg（可选）"
    if command -v ffmpeg &>/dev/null; then
        log_ok "ffmpeg 已安装"
    else
        log_info "安装 ffmpeg: sudo apt install ffmpeg"
        sudo apt-get install -y -qq ffmpeg || log_warn "ffmpeg 安装失败"
    fi

    # 扫描件识别走 vision（由模型完成），无需安装 tesseract
    log_step "7" "扫描件识别：由 vision 处理（无需额外安装）"
    log_info "推荐模型 DeepSeek V4 Flash 自带看图能力；扫描件/图片直接走 vision"
}

# Fedora/RHEL/CentOS
install_fedora() {
    log_step "1" "安装 Fedora/RHEL 核心依赖"
    local pkgs=(curl git ca-certificates)
    for pkg in "${pkgs[@]}"; do
        if rpm -q "$pkg" &>/dev/null; then
            log_ok "$pkg 已安装"
        else
            sudo dnf install -y "$pkg" || log_warn "$pkg 安装失败"
        fi
    done

    log_step "2" "build-essential（C 编译工具）"
    sudo dnf install -y gcc gcc-c++ make python3-devel libffi-devel || \
        log_warn "build tools 安装失败"

    log_step "3" "ripgrep"
    if command -v rg &>/dev/null; then
        log_ok "ripgrep 已安装"
    else
        sudo dnf install -y ripgrep || log_warn "ripgrep 安装失败"
    fi

    log_step "4" "ffmpeg"
    if command -v ffmpeg &>/dev/null; then
        log_ok "ffmpeg 已安装"
    else
        sudo dnf install -y ffmpeg || log_warn "ffmpeg 安装失败"
    fi
}

# Termux
install_termux() {
    log_step "1" "安装 Termux 基础依赖"
    local pkgs=(clang rust make pkg-config libffi openssl ca-certificates curl git)
    log_info "安装 Termux 包: ${pkgs[*]}"
    pkg update -y 2>/dev/null || true
    pkg install -y "${pkgs[@]}" || log_warn "部分包安装失败"
}

# 通用说明
show_summary() {
    echo ""
    echo "============================================================"
    echo "  前置软件检查完成"
    echo "============================================================"
    echo ""
    echo "  接下来安装 Hermes Agent："
    echo ""
    echo "  curl -fsSL \\"
    echo "    https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh \\"
    echo "    | bash"
    echo ""
    echo "  或者手动克隆:"
    echo "    git clone --branch main \\"
    echo "      https://github.com/NousResearch/hermes-agent.git \\"
    echo "      ~/.hermes/hermes-agent"
    echo "    cd ~/.hermes/hermes-agent"
    echo "    uv pip install -e ."
    echo ""
    echo "  安装完成后验证:"
    echo "    python pre_install_check.py"
    echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "============================================================"
    echo "  Hermes Agent 前置软件安装脚本"
    echo "  (仅安装系统依赖，不包含 Hermes Agent 本身)"
    echo "============================================================"
    echo ""

    detect_os

    case "$OS" in
        macos)   install_macos ;;
        debian)  install_debian ;;
        fedora)  install_fedora ;;
        termux)  install_termux ;;
        *)       log_err "不支持的操作系统: $OS"; exit 1 ;;
    esac

    show_summary
}

main "$@"
