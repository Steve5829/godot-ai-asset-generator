from router import route
from provider import PROVIDER_CLASSES

def post_process(image):
    return image

def save_image (image, folder):
    print(f"save {folder}:{image}")

class Pipeline:
    def run(self,request):
        asset = route(request)()
        plan = asset.build_plan(request)
        image = PROVIDER_CLASSES[request.provider]().generate(plan)
        image = post_process(image)
        save_image(image, plan.output_folder)
        return image


