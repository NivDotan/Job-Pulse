import pytest
from unittest.mock import patch, MagicMock
from CleanScript import JobScraper


@pytest.fixture
def scraper():
    return JobScraper([])


SAMPLE_JOBS = [{"title": "Junior Developer", "location": "Tel Aviv", "link": "http://example.com/job/1"}]


def test_routes_greenhouse_link_type(scraper):
    with patch("CleanScript.scrape_greenhouse_jobs_api", return_value=SAMPLE_JOBS) as mock_gh:
        listings, links = scraper.scrapers("https://boards.greenhouse.io/testco", "green", "testco")

    mock_gh.assert_called_once_with("testco")
    assert listings == SAMPLE_JOBS
    assert links == []


def test_routes_lever_link_type(scraper):
    with patch("CleanScript.fetch_lever_jobs_api", return_value=SAMPLE_JOBS) as mock_lever:
        listings, links = scraper.scrapers("https://jobs.lever.co/testco", "lever", "testco")

    mock_lever.assert_called_once_with("testco")
    assert listings == SAMPLE_JOBS


def test_unknown_link_type_returns_empty_tuple(scraper):
    listings, links = scraper.scrapers("https://example.com/jobs", "unknown_ats", "testco")

    assert listings == []
    assert links == []
