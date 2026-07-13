from .gemini import GeminiAdapter
from .openai_compat import OpenAICompatAdapter

ADAPTER_KINDS = {
    "gemini": GeminiAdapter,
    "openai_compat": OpenAICompatAdapter,
}
