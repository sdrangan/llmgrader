# Development Guide

## Running in Development Mode

```
python run.py
```

## Adding New Routes
Create a new file in `llmgrader/routes/` and register it in `create_app()`.

## Adding New Services
Place reusable logic in `llmgrader/services/`.

## GitHub Pages
To enable GitHub Pages:
1. Go to Settings → Pages
2. Set Branch: main
3. Set Folder: /docs
4. Save

## Creating the requirements file

Since we are deploying to render.com, we have to be picky about the requirements.txt:

- In render, add the environment variable `PYTHON_VERSION=3.12.3`. 
- In the `requirements.txt`:
   - Replace `pydantic` with `pydantic==1.10.15`
   - Remove `pydantic_core`
   - Remove `rpds-py`
 