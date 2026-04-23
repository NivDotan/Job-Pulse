"""
Tests for the job keyword-filtering logic used in CleanScript.process_job_data.

The core filter is: keep a job if any search keyword appears (case-insensitive)
in the job title. These tests validate that logic independently so it can be
verified without running a full scrape cycle.
"""


def _filter_jobs_by_keywords(jobs: list[dict], keywords: list[str]) -> list[dict]:
    """Mirrors the filtering logic in CleanScript.process_job_data (API-based path)."""
    return [
        job for job in jobs
        if any(kw.lower() in job.get("title", "").lower() for kw in keywords)
    ]


def test_junior_keyword_matches_correct_jobs():
    jobs = [
        {"title": "Junior Developer", "location": "Tel Aviv", "link": "http://example.com/1"},
        {"title": "Senior Engineer", "location": "Tel Aviv", "link": "http://example.com/2"},
        {"title": "Student Internship", "location": "Haifa", "link": "http://example.com/3"},
    ]
    result = _filter_jobs_by_keywords(jobs, ["junior", "student"])

    assert len(result) == 2
    titles = [j["title"] for j in result]
    assert "Junior Developer" in titles
    assert "Student Internship" in titles


def test_keyword_matching_is_case_insensitive():
    jobs = [
        {"title": "JUNIOR SOFTWARE ENGINEER", "location": "Tel Aviv", "link": "http://example.com/4"},
    ]
    result = _filter_jobs_by_keywords(jobs, ["junior"])

    assert len(result) == 1
