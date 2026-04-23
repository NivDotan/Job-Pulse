import pytest
from unittest.mock import patch, MagicMock

SAMPLE_JOBS_RESPONSE = {
    "jobPostings": [
        {
            "title": "Software Engineer",
            "locationsText": "Tel Aviv, Israel",
            "externalPath": "/job/123456/software-engineer",
        }
    ]
}

SAMPLE_FACETS_RESPONSE = {
    "facets": [
        {
            "facetParameter": "locationMainGroup",
            "values": [
                {
                    "facetParameter": "locationHierarchy1",
                    "descriptor": "Locations",
                    "values": [
                        {"descriptor": "Israel", "id": "israel-id", "count": 10},
                        {"descriptor": "United States", "id": "usa-id", "count": 20},
                        {"descriptor": "Germany", "id": "germany-id", "count": 5},
                    ],
                }
            ],
        }
    ],
}


# ── scrape_workday_jobs_api unit tests ───────────────────────────────────────

def _mock_post(url, **kwargs):
    mock = MagicMock()
    mock.raise_for_status = lambda: None
    mock.json.return_value = SAMPLE_JOBS_RESPONSE
    return mock


def _mock_response(data):
    mock = MagicMock()
    mock.raise_for_status = lambda: None
    mock.json.return_value = data
    return mock


def test_workday_api_url_uses_site_from_instance():
    """API URL must use the path segment from workday_instance, not hardcoded 'careers'."""
    from job_scrapers import scrape_workday_jobs_api

    with patch("requests.post", side_effect=_mock_post) as mock_post:
        jobs = scrape_workday_jobs_api(
            "checkpoint",
            workday_instance="https://checkpoint.wd1.myworkdayjobs.com/External",
        )

    called_url = mock_post.call_args[0][0]
    assert "/External/jobs" in called_url, f"Expected /External/jobs in URL, got: {called_url}"
    assert "/careers/jobs" not in called_url, "Should not hardcode /careers/"
    assert len(jobs) == 1


def test_workday_job_link_uses_site_from_instance():
    """Job links must use the site path from workday_instance, not hardcoded '/careers'."""
    from job_scrapers import scrape_workday_jobs_api

    with patch("requests.post", side_effect=_mock_post):
        jobs = scrape_workday_jobs_api(
            "checkpoint",
            workday_instance="https://checkpoint.wd1.myworkdayjobs.com/External",
        )

    assert jobs[0]["link"].startswith("https://checkpoint.wd1.myworkdayjobs.com/External/")
    assert "/careers/" not in jobs[0]["link"]


def test_workday_fallback_without_instance():
    """Without workday_instance, builds URL from company name with /careers fallback."""
    from job_scrapers import scrape_workday_jobs_api

    with patch("requests.post", side_effect=_mock_post) as mock_post:
        jobs = scrape_workday_jobs_api("acme")

    called_url = mock_post.call_args[0][0]
    assert "acme.wd5.myworkdayjobs.com" in called_url
    assert "/careers/jobs" in called_url
    assert len(jobs) == 1


def test_workday_uses_supported_page_size():
    """Workday rejects oversized page limits, so requests must use 20."""
    from job_scrapers import scrape_workday_jobs_api

    with patch("requests.post", side_effect=_mock_post) as mock_post:
        scrape_workday_jobs_api(
            "checkpoint",
            workday_instance="https://checkpoint.wd1.myworkdayjobs.com/External",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert payload["limit"] == 20


def test_workday_applies_israel_and_usa_country_facets():
    """Workday should filter by country before pagination to avoid missing relevant jobs."""
    from job_scrapers import scrape_workday_jobs_api

    jobs_response = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Software Engineer",
                "locationsText": "2 Locations",
                "externalPath": "/job/123456/software-engineer",
            }
        ],
    }

    with patch(
        "requests.post",
        side_effect=[
            _mock_response(SAMPLE_FACETS_RESPONSE),
            _mock_response(jobs_response),
        ],
    ) as mock_post:
        jobs = scrape_workday_jobs_api(
            "checkpoint",
            workday_instance="https://checkpoint.wd1.myworkdayjobs.com/External",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert payload["appliedFacets"] == {"locationHierarchy1": ["israel-id", "usa-id"]}
    assert jobs[0]["location"] == "Israel, United States (2 Locations)"


def test_workday_applies_site_location_facets_when_country_facet_missing():
    """Some tenants expose only site-level location facets instead of country facets."""
    from job_scrapers import scrape_workday_jobs_api

    facets_response = {
        "facets": [
            {
                "facetParameter": "locationMainGroup",
                "values": [
                    {
                        "facetParameter": "locations",
                        "descriptor": "Locations",
                        "values": [
                            {"descriptor": "Berlin, Germany", "id": "berlin-id", "count": 1},
                            {"descriptor": "All, California, United States of America", "id": "us-id", "count": 2},
                            {"descriptor": "Tel Aviv, Israel", "id": "israel-id", "count": 3},
                        ],
                    }
                ],
            }
        ],
    }

    with patch(
        "requests.post",
        side_effect=[
            _mock_response(facets_response),
            _mock_response(SAMPLE_JOBS_RESPONSE),
        ],
    ) as mock_post:
        scrape_workday_jobs_api(
            "checkpoint",
            workday_instance="https://checkpoint.wd1.myworkdayjobs.com/External",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert payload["appliedFacets"] == {"locations": ["us-id", "israel-id"]}


def test_workday_different_site_names():
    """Works for any site path: Jobs, Careers, en-US, etc."""
    from job_scrapers import scrape_workday_jobs_api

    for site in ["Jobs", "Careers", "en-US"]:
        with patch("requests.post", side_effect=_mock_post) as mock_post:
            scrape_workday_jobs_api(
                "somecompany",
                workday_instance=f"https://somecompany.wd3.myworkdayjobs.com/{site}",
            )
        called_url = mock_post.call_args[0][0]
        assert f"/{site}/jobs" in called_url, f"Failed for site={site}"


# ── CleanScript routing test ─────────────────────────────────────────────────

def test_cleanscript_passes_workday_instance_to_scraper():
    """scrapers() must forward the url to scrape_workday_jobs_api as workday_instance."""
    from CleanScript import JobScraper

    scraper = JobScraper([])
    instance_url = "https://checkpoint.wd1.myworkdayjobs.com/External"

    with patch("CleanScript.scrape_workday_jobs_api", return_value=[]) as mock_wd:
        scraper.scrapers(instance_url, "workday", "checkpoint")

    mock_wd.assert_called_once_with("checkpoint", workday_instance=instance_url)
