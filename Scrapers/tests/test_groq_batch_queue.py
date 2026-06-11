import json
from datetime import datetime
from zoneinfo import ZoneInfo

import groq_batch_queue
import local_llm_function


class FakeBucket:
    def __init__(self):
        self.objects = {}
        self.upload_calls = []

    def download(self, path):
        if path not in self.objects:
            raise Exception("not found")
        return self.objects[path]

    def upload(self, path, file, file_options=None):
        self.objects[path] = file
        self.upload_calls.append((path, file, file_options))
        return {"path": path}


class FakeStorage:
    def __init__(self):
        self.buckets = []
        self.bucket = FakeBucket()
        self.created = []

    def list_buckets(self):
        return self.buckets

    def create_bucket(self, bucket_name, options=None):
        self.buckets.append({"id": bucket_name, "name": bucket_name})
        self.created.append((bucket_name, options))
        return {"name": bucket_name}

    def from_(self, bucket_name):
        return self.bucket


class FakeClient:
    def __init__(self):
        self.storage = FakeStorage()


def test_build_batch_request_matches_current_groq_shape():
    raw_text = "Junior Python developer role in Tel Aviv."
    item = groq_batch_queue.build_batch_request(raw_text, "job:abc")

    assert item["custom_id"] == "job:abc"
    assert item["method"] == "POST"
    assert item["url"] == "/v1/chat/completions"
    assert item["body"]["model"] == local_llm_function.LLM_MODEL
    assert item["body"]["messages"] == [
        {"role": "user", "content": local_llm_function.build_junior_classification_prompt(raw_text)}
    ]
    assert item["body"]["temperature"] == 1
    assert item["body"]["max_completion_tokens"] == 1024
    assert item["body"]["top_p"] == 1
    assert item["body"]["stream"] is False
    assert item["body"]["response_format"] == {"type": "json_object"}


def test_queue_rate_limited_job_creates_private_bucket_and_jsonl_sidecar():
    client = FakeClient()
    now = datetime(2026, 6, 11, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))

    result = groq_batch_queue.queue_rate_limited_job(
        raw_text="Raw job text",
        company="Acme",
        job_name="Junior Developer",
        city="Tel Aviv",
        link="https://example.com/job",
        source="comeet",
        error=Exception("rate limit exceeded"),
        client=client,
        now=now,
    )

    assert result["queued"] is True
    assert client.storage.created == [("groq-batch-requests", {"public": False})]

    request_bytes = client.storage.bucket.objects["2026-06-11/groq_batch_2026-06-11.jsonl"]
    meta_bytes = client.storage.bucket.objects["2026-06-11/groq_batch_2026-06-11.meta.jsonl"]
    request_line = json.loads(request_bytes.decode("utf-8").strip())
    meta_line = json.loads(meta_bytes.decode("utf-8").strip())

    assert request_line["custom_id"] == result["custom_id"]
    assert request_line["body"]["model"] == local_llm_function.LLM_MODEL
    assert meta_line["custom_id"] == result["custom_id"]
    assert meta_line["company"] == "Acme"
    assert meta_line["source"] == "comeet"
    assert meta_line["error_type"] == "groq_rate_limit"


def test_queue_rate_limited_job_deduplicates_custom_id():
    client = FakeClient()
    now = datetime(2026, 6, 11, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    kwargs = {
        "raw_text": "Raw job text",
        "company": "Acme",
        "job_name": "Junior Developer",
        "city": "Tel Aviv",
        "link": "https://example.com/job",
        "source": "greenhouse",
        "error": Exception("too many requests"),
        "client": client,
        "now": now,
    }

    first = groq_batch_queue.queue_rate_limited_job(**kwargs)
    second = groq_batch_queue.queue_rate_limited_job(**kwargs)

    assert first["queued"] is True
    assert second["queued"] is False
    request_text = client.storage.bucket.objects["2026-06-11/groq_batch_2026-06-11.jsonl"].decode("utf-8")
    meta_text = client.storage.bucket.objects["2026-06-11/groq_batch_2026-06-11.meta.jsonl"].decode("utf-8")
    assert len([line for line in request_text.splitlines() if line.strip()]) == 1
    assert len([line for line in meta_text.splitlines() if line.strip()]) == 1


def test_rate_limit_detection_accepts_429_and_rejects_generic_errors():
    class StatusError(Exception):
        status_code = 429

    assert groq_batch_queue.is_groq_rate_limit_error(Exception("quota exceeded"))
    assert groq_batch_queue.is_groq_rate_limit_error(Exception("tokens per minute limit"))
    assert groq_batch_queue.is_groq_rate_limit_error(StatusError("nope"))
    assert not groq_batch_queue.is_groq_rate_limit_error(Exception("API unavailable"))


def test_smoke_mode_writes_only_smoke_path():
    client = FakeClient()
    now = datetime(2026, 6, 11, 12, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))

    result = groq_batch_queue.queue_rate_limited_job(
        raw_text="Raw job text",
        company="Smoke",
        job_name="Smoke Job",
        city="Test",
        link="https://example.com/smoke",
        source="smoke",
        error=Exception("smoke"),
        client=client,
        now=now,
        smoke=True,
    )

    assert result["request_path"] == "smoke/groq_batch_storage_smoke_2026-06-11.jsonl"
    assert result["meta_path"] == "smoke/groq_batch_storage_smoke_2026-06-11.meta.jsonl"
