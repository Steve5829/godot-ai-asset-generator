import requests, base64, time
from config import PIXELLAB_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_IMAGE_MODEL, OPENAI_IMAGE_QUALITY
import io
from PIL import Image

PIXELLAB_STYLE_STRENGTH = 45
PIXELLAB_V2 = "https://api.pixellab.ai/v2"

class Provider:
    def generate(self, plan, description = None):
        raise NotImplementedError
class PixellabProvider(Provider):
    def generate(self, plan, description = None):
        if not PIXELLAB_API_KEY:
            raise ValueError("PIXELLAB_API_KEY not set")
        body = {
                "description" : description or plan.description,
                "image_size": {"width": plan.width, "height": plan.height},
                "no_background": plan.no_background,
                }
        if plan.reference_mode == "style" and plan.reference_image:
            endpoint = "generate-image-bitforge"
            body["style_image"] = encode_style_image(plan.reference_image, plan.width, plan.height)
            body["style_strength"] = PIXELLAB_STYLE_STRENGTH
        else:
            endpoint = "generate-image-pixflux"
        response = requests.post(
            "https://api.pixellab.ai/v1/" + endpoint,
            headers = {"Authorization": "Bearer " + PIXELLAB_API_KEY},
            json = body,
            timeout = (10,180)
            )
        response.raise_for_status()
        payload = response.json()
        encoded = payload["image"]["base64"]
        return base64.b64decode(encoded)

class GPTProvider(Provider):
    def generate(self, plan, description = None):
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set")
        body = {
                "model": OPENAI_IMAGE_MODEL,
                "prompt" : description or plan.description,
                "size" : openai_image_size(plan.width, plan.height),
                "quality": OPENAI_IMAGE_QUALITY,
                "n": 1,
                "output_format": "png",
                }
        if plan.no_background:
            body["background"] = "transparent"
        response = requests.post(
            OPENAI_BASE_URL + "/images/generations",
            headers = {"Authorization": "Bearer " + OPENAI_API_KEY},
            json = body,
            timeout = (10,180)
            )
        response.raise_for_status()
        payload = response.json()
        encoded = payload["data"][0]["b64_json"]
        raw = base64.b64decode(encoded)
        return resize_png(raw, plan.width, plan.height)


def generate_isometric_tile(description, width, height, timeout_s=120, poll_s=3):
    # PixelLab v2 native isometric block: one call renders a finished cube
    # (top/side geometry handled server-side), returned via an async job.
    if not PIXELLAB_API_KEY:
        raise ValueError("PIXELLAB_API_KEY not set")
    headers = {"Authorization": "Bearer " + PIXELLAB_API_KEY}
    body = {"description": description, "image_size": {"width": width, "height": height}}
    started = requests.post(PIXELLAB_V2 + "/create-isometric-tile",
                            headers=headers, json=body, timeout=(10, 60))
    started.raise_for_status()
    job_id = started.json()["background_job_id"]

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = requests.get(f"{PIXELLAB_V2}/background-jobs/{job_id}",
                           headers=headers, timeout=(10, 60))
        job.raise_for_status()
        payload = job.json()
        status = payload.get("status")
        if status == "completed":
            encoded = payload["last_response"]["image"]["base64"]
            if encoded.startswith("data:"):
                encoded = encoded.split(",", 1)[1]
            return base64.b64decode(encoded)
        if status == "failed":
            raise ValueError("PixelLab isometric job failed")
        time.sleep(poll_s)
    raise TimeoutError("PixelLab isometric job timed out")


def encode_style_image(path, width, height):
    img = Image.open(path).convert("RGBA").resize((width, height), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()
    return {"type": "base64", "base64": encoded, "format": "png"}

def openai_image_size(width, height):
    if width > height:
        return "1536x1024"
    if height > width:
        return "1024x1536"
    return "1024x1024"

def resize_png(image_bytes, width, height):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    img = img.resize((width, height), Image.LANCZOS)  
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

PROVIDER_CLASSES = {
    "pixellab":PixellabProvider,
    "gpt_image":GPTProvider
}