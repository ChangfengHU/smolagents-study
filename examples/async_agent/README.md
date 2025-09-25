# Async Applications with Agents

This example demonstrates how to use a `CodeAgent` from the `smolagents` library in an asynchronous Starlette web application.
The agent is executed in a background thread using `anyio.to_thread.run_sync`, allowing you to integrate synchronous agent logic into an async web server.

## Key Concepts

- **Starlette**: A lightweight ASGI framework for building async web apps.
- **anyio.to_thread.run_sync**: Runs blocking (sync) code in a thread, so it doesn't block the async event loop.
- **CodeAgent**: An agent from the `smolagents` library that can be used to solve tasks programmatically.

## How it works

- The Starlette app exposes a `/run-agent` endpoint that accepts a JSON payload with a `task` string.
- When a request is received, the agent is run in a background thread using `anyio.to_thread.run_sync`.
- The result is returned as a JSON response.

## Implementation Note

**Why use a background thread?** 

`CodeAgent.run()` executes Python code synchronously, which would block Starlette's async event loop if called directly. By offloading this synchronous operation to a separate thread with `anyio.to_thread.run_sync`, we maintain the application's responsiveness while the agent processes requests, ensuring optimal performance in high-concurrency scenarios.

## Usage

Choose a backend. If you saw a 402 Payment Required from Hugging Face Inference Providers, prefer the OpenAI-compatible route below.

### A) Hugging Face Inference Providers (default)

1) Install deps
```bash
pip install -e .  # install local smolagents
pip install starlette anyio uvicorn
```

2) Set token (requires sufficient credits)
```bash
export HF_TOKEN=your_hf_token
# Optional:
# export HF_MODEL_ID="Qwen/Qwen2.5-Coder-32B-Instruct"
# export HF_PROVIDER="hf-inference"
```

3) Run
```bash
cd examples/async_agent && uvicorn main:app --reload
```

### B) OpenAI-compatible (OpenAI / Ollama / LM Studio)

1) Install deps (OpenAI client)
```bash
pip install -e .
pip install starlette anyio uvicorn "smolagents[openai]"
```

2) Configure one of the following:

- OpenAI
```bash
export SMOLAGENTS_BACKEND=openai
export OPENAI_API_KEY=sk-...
# Optional: OPENAI_MODEL=gpt-4o-mini
```

- Ollama (local)
```bash
# Ensure Ollama is installed and a model is available:
#   brew install ollama && ollama run llama3.1
export SMOLAGENTS_BACKEND=ollama
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_MODEL=llama3.1
export OPENAI_API_KEY=ollama
```

3) Run
```bash
cd examples/async_agent && uvicorn main:app --reload
```

### Test the endpoint
```bash
curl -X POST http://127.0.0.1:8000/run-agent \
  -H 'Content-Type: application/json' \
  -d '{"task": "What is 2+2?"}'
```

## Files

- `main.py`: Main Starlette application with async endpoint using CodeAgent.
- `README.md`: This file.

---
This example is designed to be clear and didactic for users new to async Python and agent integration.
