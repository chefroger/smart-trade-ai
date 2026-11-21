"""
Trade AI Assistant — OSINT Intelligence Module.

Comprehensive B2B due-diligence toolkit covering 6 layers:
  Layer 1 : holehe email registration (in trade/email_intel.py)
  Layer 2 : WHOIS domain lookup
  Layer 3 : corporate email verification (vs personal email)
  Layer 4 : sanctions screening (OFAC SDN/非 SDN, US CSL, UN, EU, UK)
  Layer 5 : tech stack detection (BuiltWith-style)
  Layer 6 : LinkedIn company page verification

Architecture
────────────
All functions are pure (no side-effects, no DB, no file system).
Each submodule handles one detection layer.
The orchestrator chains them into a single osint_full_check() report.

Submodules
──────────
  constants.py         — shared constants (domain blacklists, HTTP utils)
  whois.py             — Layer 2: socket-based WHOIS domain lookup
  email_verify.py      — Layer 3: corporate vs personal email + MX DNS check
  sanctions/           — Layer 4: OFAC SDN/非 SDN、CSL、UN、EU、UK 本地库筛查
  tech_stack.py        — Layer 5: HTML regex tech stack detection
  linkedin_verify.py   — Layer 6: Google-search LinkedIn page verification
  scoring.py           — risk score computation + recommendation generation
  orchestrator.py      — osint_full_check() async orchestrator

Public API
──────────
  domain_whois(domain) -> dict
  verify_corporate_email(email, website=None) -> dict
  check_sanctions(name, country=None) -> dict
  detect_tech_stack(url) -> dict
  linkedin_company_verify(domain, company_name) -> dict
  osint_full_check(target, ...) -> dict  # async orchestrator
"""

from trade.osint.constants import (
    FREE_PLATFORMS,
    PERSONAL_EMAIL_DOMAINS,
    http_get,
)
from trade.osint.email_verify import verify_corporate_email
from trade.osint.linkedin_verify import linkedin_company_verify
from trade.osint.orchestrator import osint_full_check
from trade.osint.sanctions import check_sanctions
from trade.osint.scoring import compute_risk_score, generate_recommendations
from trade.osint.tech_stack import detect_tech_stack
from trade.osint.whois import domain_whois

__all__ = [
    # Public functions
    "domain_whois",
    "verify_corporate_email",
    "check_sanctions",
    "detect_tech_stack",
    "linkedin_company_verify",
    "osint_full_check",
    # Scoring
    "compute_risk_score",
    "generate_recommendations",
    # Constants (for external consumers that need them)
    "PERSONAL_EMAIL_DOMAINS",
    "FREE_PLATFORMS",
    "http_get",
]
