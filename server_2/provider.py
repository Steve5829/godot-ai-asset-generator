class Provider:
    def generate(self, plan):
        raise NotImplementedError
class PixellabProvider(Provider):
    def generate(self, plan):
        return "pixellab image"
class GPTProvider(Provider):
    def generate(self, plan):
        return "gpt image"
    
PROVIDER_CLASSES = {
    "pixellab":PixellabProvider,
    "gpt_image":GPTProvider
}