from generate.request import Request
from generate.router import route
from generate.asset import BlockAsset

def plan_for(prompt):
    req = Request(prompt=prompt, width=16, height=16, folder="output_test")
    asset = route(req)
    assert asset is BlockAsset, f"{prompt!r} routed to {asset}, expected BlockAsset"
    return asset().build_plan(req)

# non-uniform:
grass = plan_for("a grass block")
assert grass.faces is not None, "grass should be multi-face"
assert set(grass.faces) == {"top", "front"}, grass.faces
assert "grass" in grass.faces["top"]
assert "dirt" in grass.faces["front"]
assert grass.workflow == "block"

# uniform: 
stone = plan_for("a stone block")
assert stone.faces is None, f"stone should be uniform, got {stone.faces}"
assert "stone" in stone.description
assert "top horizontal face" in stone.description

# unmatched material 
plain = plan_for("a mysterious block")
assert plain.faces is None, f"unmatched should be single, got {plain.faces}"
assert plain.description == "a mysterious block"

print("ok grass:", grass.faces)
print("ok stone: faces =", stone.faces)
print("ok plain:", plain.description)
