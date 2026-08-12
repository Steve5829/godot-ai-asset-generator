import io, base64
from PIL import Image
from llm import chat


def image_data_url(path):
    img = Image.open(path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()
    return "data:image/png;base64," + encoded


def analyze_reference(path, prompt):
    messages = [
        {"role": "system", "content":
            "You are a concise game art director. Extract transferable visual traits from the reference. "
            "Never tell the model to copy or trace it. Never mention gray backgrounds or checkerboards."},
        {"role": "user", "content": [
            {"type": "text", "text":
                "Summarize reusable visual traits (palette, outline, shading, silhouette) for this asset prompt: " + prompt},
            {"type": "image_url", "image_url": {"url": image_data_url(path)}},
        ]},
    ]
    return chat(messages)
