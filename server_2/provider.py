import requests, base64
from config import PIXELLAB_API_KEY
import io
from PIL import Image

PIXELLAB_STYLE_STRENGTH = 45

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
        not NotImplementedError

def encode_style_image(path, width, height):
    img = Image.open(path).convert("RGBA").resize((width, height), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()
    return {"type": "base64", "base64": encoded, "format": "png"}

PROVIDER_CLASSES = {
    "pixellab":PixellabProvider,
    "gpt_image":GPTProvider
}