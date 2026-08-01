from fastapi import FastAPI
from pydantic import BaseModel
from request import Request
from pipeline import Pipeline
from provider import PROVIDER_CLASSES

app = FastAPI()

class GenerateBody(BaseModel):
    prompt: str
    folder: str
    width: int = 32
    height: int = 32
    style: str = "none"
    provider: str = "pixellab"

@app.post("/vibe/generate")
def generate(body: GenerateBody):
    try:
        request = Request(
            prompt = body.prompt,
            width = body.width,
            height = body.height,
            folder = body.folder,
            style = body.style,
            provider = body.provider
        )
        outputs = Pipeline().run(request)
        return {
            "status": "success",
            "file": outputs[0]["file"],   
            "file_path": outputs[0]["file_path"],
            "outputs": outputs,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

@app.get("/vibe/options")
def options():
    return {
        "providers": list(PROVIDER_CLASSES),      
        # style:                      
    }