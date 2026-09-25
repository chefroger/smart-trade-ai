# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Foreign Trade Assistant standalone app
#
# Build:
#   pip install pyinstaller
#   pyinstaller pyinstaller.spec
#
# Output: dist/Foreign Trade Assistant.app (macOS) / dist/ (Windows)

import sys
from pathlib import Path

_block_cipher = None

# project root
ROOT = Path(SPECPATH)  # SPECPATH = directory where this .spec file lives

# files to bundle with the app
_static_files = [
    (str(ROOT / "static" / "trade_chat.html"), "static"),
]
_skill_files = []
_skills_dir = ROOT / "skills"
if _skills_dir.is_dir():
    for _skill_d in _skills_dir.iterdir():
        if _skill_d.is_dir() and _skill_d.name.startswith("b2b-"):
            _skill_md = _skill_d / "SKILL.md"
            if _skill_md.is_file():
                _skill_files.append((str(_skill_md), f"skills/{_skill_d.name}"))
# also add chat-memory skill
_chat_skill = _skills_dir / "chat-memory" / "SKILL.md"
if _chat_skill.is_file():
    _skill_files.append((str(_chat_skill), "skills/chat-memory"))

_template_files = []
_template_dir = ROOT / ".trade-template"
if _template_dir.is_dir():
    for _f in _template_dir.rglob("*"):
        if _f.is_file():
            _dest = str(_f.relative_to(ROOT))
            _template_files.append((str(_f), str(_f.parent.relative_to(ROOT))))

# hidden imports that PyInstaller may miss
_hidden_imports = [
    "trade", "trade.api", "trade.api.companies", "trade.api.onboarding",
    "trade.api.libraries", "trade.api.customers", "trade.api.conversations",
    "trade.api.chat", "trade.api.memory", "trade.api.deps",
    "trade.osint", "trade.osint.constants", "trade.osint.whois",
    "trade.osint.email_verify", "trade.osint.sanctions",
    "trade.osint.tech_stack", "trade.osint.linkedin_verify",
    "trade.osint.scoring", "trade.osint.orchestrator",
    "trade.database", "trade.company", "trade.library",
    "trade.customer", "trade.chat_memory", "trade.memory",
    "trade.helpers", "trade.prompt", "trade.prompts",
    "trade.skill_router", "trade.skill_registry",
    "trade.onboarding", "trade.email_intel", "trade.post_install",
    "hermes_cli", "hermes_cli.config", "hermes_cli.auth",
    "hermes_cli.env_loader", "hermes_cli.models",
    "hermes_constants", "run_agent",
    "openai", "anthropic",  # LLM Provider SDKs — required, not optional
    "pymupdf", "anydoc", "pypdfium2",  # 文档解析 / 图纸渲染（扫描件走 vision）
    "psutil", "dnspython",  # Process management / DNS lookups
    "fastapi", "uvicorn", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "starlette", "pydantic", "anyio", "yaml",
]

a = Analysis(
    [str(ROOT / "server.py")],
    pathex=[str(ROOT), str(ROOT / "trade")],
    binaries=[],
    datas=_static_files + _skill_files + _template_files,
    hiddenimports=_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "pandas", "numpy", "scipy",
        "PIL", "cv2", "tensorflow", "torch", "sklearn",
        "jedi", "ipython", "jupyter", "notebook",
        "pytest", "coverage", "flake8",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=_block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=_block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Foreign Trade Assistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "static" / "icon.icns") if (ROOT / "static" / "icon.icns").is_file() else None,
)

app = BUNDLE(
    exe,
    name="Foreign Trade Assistant.app",
    icon=str(ROOT / "static" / "icon.icns") if (ROOT / "static" / "icon.icns").is_file() else None,
    bundle_identifier="com.foreign-trade.assistant",
    info_plist={
        "NSHighResolutionCapable": True,
        "CFBundleShortVersionString": "0.3.0",
        "CFBundleName": "Foreign Trade Assistant",
        "LSBackgroundOnly": False,
        "NSSupportsAutomaticGraphicsSwitching": True,
    },
)
