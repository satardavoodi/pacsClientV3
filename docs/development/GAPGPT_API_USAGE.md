# GapGPT API Usage (Python)

This document explains how to authenticate, send prompts, and read responses from the GapGPT Chat Completions API.

## Overview
- Base URL: https://api.gapgpt.app/v1
- Chat endpoint: https://api.gapgpt.app/v1/chat/completions
- Authentication: API key in the `Authorization` header using the Bearer scheme

## Authentication
Send your API key in the `Authorization` header:

```
Authorization: Bearer <YOUR_GAPGPT_API_KEY>
```

## Request format (text-only)
The API expects a JSON payload with a `model` and a `messages` array. Each message has a `role` and `content`.

Example payload:

```json
{
  "model": "gpt-4.1-mini",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Write a concise report summary."}
  ]
}
```

## Response format
A successful response contains:
- `choices[0].message.content` for the assistant reply
- `usage` for token counts

Example response structure (simplified):

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "..."
      }
    }
  ],
  "usage": {
    "prompt_tokens": 123,
    "completion_tokens": 456,
    "total_tokens": 579
  }
}
```

## Python example (requests)

```python
import requests

def gapgpt_chat(api_key: str, user_msg: str, model: str = "gpt-4.1-mini") -> str:
    url = "https://api.gapgpt.app/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_msg},
        ],
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    result = response.json()
    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    return result["choices"][0]["message"]["content"]
```

## Image input (vision)
For image+text, send the user `content` as an array with `text` and `image` items. The `image` field must be raw base64, not a data URL.

```python
import base64
import requests

def gapgpt_chat_with_image(api_key: str, user_msg: str, image_path: str, model: str = "gpt-4.1") -> str:
    url = "https://api.gapgpt.app/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_msg},
                    {"type": "image", "image": image_b64}
                ]
            }
        ],
        "temperature": 0.2,
        "max_tokens": 2000
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    result = response.json()
    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    return result["choices"][0]["message"]["content"]
```

## Common errors
- Missing or invalid API key: expect non-200 status codes
- Malformed payload: check JSON fields and types
- Network issues: handle request exceptions and timeouts

## References in this codebase
- GapGPT usage example: [modules/EchoMind/viewer_chat/openai_reporter.py](../../modules/EchoMind/viewer_chat/openai_reporter.py)
