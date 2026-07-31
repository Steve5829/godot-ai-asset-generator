from composer import COMPOSER_CLASSES
from save import save_image

class Workflow:
    def execute(self, plan, provider):
        raise NotImplementedError

class IconWorkflow(Workflow):
    def execute(self, plan, provider):
        image = provider.generate(plan)
        record = save_image(image, plan, role = "single_image")
        return [record]

class BlockWorkflow(Workflow):
    def execute(self, plan, provider):
        image = provider.generate(plan)
        composed = COMPOSER_CLASSES("two_face")().compose(image, image)
        record = save_image(composed, plan, role = "block_texture")
        return [record]
WORKFLOW_CLASSES = {
    "icon": IconWorkflow,
    "block": BlockWorkflow
}
