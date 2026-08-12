from generate.request import Request
from generate.router import route
from generate.asset import BlockAsset
prompt = "a diamond block"
width = 30
height = 30
folder = None
user_request = Request(prompt, width, height,folder)
result = route(user_request)
assert result == BlockAsset