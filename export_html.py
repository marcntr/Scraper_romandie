"""HTML dashboard exporter for job scraper results.

Generates a fully self-contained HTML file (all CSS + JS inline,
zero external dependencies) readable directly in any browser.
"""

import html
import os
import re
from datetime import datetime

from models import Job


# ---------------------------------------------------------------------------
# Careers URL derivation
# ---------------------------------------------------------------------------

def _careers_url(cfg: dict) -> str:
    """Derive the public careers page URL from a company config dict."""
    ats = cfg.get("ats", "generic")
    if ats == "workday":
        tenant   = cfg.get("tenant", "")
        instance = cfg.get("instance", "wd1")
        portal   = cfg.get("portal", "")
        return f"https://{tenant}.{instance}.myworkdayjobs.com/en-US/{portal}"
    if ats == "workable":
        return f"https://apply.workable.com/{cfg.get('slug', '')}"
    if ats == "greenhouse":
        return f"https://boards.greenhouse.io/{cfg.get('board_token', '')}"
    if ats == "paylocity":
        guid = cfg.get("company_guid", "")
        slug = cfg.get("company_slug", "")
        return f"https://recruiting.paylocity.com/recruiting/jobs/All/{guid}/{slug}"
    # successfactors and generic both store careers_url directly
    return cfg.get("careers_url", "")

HTML_PATH = os.path.join(os.path.dirname(__file__), "latest_jobs.html")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(text or "", quote=True)


def _score_class(score: int) -> str:
    if score >= 6:
        return "score-green"
    if score >= 3:
        return "score-lime"
    if score >= 1:
        return "score-blue"
    if score == 0:
        return "score-slate"
    return "score-orange"


def _location_tag(location: str) -> str:
    loc_lower = (location or "").lower()
    romandie_terms = ("geneva", "lausanne", "vaud", "romand", "genève", "geneve")
    if any(t in loc_lower for t in romandie_terms):
        return '<span class="tag tag-romandie">Romandie</span>'
    return '<span class="tag tag-swiss">Switzerland</span>'


# ---------------------------------------------------------------------------
# Description section parser
# ---------------------------------------------------------------------------

# Known section-header phrases (order matters — longer phrases first to avoid
# partial matches; case-insensitive at call site via re.IGNORECASE).
# Case-sensitive patterns for ALL-CAPS inline section headers used by some ATS
# (e.g. Takeda/Workday: OBJECTIVES/PURPOSE, ACCOUNTABILITIES, …).
# Applied as a preprocessing step before the main _SECTION_RE split so that
# the resulting canonical names are detected by the case-insensitive regex.
_ALLCAPS_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Objectives / purpose → Key Responsibilities
    (re.compile(r'\bOBJECTIVES(?:/PURPOSE)?\b'), "Key Responsibilities"),
    # Accountabilities → Key Responsibilities
    (re.compile(r'\bACCOUNTABILITIES\b'), "Key Responsibilities"),
    # Combined form first (more specific) — e.g. "EDUCATION, BEHAVIOURAL COMPETENCIES AND SKILLS"
    (re.compile(r'\bEDUCATION,?\s*BEHAVIOURAL COMPETENCIES(?:\s+AND\s+SKILLS)?\b'), "Requirements"),
    (re.compile(r'\bBEHAVIORAL COMPETENCIES(?:\s+AND\s+SKILLS)?\b'), "Requirements"),
    (re.compile(r'\bBEHAVIOURAL COMPETENCIES(?:\s+AND\s+SKILLS)?\b'), "Requirements"),
    # Bare EDUCATION / SKILLS AND EXPERIENCE when used as section headers
    (re.compile(r'\bEDUCATION AND EXPERIENCE\b'), "Requirements"),
    (re.compile(r'\bSKILLS AND EXPERIENCE\b'), "Requirements"),
]

_SECTION_RE = re.compile(
    r'\b('
    # Company / role overview
    r'The Position|The Role'
    r'|About the Role|About Us|About the Company|About You|Who We Are|Who You Are'
    r'|Job Description|Job Summary|Role Summary|Position Summary'
    # Responsibilities
    r'|Key Responsibilities?|Your Responsibilities?|Main Responsibilities?'
    r'|What You\'ll Do|What You Will Do'
    # Candidate profile
    r'|What We\'re Looking For|What We Are Looking For'
    r'|What You Bring|What You\'ll Need|What You Need'
    r'|Your Background|Your Profile|Your Mission|Your Role|Your Qualifications?'
    # Generic requirements header (injected by _normalize_allcaps or used directly by some ATS)
    r'|Requirements?'
    # Essential requirements — long-form Danaher/Workday phrases first (consumed whole)
    r'|The essential requirements of the job include'
    r'|Essential Requirements?|Minimum Requirements?|Basic Requirements?'
    r'|Required Qualifications?|Minimum Qualifications?|Required Skills?'
    r'|Must Have'
    # Good-to-have — long-form phrases first
    r'|It would be a plus if you also possess previous experience in'
    r'|It would be a plus if you also'
    r'|It would be a plus if'
    r'|It would be a plus'
    r'|Nice to Have|Good to Have|Would Be a Plus'
    r'|Preferred Qualifications?|Preferred Skills?|Desired Qualifications?'
    # Offer
    r'|What We Offer'
    r')\s*:?\s+',
    re.IGNORECASE,
)

# Normalize verbose / ATS-specific header phrases to canonical display names.
_SECTION_ALIASES: dict[str, str] = {
    # ── About the Role ────────────────────────────────────────────────────
    "the position":          "About the Role",
    "the role":              "About the Role",
    "about us":              "About the Role",
    "about the company":     "About the Role",
    "who we are":            "About the Role",
    "job description":       "About the Role",
    "job summary":           "About the Role",
    "role summary":          "About the Role",
    "position summary":      "About the Role",
    # ── Key Responsibilities ──────────────────────────────────────────────
    "your responsibilities":  "Key Responsibilities",
    "main responsibilities":  "Key Responsibilities",
    "what you'll do":         "Key Responsibilities",
    "what you will do":       "Key Responsibilities",
    "your mission":           "Key Responsibilities",
    "your role":              "Key Responsibilities",
    # ── Requirements (generic — no essential/optional distinction) ────────
    "requirement":            "Requirements",
    "what we're looking for": "Requirements",
    "what we are looking for":"Requirements",
    "what you bring":         "Requirements",
    "what you'll need":       "Requirements",
    "what you need":          "Requirements",
    "your background":        "Requirements",
    "your profile":           "Requirements",
    "your qualifications":    "Requirements",
    "about you":              "Requirements",
    "who you are":            "Requirements",
    # ── Essential Requirements (orange badge) ─────────────────────────────
    "the essential requirements of the job include": "Essential Requirements",
    "essential requirement":  "Essential Requirements",
    "minimum requirements":   "Essential Requirements",
    "minimum requirement":    "Essential Requirements",
    "basic requirements":     "Essential Requirements",
    "basic requirement":      "Essential Requirements",
    "required qualifications":"Essential Requirements",
    "minimum qualifications": "Essential Requirements",
    "required skills":        "Essential Requirements",
    "must have":              "Essential Requirements",
    # ── Good to Have (teal badge) ─────────────────────────────────────────
    "it would be a plus if you also possess previous experience in": "Good to Have",
    "it would be a plus if you also": "Good to Have",
    "it would be a plus if":  "Good to Have",
    "it would be a plus":     "Good to Have",
    "would be a plus":        "Good to Have",
    "nice to have":           "Good to Have",
    "good to have":           "Good to Have",
    "preferred qualifications":"Good to Have",
    "preferred qualification": "Good to Have",
    "preferred skills":       "Good to Have",
    "preferred skill":        "Good to Have",
    "desired qualifications": "Good to Have",
    "desired qualification":  "Good to Have",
}

# Section headers that mark hard requirements → orange badge
_REQUIRED_KEYS = {
    'essential requirements', 'required skills', 'must have',
}

# Section headers that mark optional / preferred → teal badge
_OPTIONAL_KEYS = {
    'good to have', 'preferred skills', 'preferred qualifications',
}

# Section keys where content should be rendered as a bullet list
_LIST_KEYS = {
    'key responsibilities', 'requirements',
    'essential requirements', 'good to have',
    'what you\'ll do', 'what you will do',
    'what we\'re looking for', 'what we are looking for',
    'what you bring', 'what you\'ll need', 'what you need',
    'your background', 'your profile', 'who you are', 'about you',
    'your qualifications', 'required skills',
    'minimum requirements', 'must have',
    'preferred skills', 'preferred qualifications',
}


def _normalize_allcaps(text: str) -> str:
    """Replace known ALL-CAPS inline section headers with canonical names.

    Some ATS platforms (e.g. Takeda/Workday) embed section headers as ALL-CAPS
    phrases inline in the description text rather than using HTML structure.
    This step converts them to mixed-case canonical names before the main
    regex split runs, so _SECTION_RE can detect them normally.
    """
    for pattern, replacement in _ALLCAPS_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _parse_description_sections(text: str) -> list[tuple[str, str]]:
    """Split flat description text into [(header, content), …] pairs.

    The first tuple may have an empty header (preamble before any section).
    Consecutive empty sections with the same header are merged/dropped.
    """
    text = _normalize_allcaps(text)
    parts = _SECTION_RE.split(text)
    raw: list[tuple[str, str]] = []

    preamble = parts[0].strip()
    if preamble:
        raw.append(("", preamble))

    for i in range(1, len(parts), 2):
        header  = parts[i].strip().rstrip(":")
        # Normalize verbose / ATS-specific phrases to canonical display names
        header  = _SECTION_ALIASES.get(header.lower(), header)
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        raw.append((header, content))

    # Merge consecutive sections that share the same header.
    # This handles both empty-content duplicates (Roche "The Position The Position")
    # and ALL-CAPS patterns that normalize to the same canonical name
    # (e.g. OBJECTIVES/PURPOSE + ACCOUNTABILITIES → both "Key Responsibilities").
    merged: list[tuple[str, str]] = []
    for header, content in raw:
        if merged and merged[-1][0].lower() == header.lower():
            combined = (merged[-1][1] + " " + content).strip()
            merged[-1] = (merged[-1][0], combined)
        elif content or not header:
            merged.append((header, content))
        # else: skip empty-content sections that aren't the preamble

    return merged


def _split_sentences(text: str) -> list[str]:
    """Split section body text into individual sentences / list items."""
    # Split on '. ' followed by a capital letter, or on newlines
    items = re.split(r'\.\s+(?=[A-Z])', text)
    result = []
    for item in items:
        item = item.strip().rstrip(".")
        if len(item) > 15:           # drop very short fragments
            result.append(item)
    return result


def _format_description(desc: str) -> str:
    """Convert flat description text into structured HTML sections."""
    if not desc:
        return ""

    sections = _parse_description_sections(desc)
    if not sections:
        return f'<p class="desc-para">{_esc(desc)}</p>'

    parts = []
    for header, content in sections:
        if header:
            h_lower = header.lower()
            if h_lower in _REQUIRED_KEYS:
                sh_cls = "desc-sh desc-sh--required"
            elif h_lower in _OPTIONAL_KEYS:
                sh_cls = "desc-sh desc-sh--optional"
            else:
                sh_cls = "desc-sh"
            header_html = f'<div class="{sh_cls}">{_esc(header)}</div>'
        else:
            header_html = ""

        if not content:
            parts.append(f'<div class="desc-sec">{header_html}</div>')
            continue

        is_list = header.lower().rstrip(":") in _LIST_KEYS
        if is_list:
            sentences = _split_sentences(content)
            if len(sentences) > 1:
                items_html = "".join(f"<li>{_esc(s)}</li>" for s in sentences)
                body_html  = f'<ul class="desc-list">{items_html}</ul>'
            else:
                body_html = f'<p class="desc-para">{_esc(content)}</p>'
        else:
            body_html = f'<p class="desc-para">{_esc(content)}</p>'

        parts.append(f'<div class="desc-sec">{header_html}{body_html}</div>')

    return "\n".join(parts)


def _parse_alert(alert_str: str) -> tuple[str, str]:
    """Extract (url, keywords_str) from a GenericMonitor alert string.

    Expected format:
        "Potential match found at {url}. Manual review required. Matched keywords: {kw1, kw2}"
    Falls back gracefully if the format doesn't match.
    """
    url = ""
    keywords = ""
    url_match = re.search(r"Potential match found at\s+(\S+)\.", alert_str)
    if url_match:
        url = url_match.group(1)
    kw_match = re.search(r"Matched keywords:\s*(.+)$", alert_str)
    if kw_match:
        keywords = kw_match.group(1).strip()
    if not url:
        # Fallback: grab first http(s) URL
        fb = re.search(r"https?://\S+", alert_str)
        if fb:
            url = fb.group(0).rstrip(".,")
    return url, keywords


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------

def _job_card(job: Job, idx: int, is_new: bool = False) -> str:
    score_cls = _score_class(job.score)
    score_sign = f"+{job.score}" if job.score > 0 else str(job.score)
    loc_tag = _location_tag(job.location)
    posted = f"Posted {_esc(job.posted_date)}" if job.posted_date else ""
    matched = "  ".join(_esc(k) for k in job.matched_keywords) if job.matched_keywords else "(none)"
    deducted = "  ".join(_esc(k) for k in job.deducted_keywords) if job.deducted_keywords else "(none)"
    new_badge = '<span class="new-badge">New</span>' if is_new else ""

    raw_desc = job.description or ""
    has_desc = bool(raw_desc)
    toggle_btn = (
        f'<button class="toggle-btn" onclick="toggleDesc(this,{idx})">▸ Description</button>'
        if has_desc else ""
    )
    desc_structured = (
        f'<div id="desc-more-{idx}" class="desc-structured" hidden>'
        f'{_format_description(raw_desc)}'
        f'</div>'
        if has_desc else ""
    )

    # Data attributes for JS filtering
    company_data = _esc(job.company)
    score_data = job.score
    loc_data = "romandie" if any(
        t in (job.location or "").lower()
        for t in ("geneva", "lausanne", "vaud", "romand", "genève", "geneve")
    ) else "switzerland"

    if job.status == "matched":
        triage_btns = (
            '<button class="action-btn action-ignore" onclick="setJobStatus(this,\'ignored\')">Ignore</button>'
            '<button class="action-btn action-applied" onclick="setJobStatus(this,\'applied\')">&#10003; Applied</button>'
        )
    else:
        triage_btns = '<button class="action-btn action-match" onclick="setJobStatus(this,\'matched\')">&#8629; Back to Matched</button>'

    return f'''
<div class="job-card"
     data-company="{company_data}"
     data-score="{score_data}"
     data-date="{_esc(job.posted_date or '')}"
     data-location="{loc_data}"
     data-url="{_esc(job.url)}"
     data-status="{_esc(job.status)}"
     data-text="{_esc((job.title + ' ' + job.company + ' ' + ' '.join(job.matched_keywords)).lower())}">
  <div class="card-header">
    <div class="card-left">
      <span class="score-badge {score_cls}">{score_sign}</span>
      {new_badge}
      <span class="job-title">{_esc(job.title)}</span>
    </div>
    <a class="open-link" href="{_esc(job.url)}" target="_blank" rel="noopener">Open ↗</a>
  </div>
  <div class="card-meta">
    <span class="company">{_esc(job.company)}</span>
    <span class="location">📍 {_esc(job.location)}</span>
    {loc_tag}
    {f'<span class="posted">{posted}</span>' if posted else ""}
  </div>
  <div class="card-keywords">
    <span class="kw-label kw-plus">+</span><span class="kw-text">{matched}</span>
    &nbsp;&nbsp;
    <span class="kw-label kw-minus">−</span><span class="kw-text">{deducted}</span>
  </div>
  <div class="card-desc">
    {toggle_btn}
    {desc_structured}
  </div>
  <div class="card-actions">
    {triage_btns}
  </div>
</div>'''


# ---------------------------------------------------------------------------
# Company type catalogue (display-only — not stored in config.py)
# ---------------------------------------------------------------------------

_COMPANY_TYPES: dict[str, str] = {
    # Big Pharma
    "Roche":                          "Big Pharma",
    "Novartis":                       "Big Pharma",
    "Abbott":                         "Big Pharma",
    "Sanofi":                         "Big Pharma",
    "Bristol Myers Squibb":           "Big Pharma",
    "AstraZeneca":                    "Big Pharma",
    "Pfizer":                         "Big Pharma",
    "GSK":                            "Big Pharma",
    "Amgen":                          "Big Pharma",
    "Gilead Sciences":                "Big Pharma",
    "Moderna":                        "Big Pharma",
    "Takeda":                         "Big Pharma",
    "Bayer":                          "Big Pharma",
    "AbbVie":                         "Big Pharma",
    "Boehringer Ingelheim":           "Big Pharma",
    "Eli Lilly":                      "Big Pharma",
    "MSD":                            "Big Pharma",
    "Merck Group":                    "Big Pharma",
    "Johnson & Johnson / Janssen":    "Big Pharma",
    # Specialty Pharma
    "Debiopharm":                     "Specialty Pharma",
    "Ferring Pharmaceuticals":        "Specialty Pharma",
    "CSL Behring / Vifor":            "Specialty Pharma",
    "Idorsia":                        "Specialty Pharma",
    "Sobi":                           "Specialty Pharma",
    "Octapharma":                     "Specialty Pharma",
    "OM Pharma":                      "Specialty Pharma",
    "Servier Suisse":                 "Specialty Pharma",
    "Basilea Pharmaceutica":          "Specialty Pharma",
    "UCB":                            "Specialty Pharma",
    # Biotech
    "ADC Therapeutics":               "Biotech",
    "Isomorphic Labs":                "Biotech",
    "BeiGene":                        "Biotech",
    "Vertex Pharmaceuticals":         "Biotech",
    "Roivant Sciences":               "Biotech",
    "Monte Rosa Therapeutics":        "Biotech",
    "AC Immune":                      "Biotech",
    "Araris Biotech":                 "Biotech",
    "Kuros Biosciences":              "Biotech",
    "Release Therapeutics":           "Biotech",
    "Numab Therapeutics":             "Biotech",
    "Oculis":                         "Biotech",
    "Immunos Therapeutics":           "Biotech",
    "iOnctura":                       "Biotech",
    "GeNeuro":                        "Biotech",
    "Gnubiotics":                     "Biotech",
    "BioNTech":                       "Biotech",
    "Galapagos":                      "Biotech",
    "Ridgeline Discovery":            "Biotech",
    "MoonLake Immunotherapeutics":    "Biotech",
    "AMAL Therapeutics":              "Biotech",
    "HAYA Therapeutics":              "Biotech",
    "Incyte":                         "Biotech",
    "Light Chain Bioscience":         "Biotech",
    "Tigen Pharma":                   "Biotech",
    "Leman Biotech":                  "Biotech",
    "Signal26":                       "Biotech",
    "Novigenix":                      "Biotech",
    "Hurdle Bio":                     "Biotech",
    "Cutiss":                         "Biotech",
    "Molecular Partners":             "Biotech",
    "Molecular Partners (ETH)":       "Biotech",
    # CRO / Preclinical
    "Labcorp":                        "CRO",
    "IQVIA":                          "CRO",
    "ICON plc":                       "CRO",
    "Parexel":                        "CRO",
    "Syneos Health":                  "CRO",
    "Charles River Laboratories":     "CRO",
    "Medpace":                        "CRO",
    "PSI CRO":                        "CRO",
    # KCR removed (acquired by ICON)
    "BioLizard":                      "CRO",
    "Alira Health":                   "CRO",
    # CDMO
    "Lonza":                          "CDMO",
    # Distribution
    "Cencora":                        "Distribution",
    # Life Science Tools
    "Bio-Techne / Lunaphore":         "Life Science Tools",
    "SOPHiA GENETICS":                "Life Science Tools",
    "Thermo Fisher Scientific":       "Life Science Tools",
    "Danaher":                        "Life Science Tools",
    "Illumina":                       "Life Science Tools",
    "Qiagen":                         "Life Science Tools",
    "Agilent Technologies":           "Life Science Tools",
    "10x Genomics":                   "Life Science Tools",
    "Bio-Rad":                        "Life Science Tools",
    "Zeiss":                          "Life Science Tools",
    "Tecan":                          "Life Science Tools",
    "Hamilton":                       "Life Science Tools",
    "Biognosys":                      "Life Science Tools",
    "PerkinElmer / Revvity":          "Life Science Tools",
    # Medical Devices
    "Alcon":                          "Medical Devices",
    "Galderma":                       "Medical Devices",
    "Becton Dickinson":               "Medical Devices",
    "Straumann":                      "Medical Devices",
    # AI / Data
    "Owkin":                          "AI / Data",
    "DNAnexus":                       "AI / Data",
    "Seven Bridges / Velsera":        "AI / Data",
    "Tempus":                         "AI / Data",
    "Insilico Medicine":              "AI / Data",
    "BC Platforms":                   "AI / Data",
    "ABCDx":                          "AI / Data",
    "chAIron SA":                     "AI / Data",
    # Tech / SaaS
    "Benchling":                      "Tech / SaaS",
    "Veeva Systems":                  "Tech / SaaS",
    "Genedata":                       "Tech / SaaS",
    "Palantir":                       "Tech / SaaS",
    "EPAM Systems":                   "Tech / SaaS",
    "Zühlke":                         "Tech / SaaS",
    # Consumer Health
    "Nestlé Health Science":          "Consumer Health",
    "dsm-firmenich":                  "Consumer Health",
    # New additions
    "Daiichi Sankyo":                 "Big Pharma",
    "Astellas Pharma":                "Big Pharma",
    "Blueprint Medicines":            "Biotech",
    "KBI Biopharma":                  "CDMO",
    "Dotmatics":                      "Life Science Tools",
    "Certara":                        "Life Science Tools",
    "CDD Vault":                      "Life Science Tools",
    "Scailyte":                       "AI / Data",
    "Telix Pharmaceuticals":          "Specialty Pharma",
}

_TYPE_BADGE: dict[str, tuple[str, str]] = {
    "Big Pharma":        ("#1e3a5f", "#60a5fa"),   # blue
    "Specialty Pharma":  ("#1e1b4b", "#a5b4fc"),   # indigo
    "Biotech":           ("#14532d", "#4ade80"),   # green
    "CRO":               ("#451a03", "#fb923c"),   # orange
    "CDMO":              ("#0c4a6e", "#38bdf8"),   # sky blue
    "Life Science Tools":("#1a2e05", "#84cc16"),   # lime
    "Medical Devices":   ("#3b0764", "#c084fc"),   # purple
    "AI / Data":         ("#4c0519", "#f87171"),   # rose
    "Tech / SaaS":       ("#312e81", "#818cf8"),   # violet
    "Consumer Health":   ("#064e3b", "#34d399"),   # emerald
    "Distribution":      ("#1f2937", "#9ca3af"),   # gray
}


def _type_badge(name: str) -> str:
    typ = _COMPANY_TYPES.get(name, "")
    if not typ:
        return ""
    bg, fg = _TYPE_BADGE.get(typ, ("#1f2937", "#9ca3af"))
    return f'<span class="ats-badge" style="background:{bg};color:{fg}">{_esc(typ)}</span>'


_ATS_BADGE: dict[str, tuple[str, str]] = {
    "workday":       ("#1e1b4b", "#a5b4fc"),   # indigo
    "workable":      ("#0c4a6e", "#67e8f9"),   # cyan
    "greenhouse":    ("#14532d", "#86efac"),   # green
    "successfactors":("#78350f", "#fcd34d"),   # amber
    "paylocity":     ("#1e3a5f", "#93c5fd"),   # blue
    "smartrecruiters":     ("#0c2340", "#38bdf8"),   # sky-blue (SR brand)
    "nestlehealthscience": ("#1a2e05", "#84cc16"),   # lime
    "michaelpage":         ("#1c1917", "#f97316"),   # orange
    "hayatx":              ("#1a1a2e", "#e879f9"),   # fuchsia
    "hays":          ("#172554", "#60a5fa"),   # blue-dark
    "randstad":      ("#1c1917", "#fb923c"),   # orange-dark
    "stettler":      ("#0f172a", "#94a3b8"),   # slate-dark
    "alecallan":     ("#0f172a", "#7dd3fc"),   # sky
    "gloorlang":     ("#0f172a", "#86efac"),   # green-dark
    "generic":       ("#1f2937", "#9ca3af"),   # slate
}

def _company_row(cfg: dict) -> str:
    name = cfg.get("name", "")
    ats  = cfg.get("ats", "generic")
    url  = _careers_url(cfg)
    typ  = _COMPANY_TYPES.get(name, "")

    bg, fg = _ATS_BADGE.get(ats, _ATS_BADGE["generic"])
    ats_badge = (
        f'<span class="ats-badge" style="background:{bg};color:{fg}">'
        f'{_esc(ats)}</span>'
    )
    type_cell = _type_badge(name)
    visit = (
        f'<a class="open-link" href="{_esc(url)}" target="_blank" rel="noopener">Visit ↗</a>'
        if url else '<span style="color:#4b5563">—</span>'
    )
    return (
        f'<tr class="co-row" data-name="{_esc(name.lower())}" data-type="{_esc(typ.lower())}">'
        f'<td class="co-name">{_esc(name)}</td>'
        f'<td>{type_cell}</td>'
        f'<td>{ats_badge}</td>'
        f'<td class="co-url">{_esc(url)}</td>'
        f'<td>{visit}</td>'
        f'</tr>'
    )


def _alert_card(company: str, alert_str: str) -> str:
    url, keywords = _parse_alert(alert_str)
    kw_display = "  ".join(_esc(k.strip()) for k in keywords.split(",") if k.strip()) if keywords else ""
    return f'''
<div class="alert-card">
  <div class="alert-header">
    <span class="alert-company">{_esc(company)}</span>
    {f'<a class="open-link" href="{_esc(url)}" target="_blank" rel="noopener">Visit ↗</a>' if url else ""}
  </div>
  {f'<div class="alert-url">{_esc(url)}</div>' if url else ""}
  {f'<div class="alert-keywords">{kw_display}</div>' if kw_display else ""}
</div>'''


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def export_html(
    jobs: list[Job],
    alerts: list[tuple[str, str]],
    companies_cfg: list[dict] | None = None,
    path: str = HTML_PATH,
    known_urls: set[str] | None = None,
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    matched_jobs = [j for j in jobs if j.status == "matched"]
    ignored_jobs = [j for j in jobs if j.status == "ignored"]
    applied_jobs = [j for j in jobs if j.status == "applied"]
    n_matched  = len(matched_jobs)
    n_ignored  = len(ignored_jobs)
    n_applied  = len(applied_jobs)
    n_jobs     = len(jobs)
    n_alerts   = len(alerts)
    all_cfgs   = sorted(companies_cfg or [], key=lambda c: c.get("name", "").lower())
    n_monitored = len(all_cfgs)

    job_companies = sorted({j.company for j in matched_jobs})

    job_cards_html = "\n".join(
        _job_card(j, i, is_new=(known_urls is not None and j.url not in known_urls))
        for i, j in enumerate(matched_jobs)
    )
    ignored_cards_html = "\n".join(
        _job_card(j, n_matched + i, is_new=False)
        for i, j in enumerate(ignored_jobs)
    )
    applied_cards_html = "\n".join(
        _job_card(j, n_matched + n_ignored + i, is_new=False)
        for i, j in enumerate(applied_jobs)
    )
    alert_cards_html = "\n".join(_alert_card(c, a) for c, a in alerts)
    company_rows_html = "\n".join(_company_row(cfg) for cfg in all_cfgs)

    company_options = "\n".join(
        f'<option value="{_esc(c)}">{_esc(c)}</option>' for c in job_companies
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Dashboard — {_esc(timestamp)}</title>
<style>
/* ── Reset & base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 14px;
  background: #0f1117;
  color: #d1d5db;
  min-height: 100vh;
}}
a {{ color: inherit; text-decoration: none; }}

/* ── Header ── */
.header {{
  background: linear-gradient(135deg, #1a1f2e 0%, #0d1525 60%, #0a0f1a 100%);
  border-bottom: 1px solid #2a2f3e;
  padding: 28px 32px 24px;
}}
.header h1 {{
  font-size: 22px;
  font-weight: 700;
  color: #f0f4ff;
  letter-spacing: 0.5px;
}}
.header .subtitle {{
  color: #6b7280;
  font-size: 12px;
  margin-top: 4px;
}}
.stats {{
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}}
.stat-chip {{
  background: #1e2535;
  border: 1px solid #2d3448;
  border-radius: 20px;
  padding: 5px 14px;
  font-size: 13px;
  color: #9ca3af;
}}
.stat-chip strong {{
  color: #e2e8f0;
}}

/* ── Tab bar ── */
.tab-bar {{
  display: flex;
  gap: 0;
  border-bottom: 1px solid #2a2f3e;
  background: #12161f;
  padding: 0 32px;
}}
.tab-btn {{
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: #6b7280;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  padding: 12px 18px;
  transition: color 0.15s, border-color 0.15s;
}}
.tab-btn:hover {{ color: #9ca3af; }}
.tab-btn.active {{
  color: #818cf8;
  border-bottom-color: #818cf8;
}}

/* ── Content area ── */
.content {{ padding: 24px 32px; }}
.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; }}

/* ── Filter bar ── */
.filter-bar {{
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  position: sticky;
  top: 0;
  z-index: 10;
  background: #0f1117;
  padding: 12px 0 10px;
  margin-bottom: 10px;
  border-bottom: 1px solid #1e2535;
}}
.sort-btn {{
  background: #1a1f2e;
  border: 1px solid #2d3448;
  border-radius: 6px;
  color: #9ca3af;
  cursor: pointer;
  font-size: 13px;
  padding: 7px 11px;
  white-space: nowrap;
  transition: color 0.15s, border-color 0.15s;
}}
.sort-btn:hover {{ color: #d1d5db; border-color: #3d4460; }}
.sort-btn.active {{ color: #818cf8; border-color: #818cf8; }}
.filter-bar input,
.filter-bar select {{
  background: #1a1f2e;
  border: 1px solid #2d3448;
  border-radius: 6px;
  color: #d1d5db;
  font-size: 13px;
  padding: 7px 11px;
  outline: none;
}}
.filter-bar input {{ flex: 1; min-width: 180px; }}
.filter-bar input:focus,
.filter-bar select:focus {{ border-color: #818cf8; }}
.filter-bar select option {{ background: #1a1f2e; }}
.results-count {{
  color: #6b7280;
  font-size: 12px;
  margin-bottom: 14px;
}}

/* ── Job cards ── */
.job-card {{
  background: #161b27;
  border: 1px solid #242938;
  border-radius: 10px;
  margin-bottom: 12px;
  padding: 16px 18px;
  transition: border-color 0.15s;
}}
.job-card:hover {{ border-color: #3d4460; }}
.card-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}}
.card-left {{
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}}
.job-title {{
  font-size: 15px;
  font-weight: 600;
  color: #e2e8f0;
  line-height: 1.4;
}}
.new-badge {{
  background: #14532d;
  color: #4ade80;
  border: 1px solid #166534;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  flex-shrink: 0;
  white-space: nowrap;
}}
.score-badge {{
  border-radius: 5px;
  font-size: 12px;
  font-weight: 700;
  padding: 2px 7px;
  white-space: nowrap;
  flex-shrink: 0;
}}
.score-green  {{ background: #14532d; color: #4ade80; }}
.score-lime   {{ background: #365314; color: #a3e635; }}
.score-blue   {{ background: #1e3a5f; color: #60a5fa; }}
.score-slate  {{ background: #1e2535; color: #94a3b8; }}
.score-orange {{ background: #431407; color: #fb923c; }}

.open-link {{
  background: #1e2535;
  border: 1px solid #3d4460;
  border-radius: 5px;
  color: #818cf8;
  font-size: 12px;
  padding: 4px 10px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background 0.15s;
}}
.open-link:hover {{ background: #2a3050; }}

/* ── Card meta ── */
.card-meta {{
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  color: #6b7280;
  font-size: 12px;
}}
.company {{ color: #9ca3af; font-weight: 500; }}
.tag {{
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  letter-spacing: 0.3px;
}}
.tag-romandie {{ background: #3b1f5e; color: #c084fc; }}
.tag-swiss    {{ background: #1e3a5f; color: #60a5fa; }}
.posted {{ color: #4b5563; }}

/* ── Keywords ── */
.card-keywords {{
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 8px;
}}
.kw-label {{
  border-radius: 3px;
  font-weight: 700;
  font-size: 11px;
  padding: 1px 5px;
}}
.kw-plus {{ background: #14532d; color: #4ade80; }}
.kw-minus {{ background: #431407; color: #fb923c; }}
.kw-text {{ color: #9ca3af; }}

/* ── Description ── */
.card-desc {{
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
}}
.toggle-btn {{
  background: none;
  border: none;
  color: #818cf8;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}}
.toggle-btn:hover {{ color: #a5b4fc; }}
.desc-structured {{
  margin-top: 10px;
  border-top: 1px solid #1e2535;
  padding-top: 10px;
}}
.desc-sec {{
  margin-bottom: 10px;
}}
.desc-sh {{
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: #818cf8;
  margin-bottom: 5px;
}}
.desc-sh--required {{
  color: #fb923c;
}}
.desc-sh--optional {{
  color: #34d399;
}}
.desc-para {{
  color: #9ca3af;
  line-height: 1.6;
  margin: 0;
}}
.desc-list {{
  margin: 0;
  padding-left: 18px;
  color: #9ca3af;
  line-height: 1.6;
}}
.desc-list li {{
  margin-bottom: 3px;
}}

/* ── Alert cards ── */
.alert-card {{
  background: #161b27;
  border: 1px solid #242938;
  border-left: 3px solid #d97706;
  border-radius: 8px;
  margin-bottom: 10px;
  padding: 14px 16px;
}}
.alert-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}}
.alert-company {{
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
}}
.alert-url {{
  color: #6b7280;
  font-size: 12px;
  margin-bottom: 5px;
  word-break: break-all;
}}
.alert-keywords {{
  color: #9ca3af;
  font-size: 12px;
}}

/* ── Empty state ── */
.empty {{ color: #4b5563; padding: 32px 0; text-align: center; }}

/* ── Companies table ── */
.co-search {{
  background: #1a1f2e;
  border: 1px solid #2d3448;
  border-radius: 6px;
  color: #d1d5db;
  font-size: 13px;
  padding: 7px 11px;
  outline: none;
  width: 280px;
  margin-bottom: 16px;
}}
.co-search:focus {{ border-color: #818cf8; }}
.co-table {{
  width: 100%;
  border-collapse: collapse;
}}
.co-table th {{
  color: #6b7280;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
  padding: 8px 12px;
  text-align: left;
  text-transform: uppercase;
  border-bottom: 1px solid #242938;
}}
.co-row {{
  border-bottom: 1px solid #1a1f2e;
  transition: background 0.1s;
}}
.co-row:hover {{ background: #161b27; }}
.co-row td {{ padding: 10px 12px; vertical-align: middle; }}
.co-name {{
  color: #e2e8f0;
  font-weight: 500;
  font-size: 13px;
  white-space: nowrap;
}}
.co-url {{
  color: #4b5563;
  font-size: 11px;
  word-break: break-all;
  max-width: 420px;
}}
.ats-badge {{
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  white-space: nowrap;
  letter-spacing: 0.3px;
}}
.co-count {{
  color: #6b7280;
  font-size: 12px;
  margin-bottom: 12px;
}}

/* ── Triage action buttons ── */
.card-actions {{
  display: flex;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #1e2535;
}}
.action-btn {{
  border: 1px solid;
  border-radius: 5px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  transition: opacity 0.15s;
}}
.action-btn:hover {{ opacity: 0.8; }}
.action-ignore {{
  background: #1c1917;
  border-color: #57534e;
  color: #a8a29e;
}}
.action-applied {{
  background: #14532d;
  border-color: #166534;
  color: #4ade80;
}}
.action-match {{
  background: #1e2535;
  border-color: #3d4460;
  color: #818cf8;
}}

/* ── Triage tabs empty state ── */
.triage-empty {{
  color: #4b5563;
  padding: 32px 0;
  text-align: center;
  font-size: 13px;
}}
</style>
</head>
<body>

<div class="header">
  <h1>Biopharma Job Dashboard</h1>
  <div class="subtitle">Run: {_esc(timestamp)}</div>
  <div class="stats">
    <div class="stat-chip"><strong>{n_matched}</strong> matched jobs</div>
    <div class="stat-chip"><strong>{n_ignored}</strong> ignored</div>
    <div class="stat-chip"><strong>{n_applied}</strong> applied</div>
    <div class="stat-chip"><strong>{n_alerts}</strong> alerts</div>
    <div class="stat-chip"><strong>{n_monitored}</strong> companies monitored</div>
  </div>
</div>

<div class="tab-bar">
  <button id="tab-btn-matched" class="tab-btn active" onclick="showTab(this,'matched')">Matched Jobs ({n_matched})</button>
  <button id="tab-btn-ignored" class="tab-btn" onclick="showTab(this,'ignored')">Ignored ({n_ignored})</button>
  <button id="tab-btn-applied" class="tab-btn" onclick="showTab(this,'applied')">Applied ({n_applied})</button>
  {f'<button class="tab-btn" onclick="showTab(this,\'alerts\')">Alerts ({n_alerts})</button>' if n_alerts else ''}
  <button class="tab-btn" onclick="showTab(this,'companies')">Companies ({n_monitored})</button>
</div>

<div class="content">

  <!-- ── Matched Jobs tab ── -->
  <div id="tab-matched" class="tab-panel active">
    <div class="filter-bar">
      <input type="text" id="filter-text" placeholder="Search title, company, keywords…" oninput="applyFilters()">
      <select id="filter-company" onchange="applyFilters()">
        <option value="">All companies</option>
        {company_options}
      </select>
      <select id="filter-score" onchange="applyFilters()">
        <option value="">Any score</option>
        <option value="6">Score ≥ 6</option>
        <option value="3">Score ≥ 3</option>
        <option value="1">Score ≥ 1</option>
        <option value="0">Score ≥ 0</option>
      </select>
      <select id="filter-location" onchange="applyFilters()">
        <option value="">All locations</option>
        <option value="romandie">Romandie</option>
        <option value="switzerland">Switzerland</option>
      </select>
      <button class="sort-btn active" id="sort-date-btn" onclick="setSort('date')">Date ↓</button>
      <button class="sort-btn" id="sort-score-btn" onclick="setSort('score')">Score ↓</button>
    </div>
    <div class="results-count" id="results-count">{n_matched} job{'s' if n_matched != 1 else ''} shown</div>
    <div id="job-list">
      {job_cards_html if job_cards_html.strip() else '<div class="triage-empty">No matched jobs this run.</div>'}
    </div>
  </div>

  <!-- ── Ignored tab ── -->
  <div id="tab-ignored" class="tab-panel">
    <div id="ignored-list">
      {ignored_cards_html if ignored_cards_html.strip() else '<div class="triage-empty">No ignored jobs.</div>'}
    </div>
  </div>

  <!-- ── Applied tab ── -->
  <div id="tab-applied" class="tab-panel">
    <div id="applied-list">
      {applied_cards_html if applied_cards_html.strip() else '<div class="triage-empty">No applied jobs.</div>'}
    </div>
  </div>

  <!-- ── Alerts tab (only rendered when there are alerts) ── -->
  {f'<div id="tab-alerts" class="tab-panel">{alert_cards_html}</div>' if n_alerts else ''}

  <!-- ── Companies tab ── -->
  <div id="tab-companies" class="tab-panel">
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;align-items:center">
      <input class="co-search" type="text" id="co-search" placeholder="Filter companies…" oninput="filterCompanies()" style="margin-bottom:0">
      <select class="co-search" id="co-type-filter" onchange="filterCompanies()" style="margin-bottom:0;width:auto">
        <option value="">All types</option>
        <option value="big pharma">Big Pharma</option>
        <option value="specialty pharma">Specialty Pharma</option>
        <option value="biotech">Biotech</option>
        <option value="cro">CRO</option>
        <option value="cdmo">CDMO</option>
        <option value="life science tools">Life Science Tools</option>
        <option value="medical devices">Medical Devices</option>
        <option value="ai / data">AI / Data</option>
        <option value="tech / saas">Tech / SaaS</option>
        <option value="consumer health">Consumer Health</option>
        <option value="distribution">Distribution</option>
      </select>
    </div>
    <div class="co-count" id="co-count">{n_monitored} companies monitored</div>
    <table class="co-table">
      <thead>
        <tr>
          <th>Company</th>
          <th>Type</th>
          <th>ATS</th>
          <th>Careers URL</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="co-tbody">
        {company_rows_html}
      </tbody>
    </table>
  </div>

</div>

<script>
// ── Tab switching ──
function showTab(btn, name) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
}}

// ── Triage: update tab counters ──
function updateTabCounts() {{
  const nM = document.querySelectorAll('#job-list .job-card').length;
  const nI = document.querySelectorAll('#ignored-list .job-card').length;
  const nA = document.querySelectorAll('#applied-list .job-card').length;
  document.getElementById('tab-btn-matched').textContent = 'Matched Jobs (' + nM + ')';
  document.getElementById('tab-btn-ignored').textContent = 'Ignored (' + nI + ')';
  document.getElementById('tab-btn-applied').textContent = 'Applied (' + nA + ')';
  document.getElementById('results-count').textContent =
    nM + ' job' + (nM === 1 ? '' : 's') + ' shown';
}}

// ── Triage: rebuild action buttons after a status change ──
function renderTriageBtns(card, status) {{
  card.dataset.status = status;
  const div = card.querySelector('.card-actions');
  if (status === 'matched') {{
    div.innerHTML =
      '<button class="action-btn action-ignore" onclick="setJobStatus(this,\\'ignored\\')">Ignore</button>' +
      '<button class="action-btn action-applied" onclick="setJobStatus(this,\\'applied\\')">&#10003; Applied</button>';
  }} else {{
    div.innerHTML =
      '<button class="action-btn action-match" onclick="setJobStatus(this,\\'matched\\')">&#8629; Back to Matched</button>';
  }}
}}

// ── Triage: call API then move card ──
async function setJobStatus(btn, newStatus) {{
  const card = btn.closest('.job-card');
  const url  = card.dataset.url;
  try {{
    const resp = await fetch('/api/status', {{
      method:  'POST',
      headers: {{'Content-Type': 'application/json'}},
      body:    JSON.stringify({{url, status: newStatus}}),
    }});
    if (!resp.ok) throw new Error('Server returned ' + resp.status);
  }} catch(e) {{
    alert('Status update failed — is server.py running?\n(' + e.message + ')');
    return;
  }}
  const listId = newStatus === 'matched'  ? 'job-list'
               : newStatus === 'ignored'  ? 'ignored-list'
               :                            'applied-list';
  document.getElementById(listId).prepend(card);
  renderTriageBtns(card, newStatus);
  updateTabCounts();
}}

// ── Description toggle ──
function toggleDesc(btn, id) {{
  const div = document.getElementById('desc-more-' + id);
  if (div.hidden) {{
    div.hidden = false;
    btn.textContent = '▾ Description';
  }} else {{
    div.hidden = true;
    btn.textContent = '▸ Description';
  }}
}}

// ── Companies filter ──
function filterCompanies() {{
  const q   = document.getElementById('co-search').value.toLowerCase();
  const typ = document.getElementById('co-type-filter').value.toLowerCase();
  const rows = document.querySelectorAll('#co-tbody .co-row');
  let visible = 0;
  rows.forEach(row => {{
    const nameMatch = !q   || (row.dataset.name || '').includes(q);
    const typeMatch = !typ || (row.dataset.type || '').includes(typ);
    const show = nameMatch && typeMatch;
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  document.getElementById('co-count').textContent =
    visible + ' compan' + (visible === 1 ? 'y' : 'ies') + ' monitored';
}}

// ── Sort ──
let currentSort = 'date';

function setSort(s) {{
  currentSort = s;
  document.getElementById('sort-date-btn').classList.toggle('active', s === 'date');
  document.getElementById('sort-score-btn').classList.toggle('active', s === 'score');
  localStorage.setItem('jd_sort', s);
  applyFilters();
}}

// ── Jobs filter + sort ──
function applyFilters() {{
  const text    = document.getElementById('filter-text').value.toLowerCase();
  const company = document.getElementById('filter-company').value;
  const score   = document.getElementById('filter-score').value;
  const loc     = document.getElementById('filter-location').value;

  // Persist filter state
  localStorage.setItem('jd_text',     document.getElementById('filter-text').value);
  localStorage.setItem('jd_company',  company);
  localStorage.setItem('jd_score',    score);
  localStorage.setItem('jd_location', loc);

  const list  = document.getElementById('job-list');
  const cards = Array.from(list.querySelectorAll('.job-card'));

  // Sort cards in DOM before applying visibility
  cards.sort((a, b) => {{
    if (currentSort === 'score') {{
      const sd = parseInt(b.dataset.score, 10) - parseInt(a.dataset.score, 10);
      if (sd !== 0) return sd;
      return (b.dataset.date || '').localeCompare(a.dataset.date || '');
    }} else {{
      const dd = (b.dataset.date || '').localeCompare(a.dataset.date || '');
      if (dd !== 0) return dd;
      return parseInt(b.dataset.score, 10) - parseInt(a.dataset.score, 10);
    }}
  }});
  cards.forEach(card => list.appendChild(card));

  // Apply visibility filters
  let visible = 0;
  cards.forEach(card => {{
    const cardText    = card.dataset.text || '';
    const cardCompany = card.dataset.company || '';
    const cardScore   = parseInt(card.dataset.score, 10);
    const cardLoc     = card.dataset.location || '';

    const matchText    = !text    || cardText.includes(text);
    const matchCompany = !company || cardCompany === company;
    const matchScore   = !score   || cardScore >= parseInt(score, 10);
    const matchLoc     = !loc     || cardLoc === loc;

    if (matchText && matchCompany && matchScore && matchLoc) {{
      card.style.display = '';
      visible++;
    }} else {{
      card.style.display = 'none';
    }}
  }});

  document.getElementById('results-count').textContent =
    visible + ' job' + (visible === 1 ? '' : 's') + ' shown';
}}

// ── Init: restore persisted state then render ──
(function init() {{
  const txt = localStorage.getItem('jd_text');
  const co  = localStorage.getItem('jd_company');
  const sc  = localStorage.getItem('jd_score');
  const lo  = localStorage.getItem('jd_location');
  const so  = localStorage.getItem('jd_sort');
  if (txt) document.getElementById('filter-text').value = txt;
  if (co)  document.getElementById('filter-company').value = co;
  if (sc)  document.getElementById('filter-score').value = sc;
  if (lo)  document.getElementById('filter-location').value = lo;
  if (so) {{
    currentSort = so;
    document.getElementById('sort-date-btn').classList.toggle('active', so === 'date');
    document.getElementById('sort-score-btn').classList.toggle('active', so === 'score');
  }}
  applyFilters();
}})();
</script>

</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"  Exported HTML dashboard → {path}")
