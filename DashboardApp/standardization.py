"""
Read-time standardization helpers for dashboard analytics.

These functions keep raw Supabase rows unchanged while giving the analytics
layer stable fields for grouping, filtering, and display.
"""
import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_KNOWN_COMPANY_DISPLAY = {
    "ai21": "AI21",
    "ptc": "PTC",
    "buyme": "BUYME",
    "tlv": "TLV",
}

_ATS_DISPLAY = {
    "green": "Greenhouse",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "comeet": "Comeet",
    "smart": "SmartRecruiters",
    "smartrecruiters": "SmartRecruiters",
    "bamboohr": "BambooHR",
    "ashby": "Ashby",
    "workday": "Workday",
    "icims": "iCIMS",
    "jobvite": "Jobvite",
    "taleo": "Taleo",
}

_ISRAEL_CITIES = {
    "tel aviv", "tel-aviv", "tlv", "jerusalem", "haifa", "herzliya",
    "ramat gan", "petah tikva", "petah tiqva", "netanya", "kfar saba",
    "holon", "rehovot", "rechovot", "beer sheva", "beersheba", "ashdod",
    "or yehuda", "or-yehuda", "yokneam", "raanana", "ra'anana",
    "hod hasharon", "givatayim", "bnei brak", "hadera", "modiin",
}

_USA_TERMS = {
    "united states", "usa", "u.s.", "u.s.a", "us,", "california", "new york",
    "texas", "washington", "oregon", "massachusetts", "illinois", "georgia",
    "florida", "colorado", "arizona", "virginia", "north carolina",
    "pennsylvania", "sunnyvale", "santa clara", "san jose", "san francisco",
    "seattle", "austin", "boston", "chicago", "atlanta", "remote - us",
}

_NOISE_QUERY_PARAMS = {
    "gh_src", "source", "utm_source", "utm_medium", "utm_campaign",
    "utm_term", "utm_content", "ref", "referrer",
}

_REQ_STOPWORDS = {
    "and", "the", "for", "with", "you", "your", "our", "are", "will",
    "from", "that", "this", "have", "has", "job", "work", "team", "years",
    "year", "experience", "required", "preferred", "ability", "skills",
    "skill", "using", "must", "plus", "knowledge", "strong", "good",
    "etc", "candidate", "role", "position", "including", "within",
}

SKILL_TAXONOMY = {
    "programming_languages": {
        "Python": ["python"],
        "SQL": ["sql"],
        "Java": ["java"],
        "JavaScript": ["javascript", "js"],
        "TypeScript": ["typescript"],
        "C++": ["c++", "cpp"],
        "C#": ["c#"],
        "Go": ["go", "golang"],
        "Bash": ["bash", "shell scripting"],
        "PowerShell": ["powershell"],
        "Ruby": ["ruby"],
        "PHP": ["php"],
        "Kotlin": ["kotlin"],
        "Swift": ["swift"],
        "Scala": ["scala"],
        "Perl": ["perl"],
        "TCL": ["tcl"],
    },
    "cloud_infrastructure": {
        "AWS": ["aws", "amazon web services"],
        "Azure": ["azure"],
        "GCP": ["gcp", "google cloud"],
        "Kubernetes": ["kubernetes", "k8s"],
        "Docker": ["docker"],
        "Terraform": ["terraform"],
        "Helm": ["helm"],
        "Linux": ["linux"],
        "CI/CD": ["ci/cd", "cicd", "continuous integration", "continuous deployment"],
        "GitHub Actions": ["github actions"],
        "GitLab": ["gitlab"],
        "Jenkins": ["jenkins"],
        "Microservices": ["microservices"],
        "Serverless": ["serverless"],
        "Prometheus": ["prometheus"],
        "Grafana": ["grafana"],
        "DevOps": ["devops"],
    },
    "data_analytics": {
        "Excel": ["excel"],
        "Tableau": ["tableau"],
        "Power BI": ["power bi", "powerbi"],
        "Looker": ["looker"],
        "Snowflake": ["snowflake"],
        "BigQuery": ["bigquery"],
        "ETL": ["etl"],
        "dbt": ["dbt"],
        "Airflow": ["airflow"],
        "Spark": ["spark"],
        "Pandas": ["pandas"],
        "NumPy": ["numpy"],
        "Statistics": ["statistics", "statistical"],
        "Data Visualization": ["data visualization", "dashboards", "dashboard"],
        "Analytics": ["analytics"],
    },
    "ai_ml": {
        "Machine Learning": ["machine learning", "ai/ml"],
        "Deep Learning": ["deep learning"],
        "LLM": ["llm", "llms", "large language model"],
        "GenAI": ["genai", "generative ai"],
        "RAG": ["rag", "retrieval augmented"],
        "NLP": ["nlp", "natural language processing"],
        "PyTorch": ["pytorch"],
        "TensorFlow": ["tensorflow"],
        "Computer Vision": ["computer vision"],
        "Semantic Search": ["semantic search"],
    },
    "frontend_backend": {
        "React": ["react"],
        "Angular": ["angular"],
        "Vue": ["vue"],
        "Node.js": ["node.js", "nodejs"],
        "Django": ["django"],
        "Flask": ["flask"],
        "Spring": ["spring"],
        "REST APIs": ["rest api", "restful", "rest"],
        "GraphQL": ["graphql"],
        "HTML": ["html"],
        "CSS": ["css"],
    },
    "security": {
        "Security": ["security"],
        "Cybersecurity": ["cyber", "cybersecurity"],
        "SIEM": ["siem"],
        "SOC": ["soc"],
        "Vulnerability": ["vulnerability", "vulnerabilities"],
        "Penetration Testing": ["penetration"],
        "IAM": ["iam", "identity and access"],
        "OAuth": ["oauth"],
        "Zero Trust": ["zero trust"],
    },
}


def clean_text(value):
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _fix_mojibake(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fix_mojibake(text):
    replacements = {
        "â": "-",
        "â": "-",
        "â": "'",
        "â": "'",
        "â": '"',
        "â": '"',
        "â¢": "•",
        "ג€”": "-",
        "ג€¢": "•",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text


def _slug_text(value):
    text = clean_text(value).lower()
    text = re.sub(r"[_/|]+", " ", text)
    text = re.sub(r"[^a-z0-9+#.\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def standardize_company(value):
    raw = clean_text(value)
    text = raw
    if text.startswith("/embed/job_board?for="):
        text = text.split("=", 1)[-1]
    text = text.strip(" /")
    normalized = _slug_text(text).replace(" ", "")
    display = _KNOWN_COMPANY_DISPLAY.get(normalized)
    if not display:
        display = re.sub(r"[_\-]+", " ", text).strip()
        display = display.title() if display.islower() or display.isupper() else display
    return {
        "raw": raw,
        "display": display or "Unknown",
        "normalized": normalized or "unknown",
    }


def standardize_title(value):
    raw = clean_text(value)
    normalized = _slug_text(raw)
    title = re.sub(r"\s*[-|/]\s*", " ", raw)
    title = re.sub(r"\s+", " ", title).strip()

    seniority = "Unspecified"
    checks = [
        ("Intern", r"\b(intern|internship|student|undergraduate)\b"),
        ("Entry", r"\b(entry|graduate|new grad|junior|jr\.?)\b"),
        ("Senior", r"\b(senior|sr\.?|lead|principal|staff)\b"),
        ("Manager", r"\b(manager|head of|director)\b"),
    ]
    for label, pattern in checks:
        if re.search(pattern, normalized):
            seniority = label
            break

    family = "Other"
    families = [
        ("Data", r"\b(data|analytics|analyst|bi|business intelligence|machine learning|ml|ai)\b"),
        ("Software Engineering", r"\b(software|developer|engineer|backend|frontend|full stack|fullstack)\b"),
        ("Product", r"\b(product|pm)\b"),
        ("QA", r"\b(qa|quality|automation)\b"),
        ("DevOps", r"\b(devops|sre|platform|cloud|infrastructure)\b"),
        ("Security", r"\b(security|cyber|soc)\b"),
        ("Design", r"\b(design|ux|ui)\b"),
    ]
    for label, pattern in families:
        if re.search(pattern, normalized):
            family = label
            break

    return {
        "raw": raw,
        "display": title or "Untitled",
        "normalized": normalized,
        "title_family": family,
        "seniority": seniority,
    }


def standardize_location(value):
    raw = clean_text(value)
    normalized = _slug_text(raw)

    workplace = "Onsite"
    if "remote" in normalized:
        workplace = "Remote"
    elif "hybrid" in normalized:
        workplace = "Hybrid"

    country = "Other"
    if "israel" in normalized or any(city in normalized for city in _ISRAEL_CITIES):
        country = "Israel"
    elif any(term in normalized for term in _USA_TERMS):
        country = "United States"
    elif not normalized or normalized in {"n/a", "none", "unknown"}:
        country = "Unknown"

    parts = [p.strip() for p in re.split(r"[,;/|]", raw) if p.strip()]
    city = parts[0] if parts else ""
    if country == "Israel" and normalized in {"israel", "il"}:
        city = ""
    if country == "United States" and normalized in {"united states", "usa", "u.s.", "us"}:
        city = ""

    region = country if country in {"Israel", "United States"} else "Other"
    display = raw or "Unknown"
    return {
        "raw": raw,
        "display": display,
        "city": city,
        "country": country,
        "region": region,
        "workplace": workplace,
        "normalized": normalized,
    }


def canonicalize_link(value):
    raw = clean_text(value)
    if not raw:
        return {"raw": raw, "canonical": "", "is_valid": False}
    try:
        parsed = urlsplit(raw)
        scheme = (parsed.scheme or "https").lower()
        netloc = parsed.netloc.lower()
        path = re.sub(r"/+$", "", parsed.path)
        query = urlencode(
            [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if k.lower() not in _NOISE_QUERY_PARAMS]
        )
        canonical = urlunsplit((scheme, netloc, path, query, ""))
        return {"raw": raw, "canonical": canonical, "is_valid": bool(netloc)}
    except Exception:
        return {"raw": raw, "canonical": raw, "is_valid": False}


def normalize_ats(value):
    raw = clean_text(value)
    key = _slug_text(raw).replace(" ", "")
    return {"raw": raw, "normalized": key or "unknown", "display": _ATS_DISPLAY.get(key, raw or "Unknown")}


def normalize_junior_label(value):
    raw = value
    if isinstance(value, bool):
        label = "Junior" if value else "Not Junior"
    else:
        text = clean_text(value).lower()
        if text in {"true", "junior", "yes", "1"}:
            label = "Junior"
        elif text in {"false", "senior", "not junior", "no", "0"}:
            label = "Not Junior"
        elif text in {"unclear", "unknown", "maybe"}:
            label = "Unclear"
        else:
            label = "Unknown"
    return {"raw": raw, "label": label, "is_junior_suitable": label in {"Junior", "Unclear"}}


def parse_requirements(value):
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        text = clean_text(value)
        if not text:
            return []
        items = None
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    items = parsed
            except Exception:
                items = None
        if items is None:
            items = re.split(r"\n|;|•|\u2022|-{1,2}\s+", text)
    cleaned = []
    seen = set()
    for item in items:
        text = clean_text(item)
        text = re.sub(r"^[*\-•\d.)\s]+", "", text).strip()
        if text and text.lower() not in seen:
            cleaned.append(text)
            seen.add(text.lower())
    return cleaned


def clean_description(value, max_preview=220):
    text = clean_text(value)
    text = re.sub(r"\b(apply now|equal opportunity employer|privacy notice)\b.*$", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    preview = text[:max_preview].rstrip()
    if len(text) > max_preview:
        preview += "..."
    return {"text": text, "preview": preview}


def extract_skill_terms(requirements):
    counts = {}
    for item in requirements:
        lowered = _slug_text(item)
        tokens = re.findall(r"[a-z0-9+#.]{2,}", lowered)
        for token in tokens:
            if token in _REQ_STOPWORDS:
                continue
            term = _SKILL_ALIASES.get(token)
            if not term and len(token) >= 3:
                term = token.title()
            if term:
                counts[term] = counts.get(term, 0) + 1
    return counts


def parse_requirements(value):
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        text = clean_text(value)
        if not text:
            return []
        items = None
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    items = parsed
            except Exception:
                items = None
        if items is None:
            items = re.split(r"\n|;|\u2022|-{1,2}\s+", text)
    cleaned = []
    seen = set()
    for item in items:
        text = clean_text(item)
        text = re.sub(r"^[*\-•\s]+", "", text).strip()
        text = re.sub(r"^\d+[\.)]\s+", "", text).strip()
        if text and text.lower() not in seen:
            cleaned.append(text)
            seen.add(text.lower())
    return cleaned


def _term_in_text(term, text):
    pattern = r"(?<![a-z0-9+#.])" + re.escape(term.lower()) + r"(?![a-z0-9+#.])"
    return re.search(pattern, text) is not None


def extract_skill_taxonomy(requirements, description="", title=""):
    text = f" {_slug_text(title)} {_slug_text(description)} {_slug_text(' '.join(requirements))} "
    result = {}
    for category, terms in SKILL_TAXONOMY.items():
        category_counts = {}
        for canonical, aliases in terms.items():
            count = sum(1 for alias in aliases if _term_in_text(alias, text))
            if count:
                category_counts[canonical] = count
        result[category] = category_counts
    return result


def extract_skill_terms(requirements, description="", title=""):
    counts = {}
    taxonomy = extract_skill_taxonomy(requirements, description=description, title=title)
    for category_counts in taxonomy.values():
        for term, count in category_counts.items():
            counts[term] = counts.get(term, 0) + count
    return counts


def infer_job_type(title, description="", requirements=None):
    requirements = requirements or []
    text = f" {_slug_text(title)} {_slug_text(description)} {_slug_text(' '.join(requirements))} "
    checks = [
        ("AI / ML", ["machine learning", "deep learning", " llm ", " genai ", "ai/ml", "pytorch", "tensorflow", "rag"]),
        ("Data / BI", ["data analyst", "data scientist", "analytics", "business intelligence", " bi ", "sql", "dashboard"]),
        ("Full Stack", ["full stack", "fullstack"]),
        ("Frontend Engineering", ["frontend", "front end", "react", "vue", "angular", "javascript", "typescript"]),
        ("Backend Engineering", ["backend", "server-side", "microservices", "api", "java", "python", " go "]),
        ("DevOps / SRE", ["devops", "sre", "site reliability", "kubernetes", "terraform", "ci/cd", "cloud"]),
        ("Security", ["security", "cyber", "soc", "vulnerability", "penetration"]),
        ("QA / Automation", ["qa", "quality assurance", "automation engineer", "test automation"]),
        ("Product", ["product manager", "product owner", "product management"]),
        ("Hardware / VLSI", ["vlsi", "asic", "fpga", "verification", "verilog", "hardware"]),
        ("Customer / Pre-Sales", ["pre-sales", "presales", "solution engineer", "customer success", "account executive"]),
        ("IT / Systems", ["system administrator", " it ", "helpdesk", "network"]),
    ]
    for label, aliases in checks:
        if any(alias in text for alias in aliases):
            return label
    return "Other"


def extract_experience_years(requirements, title="", description=""):
    text = " ".join([title, description, " ".join(requirements)])
    years = []
    for match in re.finditer(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?years?", text, flags=re.I):
        try:
            years.append(int(match.group(1)))
        except Exception:
            pass
    if not years:
        return {"min_years": None, "level": "Unspecified"}
    min_years = min(years)
    if min_years <= 2:
        level = "Entry"
    elif min_years <= 5:
        level = "Mid"
    else:
        level = "Senior"
    return {"min_years": min_years, "level": level}


def extract_education(requirements):
    text = _slug_text(" ".join(requirements))
    levels = []
    if "phd" in text or "ph.d" in text:
        levels.append("PhD")
    if "master" in text or "msc" in text or "m.sc" in text:
        levels.append("Master")
    if "bachelor" in text or "bsc" in text or "b.sc" in text:
        levels.append("Bachelor")
    return levels or ["Unspecified"]


def normalize_timestamp(value):
    raw = clean_text(value)
    if not raw:
        return {"raw": raw, "iso": "", "date": ""}
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        iso = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return {"raw": raw, "iso": iso, "date": iso[:10]}
    except Exception:
        return {"raw": raw, "iso": raw, "date": raw[:10] if len(raw) >= 10 else ""}


def normalize_status(value):
    raw = clean_text(value)
    text = raw.lower()
    if text in {"completed", "success", "ok"}:
        label = "Success"
    elif text in {"failed", "error"}:
        label = "Failed"
    elif text in {"warning", "partial"}:
        label = "Warning"
    elif text in {"running", "in_progress"}:
        label = "Running"
    else:
        label = "Unknown" if not text else raw.title()
    return {"raw": raw, "label": label}


def standardize_job_record(row, source="scrapers_data"):
    company = standardize_company(row.get("company") or row.get("Company"))
    title = standardize_title(row.get("job_name") or row.get("title") or row.get("JobDesc"))
    location = standardize_location(row.get("city") or row.get("location"))
    link = canonicalize_link(row.get("link") or row.get("Link"))
    created = normalize_timestamp(row.get("created_at") or row.get("sent_at") or row.get("email_date"))
    requirements = parse_requirements(row.get("reqs"))
    description = clean_description(row.get("desc"))
    junior = normalize_junior_label(row.get("suitable_for_junior") or row.get("is_filtered"))
    taxonomy = extract_skill_taxonomy(requirements, description=description["text"], title=title["display"])

    return {
        "source": source,
        "company": company,
        "title": title,
        "location": location,
        "link": link,
        "created_at": created,
        "requirements": requirements,
        "description": description,
        "junior": junior,
        "skills": extract_skill_terms(requirements, description=description["text"], title=title["display"]),
        "skill_taxonomy": taxonomy,
        "job_type": infer_job_type(title["display"], description=description["text"], requirements=requirements),
        "experience": extract_experience_years(requirements, title=title["display"], description=description["text"]),
        "education": extract_education(requirements),
        "raw": row,
    }
