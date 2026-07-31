from router import route
from provider import PROVIDER_CLASSES
from composer import COMPOSER_CLASSES

def post_process(image):
    return image

class Pipeline:
    def run(self,request):
        asset = route(request)()
        plan = asset.build_plan(request)
        provider = PROVIDER_CLASSES[request.provider]()
        return WORKFLOW_CLASSES[plan.workflow]().execute(plan, provider)


