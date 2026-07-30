import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent/"server"/".env")
PIXELLAB_API_KEY = os.getenv("PIXELLAB_API_KEY")
