"""
Async CodeAgent Example with Starlette

This example demonstrates how to use a CodeAgent in an async Starlette app,
running the agent in a background thread using anyio.to_thread.run_sync.

Backends
- HF Inference Providers (default): requires `HF_TOKEN` with available credits
- OpenAI-compatible (OpenAI / Ollama / LM Studio): set env to use OpenAI server

Env variables (optional)
- HF: `HF_TOKEN`, `HF_MODEL_ID`, `HF_PROVIDER`, `HF_BASE_URL`
- OpenAI-compatible: `SMOLAGENTS_BACKEND=openai|ollama`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`
"""

import os
import anyio.to_thread
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from smolagents import CodeAgent, InferenceClientModel, OpenAIServerModel


def _get_model():
    """Select model backend via env vars.

    Preference order:
    1) OpenAI-compatible if `SMOLAGENTS_BACKEND` in {openai, ollama} or OPENAI_* vars present
    2) HF Inference Providers (default)
    """
    backend = (os.getenv("SMOLAGENTS_BACKEND") or "").lower()
    wants_openai = backend in {"openai", "ollama"} or os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BASE_URL")
    if wants_openai:
        api_base = os.getenv("OPENAI_BASE_URL")
        # For Ollama, an API key is not enforced; using a placeholder is common
        api_key = os.getenv("OPENAI_API_KEY") or ("ollama" if (backend == "ollama" or (api_base and "11434" in api_base)) else None)
        # Reasonable defaults
        default_ollama_model = "llama3.1"
        default_openai_model = "gpt-4o-mini"
        model_id = os.getenv("OPENAI_MODEL") or (default_ollama_model if (api_base and "11434" in api_base) or backend == "ollama" else default_openai_model)
        return OpenAIServerModel(model_id=model_id, api_base=api_base, api_key=api_key)

    # Default: Hugging Face Inference Providers
    return InferenceClientModel(
        model_id=os.getenv("HF_MODEL_ID", "Qwen/Qwen2.5-Coder-32B-Instruct"),
        provider=os.getenv("HF_PROVIDER") or None,
        token=os.getenv("HF_TOKEN"),
        base_url=os.getenv("HF_BASE_URL") or None,
    )


# Create a simple agent instance (customize as needed)
def get_agent():
    return CodeAgent(
        model=_get_model(),
        tools=[],
    )


async def run_agent_in_thread(task: str):
    agent = get_agent()
    # The agent's run method is synchronous
    result = await anyio.to_thread.run_sync(agent.run, task)
    return result


async def run_agent_endpoint(request: Request):
    data = await request.json()
    task = data.get("task")
    if not task:
        return JSONResponse({"error": 'Missing "task" in request body.'}, status_code=400)
    try:
        result = await run_agent_in_thread(task)
        return JSONResponse({"result": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


routes = [
    Route("/run-agent", run_agent_endpoint, methods=["POST"]),
]

app = Starlette(debug=True, routes=routes)
