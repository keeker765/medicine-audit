"""LLM 调用模块 — httpx 直接调用 OpenRouter API"""
import json
import httpx

from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, LLM_MODEL, OCR_MODEL

_headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:8000",
    "X-Title": "Microbiology Report AI",
}


def chat_completion(messages: list[dict], tools: list[dict] = None, model: str = None) -> dict:
    """非流式 LLM 调用"""
    payload = {
        "model": model or LLM_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4096,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    with httpx.Client(timeout=120) as client:
        resp = client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=_headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


def chat_completion_stream(messages: list[dict], tools: list[dict] = None, model: str = None):
    """流式 LLM 调用，yield 解析后的 SSE 事件 dict"""
    payload = {
        "model": model or LLM_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4096,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    with httpx.Client(timeout=180) as client:
        with client.stream(
            "POST",
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=_headers,
            json=payload,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        return
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue


def ocr_image(image_base64: str, prompt: str, mime: str = "image/jpeg") -> str:
    """调用视觉模型进行 OCR"""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_base64}"}},
            ],
        }
    ]
    result = chat_completion(messages, model=OCR_MODEL)
    return result["choices"][0]["message"]["content"]
