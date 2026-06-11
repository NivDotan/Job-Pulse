import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as dashboard_app


def test_portfolio_api_smoke_with_mocked_analytics(monkeypatch):
    def fake_portfolio(start, end, companies=None, keyword="", country="", seniority="", limit=50):
        assert start == date(2026, 1, 1)
        assert end == date(2026, 1, 31)
        assert companies == ["monday"]
        assert keyword == "python"
        assert country == "Israel"
        assert seniority == "Entry"
        assert limit == 25
        return {
            "summary": {"live_jobs": 1},
            "funnel": [],
            "trends": [],
            "skills": [],
            "locations": {"countries": [], "cities": [], "workplace": []},
            "companies": {"top_hiring": [], "health": []},
            "quality": {"score": 100},
            "matching_jobs": [],
            "methodology": [],
        }

    monkeypatch.setattr(dashboard_app, "get_portfolio_analytics", fake_portfolio)
    client = dashboard_app.app.test_client()
    response = client.get(
        "/api/analytics/portfolio?start=2026-01-01&end=2026-01-31"
        "&companies=monday&keyword=python&country=Israel&seniority=Entry&limit=25"
    )

    assert response.status_code == 200
    assert response.get_json()["summary"]["live_jobs"] == 1


def test_portfolio_api_rejects_invalid_date_range():
    client = dashboard_app.app.test_client()
    response = client.get("/api/analytics/portfolio?start=2026-02-01&end=2026-01-01")

    assert response.status_code == 400
