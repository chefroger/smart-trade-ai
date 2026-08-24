# Smart Trade AI

[![Test](https://github.com/chefroger/smart-trade-ai/actions/workflows/test.yml/badge.svg)](https://github.com/chefroger/smart-trade-ai/actions/workflows/test.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

[中文](README.md) | [English](README.en.md)

> **Important Notice**  
> This tool requires access to GitHub and PyPI for installation and updates — **a stable VPN connection is essential**.  
> Smart Trade AI generates responses using large language models (LLMs). Due to current technological limitations, LLMs may produce hallucinations. **All output is for reference only and does not constitute professional advice of any kind.** The user is solely responsible for independently verifying accuracy before relying on any information. For critical business decisions involving contracts, pricing, compliance, or due diligence, always consult qualified professionals. Use of this tool is at your own risk.

<div align="center">
  <h3>AI Assistant for International Trade Professionals</h3>
  <p>Runs on your machine. Your data stays with you.</p>
</div>

**Cold emails, client research, B2B platform management — this tool handles the repetitive stuff so you don't have to. Bilingual interface (Chinese/English) included — switch anytime.**

---

<p align="center">
  <img src="docs/screenshot-2.png" alt="Customer & Cron Panel" width="75%">
  <br>
  <em>Customer management + Cron task panel</em>
</p>

---

## Why do traders need this?

| Pain Point | Without This Tool | With Smart Trade AI |
|------|-------------|---------|
| Morning Brief | Open 5 websites every morning for FX rates / commodity prices / market news | Auto-generated — live rates, commodity prices, market news + client follow-up reminders |
| Due Diligence | Manual Google → LinkedIn → WHOIS | One-click 6-layer verification: email registration check → WHOIS → sanctions screening → MX verification → tech stack → LinkedIn |
| Cold Emails | Write each one from scratch, forget details when clients pile up | Auto-generated from client profiles, with specific pain-point references |
| B2B Platforms | Manually log in to check Alibaba / Made-in-China every day | Scheduled auto-checks — new inquiries and pending quotes at a glance |
| LinkedIn | Don't know what to post | AI generates weekly content calendar, rotating between industry insights / product cases / engagement polls |
| Client Data | Scattered across Excel / WhatsApp / email | Centralized management, A/B/C grading, linked to document libraries |

---

<p align="center">
  <img src="docs/screenshot-1.png" alt="AI Chat Interface" width="75%">
  <br>
  <em>AI Chat — auto-invokes web_search / read_file / database tools</em>
</p>

---

## Prerequisite: LLM API Key

> Smart Trade AI uses Hermes Agent as its AI engine. You need to register with a model provider and get an API Key.

Recommended plan:

| Plan | Model | Best For | Sign Up |
|------|-------|----------|---------|
| **Recommended** | DeepSeek V4 Flash | Daily chat, doc analysis, cold emails | [platform.deepseek.com](https://platform.deepseek.com) → Top-up → API Keys |

> MiniMax is no longer recommended — the M3 launch brought significant price hikes with no remaining cost advantage.

After getting your API Key, run `hermes setup` in terminal, choose your provider, and paste the key.

---

## Important Notes

### Network Requirements

The installation process clones repositories from GitHub and downloads Python dependencies. **You need a stable connection to GitHub.** If Hermes installation fails repeatedly, it's almost certainly a network issue:

- **Users in mainland China should use a VPN throughout installation**, otherwise `git clone` and `pip install` will likely time out
- If your VPN is unstable, retry the install command — the script supports resuming from where it left off
- Windows users: if the VPN proxy isn't taking effect, set it explicitly in PowerShell first:
  ```powershell
  $env:HTTPS_PROXY = "http://127.0.0.1:your-proxy-port"
  ```

### Tavily Search API (Strongly Recommended)

Trade's search and due diligence features rely on Tavily's AI search engine. Sign up for a free account to get 1,000 free searches per month — more than enough for personal use:

1. Go to [tavily.com](https://tavily.com) and sign up
2. Go to Dashboard → API Keys and copy your key
3. Run `hermes setup`, find the Tavily option, and paste the key

> Skipping this won't break chat, but search and due diligence quality will be noticeably degraded.

### If Trade Installation Fails

Manual Trade installation involves three steps (`git clone` + `pip install` + `install-trade-skills`), and network fluctuations can cause any one of them to fail. If you've already successfully installed **Hermes Agent and configured an LLM** but are struggling with the Trade install, simply give the Trade repo URL to Hermes and let it handle the rest:

> Tell Hermes directly in chat:
> "Help me install Trade from https://github.com/chefroger/smart-trade-ai.git"

Hermes will handle cloning, installing dependencies, and registering skills automatically. This approach has a much higher success rate than manual commands.

---

## Get started

### Quickest: one command

```bash
curl -fsSL https://raw.githubusercontent.com/chefroger/smart-trade-ai/main/scripts/install.sh | bash
```

The script handles: Python check → Hermes Agent → Smart Trade AI → 38 skills → database init.

> **Prefer to review before running?**
> ```bash
> curl -fsSLO https://raw.githubusercontent.com/chefroger/smart-trade-ai/main/scripts/install.sh
> less install.sh       # review, then
> bash install.sh
> ```

### Want a specific version? Use a release

Visit [Releases](https://github.com/chefroger/smart-trade-ai/releases) or specify a version:

```bash
git clone --branch v0.6.7 https://github.com/chefroger/smart-trade-ai.git ~/.trade/smart-trade-ai
cd ~/.trade/smart-trade-ai && pip install -e ".[docs]"
install-trade-skills
python server.py
```

### Or do it step by step

**Prerequisites**: Python >= 3.11 · Git · LLM API Key (OpenAI / Anthropic / DeepSeek / MiniMax etc.)

```bash
# 1. Install Hermes Agent (AI engine)
git clone --branch main https://github.com/NousResearch/hermes-agent.git ~/.hermes/hermes-agent
cd ~/.hermes/hermes-agent && pip install -e "."

# 2. Configure LLM
hermes setup      # Choose provider, paste API key

# 3. Install Smart Trade AI
git clone --branch main https://github.com/chefroger/smart-trade-ai.git ~/.trade/smart-trade-ai
cd ~/.trade/smart-trade-ai && pip install -e ".[docs]"

# 4. Install skills and launch
install-trade-skills
python server.py
# → Open http://127.0.0.1:9119/trade
```

### Windows

**Both Python and Git need manual install:**

1. **Python** — Download **Python 3.11 ~ 3.13 Windows installer (64-bit)** from [python.org](https://www.python.org/downloads/). Check "Add Python to PATH" during install.
2. **Git** — Download from [git-scm.com](https://git-scm.com/download/win) and install with default options. Or run `winget install --id Git.Git -e --silent` in PowerShell.

> Node.js is handled automatically by Hermes' one-liner installer — no manual setup needed.

After installing Python and Git, **reopen PowerShell** (to refresh PATH) and run:

```powershell
# 0. Enable Windows long path support (run PowerShell as Administrator, one-time only)
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
# Reboot after running this command

# 1. Install Hermes Agent (auto-installs Node.js + Git + dependencies)
irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1 | iex

# 2. Configure LLM
hermes setup

# 3. Install Smart Trade AI
git clone --branch main https://github.com/chefroger/smart-trade-ai.git $env:LOCALAPPDATA\trade\foreign-trade-assistant
cd $env:LOCALAPPDATA\trade\foreign-trade-assistant; pip install -e "."; install-trade-skills

python server.py
# → Open http://127.0.0.1:9119/trade
```

> If step 3 fails with `Filename too long`, long paths are not enabled. Verify step 0 was run and the machine was rebooted.

### Build standalone app (double-click to run, no terminal needed)

```bash
pip install pyinstaller
./scripts/build.sh          # macOS → dist/Smart Trade AI.app
powershell -File scripts/build.ps1  # Windows → dist/Smart Trade AI.exe
```

---

## 38 Professional Skills

| Skill | Description |
|------|------|
| Platform Diagnostics | Analyze Alibaba / Made-in-China product pages, output optimization suggestions |
| Social Media Marketing | Generate Facebook / Instagram / TikTok / YouTube content calendars |
| LinkedIn Operations | Profile optimization + content strategy + InMail templates |
| Customs Data | Analyze import/export data, identify high-value buyers |
| Lead Generation | Google Maps + LinkedIn + Facebook multi-channel customer discovery, one-click save |
| Cold Outreach | Product promotion emails / cold emails / follow-ups based on company product data |
| Email Intelligence | 120+ platform email registration check (holehe), social profile discovery |
| Client Management | A/B/C grading, detail panel, document library linking |
| Document Analysis | Complete file-by-file parsing of PDF/Word/Excel/PPT, never skips or truncates |
| Business Doc Generation | One-click quotes, proforma invoices, contracts (DOCX / XLSX / PPTX) |
| Quote & Negotiation | Negotiation strategy based on product knowledge base + client profile |
| Due Diligence | 6-layer verification: email → WHOIS → sanctions → MX → tech stack → LinkedIn |
| Customer Intel | Single-customer 15-dimension deep profile: decision chain, purchasing preferences, gift advice |
| Customer Finder | 3-question wizard: what to sell → where to sell → find who, auto search + cold email |
| Morning Brief | Live FX rates + commodities + market news + client follow-up reminders |
| Cron Tasks | Workday automations: morning brief / outreach / social posts / daily summary |
| Chat History | Per-company chat memory, searchable and retraceable |
| Email Imitation | Analyze excellent cold email samples → extract AIDA structure and style → generate original emails for your own products |
| Buyer Persona | Role-based buyer analysis (procurement/technical/executive) with FAB value proposition per role |
| Market Analysis | Go-to-market war map: certifications, tariffs, keyword arsenal, 3-second hooks, action roadmap |
| Sales Pipeline | 5-stage customer journey mapping, 30-day follow-up timeline, KPI tracking, pipeline health dashboard |
| Inquiry Training | Dual-AI adversarial training for inquiry responses, buyer persona simulation, objection handling |
| Trade Operations | 11 post-deal scenarios: payment reminders / claims / exhibitions / factory audits / logistics / after-sales / satisfaction surveys / annual reviews |
| Trade Compliance | Cultural taboo check / abbreviation standards / Incoterms 2020 / translation review / bidding / e-commerce listing |
| KOL Style Imitation | Analyze LinkedIn KOL content style (tone/structure/hooks) and apply to your own brand |
| Reddit Engagement | Build trust in Reddit communities via valuable comments, drive B2B leads |
| SEO + AEO Articles | Generate content optimized for both Google search and AI search (Perplexity/Gemini/ChatGPT) |
| Short Video Script | B2B product/factory video scripts (TikTok/YouTube Shorts/Reels) with storyboard |
| Exhibition Manager | Full trade show lifecycle: pre-show invites → on-site records → 48h post-show follow-up |
| Product Description | FAB method product selling points & sales kits (catalog/website/email embedded) |
| Decision Coach | Six Thinking Hats methodology for trade decisions (supplier selection, exhibition, payment terms) |
| Onboarding Wizard | 2-step guided setup: create company → paste customer URL → auto OSINT + cold email |
| Inquiry Meeting | Weekly inquiry review: per-rep analysis, key inquiry deep-dive, follow-up action plan |
| Sales Playbook | Turn top sales experience into SOPs / scripts / onboarding path / pitfall checklist |
| Business Proposal | 3-tier proposal comparison + ROI analysis + implementation roadmap for clients |
| Skill Generator | Describe what you need, auto-generates a new B2B skill + registers it |
| Tech Drawing Analysis | Extract part name / material / dimensions / tolerances from customer engineering-drawing PDFs (experimental — verify manually) |
| Auto Customer Dev | One-click end-to-end pipeline: search → vet → score → email → save → log |
| ~~Auto SMTP Email~~ | ~~Preview-then-send via SMTP — disabled, AI does not send emails on behalf of users~~ |

---

## Data Security

- **Business data is stored locally by default** (`~/.trade/`), nothing uploaded to any server
- With **Ollama or other local models**, full local operation is possible — no data leaves your machine
- With **OpenAI / Anthropic / DeepSeek / MiniMax or other cloud LLMs**, your input and necessary context are sent to the chosen provider — client identity data is NOT included
- Multi-company isolation (`X-Company-ID` header)
- Bound to `127.0.0.1` — only accessible from your local browser
- **Auto-backup before upgrades** → `~/.trade/backups/`

> **Disclaimer**: Alibaba, LinkedIn, Facebook, Instagram, TikTok, YouTube, WhatsApp and other platform names mentioned in this documentation are trademarks of their respective owners. This tool provides analysis assistance for these platforms and is not affiliated with them. Sanctions data is sourced from OFAC/UN/EU public datasets — results are for reference only and do not constitute legal advice. See [SECURITY.md](SECURITY.md) for details.

---

## Tech Stack

- **AI Engine**: [Hermes Agent](https://github.com/NousResearch/hermes-agent) (MIT licensed)
- **Backend**: FastAPI + SQLite + uvicorn
- **Frontend**: Vanilla JavaScript SPA (HTML/CSS/JS, zero build dependencies)
- **LLM**: Compatible with OpenAI / Anthropic / DeepSeek / MiniMax / Ollama etc.
- **Document Parsing**: PyMuPDF / python-docx / openpyxl / python-pptx

---

## Project Structure

```
trade/                     B2B business layer
├── api/                   FastAPI routes (10 business domains)
├── osint/                 Client due diligence module (6-layer verification)
├── skill_router.py        Skill auto-matching engine
├── skill_registry.py      38 skill registry (pure data)
└── ... + 20 business modules

skills/                    38 B2B skills (Markdown-driven)
tests/                     Test coverage (database / business / API / OSINT / smoke)
server.py                  FastAPI entry point
```

---

## Development

```bash
pip install -e ".[dev,docs]"
python -m pytest tests/ -v   # Run tests
ruff check trade/ server.py  # Lint
```

## Documentation

- [Product Requirements (en)](项目需求文档.en.md)
- [Business Overview (en)](业务概览.en.md)
- [Data Directory Structure (en)](Trade数据目录结构设计.en.md)
- [COMPATIBILITY.md](COMPATIBILITY.md) — Hermes version compatibility
- [Database Schema](docs/database-schema.md)

---

## Contact

<div style="display:flex;gap:40px;align-items:flex-start;">
  <div>
    <img src="docs/wechat-contact.jpeg" alt="WeChat" width="200"><br>
    <small>WeChat · Note "Trade"</small>
  </div>
  <div>
    <img src="docs/whatsapp-contact.png" alt="WhatsApp" width="200"><br>
    <small>WhatsApp</small>
  </div>
</div>

For business or support, email lauroge@gmail.com.

---

Smart Trade AI — an AI assistant for international trade professionals, running locally.
