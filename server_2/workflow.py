from composer import COMPOSER_CLASSES
from save import save_image
import io
from PIL import Image

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
        composed = COMPOSER_CLASSES["two_face"]().compose(image, image)
        record = save_image(composed, plan, role = "block_texture")
        return [record]

class SliceWorkflow(Workflow):
    cell_role = "cell"
    def grid(self, sheet):
        raise NotImplementedError
    def execute(self, plan, provider):
        image = provider.generate(plan)
        sheet = Image.open(io.BytesIO(image))
        columns, rows = self.grid(sheet)
        outputs = [save_image(image, plan, role="full_image")]
        for cell_bytes, r, c in crop_grid(image, columns, rows):
            outputs.append(save_image(cell_bytes, plan, role=self.cell_role,
                                      suffix=f"_r{r:02d}_c{c:02d}"))
        return outputs

class SpriteSheetWorkflow(SliceWorkflow):
    columns = 4
    rows = 4
    cell_role = "cell"
    def grid(self, sheet):
        return self.columns, self.rows

class GroundAtlasWorkflow(SliceWorkflow):
    tile_width = 32
    tile_height = 32
    cell_role = "atlas_tile"
    def grid(self, sheet):
        return sheet.width // self.tile_width, sheet.height // self.tile_height

def crop_grid(image_bytes, columns, rows):
        sheet = Image.open(io.BytesIO(image_bytes))
        cell_w = sheet.width//columns
        cell_h = sheet.height//rows
        cells = []
        for r in range(rows):
            for c in range (columns):
                cell = sheet.crop ((c*cell_w, r*cell_h, (c+1)*cell_w, (r+1)*cell_h) )
                buf = io.BytesIO()
                cell.save(buf, format = "PNG")
                cells.append((buf.getvalue(),r,c))
        return cells

WORKFLOW_CLASSES = {
    "icon": IconWorkflow,
    "block": BlockWorkflow,
    "spritesheet": SpriteSheetWorkflow,
    "ground_atlas": GroundAtlasWorkflow
}
