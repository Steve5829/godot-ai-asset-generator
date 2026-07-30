import requests, base64
from config import PIXELLAB_API_KEY

class Provider:
    def generate(self, plan):
        raise NotImplementedError
class PixellabProvider(Provider):
    def generate(self, plan):
        if not PIXELLAB_API_KEY:
            raise ValueError("PIXELLAB_API_KEY not set")
        body = {
                "description" : plan.description,
                "image_size": {"width": plan.width, "height": plan.height},
                "no_background": plan.no_background,
                }
        response = requests.post(
            "https://api.pixellab.ai/v1/generate-image-pixflux",
            headers = {"Authorization": "Bearer " + PIXELLAB_API_KEY},
            json = body,
            timeout = (10,180)
            )
        response.raise_for_status()
        payload = response.json()
        encoded = payload["image"]["base64"]
        return base64.b64decode(encoded)

class GPTProvider(Provider):
    def generate(self, plan):
        return "gpt image"
    
PROVIDER_CLASSES = {
    "pixellab":PixellabProvider,
    "gpt_image":GPTProvider
}