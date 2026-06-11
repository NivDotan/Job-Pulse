import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from standardization import (
    canonicalize_link,
    clean_description,
    extract_skill_taxonomy,
    normalize_junior_label,
    parse_requirements,
    standardize_company,
    standardize_job_record,
    standardize_location,
    standardize_title,
)


def test_company_artifacts_are_standardized():
    company = standardize_company("/embed/job_board?for=ai21")
    assert company["display"] == "AI21"
    assert company["normalized"] == "ai21"


def test_title_extracts_seniority_and_family():
    title = standardize_title("Junior Data Analyst - BI")
    assert title["seniority"] == "Entry"
    assert title["title_family"] == "Data"


def test_location_detects_country_and_workplace():
    location = standardize_location("Remote (Israel) - Tel Aviv")
    assert location["country"] == "Israel"
    assert location["workplace"] == "Remote"

    usa = standardize_location("USA - Sunnyvale, CA")
    assert usa["country"] == "United States"


def test_requirements_parse_json_and_text():
    assert parse_requirements('["Python", " SQL ", "Python"]') == ["Python", "SQL"]
    assert parse_requirements("Python; SQL\n- Tableau") == ["Python", "SQL", "Tableau"]
    assert parse_requirements('["2+ years of Python experience"]') == ["2+ years of Python experience"]


def test_requirement_taxonomy_extracts_real_categories():
    taxonomy = extract_skill_taxonomy([
        "Strong proficiency in Python and SQL",
        "Experience deploying production-grade models on AWS and Kubernetes",
        "Power BI dashboards and statistics",
        "Excellent communication, customer-facing work, and problem solving",
    ])
    assert taxonomy["programming_languages"]["Python"] == 1
    assert taxonomy["programming_languages"]["SQL"] == 1
    assert taxonomy["cloud_infrastructure"]["AWS"] == 1
    assert taxonomy["cloud_infrastructure"]["Kubernetes"] == 1
    assert taxonomy["data_analytics"]["Power BI"] == 1
    assert "business_soft_skills" not in taxonomy


def test_description_cleanup_strips_html_entities():
    desc = clean_description("<p>Build dashboards&nbsp;with SQL.</p>")
    assert desc["text"] == "Build dashboards with SQL."
    assert "Build dashboards" in desc["preview"]


def test_junior_label_normalization():
    assert normalize_junior_label("True")["label"] == "Junior"
    assert normalize_junior_label(False)["label"] == "Not Junior"
    assert normalize_junior_label("Unclear")["is_junior_suitable"] is True


def test_link_canonicalization_removes_tracking_and_fragments():
    link = canonicalize_link("HTTPS://Example.COM/job/123/?utm_source=x&gh_src=y#apply")
    assert link["canonical"] == "https://example.com/job/123"


def test_standardized_job_record_keeps_raw_values():
    row = {
        "Company": "monday",
        "JobDesc": "Graduate Software Engineer",
        "city": "Tel Aviv, Israel",
        "Link": "https://example.com/job?utm_campaign=test",
        "reqs": "Python; Git",
        "desc": "<b>Great role</b>",
        "suitable_for_junior": "True",
    }
    job = standardize_job_record(row, "test")
    assert job["company"]["display"] == "Monday"
    assert job["title"]["seniority"] == "Entry"
    assert job["location"]["country"] == "Israel"
    assert job["requirements"] == ["Python", "Git"]
    assert job["job_type"] in {"Backend Engineering", "Data / BI", "Other"}
    assert "programming_languages" in job["skill_taxonomy"]
    assert job["experience"]["level"] == "Unspecified"
    assert job["raw"] == row
