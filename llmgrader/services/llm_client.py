"""
Abstraction layer for LLM API calls.
Supports OpenAI and HuggingFace Inference API.
"""

import requests
import json
from typing import Dict, Any
from pydantic import BaseModel
from typing import Literal


try:
    from openai import OpenAI, APITimeoutError
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    # Define a dummy exception for compatibility
    class APITimeoutError(Exception):
        pass

try:
    from huggingface_hub import InferenceClient
    HUGGINGFACE_AVAILABLE = True
except ImportError:
    InferenceClient = None
    HUGGINGFACE_AVAILABLE = False

try:
    from llmgrader.config import PROVIDER, HF_API_URL, HF_DEFAULT_MODEL
except ImportError:
    # Fallback defaults if config doesn't exist yet
    PROVIDER = "openai"
    HF_API_URL = "https://router.huggingface.co/models/{model}/v1/chat/completions"
    HF_DEFAULT_MODEL = "meta-llama/Llama-3.1-70B-Instruct"


class GradeResult(BaseModel):
    """Data model for grading results."""
    result: Literal["pass", "fail", "error"]
    full_explanation: str
    feedback: str


class LLMClient:
    """Unified client for different LLM providers."""
    
    def __init__(self, api_key: str, provider: str = None):
        """
        Initialize LLM client.
        
        Parameters
        ----------
        api_key : str
            API key for the provider
        provider : str, optional
            Provider type: "openai" or "huggingface". If None, uses config.PROVIDER
        """
        self.api_key = api_key
        self.provider = provider if provider is not None else PROVIDER
        
        if self.provider == "openai":
            if not OPENAI_AVAILABLE:
                raise ImportError("OpenAI package not installed. Run: pip install openai")
            self.client = OpenAI(api_key=api_key)
        elif self.provider == "huggingface":
            self.client = None  # Use requests directly
        else:
            raise ValueError(f"Unknown provider: {self.provider}. Must be 'openai' or 'huggingface'")
    
    def call(self, task: str, model: str, temperature: float, timeout: int) -> Dict[str, Any]:
        """
        Call the LLM API and return structured response.
        
        Parameters
        ----------
        task : str
            The prompt/task to send to the LLM
        model : str
            Model identifier
        temperature : float
            Sampling temperature
        timeout : int
            Timeout in seconds
            
        Returns
        -------
        dict
            Response with keys: result, full_explanation, feedback
        """
        if self.provider == "openai":
            return self._call_openai(task, model, temperature, timeout)
        elif self.provider == "huggingface":
            return self._call_huggingface(task, model, temperature, timeout)
    
    def _call_openai(self, task: str, model: str, temperature: float, timeout: int) -> Dict[str, Any]:
        """Call OpenAI API with structured output."""
        response = self.client.responses.parse(
            model=model,
            input=task,
            text_format=GradeResult,
            temperature=temperature,
            timeout=timeout
        )
        return response.output_parsed.model_dump()
    
    def _call_huggingface(self, task: str, model: str, temperature: float, timeout: int) -> Dict[str, Any]:
        """
        Call HuggingFace Inference API.
        
        Uses the standard text generation endpoint.
        """
        # Use provided model or default
        api_model = model if model and not model.startswith("gpt") else HF_DEFAULT_MODEL
        
        # Format API URL with model name
        api_url = HF_API_URL.format(model=api_model)
        
        # Add JSON instruction to ensure structured output
        json_instruction = (
            "\n\nIMPORTANT: You must respond with ONLY valid JSON in this exact format (no other text):\n"
            '{\n'
            '  "result": "pass",  // must be exactly "pass", "fail", or "error"\n'
            '  "full_explanation": "your detailed reasoning here",\n'
            '  "feedback": "concise student guidance here"\n'
            '}'
        )
        
        # Use the Hugging Face SDK (InferenceClient) when available. This handles
        # Router semantics and deployments (model:deployment) correctly.
        if not HUGGINGFACE_AVAILABLE or InferenceClient is None:
            raise ImportError("huggingface_hub is required for HuggingFace provider. Run: pip install huggingface_hub")

        try:
            client = InferenceClient(api_key=self.api_key)

            # model should be the full Router identifier, e.g. "HuggingFaceH4/zephyr-7b-beta:featherless-ai"
            api_model = model if model and not model.startswith("gpt") else HF_DEFAULT_MODEL

            completion = client.chat.completions.create(
                model=api_model,
                messages=[{"role": "user", "content": task + json_instruction}],
                temperature=temperature,
                max_tokens=2000,
            )

            # Extract text content robustly from the completion
            content = None
            try:
                # SDK objects may expose .choices with message objects
                choices = getattr(completion, "choices", None)
                if choices and len(choices) > 0:
                    first = choices[0]
                    msg = getattr(first, "message", None) or (first.get("message") if isinstance(first, dict) else None)
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        # content may itself be a dict with 'text'
                        if isinstance(content, dict) and "text" in content:
                            content = content["text"]
                    else:
                        content = getattr(msg, "content", None)

                # Fallback to dict-like access
                if content is None:
                    data = completion if isinstance(completion, dict) else None
                    if data and "choices" in data and len(data["choices"]) > 0:
                        c = data["choices"][0]
                        msg = c.get("message") if isinstance(c, dict) else None
                        if isinstance(msg, dict):
                            content = msg.get("content")
                    elif isinstance(completion, dict) and "generated_text" in completion:
                        content = completion["generated_text"]

                if content is None:
                    content = str(completion)

            except Exception:
                content = str(completion)

            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            # Parse JSON from content
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    raise ValueError(f"Could not parse JSON from HuggingFace response. Content: {content[:200]}")

            # Validate required fields
            required_fields = ["result", "full_explanation", "feedback"]
            missing = [f for f in required_fields if f not in result]
            if missing:
                raise ValueError(f"HuggingFace response missing required fields: {missing}. Got: {list(result.keys())}")

            # Normalize result
            if result["result"] not in ["pass", "fail", "error"]:
                rl = str(result["result"]).lower()
                if "pass" in rl:
                    result["result"] = "pass"
                elif "fail" in rl:
                    result["result"] = "fail"
                else:
                    result["result"] = "error"

            return result

        except Exception as e:
            # Surface useful Hugging Face SDK errors
            msg = str(e)
            if "404" in msg or "Not Found" in msg:
                raise Exception(f"HuggingFace model '{api_model}' not found or not deployed: {msg}")
            raise Exception(f"HuggingFace SDK call failed: {msg}")


# Export the exception for compatibility
__all__ = ['LLMClient', 'GradeResult', 'APITimeoutError']
