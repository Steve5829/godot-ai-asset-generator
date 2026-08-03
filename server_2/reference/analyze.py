import io, base64, requests
from PIL import Image
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_VISION_MODEL

def image_data_url(path):
    img = Image.open(path).convert("RGB")
    buf = io.BytesIO(); img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{encoded}" 

def analyze_reference(path, prompt):
    if not OPENAI_API_KEY:
        return ""                                 
    try:
        response = requests.post(
            OPENAI_BASE_URL + "/chat/completions",
            headers = {"Authorization": "Bearer " + OPENAI_API_KEY, "Content-Type": "application/json"},
            json = {
                "model": OPENAI_VISION_MODEL,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content":
                        "You are a concise game art director. Extract transferable visual traits "
                        "from the reference. Never tell the model to copy or trace it. "
                        "Never mention gray backgrounds or checkerboards."},
                    {"role": "user", "content": [
                        {"type": "text", "text":
                            f"Summarize reusable visual traits (palette, outline, shading, silhouette) "
                            f"for this asset prompt: {prompt}"},
                        {"type": "image_url", "image_url": {"url": image_data_url(path)}},
                    ]},
                ],
            },
            timeout = (10, 45),
        )
        response.raise_for_status()
        choices = response.json().get("choices") or []
        return choices[0]["message"]["content"].strip() if choices else ""
    except Exception as exc:
        print("reference analysis failed:", exc)    
        return ""