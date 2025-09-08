from smolagents import LiteLLMModel, DuckDuckGoSearchTool
from smolagents import CodeAgent

# 使用ollama api
model = LiteLLMModel(
    model_id="ollama/gemma3",
    # model_id="ollama/qwen3:latest",

    api_base="http://127.0.0.1:11434",
    api_key="ollama",
)

agent = CodeAgent(tools=[DuckDuckGoSearchTool()], model=model)

# 测试智能体
agent.run("What's the 20th number in the Fibonacci sequence?")
