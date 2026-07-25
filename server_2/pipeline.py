from router import route
from provider import PROVIDER_CLASSES
from pathlib import Path

def post_process(image):
    return image

def save_image (image, plan):
    folder = plan.output_folder
    filename = plan.filename
    path = Path(folder)/f"{filename}.png"
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_bytes(image)
    print(f"save {folder}:{image}")

class Pipeline:
    def run(self,request):
        asset = route(request)()
        plan = asset.build_plan(request)
        image = PROVIDER_CLASSES[request.provider]().generate(plan)
        image = post_process(image)
        save_image(image, plan)
        return image


