import json
import pytest
from CleanScript import JobScraper


@pytest.fixture
def scraper():
    return JobScraper([])


def test_removes_duplicate_links(scraper, tmp_path):
    data = [
        ["CompanyA", [
            {"title": "Developer", "location": "Tel Aviv", "link": "http://jobs.example.com/1"},
            {"title": "Developer", "location": "Tel Aviv", "link": "http://jobs.example.com/1"},
            {"title": "Engineer", "location": "Tel Aviv", "link": "http://jobs.example.com/2"},
        ]]
    ]
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.json"
    input_file.write_text(json.dumps(data), encoding="utf-8")

    scraper.remove_duplicates_json(str(input_file), str(output_file))

    result = json.loads(output_file.read_text(encoding="utf-8"))
    assert len(result[0][1]) == 2


def test_preserves_unique_jobs(scraper, tmp_path):
    data = [
        ["CompanyB", [
            {"title": "Frontend Dev", "location": "Tel Aviv", "link": "http://jobs.example.com/10"},
            {"title": "Backend Dev", "location": "Tel Aviv", "link": "http://jobs.example.com/11"},
        ]]
    ]
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.json"
    input_file.write_text(json.dumps(data), encoding="utf-8")

    scraper.remove_duplicates_json(str(input_file), str(output_file))

    result = json.loads(output_file.read_text(encoding="utf-8"))
    assert len(result[0][1]) == 2


def test_handles_empty_job_list(scraper, tmp_path):
    data = [["CompanyC", []]]
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.json"
    input_file.write_text(json.dumps(data), encoding="utf-8")

    scraper.remove_duplicates_json(str(input_file), str(output_file))

    result = json.loads(output_file.read_text(encoding="utf-8"))
    assert result[0][1] == []
