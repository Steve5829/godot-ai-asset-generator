from plan import Plan
import re

# slug filename for path
def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

class Asset:
    needs_compose = False
    def build_plan(self, request):
            return Plan(
                description = request.prompt,
                width = request.width,
                height = request.height,
                output_folder = request.folder,
                filename = slug(request.prompt),
                needs_compose = self.needs_compose
            )

class IconAsset(Asset):
    pass
    
class BlockAsset(Asset):
     needs_compose = True


        

    
