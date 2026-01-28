# LLM Provider Configuration

## Switching Between Providers

Edit `llmgrader/config.py` to change the LLM provider:

### OpenAI (default)
```python
PROVIDER = "openai"
```
- Uses OpenAI API (GPT models)
- Requires OpenAI API key
- Models: `gpt-4o`, `gpt-4.1-mini`, etc.

### HuggingFace
```python
PROVIDER = "huggingface"
```
- Uses HuggingFace Inference API
- Requires HuggingFace API token
- Default model: `meta-llama/Llama-3.1-70B-Instruct`
- Can be changed via `HF_DEFAULT_MODEL` in config

## API Keys

- **OpenAI**: Enter your OpenAI API key in the web UI (stored in browser localStorage)
- **HuggingFace**: Enter your HuggingFace token in the web UI (same input field)

## HuggingFace Models

To use a different HuggingFace model, edit `llmgrader/config.py`:

```python
HF_DEFAULT_MODEL = "meta-llama/Llama-3.1-70B-Instruct"  # or any other model
```

Popular options:
- `meta-llama/Llama-3.1-70B-Instruct`
- `mistralai/Mixtral-8x7B-Instruct-v0.1`
- `Qwen/Qwen2.5-72B-Instruct`

## Testing

After changing the provider:
1. Restart the Flask app
2. Enter the appropriate API key in the web UI
3. Try grading a solution

The app will automatically use the configured provider.
