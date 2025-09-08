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
from smolagents import CodeAgent, OpenAIServerModel, WebSearchTool
from smolagents.models import ChatMessageStreamDelta


PROMPT = "请为我制定一个详细的3天杭州旅行计划。要求：1. 每天安排2个主要景点；2. 为每个景点提供选择理由；3. 包含天气查询和相应的建议；4. 推荐每个区域的特色餐厅；5. 提供交通建议。请使用工具查询相关信息，并生成结构化的行程表。"


def main() -> None:
    # Load .env if present
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    model_id = os.getenv("OPENAI_MODEL_ID", "gpt-4o-mini")

    # If OPENAI_API_KEY is missing, do a friendly dry-run instead of crashing
    if not api_key:
        print("[dry-run] 未检测到环境变量 OPENAI_API_KEY。请在 PyCharm 的 Run/Debug 配置里添加：")
        print("  OPENAI_API_KEY=<你的OpenAI密钥>")
        print("可选：OPENAI_API_BASE=https://api.openai.com/v1  OPENAI_MODEL_ID=gpt-4o-mini")
        print("然后再次运行本脚本即可真正调用模型.\n")
        print("本脚本将使用一个主 Agent 和多个子 Agent 协作完成任务。")
        print(f"PROMPT: {PROMPT}")
        return

    model = OpenAIServerModel(
        model_id=model_id,
        api_base=api_base,
        api_key=api_key,
    )

    # Define the tool that sub-agents will use
    search_tool = WebSearchTool(max_results=5, engine="duckduckgo")

    # Define Sub-Agents
    weather_agent = CodeAgent(
        tools=[search_tool],
        model=model,
        name="weather_reporter",
        description="查询杭州未来3天的天气预报并提供建议。",
        instructions="你是一个天气预报员。使用网页搜索工具查询杭州未来3天的天气预报。总结天气情况并提供穿衣建议。",
        stream_outputs=False,  # Sub-agents should return the final result directly
    )

    attraction_agent = CodeAgent(
        tools=[search_tool],
        model=model,
        name="attraction_specialist",
        description="研究并提供杭州的旅游景点信息。",
        instructions="你是一位专门研究景点的旅行专家。使用网页搜索工具查找6个适合3日游的杭州热门景点。为每个景点提供游览理由。",
        stream_outputs=False,
    )

    restaurant_agent = CodeAgent(
        tools=[search_tool],
        model=model,
        name="food_critic",
        description="推荐杭州当地的特色餐厅。",
        instructions="你是一位美食评论家。请为杭州的以下每个区域推荐一家特色餐厅：西湖景区、灵隐寺附近、河坊街附近。",
        stream_outputs=False,
    )

    transport_agent = CodeAgent(
        tools=[search_tool],
        model=model,
        name="transport_advisor",
        description="提供杭州市内的交通建议。",
        instructions="你是一位交通顾问。提供在杭州市内出行的建议（例如，地铁、公交、出租车、共享单车等）。",
        stream_outputs=False,
    )

    # Define the Main Agent (Orchestrator)
    # This agent does not have direct access to tools, it uses the sub-agents.
    main_agent = CodeAgent(
        tools=[],
        managed_agents=[weather_agent, attraction_agent, restaurant_agent, transport_agent],
        model=model,
        name="trip_planner_manager",
        description="一个管理代理，通过将任务委派给专门的子代理来规划行程。",
        instructions="""你是一个旅行规划经理。你的工作是通过将任务委派给你的专家团队来为杭州制定一个详细的3天旅行计划。
你没有任何直接的工具，你必须使用你的团队成员。

1. 首先，调用 weather_reporter 获取天气预报。
2. 然后，调用 attraction_specialist 获取景点列表。
3. 接着，调用 restaurant_agent 获取餐厅推荐。
4. 之后，调用 transport_advisor 获取交通建议。
5. 最后，将你团队成员提供的所有信息整合成一个连贯且结构化的3日行程表。
请用中文提供最终的计划。
""",
        verbosity_level=1,
        stream_outputs=True,  # Stream the output of the main agent
    )

    for step in main_agent.run(PROMPT, stream=True):
        if isinstance(step, ChatMessageStreamDelta):
            continue
        print(f"收到步骤: {step}")
    print("\n=== 最终结果 ===\n")



if __name__ == "__main__":
    main()
