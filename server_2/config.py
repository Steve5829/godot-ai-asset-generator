import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent/".env")
PIXELLAB_API_KEY = os.getenv("PIXELLAB_API_KEY")
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL") or "gpt-4o-mini"
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1"
OPENAI_IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY") or "medium"