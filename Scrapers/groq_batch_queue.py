import argparse
import hashlib
import json
import os
from datetime import datetime
from os.path import dirname, join
from typing import Any
from zoneinfo import ZoneInfo

import supabase
from dotenv import load_dotenv

try:
    import groq
except Exception:  # pragma: no cover - tests can run without importing SDK internals
    groq = None

import local_llm_function


dotenv_path = join(dirname(__file__), ".env")
load_dotenv(dotenv_path)

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
DEFAULT_BUCKET = os.environ.get("GROQ_BATCH_BUCKET", "groq-batch-requests")
DEFAULT_QUEUE_DIR = os.environ.get("GROQ_BATCH_QUEUE_DIR", "")

RATE_LIMIT_TERMS = (
    "rate limit",
    "ratelimit",
    "quota",
    "daily limit",
    "too many requests",
    "tokens per",
)


class GroqBatchQueueCandidate(Exception):
    """Carries extracted text from a job whose live Groq call hit quota/rate limits."""

    def __init__(self, raw_text: str, source: str, original_error: Exception):
        super().__init__(str(original_error))
        self.raw_text = raw_text
        self.source = source
        self.original_error = original_error


def is_groq_rate_limit_error(error: Exception) -> bool:
    if groq is not None and isinstance(error, getattr(groq, "RateLimitError", ())):
        return True

    status_code = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status_code == 429 or getattr(response, "status_code", None) == 429:
        return True

    text = str(error).lower()
    return any(term in text for term in RATE_LIMIT_TERMS)


def get_supabase_client():
    supabase_url = os.environ.get("supabaseUrl")
    supabase_key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("supabaseServiceKey")
        or os.environ.get("supabaseKey")
    )
    if not supabase_url or not supabase_key:
        raise ValueError("Supabase credentials not found in environment variables")
    return supabase.create_client(supabase_url, supabase_key)


def make_custom_id(company: str, job_name: str, link: str) -> str:
    raw = "|".join([(company or "").strip(), (job_name or "").strip(), (link or "").strip()])
    return "job:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_batch_request(raw_text: str, custom_id: str, model: str | None = None) -> dict[str, Any]:
    model = model or local_llm_function.LLM_MODEL
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": local_llm_function.build_junior_classification_prompt(raw_text),
                }
            ],
            "temperature": 1,
            "max_completion_tokens": 1024,
            "top_p": 1,
            "stream": False,
            "response_format": {"type": "json_object"},
        },
    }


def build_metadata(
    *,
    custom_id: str,
    company: str,
    job_name: str,
    city: str,
    link: str,
    source: str,
    error: Exception,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(ISRAEL_TZ)
    return {
        "custom_id": custom_id,
        "company": company or "",
        "job_name": job_name or "",
        "city": city or "",
        "link": link or "",
        "source": source or "",
        "queued_at": now.isoformat(),
        "error_type": "groq_rate_limit",
        "error_message": str(error),
    }


def daily_object_paths(now: datetime | None = None, *, smoke: bool = False) -> tuple[str, str]:
    now = now or datetime.now(ISRAEL_TZ)
    day = now.strftime("%Y-%m-%d")
    if smoke:
        base = f"smoke/groq_batch_storage_smoke_{day}"
    else:
        prefix = DEFAULT_QUEUE_DIR.strip("/")
        day_dir = f"{prefix}/{day}" if prefix else day
        base = f"{day_dir}/groq_batch_{day}"
    return f"{base}.jsonl", f"{base}.meta.jsonl"


def _bucket_name(bucket: Any) -> str:
    if isinstance(bucket, dict):
        return bucket.get("id") or bucket.get("name") or ""
    return getattr(bucket, "id", None) or getattr(bucket, "name", None) or ""


def ensure_bucket(client: Any, bucket_name: str = DEFAULT_BUCKET) -> None:
    buckets = client.storage.list_buckets()
    if any(_bucket_name(bucket) == bucket_name for bucket in buckets):
        return
    try:
        client.storage.create_bucket(bucket_name, options={"public": False})
    except Exception as error:
        message = str(error)
        if "row-level security" in message.lower() or "unauthorized" in message.lower():
            raise PermissionError(
                f"Supabase Storage bucket '{bucket_name}' does not exist and the configured key cannot create it. "
                "Use a service-role key in SUPABASE_SERVICE_ROLE_KEY/supabaseServiceKey, or create the private "
                "bucket and storage policies in Supabase before running the smoke command."
            ) from error
        raise


def _download_text(bucket: Any, path: str) -> str:
    try:
        data = bucket.download(path)
    except Exception as error:
        text = str(error).lower()
        if "not found" in text or "404" in text or "does not exist" in text:
            return ""
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8")
    return str(data or "")


def _existing_custom_ids(text: str) -> set[str]:
    ids = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        custom_id = item.get("custom_id")
        if custom_id:
            ids.add(custom_id)
    return ids


def append_jsonl_if_new(bucket: Any, path: str, item: dict[str, Any]) -> bool:
    existing_text = _download_text(bucket, path)
    custom_id = item.get("custom_id")
    if custom_id and custom_id in _existing_custom_ids(existing_text):
        return False

    lines = [line for line in existing_text.splitlines() if line.strip()]
    lines.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    new_text = "\n".join(lines) + "\n"
    bucket.upload(
        path,
        new_text.encode("utf-8"),
        file_options={"content-type": "application/jsonl", "x-upsert": "true"},
    )
    return True


def queue_rate_limited_job(
    *,
    raw_text: str,
    company: str,
    job_name: str,
    city: str,
    link: str,
    source: str,
    error: Exception,
    client: Any | None = None,
    now: datetime | None = None,
    bucket_name: str = DEFAULT_BUCKET,
    smoke: bool = False,
) -> dict[str, Any]:
    client = client or get_supabase_client()
    now = now or datetime.now(ISRAEL_TZ)
    ensure_bucket(client, bucket_name)
    bucket = client.storage.from_(bucket_name)

    custom_id = make_custom_id(company, job_name, link)
    request_path, meta_path = daily_object_paths(now, smoke=smoke)
    request_item = build_batch_request(raw_text, custom_id)
    metadata_item = build_metadata(
        custom_id=custom_id,
        company=company,
        job_name=job_name,
        city=city,
        link=link,
        source=source,
        error=error,
        now=now,
    )

    queued = append_jsonl_if_new(bucket, request_path, request_item)
    if queued:
        append_jsonl_if_new(bucket, meta_path, metadata_item)
    return {
        "queued": queued,
        "custom_id": custom_id,
        "bucket": bucket_name,
        "request_path": request_path,
        "meta_path": meta_path,
    }


def run_smoke() -> dict[str, Any]:
    return queue_rate_limited_job(
        raw_text="Smoke test job text for Groq batch storage validation.",
        company="Smoke Test",
        job_name="Groq Batch Storage Smoke",
        city="Test",
        link="https://example.com/groq-batch-storage-smoke",
        source="smoke",
        error=Exception("smoke test"),
        smoke=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue Groq Batch-compatible requests in Supabase Storage")
    parser.add_argument("--smoke", action="store_true", help="Write/update a smoke-test JSONL object in Supabase Storage")
    args = parser.parse_args()

    if args.smoke:
        result = run_smoke()
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
