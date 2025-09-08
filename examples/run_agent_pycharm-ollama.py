import os
import sys
from pathlib import Path

# Make local "src" importable without installing the package (useful for quick local runs / PyCharm)
#https://platform.openai.com/docs/pricing
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # type: ignore
from smolagents import CodeAgent, OpenAIServerModel, WebSearchTool, ToolCallingAgent
from smolagents.models import ChatMessageStreamDelta, LiteLLMModel

PROMPT = "请为我制定一个详细的3天杭州旅行计划。要求：1. 每天安排2个主要景点；2. 为每个景点提供选择理由；3. 包含天气查询和相应的建议；4. 推荐每个区域的特色餐厅；5. 提供交通建议。请使用工具查询相关信息，并生成结构化的行程表。"


def main() -> None:
    # Load .env if present
    load_dotenv()
     # gpt-5-nano	$0.05
    #  gpt-4.1-nano	$0.10
    #gpt-4o-mini	$0.15
    api_key = os.getenv("OPENAI_API_KEY")
    api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    model_id = os.getenv("OPENAI_MODEL_ID", "gpt-4.1-nano")
    # model_id = os.getenv("OPENAI_MODEL_ID", "gpt-3.5-turbo")
    # model_id = os.getenv("OPENAI_MODEL_ID", "gpt-4o-mini")
    # model_id = os.getenv("OPENAI_MODEL_ID", "gpt-5-nano-2025-08-07")

    # If OPENAI_API_KEY is missing, do a friendly dry-run instead of crashing
    if not api_key:
        print("[dry-run] 未检测到环境变量 OPENAI_API_KEY。请在 PyCharm 的 Run/Debug 配置里添加：")
        print("  OPENAI_API_KEY=<你的OpenAI密钥>")
        print("可选：OPENAI_API_BASE=https://api.openai.com/v1  OPENAI_MODEL_ID=gpt-4o-mini")
        print("然后再次运行本脚本即可真正调用模型。\n")
        print("本脚本将使用 WebSearchTool（DuckDuckGo 抓取）与 OpenAIServerModel 组合。")
        print(f"PROMPT: {PROMPT}")
        return

    # model = LiteLLMModel(
    #     model_id="ollama/gemma3",
    #     api_base="https://ollama.vyibc.com",
    #     api_key="ollama",
    # )

    model = LiteLLMModel(
        model_id="ollama/gemma3",
        # model_id="ollama/qwen3:latest",

        api_base="http://127.0.0.1:11434",
        api_key="ollama",
    )
    # 使用无需额外依赖的 WebSearchTool（内部用 requests）
    tools = [WebSearchTool(max_results=10, engine="duckduckgo")]

    agent = ToolCallingAgent(
        tools=tools,
        model=model,
        verbosity_level=1,
        stream_outputs=True,
        planning_interval=3,
        name="hangzhou_trip_agent",
        description="专业的杭州旅行规划助手，能够制定详细的3天行程安排，包括景点推荐、用餐建议和交通指南。",
        instructions="""你是一个专业的旅行规划助手。请用中文进行思考和回答。

在解决任务时，请按照以下步骤进行：
1. 在"思考："部分，用中文解释你的推理过程和要使用的工具
2. 在代码部分编写Python代码来执行任务
3. 在"观察："部分，用中文总结代码执行的结果
4. 最后用中文提供最终答案

请确保所有的思考过程、观察结果和最终答案都使用中文表达。""",
    )

    # result = agent.run(PROMPT)
    for step in agent.run(PROMPT, stream=True):
        if isinstance(step, ChatMessageStreamDelta):
            continue  # 跳过 ChatMessageStreamDelta 类型的步骤
        print(f"收到步骤: {step}")  # 🔥 最终接收到所有event
    print("\n=== 最终结果 ===\n")
    # print(result)


if __name__ == "__main__":
    main()
