from plan import Plan
import re

# slug filename for path
def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

class Asset:
    no_background = True
    workflow = "icon"
    def build_plan(self, request):
            return Plan(
                description = request.prompt,
                width = request.width,
                height = request.height,
                output_folder = request.folder,
                filename = slug(request.prompt),
                no_background = self.no_background,
                workflow = self.workflow
            )

class IconAsset(Asset):
    pass
    
class BlockAsset(Asset):
    no_background = False
    workflow = "block"

class SpriteSheetAsset(Asset):
     workflow = "spritesheet"

class GroundAtlasAsset(Asset):
     no_background = False
     workflow = "ground_atlas"
        

    
