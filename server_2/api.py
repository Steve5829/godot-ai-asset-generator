from fastapi import FastAPI
from pydantic import BaseModel
from generate.request import Request
from generate.pipeline import Pipeline
from generate.provider import PROVIDER_CLASSES
from automate.planner import plan_actions

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
            "type": "asset",
            "file": outputs[0]["file"],   
            "file_path": outputs[0]["file_path"],
            "outputs": outputs
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

class AutomateBody(BaseModel):
    prompt: str
    selected_nodes: list = []
    mode: str = "llm"

@app.post("/vibe/automate")
def automate(body: AutomateBody):
    try:
        actions = plan_actions(body.prompt, body.selected_nodes, body.mode)
        return {"status": "success", "type": "automation", "actions": actions}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

@app.get("/vibe/options")
def options():
    return {
        "providers": list(PROVIDER_CLASSES),
        # style:
    }