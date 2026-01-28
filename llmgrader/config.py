"""
Configuration for LLM providers.
"""

# Provider type: "openai" or "huggingface"
PROVIDER = "huggingface"

# HuggingFace configuration (used when PROVIDER="huggingface")
# Use the Hugging Face Router endpoint (recommended replacement for api-inference)
# {model} will be replaced with the chosen model id, e.g. "HuggingFaceH4/zephyr-7b-beta"
HF_API_URL = "https://router.huggingface.co/models/{model}"
# Use a stable, actively maintained model:
# - "HuggingFaceH4/zephyr-7b-beta" (reliable, good instruction following)
# - "microsoft/Phi-3-mini-4k-instruct" (fast, efficient)
# - "Qwen/Qwen2.5-7B-Instruct" (newer, high quality)
HF_DEFAULT_MODEL = "deepseek-ai/DeepSeek-R1:novita"

# Request timeout settings
DEFAULT_TIMEOUT = 20  # seconds
ADDITIONAL_TIMEOUT_BUFFER = 5  # seconds
