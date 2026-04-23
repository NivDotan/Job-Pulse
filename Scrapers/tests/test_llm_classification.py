import json
import pytest
from unittest.mock import MagicMock, patch
from local_llm_function import classify_job_for_juniors


SAMPLE_JOB_TEXT = "We are looking for a junior Python developer to join our team in Tel Aviv."

MOCK_LLM_RESPONSE = json.dumps({
    "desc": "Junior Python developer role in Tel Aviv.",
    "reqs": ["Python", "Git", "REST APIs"],
    "suitable_for_junior": "True"
})


def _make_groq_mock(content: str) -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = content
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def test_returns_expected_keys():
    with patch("local_llm_function.Groq", return_value=_make_groq_mock(MOCK_LLM_RESPONSE)):
        result = classify_job_for_juniors(SAMPLE_JOB_TEXT)

    parsed = json.loads(result)
    assert "desc" in parsed
    assert "reqs" in parsed
    assert "suitable_for_junior" in parsed


def test_suitable_for_junior_value_is_true():
    with patch("local_llm_function.Groq", return_value=_make_groq_mock(MOCK_LLM_RESPONSE)):
        result = classify_job_for_juniors(SAMPLE_JOB_TEXT)

    assert json.loads(result)["suitable_for_junior"] == "True"


def test_groq_exception_propagates():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API unavailable")

    with patch("local_llm_function.Groq", return_value=mock_client):
        with pytest.raises(Exception, match="API unavailable"):
            classify_job_for_juniors(SAMPLE_JOB_TEXT)
