import os
import requests
from typing import Optional
from dotenv import load_dotenv
from os.path import join, dirname
from groq import Groq

# Load environment variables
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

# LLM Configuration - defaults to Groq free tier (Llama 3.1 8B)
LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama-3.1-8b-instant")


def _get_headers() -> dict[str, str]:
    """Build request headers with optional API key for cloud providers."""
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    return headers


def extract_job_info_from_text(raw_text: str, model: Optional[str] = None, server_url: Optional[str] = None) -> str:
    """
    Extract job description and requirements from raw text using LLM.
    
    Uses environment variables for configuration:
        LLM_API_URL  - API endpoint (default: Groq)
        LLM_API_KEY  - API key (required for cloud providers like Groq)
        LLM_MODEL    - Model name (default: llama-3.1-8b-instant)
    """
    model = model or LLM_MODEL
    server_url = server_url or LLM_API_URL
    headers = _get_headers()

    prompt = (
        f"Here is the raw text extracted from a job listing webpage: {raw_text}\n"
        "Extract only the job description and requirements from this text.\n"
        "Return a JSON object with two keys: 'desc' (job description) and 'reqs' (job requirements).\n"
        "'desc' should summarize the key job responsibilities, while 'reqs' should list the qualifications or skills required.\n"
        "Ensure the result contains only relevant information without extra text."
    )

    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post(server_url, headers=headers, json=data)

    if response.ok:
        return response.json()['choices'][0]['message']['content']
    else:
        raise Exception(f"Request failed with status {response.status_code}: {response.text}")


def classify_job_for_juniors_Local(raw_text: str, model: Optional[str] = None, server_url: Optional[str] = None) -> str:
    """
    Classify whether a job is suitable for junior developers using LLM.
    
    Uses environment variables for configuration:
        LLM_API_URL  - API endpoint (default: Groq)
        LLM_API_KEY  - API key (required for cloud providers like Groq)
        LLM_MODEL    - Model name (default: llama-3.1-8b-instant)
    """
    model = model or LLM_MODEL
    server_url = server_url or LLM_API_URL
    headers = _get_headers()

    prompt = (
    f"Here is the raw text extracted from a job listing webpage:\n\n{raw_text}\n\n"
    "Your task is to extract structured information in JSON format. The JSON must include:\n"
    "1. 'desc': a concise summary of the job description and responsibilities.\n"
    "2. 'reqs': a list of required qualifications or skills (as an array of strings).\n"
    "3. 'suitable_for_junior': whether this job is suitable for a computer science student, junior developer, or someone early in their career.\n\n"
    "The JSON response should look like this:\n"
    "{\n"
    '  "desc": string,\n'
    '  "reqs": [string, string, ...],\n'
    '  "suitable_for_junior": "True" | "False" | "Unclear"\n'
    "}\n\n"
    "Ensure the result contains only relevant information from the raw text and no extra commentary."
)

    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post(server_url, headers=headers, json=data)

    if response.ok:
        print(response.json()['choices'][0]['message']['content'].strip())
        return response.json()['choices'][0]['message']['content'].strip()
    else:
        raise Exception(f"Request failed with status {response.status_code}: {response.text}")

def classify_job_for_juniors(raw_text: str, model: Optional[str] = None, server_url: Optional[str] = None) -> str:
    """
    Classify whether a job is suitable for junior developers using Groq SDK.
    Returns JSON string with desc, reqs, and suitable_for_junior fields.
    """
    model = model or LLM_MODEL

    prompt = (
        f"Here is the raw text extracted from a job listing webpage:\n\n{raw_text}\n\n"
        "Your task is to extract structured information in JSON format. The JSON must include:\n"
        "1. 'desc': a concise summary of the job description and responsibilities.\n"
        "2. 'reqs': a list of required qualifications or skills (as an array of strings).\n"
        "3. 'suitable_for_junior': whether this job is suitable for a computer science student, junior developer, or someone early in their career.\n\n"
        "The JSON response should look like this:\n"
        "{\n"
        '  "desc": string,\n'
        '  "reqs": [string, string, ...],\n'
        '  "suitable_for_junior": "True" | "False" | "Unclear"\n'
        "}\n\n"
        "Ensure the result contains only relevant information from the raw text and no extra commentary."
    )

    client = Groq(api_key=LLM_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=1,
        max_completion_tokens=1024,
        top_p=1,
        stream=False,
        response_format={"type": "json_object"},
        stop=None
    )
    result = response.choices[0].message.content.strip()
    print(result)
    return result
