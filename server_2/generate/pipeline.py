from generate.router import route
from generate.provider import PROVIDER_CLASSES
from generate.workflow import WORKFLOW_CLASSES
class Pipeline:
    def run(self,request):
        asset = route(request)()
        plan = asset.build_plan(request)
        provider = PROVIDER_CLASSES[request.provider]()
        return WORKFLOW_CLASSES[plan.workflow]().execute(plan, provider)


