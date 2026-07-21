from plan import Plan

class Asset:
    def build_plan(self, request):
        raise NotImplementedError

class IconAsset(Asset):
    def build_plan(self, request):
        return Plan(
            description = request.prompt,
            width = request.width,
            height = request.height,
            output_folder = request.folder
        )
class BlockAsset(Asset):
    def build_plan(self, request):
        return Plan(
            description = request.prompt,
            width = request.width,
            height = request.height,
            output_folder = request.folder,
            needs_compose = True

        )

    
