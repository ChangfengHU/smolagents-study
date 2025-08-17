import os
import sys
from pathlib import Path

# Make local "src" importable without installing the package (useful for quick local runs / PyCharm)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # type: ignore
from smolagents import CodeAgent, OpenAIServerModel, WebSearchTool


PROMPT = "给我一个 3 天东京行程，每天 2 个景点并给出理由"


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
        print("然后再次运行本脚本即可真正调用模型。\n")
        print("本脚本将使用 WebSearchTool（DuckDuckGo 抓取）与 OpenAIServerModel 组合。")
        print(f"PROMPT: {PROMPT}")
        return

    model = OpenAIServerModel(
        model_id=model_id,
        api_base=api_base,
        api_key=api_key,
    )

    # 使用无需额外依赖的 WebSearchTool（内部用 requests）
    tools = [WebSearchTool(max_results=10, engine="duckduckgo")]

    agent = CodeAgent(
        tools=tools,
        model=model,
        verbosity_level=1,
        stream_outputs=True,
        name="tokyo_trip_agent",
        description="Generate a 3-day Tokyo itinerary with 2 attractions per day and reasons.",
    )

    result = agent.run(PROMPT)

    print("\n=== 最终结果 ===\n")
    print(result)


if __name__ == "__main__":
    main()
