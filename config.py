# ---------------------------------------------------------------------------
# Location filters — case-insensitive substring match against job.location
# ---------------------------------------------------------------------------
LOCATION_FILTERS: list[str] = [
    # Broad Swiss filter — Phase 1.5 keeps any job in Switzerland.
    # Scoring then applies geographic preference (+2 Romandie, 0 other CH, -2 outside CH).
    "switzerland",
    "schweiz",      # German
    "suisse",       # French
    "svizzera",     # Italian
    # City / region terms as fallbacks for boards that omit the country name
    "geneva",
    "genève",
    "geneve",
    "lausanne",
    "vaud",
    "zurich",
    "zürich",
    "basel",
    "bern",
    "zug",
    "romand",       # catches "Romandie", "Romand" etc.
]

# ---------------------------------------------------------------------------
# Title filters — case-insensitive substring match against job.title
# ---------------------------------------------------------------------------
TITLE_FILTERS: list[str] = [
    "translational medicine",
    "precision medicine",
    "biomarker science",
    "biomarker",
    "data science",
    "scientific diligence",
    "search & evaluation",
    "search and evaluation",
    "business development",
    "clinical research scientist",
    "clinical scientist",
    "staff scientist",
    "scientist",
    "flow cytometry",
    # Medical Affairs / MSL
    "medical affairs",
    "medical science liaison",
    "medical advisor",
    # Medical Affairs / MSL
    "medical monitor",
    # Regulatory
    "regulatory affairs",
    "regulatory",
    # Business development & licensing
    "business development manager",
    "alliance management",
    "licensing",
    # Clinical & translational
    "clinical development",
    "translational scientist",
    # Evidence & outcomes
    "evidence generation",
    "health economics",
    "heor",
    # Strategy & pipeline
    "portfolio",
    "product strategy",
    "clinical product manager",
    # Field & advisory
    "field application scientist",
    "scientific advisor",
    # Preclinical & biology
    "preclinical development",
    "preclinical strategy",
    "immuno-oncology",
    "spatial biology",
    "assay development",
    "computational biology",
    "bioinformatics",
    # Commercial strategy
    "competitive intelligence",
    "new product planning",
    "npp",
    # Communications
    "scientific communications",
    "medical communications",
    "medical writer",
    # Implementation / professional services (relevant for life science SaaS)
    "implementation manager",
    "implementation specialist",
    # Research scientist variants
    "investigator",
    # Consulting
    "life sciences strategy consultant",
    "strategy consultant",
    "associate consultant",
]

# ---------------------------------------------------------------------------
# Company configurations — one dict per company
# ---------------------------------------------------------------------------
COMPANIES: list[dict] = [
    # ── Phase 2 POC ─────────────────────────────────────────────────────────
    {
        "name": "Debiopharm",
        "ats": "workable",
        "slug": "debiopharm",
    },
    # ── Phase 3: Workday group ───────────────────────────────────────────────
    {
        "name": "Labcorp",
        "ats": "workday",
        "tenant": "labcorp",
        "instance": "wd1",
        "portal": "External",
        # Only one Swiss location exists in Labcorp's facet (CHE-based country code)
        "location_facets": {"locations": ["4a6c2a97581e0100c7d9f621e1e90000"]},
    },
    {
        "name": "Bristol Myers Squibb",
        "ats": "workday",
        "tenant": "bristolmyerssquibb",   # verified — "bms" returns 404
        "instance": "wd5",                 # verified — not wd1
        "portal": "BMS",                   # verified — not "External"
        # Country-level facet covers all Swiss cantons (Neuchatel etc.)
        "location_facets": {"locationHierarchy2": ["7b0045a3289810548a41270096eb9069"]},
    },
    {
        "name": "Eli Lilly",
        "ats": "workday",
        "tenant": "lilly",
        "instance": "wd5",
        "portal": "LLY",
        # Country-level facet covers all Swiss cantons (Vernier, Remote etc.)
        "location_facets": {"locationCountry": ["187134fccb084a0ea9b4b95f23890dbe"]},
    },
    {
        "name": "Ferring Pharmaceuticals",
        "ats": "workday",
        "tenant": "ferring",
        "instance": "wd3",
        "portal": "Ferring",
        # No Swiss locations in their facet — scan all 126 jobs (cheap enough)
        "location_facets": {},
    },
    # ── Phase 4: Workday additions ───────────────────────────────────────────
    {
        "name": "Bio-Techne / Lunaphore",
        "ats": "workday",
        "tenant": "biotechne",
        "instance": "wd5",
        "portal": "Biotechne",
        # Tolochenaz (Vaud) = Lunaphore site; only Swiss location in their facet
        "location_facets": {"locations": ["2b424d5482a9100169342869ee560000"]},
    },
    # ── Phase 4: Workable additions ──────────────────────────────────────────
    {
        "name": "SOPHiA GENETICS",
        "ats": "workable",
        "slug": "sophia-genetics",
    },
    # ── Phase 4: Paylocity ───────────────────────────────────────────────────
    {
        "name": "ADC Therapeutics",
        "ats": "paylocity",
        "company_guid": "8759d8d9-b6f5-49b5-b817-f3c4f69a25ed",
        "company_slug": "ADC-Therapeutics-America-Inc",
    },
    # ── Phase 5: Greenhouse ───────────────────────────────────────────────────
    {
        "name": "Isomorphic Labs",
        "ats": "greenhouse",
        "board_token": "isomorphiclabs",
    },
    # ── Phase 5: SuccessFactors ───────────────────────────────────────────────
    {
        "name": "Boehringer Ingelheim",
        "ats": "successfactors",
        "careers_url": "https://jobs.boehringer-ingelheim.com",
        # BI stores location as "Basel, Switzerland, Basel-Stadt" in the feed title.
        # Swiss field roles (MSL, KAM) list Basel as legal entity but cover all territories.
        # Use "switzerland" to catch all Swiss postings; title filter handles relevance.
        "location_terms": ["switzerland"],
    },
    # ── Generic monitors (unstructured pages — keyword presence only) ─────────
    {
        "name": "Novigenix",
        "ats": "generic",
        "careers_url": "https://novigenix.com/career/",
        "keywords": TITLE_FILTERS,
    },
    {
        "name": "Tigen Pharma",
        "ats": "generic",
        "careers_url": "https://www.tigenpharma.com/team",
        "keywords": TITLE_FILTERS,
    },
    {
        "name": "Leman Biotech",
        "ats": "generic",
        "careers_url": "https://www.lemanbio.com/en/join-us",
        "keywords": TITLE_FILTERS,
    },
    {
        "name": "Light Chain Bioscience",
        "ats": "generic",
        "careers_url": "https://www.lightchainbio.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    {
        "name": "BioLizard",
        "ats": "generic",
        "careers_url": "https://lizard.bio/careers/",
        "keywords": TITLE_FILTERS,
    },
    {
        "name": "Signal26",
        "ats": "generic",
        "careers_url": "https://www.signal26bio.com/careers",
        "keywords": TITLE_FILTERS,
    },
    {
        "name": "chAIron SA",
        "ats": "generic",
        "careers_url": "https://chairon.io/",
        "keywords": TITLE_FILTERS,
    },
    # AMAL Therapeutics was acquired by Boehringer Ingelheim in 2021 and no
    # longer operates as an independent entity.  Their jobs are now covered by
    # the Boehringer Ingelheim SuccessFactors scraper above.
    # {
    #     "name": "AMAL Therapeutics",
    #     "ats": "generic",
    #     "careers_url": "https://www.amaltherapeutics.com/careers",
    # },
    # ── Phase 6: Large pharma — Workday ──────────────────────────────────────
    {
        "name": "Roche",
        "ats": "workday",
        "tenant": "roche",
        "instance": "wd3",
        "portal": "roche-ext",
        "location_facets": {},
        # Listings use "Basel" / "Kaiseraugst" without "Switzerland" in the text.
        "search_fallback_terms": ["Basel", "Kaiseraugst"],
    },
    {
        "name": "Novartis",
        "ats": "workday",
        "tenant": "novartis",
        "instance": "wd3",
        "portal": "Novartis_Careers",
        "location_facets": {},
        # Listings use "Basel" / "Stein" without "Switzerland" in the text.
        "search_fallback_terms": ["Basel", "Stein"],
    },
    {
        "name": "Sanofi",
        "ats": "workday",
        "tenant": "sanofi",
        "instance": "wd3",
        "portal": "SanofiCareers",
        # No verified Swiss facet ID — scan all, Phase 1.5 pre-filter handles triage.
        "location_facets": {},
    },
    {
        "name": "Abbott",
        "ats": "workday",
        "tenant": "abbott",
        "instance": "wd5",
        "portal": "abbottcareers",
        # No verified Swiss facet ID — scan all, Phase 1.5 pre-filter handles triage.
        "location_facets": {},
    },
    # ── Phase 6: Large pharma — SuccessFactors ───────────────────────────────
    {
        "name": "Bayer",
        "ats": "successfactors",
        "careers_url": "https://jobs.bayer.com",
        # Bayer is Basel-centric in Switzerland; broad filter + scoring handles triage
        "location_terms": ["switzerland"],
    },
    # ── Phase 6: Greenhouse ──────────────────────────────────────────────────
    {
        "name": "Benchling",
        "ats": "ashby",
        "slug": "benchling",
    },
    # ── Phase 6: SmartRecruiters API ─────────────────────────────────────────
    # AbbVie (Cham) — SmartRecruiters public API, country=ch filter
    {
        "name": "AbbVie",
        "ats": "smartrecruiters",
        "company_id": "AbbVie",
    },
    # Galapagos — migrated from Recruitee to workatgalapagos.com
    {
        "name": "Galapagos",
        "ats": "generic",
        "careers_url": "https://www.workatgalapagos.com/join-us",
        "keywords": TITLE_FILTERS,
    },
    # Monte Rosa Therapeutics — migrated from iCIMS to Workable
    {
        "name": "Monte Rosa Therapeutics",
        "ats": "workable",
        "slug": "monte-rosa-therapeutics",
        "location_terms": LOCATION_FILTERS,
        "title_terms": TITLE_FILTERS,
    },
    # Ridgeline Discovery uses Freshteam — no structured scraper.
    {
        "name": "Ridgeline Discovery",
        "ats": "generic",
        "careers_url": "https://careers.ridgelinediscovery.com/jobs",
        "keywords": TITLE_FILTERS,
    },
    # ── Phase 7: Large pharma — Workday ──────────────────────────────────────
    {
        "name": "Pfizer",
        "ats": "workday",
        "tenant": "pfizer",
        "instance": "wd1",
        "portal": "PfizerCareers",
        "location_facets": {},
    },
    {
        "name": "GSK",
        "ats": "workday",
        "tenant": "gsk",
        "instance": "wd5",
        "portal": "GSKCareers",
        "location_facets": {},
    },
    {
        "name": "AstraZeneca",
        "ats": "workday",
        "tenant": "astrazeneca",
        "instance": "wd3",
        "portal": "Careers",
        "location_facets": {},
    },
    {
        "name": "Amgen",
        "ats": "workday",
        "tenant": "amgen",
        "instance": "wd1",
        "portal": "Careers",
        "location_facets": {},
    },
    {
        "name": "Gilead Sciences",
        "ats": "workday",
        "tenant": "gilead",
        "instance": "wd1",
        "portal": "gileadcareers",
        "location_facets": {},
    },
    {
        "name": "Moderna",
        "ats": "workday",
        "tenant": "modernatx",
        "instance": "wd1",
        "portal": "M_tx",
        "location_facets": {},
    },
    {
        "name": "Takeda",
        "ats": "workday",
        "tenant": "takeda",
        "instance": "wd3",
        "portal": "External",
        "location_facets": {},
        # Swiss HQ is Glattpark (Opfikon) near Zurich; listings use "Zurich" or "Zug".
        "search_fallback_terms": ["Zurich", "Zug", "Glattpark"],
    },
    {
        "name": "BeiGene",
        "ats": "workday",
        "tenant": "beigene",
        "instance": "wd5",
        "portal": "BeiGene",
        "location_facets": {},
    },
    {
        # MSD = Merck Sharp & Dohme (US Merck) — distinct from Merck Group (Germany)
        "name": "MSD",
        "ats": "workday",
        "tenant": "msd",
        "instance": "wd5",
        "portal": "SearchJobs",
        "location_facets": {},
    },
    {
        "name": "Vertex Pharmaceuticals",
        "ats": "workday",
        "tenant": "vrtx",
        "instance": "wd501",
        "portal": "Vertex_Careers",
        "location_facets": {},
    },
    # ── Phase 7: CDMO / contract mfg — Workday ───────────────────────────────
    {
        "name": "Lonza",
        "ats": "workday",
        "tenant": "lonza",
        "instance": "wd3",
        "portal": "Lonza_Careers",
        "location_facets": {},
        # Major Swiss sites: Basel (HQ), Visp (manufacturing), Stein (biologics).
        "search_fallback_terms": ["Basel", "Visp", "Stein"],
    },
    {
        # CSL_External covers both CSL Behring and CSL Vifor (post-2022 acquisition)
        "name": "CSL Behring / Vifor",
        "ats": "workday",
        "tenant": "csl",
        "instance": "wd1",
        "portal": "CSL_External",
        "location_facets": {},
        # CSL Behring: Bern; Vifor: Villars-sur-Glâne (FR), St. Gallen, Romont.
        "search_fallback_terms": ["Bern", "Villars-sur-Gl", "St. Gallen", "Romont"],
    },
    # ── Phase 7: Medical devices / ophthalmology / dermatology — Workday ─────
    {
        "name": "Alcon",
        "ats": "workday",
        "tenant": "alcon",
        "instance": "wd5",
        "portal": "careers_alcon",
        "location_facets": {},
        # EMEA HQ in Geneva; operations in Hünenberg (Zug).
        "search_fallback_terms": ["Geneva", "Hünenberg", "Zurich"],
    },
    {
        "name": "Galderma",
        "ats": "workday",
        "tenant": "galderma",
        "instance": "wd3",
        "portal": "External",
        "location_facets": {},
        # Global HQ in Zug; R&D in La Tour-de-Peilz (near Montreux, Vaud).
        "search_fallback_terms": ["Zug", "La Tour-de-Peilz", "Lausanne"],
    },
    # ── Phase 7: CROs — Workday ───────────────────────────────────────────────
    {
        "name": "IQVIA",
        "ats": "workday",
        "tenant": "iqvia",
        "instance": "wd1",
        "portal": "IQVIA",
        "location_facets": {},
    },
    {
        "name": "ICON plc",
        "ats": "workday",
        "tenant": "icon",
        "instance": "wd3",
        "portal": "broadbean_external",
        "location_facets": {},
    },
    {
        "name": "Parexel",
        "ats": "workday",
        "tenant": "parexel",
        "instance": "wd1",
        "portal": "Parexel_External_Careers",
        "location_facets": {},
    },
    {
        "name": "Syneos Health",
        "ats": "workday",
        "tenant": "syneoshealth",
        "instance": "wd12",
        "portal": "Syneos_Health_External_Site",
        "location_facets": {},
    },
    {
        # Cencora = formerly AmerisourceBergen; Workday tenant is still "myhrabc"
        "name": "Cencora",
        "ats": "workday",
        "tenant": "myhrabc",
        "instance": "wd5",
        "portal": "Global",
        "location_facets": {},
    },
    # ── Phase 7: Life science tools — Workday ─────────────────────────────────
    {
        # PPD is now part of Thermo Fisher; covered by this entry
        "name": "Thermo Fisher Scientific",
        "ats": "workday",
        "tenant": "thermofisher",
        "instance": "wd5",
        "portal": "ThermoFisherCareers",
        "location_facets": {},
    },
    {
        # Danaher portfolio includes Beckman Coulter, Cytiva, Leica, Hologic etc.
        "name": "Danaher",
        "ats": "workday",
        "tenant": "danaher",
        "instance": "wd1",
        "portal": "DanaherJobs",
        "location_facets": {},
    },
    {
        "name": "Illumina",
        "ats": "workday",
        "tenant": "illumina",
        "instance": "wd1",
        "portal": "illumina-careers",
        "location_facets": {},
    },
    {
        "name": "Qiagen",
        "ats": "workday",
        "tenant": "qiagen",
        "instance": "wd3",
        "portal": "QIAGEN",
        "location_facets": {},
    },
    {
        "name": "Agilent Technologies",
        "ats": "workday",
        "tenant": "agilent",
        "instance": "wd5",
        "portal": "Agilent_Careers",
        "location_facets": {},
    },
    # ── Phase 7: Greenhouse additions ─────────────────────────────────────────
    {
        "name": "10x Genomics",
        "ats": "greenhouse",
        "board_token": "10xgenomics",
    },
    {
        "name": "Roivant Sciences",
        "ats": "greenhouse",
        "board_token": "roivantsciences",
    },
    # ── Phase 7: Generic monitors (own ATS / unsupported platform) ────────────
    # J&J uses Phenom People (jobs.jnj.com) — no structured scraper
    {
        "name": "Johnson & Johnson / Janssen",
        "ats": "generic",
        "careers_url": "https://jobs.jnj.com/jobs",
        "keywords": TITLE_FILTERS,
    },
    # UCB uses custom career portal (careers.ucb.com) — own ATS
    {
        "name": "UCB",
        "ats": "generic",
        "careers_url": "https://careers.ucb.com/global/en",
        "keywords": TITLE_FILTERS,
    },
    # Charles River Labs uses own ATS at jobs.criver.com
    {
        "name": "Charles River Laboratories",
        "ats": "generic",
        "careers_url": "https://jobs.criver.com/job-search-results/",
        "keywords": TITLE_FILTERS,
    },
    # BD uses region-specific Workday portals; monitoring EMEA careers page
    {
        "name": "Becton Dickinson",
        "ats": "generic",
        "careers_url": "https://jobs.bd.com/en/search-jobs",
        "keywords": TITLE_FILTERS,
    },
    # Tecan uses own ATS (careers.tecan.com) — Swiss company
    {
        "name": "Tecan",
        "ats": "generic",
        "careers_url": "https://careers.tecan.com/viewalljobs/",
        "keywords": TITLE_FILTERS,
    },
    # Idorsia (Allschwil, Basel) uses own ATS (careers.idorsia.com)
    {
        "name": "Idorsia",
        "ats": "generic",
        "careers_url": "https://careers.idorsia.com/",
        "keywords": TITLE_FILTERS,
    },
    # Sobi — SmartRecruiters public API (16 CH postings confirmed)
    {
        "name": "Sobi",
        "ats": "smartrecruiters",
        "company_id": "Sobi",
    },
    # Medpace uses own ATS (not Workday)
    {
        "name": "Medpace",
        "ats": "generic",
        "careers_url": "https://www.medpace.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Molecular Partners (Zurich) — small Swiss biotech
    {
        "name": "Molecular Partners",
        "ats": "generic",
        "careers_url": "https://www.molecularpartners.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # MoonLake Immunotherapeutics (Zug) — small Swiss biotech
    {
        "name": "MoonLake Immunotherapeutics",
        "ats": "generic",
        "careers_url": "https://moonlaketx.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # dsm-firmenich (Kaiseraugst, Swiss HQ) — merged specialty ingredients co.
    {
        "name": "dsm-firmenich",
        "ats": "generic",
        "careers_url": "https://careers.dsm-firmenich.com/en/careers.html",
        "keywords": TITLE_FILTERS,
    },
    # Straumann (Basel) — Swiss dental implants company
    {
        "name": "Straumann",
        "ats": "generic",
        "careers_url": "https://www.straumann.com/group/en/home/careers.html",
        "keywords": TITLE_FILTERS,
    },
    # Nestlé Health Science (Vevey) — Drupal/Avature portal at nestlejobs.com
    {
        "name": "Nestlé Health Science",
        "ats": "nestlehealthscience",
    },
    # PerkinElmer rebranded to Revvity in 2023 (life sciences instruments)
    {
        "name": "PerkinElmer / Revvity",
        "ats": "generic",
        "careers_url": "https://www.revvity.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Merck Group = EMD / Merck KGaA (German) — distinct from MSD (US Merck)
    {
        "name": "Merck Group",
        "ats": "generic",
        "careers_url": "https://careers.merckgroup.com/global/en/",
        "keywords": TITLE_FILTERS,
    },
    # BioNTech (Mainz, DE) — may have Swiss-based openings
    {
        "name": "BioNTech",
        "ats": "generic",
        "careers_url": "https://jobs.biontech.com",
        "keywords": TITLE_FILTERS,
    },
    # Bio-Rad (Cressier, Switzerland manufacturing site)
    {
        "name": "Bio-Rad",
        "ats": "generic",
        "careers_url": "https://careers.bio-rad.com/homepage",
        "keywords": TITLE_FILTERS,
    },
    # Zeiss (major optical / imaging tools; Swiss sales & service roles)
    {
        "name": "Zeiss",
        "ats": "generic",
        "careers_url": "https://www.zeiss.com/career",
        "keywords": TITLE_FILTERS,
    },
    # Hamilton (Bonaduz, Swiss lab automation company)
    {
        "name": "Hamilton",
        "ats": "generic",
        "careers_url": "https://www.hamiltoncompany.com/about/careers",
        "keywords": TITLE_FILTERS,
    },
    # PSI CRO (Zug, Swiss CRO)
    {
        "name": "PSI CRO",
        "ats": "smartrecruiters",
        "company_id": "PSICRO",
    },
    # KCR — acquired by ICON plc August 2024, removed (ICON already in list)
    # Alira Health (Boston / Swiss healthcare consulting)
    {
        "name": "Alira Health",
        "ats": "generic",
        "careers_url": "https://alirahealth.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Servier Suisse (French pharma, Swiss commercial entity)
    {
        "name": "Servier Suisse",
        "ats": "generic",
        "careers_url": "https://www.servier.com/en/careers/",
        "keywords": TITLE_FILTERS,
    },
    # OM Pharma (Geneva — subsidiary of Vifor/CSL, immunotherapy)
    {
        "name": "OM Pharma",
        "ats": "generic",
        "careers_url": "https://careers.ompharma.com/",
        "keywords": TITLE_FILTERS,
    },
    # Octapharma (Lachen, Swiss plasma protein products company)
    {
        "name": "Octapharma",
        "ats": "generic",
        "careers_url": "https://careers.octapharma.com/",
        "keywords": TITLE_FILTERS,
    },
    # Veeva Systems (pharma SaaS; has Swiss presence)
    {
        "name": "Veeva Systems",
        "ats": "generic",
        "careers_url": "https://www.veeva.com/company/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Palantir (Zürich office — data analytics)
    {
        "name": "Palantir",
        "ats": "generic",
        "careers_url": "https://www.palantir.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # EPAM Systems (IT consulting; Swiss clients in pharma)
    {
        "name": "EPAM Systems",
        "ats": "generic",
        "careers_url": "https://www.epam.com/careers",
        "keywords": TITLE_FILTERS,
    },
    # Zühlke (Swiss tech engineering consultancy, Schlieren HQ)
    {
        "name": "Zühlke",
        "ats": "generic",
        "careers_url": "https://www.zuehlke.com/en/careers",
        "keywords": TITLE_FILTERS,
    },
    # AC Immune (EPFL Innovation Park, Lausanne — Alzheimer biomarkers)
    {
        "name": "AC Immune",
        "ats": "generic",
        "careers_url": "https://www.acimmune.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Basilea Pharmaceutica (Basel — antibiotics, antifungals)
    {
        "name": "Basilea Pharmaceutica",
        "ats": "generic",
        "careers_url": "https://www.basilea.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Araris Biotech (Basel — ADC linker technology)
    {
        "name": "Araris Biotech",
        "ats": "generic",
        "careers_url": "https://www.ararisbiotech.com/#jobs",
        "keywords": TITLE_FILTERS,
    },
    # Kuros Biosciences (Zurich — bone/tissue regeneration)
    {
        "name": "Kuros Biosciences",
        "ats": "generic",
        "careers_url": "https://kurosbio.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Release Therapeutics (Basel/Geneva — CNS; spun out of MaxiVAX in 2023)
    {
        "name": "Release Therapeutics",
        "ats": "generic",
        "careers_url": "https://www.release-tx.com/career",
        "keywords": TITLE_FILTERS,
    },
    # Numab Therapeutics (Wädenswil — multispecific antibodies)
    {
        "name": "Numab Therapeutics",
        "ats": "generic",
        "careers_url": "https://www.numab.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Oculis (Geneva — ophthalmology, now public)
    {
        "name": "Oculis",
        "ats": "generic",
        "careers_url": "https://oculis.com/join-us/",
        "keywords": TITLE_FILTERS,
    },
    # Immunos Therapeutics (Geneva — cancer immunotherapy)
    {
        "name": "Immunos Therapeutics",
        "ats": "generic",
        "careers_url": "https://www.immunostherapeutics.com/company/careers/",
        "keywords": TITLE_FILTERS,
    },
    # iOnctura (Geneva — oncology small molecules; no dedicated careers page)
    {
        "name": "iOnctura",
        "ats": "generic",
        "careers_url": "https://www.ionctura.com/contact/",
        "keywords": TITLE_FILTERS,
    },
    # GeNeuro — bankrupt January 2026, removed
    # Gnubiotics Sciences (Lausanne — gut microbiome)
    {
        "name": "Gnubiotics",
        "ats": "generic",
        "careers_url": "https://gnubiotics.com/",
        "keywords": TITLE_FILTERS,
    },
    # Hurdle Bio (rebranded from Chronomics; UK epigenomics)
    {
        "name": "Hurdle Bio",
        "ats": "generic",
        "careers_url": "https://hurdle.bio/",
        "keywords": TITLE_FILTERS,
    },
    # Cutiss (Zurich — skin bio-engineering)
    {
        "name": "Cutiss",
        "ats": "generic",
        "careers_url": "https://cutiss.swiss/career/",
        "keywords": TITLE_FILTERS,
    },
    # BC Platforms (health data management)
    {
        "name": "BC Platforms",
        "ats": "generic",
        "careers_url": "https://careers.bcplatforms.com",
        "keywords": TITLE_FILTERS,
    },
    # ABCDx (French liquid biopsy company)
    {
        "name": "ABCDx",
        "ats": "generic",
        "careers_url": "https://www.abcdx.ch/",
        "keywords": TITLE_FILTERS,
    },
    # Biognosys (Schlieren — proteomics)
    {
        "name": "Biognosys",
        "ats": "generic",
        "careers_url": "https://biognosys.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Genedata (Basel — bioinformatics software; now part of Danaher)
    {
        "name": "Genedata",
        "ats": "generic",
        "careers_url": "https://jobs.danaher.com/global/en/genedata",
        "keywords": TITLE_FILTERS,
    },
    # Insilico Medicine (AI drug discovery; EU presence)
    {
        "name": "Insilico Medicine",
        "ats": "generic",
        "careers_url": "https://insilico.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Owkin (French AI biomarker company; Swiss pharma partners) — Ashby board
    {
        "name": "Owkin",
        "ats": "ashby",
        "slug": "owkin",
    },
    # DNAnexus (genomics cloud; possible Swiss affiliate roles)
    {
        "name": "DNAnexus",
        "ats": "generic",
        "careers_url": "https://www.dnanexus.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Velsera (formerly Seven Bridges; bioinformatics platform)
    {
        "name": "Seven Bridges / Velsera",
        "ats": "generic",
        "careers_url": "https://velsera.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Tempus AI (US precision medicine; EU expansion)
    {
        "name": "Tempus",
        "ats": "generic",
        "careers_url": "https://www.tempus.com/careers/",
        "keywords": TITLE_FILTERS,
    },
    # Executive Insight (Basel/Zurich — healthcare consulting for biopharma launch)
    # Uses Breezy HR at executive-insight.breezy.hr — no structured scraper
    {
        "name": "Executive Insight",
        "ats": "generic",
        "careers_url": "https://executive-insight.breezy.hr/",
        "keywords": TITLE_FILTERS,
    },
    # IGI Innovate / Ichnos Sciences (Epalinges, Vaud — bispecific antibodies)
    # SuccessFactors hosted at career41.sapsf.com via careers.iginnovate.com
    {
        "name": "IGI Innovate / Ichnos Sciences",
        "ats": "successfactors",
        "careers_url": "https://careers.iginnovate.com",
        "location_terms": ["switzerland"],
    },
    # Nanolive (Tolochenaz, Vaud — live cell imaging; plain WordPress jobs page)
    {
        "name": "Nanolive",
        "ats": "generic",
        "careers_url": "https://www.nanolive.com/about/jobs/",
        "keywords": TITLE_FILTERS,
    },
    # ── Not yet scrapable / no public careers page ────────────────────────────
    # Note: chAIron SA uses a JS-rendered Framer site with no careers subpage;
    # GenericMonitor will scan the homepage but may miss dynamically loaded content.
    # Onward Therapeutics  — no careers page found
    # Biodelphis           — no web presence found
    # Adoram               — no careers page found (adoram.ch)
    # Abologic / Abologix  — no web presence found (may be same company, unverified)
    # Cellula Therapeutics — no web presence found
    # ── Phase 3: Phenom People ───────────────────────────────────────────────
    # {
    #     "name": "Merck Group",
    #     "ats": "phenom",
    #     "careers_url": "https://careers.emdgroup.com/global/en/",
    # },
    # Incyte — Jibe Apply (Google CTS) frontend over iCIMS; JS-rendered SPA with
    # no accessible public API endpoint.  Kept as generic keyword monitor.
    {
        "name": "Incyte",
        "ats": "generic",
        "careers_url": "https://careers.incyte.com/jobs",
        "keywords": TITLE_FILTERS,
    },
    # ── Phase 3: HAYA Therapeutics — WordPress AJAX → LinkedIn links
    {
        "name": "HAYA Therapeutics",
        "ats": "hayatx",
    },
    # ── New additions ────────────────────────────────────────────────────────
    # Dotmatics (life science informatics / ELN / LIMS software — Greenhouse)
    {
        "name": "Dotmatics",
        "ats": "greenhouse",
        "board_token": "dotmatics",
    },
    # Blueprint Medicines (precision oncology; Sanofi subsidiary — Greenhouse)
    {
        "name": "Blueprint Medicines",
        "ats": "greenhouse",
        "board_token": "blueprintmedicines",
    },
    # KBI Biopharma (CDMO; JSR Group Workday tenant)
    {
        "name": "KBI Biopharma",
        "ats": "workday",
        "tenant": "jsrglobal",
        "instance": "wd1",
        "portal": "KBI_Biopharma",
        "location_facets": {},
    },
    # Daiichi Sankyo Europe (Japanese pharma; EU operations on SuccessFactors EU)
    {
        "name": "Daiichi Sankyo",
        "ats": "successfactors",
        "careers_url": "https://jobs.daiichi-sankyo.eu/",
    },
    # Astellas Pharma (Japanese pharma; global/EMEA careers on Avature — generic)
    {
        "name": "Astellas Pharma",
        "ats": "generic",
        "careers_url": "https://astellas.avature.net/en_GB/careers",
        "keywords": TITLE_FILTERS,
    },
    # Certara (PBPK/drug development software; iCIMS ATS — generic monitor)
    {
        "name": "Certara",
        "ats": "generic",
        "careers_url": "https://careers.certara.com/jobs",
        "keywords": TITLE_FILTERS,
    },
    # CDD Vault / Collaborative Drug Discovery (drug discovery informatics — no ATS)
    {
        "name": "CDD Vault",
        "ats": "generic",
        "careers_url": "https://www.collaborativedrug.com/careers",
        "keywords": TITLE_FILTERS,
    },
    # Scailyte (ETH spin-off, single-cell AI; uses JOIN.com — generic monitor)
    {
        "name": "Scailyte",
        "ats": "generic",
        "careers_url": "https://join.com/companies/scailyte",
        "keywords": TITLE_FILTERS,
    },
    # +ND Capital (life science VC, Lausanne/Geneva — no structured careers page)
    {
        "name": "+ND Capital",
        "ats": "generic",
        "careers_url": "https://nd.capital/",
        "keywords": TITLE_FILTERS,
    },
    # Telix Pharmaceuticals (radiopharmaceuticals; posts via LinkedIn — generic monitor)
    {
        "name": "Telix Pharmaceuticals",
        "ats": "generic",
        "careers_url": "https://telixpharma.com/careers/find-a-job/",
        "keywords": TITLE_FILTERS,
    },
    # Randstad (staffing agency; Swiss life science placements)
    {
        "name": "Randstad",
        "ats": "randstad",
    },
    # Gloor & Lang (Swiss life science recruitment / staffing)
    {
        "name": "Gloor & Lang",
        "ats": "gloorlang",
    },
    # Stettler Consulting (Swiss healthcare recruiter — WordPress / YMC Smart Filter)
    {
        "name": "Stettler Consulting",
        "ats": "stettler",
    },
    # Alec Allan & Associés SA (Swiss finance/legal recruiter — HR4You XML feed)
    {
        "name": "Alec Allan",
        "ats": "alecallan",
    },
    # Hays Switzerland (global staffing — Liferay / Life Sciences specialism)
    {
        "name": "Hays Switzerland",
        "ats": "hays",
    },
    # Michael Page Switzerland (global staffing — Drupal server-rendered listings)
    {
        "name": "Michael Page Switzerland",
        "ats": "michaelpage",
    },
]

# ---------------------------------------------------------------------------
# False-positive title exclusion — hard-drop before scoring
# Whole-word / phrase matches; case-insensitive at use site.
# ---------------------------------------------------------------------------
EXCLUDE_TITLE_PATTERNS: list[str] = [
    r"\bVP\b",                # Vice President — but not "MVP", "VPM", etc.
    r"\bHead\s+of\b",
    r"\bSenior\s+Director\b",
    r"\bPrincipal\b",
    # Roles where ML is the *primary* specialty (in parens = job focus)
    # Keeps roles that merely use ML as a tool (e.g. "Drug Discovery Scientist ... using ML")
    r"\(Machine Learning\)",
]

# ---------------------------------------------------------------------------
# Scoring — positive keywords (+1 per unique match, title + description)
# ---------------------------------------------------------------------------
SCORE_POSITIVE: list[str] = [
    # Language skills
    "French",
    "bilingual",
    "francophone",
    # Qualifications
    "PhD",
    "Post-doc",
    "Postdoc",
    "postdoctoral",
    "post-doctoral",
    "MSc",
    "Master's degree",
    "Masters degree",
    "Master of Science",
    # Single-cell / genomics
    "Cancer Biology",
    "Single-cell RNA sequencing",
    "scRNA-seq",
    "10x Genomics",
    "Seurat",
    "genomics",
    "spatial transcriptomics",
    "Perturb-seq",
    "computational biology",
    "bioinformatics",
    "high-dimensional data",
    # Molecular / lab
    "molecular biology",
    "lentiviral production",
    "QuPath",
    "Life Sciences Engineering",
    "in vitro",
    "in vivo",
    "organoid",
    "CRISPR",
    "multiplex immunofluorescence",
    "spectral flow cytometry",
    # Biopharma / biomarker
    "immunology",
    "oncology",
    "proteomics",
    "assay development",
    "drug discovery",
    "translational research",
    "pharmacology",
    "drug development",
    "clinical pharmacology",
    "biomarker strategy",
    "biomarker discovery",
    "spatial biology",
    "digital pathology",
    # Translational / medical
    "translational medicine",
    "medical affairs",
    # Immuno-oncology
    "tumor microenvironment",
    "immuno-oncology",
    "innate immunity",
    "stromal biology",
    "metastasis",
    "cancer-associated fibroblasts",
    "CAFs",
    "T-cell exhaustion",
    "macrophages",
    # Preclinical
    "preclinical",
    # Strategy / intelligence
    "search and evaluation",
    "competitive intelligence",
    "scientific diligence",
    "new product planning",
]

# ---------------------------------------------------------------------------
# Scoring — negative exact phrases (-2 per unique match, description only)
# ---------------------------------------------------------------------------
SCORE_NEGATIVE_PHRASES: list[str] = [
    "clinical trial management",
    "clinical operations",
    "clinical research coordinator",
    "CRA",
]

# ---------------------------------------------------------------------------
# Scoring — negative regex patterns (-2 per match, description only)
# Catches explicit year-of-experience demands in clinical research.
# Examples matched: "3 years of clinical research experience",
#                   "5+ years clinical research experience",
#                   "minimum 2 years of direct clinical research"
# ---------------------------------------------------------------------------
SCORE_NEGATIVE_REGEX: list[str] = [
    r"\b\d+\s+years?\s+(?:of\s+)?clinical\s+research\s+experience\b",
    r"minimum\s+\d+\s+years?\s+(?:of\s+)?clinical\s+research",
]

# ---------------------------------------------------------------------------
# Geographic scoring — applied to job.location in score_job()
#
#   +2  : location matches a Romandie / primary-target area
#    0  : location matches a major Swiss hub outside the primary target
#   -2  : location matches neither list (elsewhere / unrecognised)
#
# "remote" is in the positive list — remote Swiss roles score +4 (same as Romandie).
# ---------------------------------------------------------------------------
SCORE_LOCATION_POSITIVE: list[str] = [
    "geneva", "genève",
    "lausanne",
    "vaud",
    "neuchâtel", "neuchatel",
    "fribourg",
    "valais",
    "jura",
    "romandie",
    "nyon",
    "morges",
    "rolle",
    "yverdon",
    "montreux",
    "remote",
]

SCORE_LOCATION_NEUTRAL: list[str] = [
    "basel", "bâle",
    "zurich", "zürich",
    "bern", "berne",
    "zug",
]
