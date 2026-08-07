import requests
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_VISION_MODEL


def chat(messages, temperature=0.1, response_format=None):
    if not OPENAI_API_KEY:
        return ""
    payload = {"model": OPENAI_VISION_MODEL, "temperature": temperature, "messages": messages}
    if response_format is not None:
        payload["response_format"] = response_format
    try:
        response = requests.post(
            OPENAI_BASE_URL + "/chat/completions",
            headers={"Authorization": "Bearer " + OPENAI_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=(10, 45),
        )
        response.raise_for_status()
        choices = response.json().get("choices") or []
        return choices[0]["message"]["content"].strip() if choices else ""
    except Exception as exc:
        print("llm chat failed:", exc)
        return ""
