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
from smolagents.memory import ActionStep, FinalAnswerStep, PlanningStep, AgentMemory


PROMPT = "给我一个 3 天东京行程，每天 2 个景点并给出理由。对于每个景点，请推荐一个附近的高分餐厅。"


class MyCallbacks:
    """
    一个用于处理代理步骤回调的示例类。
    您可以根据需要实现 on_{step_type}_step 方法。
    """

    def on_planning_step(self, step: PlanningStep, agent: CodeAgent):
        print(f"\n[Callback] 代理 '{agent.name}' 正在执行计划步骤...")
        print(f"  - 计划内容: {step.plan[:100]}...")
        print(f"  - Token 使用: {step.token_usage}")

    def on_action_step(self, step: ActionStep, agent: CodeAgent):
        print(f"\n[Callback] 代理 '{agent.name}' 正在执行动作步骤 {step.step_number}...")
        if step.tool_calls:
            tool_names = [tool.name for tool in step.tool_calls]
            print(f"  - 尝试调用工具或托管代理: {tool_names}")
            if "restaurant_finder" in tool_names:
                print("    (检测到调用餐厅助手) ")
        if step.observations:
            print(f"  - 观察结果: {step.observations[:100]}...")
        if step.error:
            print(f"  - 发生错误: {step.error}")

    def on_final_answer_step(self, step: FinalAnswerStep, agent: CodeAgent):
        print(f"\n[Callback] 代理 '{agent.name}' 准备生成最终答案...")
        print(f"  - 最终输出: {step.output}")


def validate_final_answer(final_answer: str, memory: AgentMemory) -> bool:
    """
    一个简单的最终答案验证函数。
    检查最终答案是否为非空字符串。
    """
    print("\n[Final Answer Check] 正在验证最终答案...")
    is_valid = isinstance(final_answer, str) and bool(final_answer)
    print(f"  - 答案是否有效: {is_valid}")
    return is_valid


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
        print("本脚本将使用 WebSearchTool（DuckDuckGo 抓取）与 OpenAIServerModel 组合。")
        print(f"PROMPT: {PROMPT}")
        return

    model = OpenAIServerModel(
        model_id=model_id,
        api_base=api_base,
        api_key=api_key,
    )

    # --- 定义托管代理（助手） ---
    restaurant_finder_agent = CodeAgent(
        tools=[WebSearchTool(max_results=5, engine="duckduckgo")],
        model=model,
        name="restaurant_finder",
        description="根据指定的地点，搜索附近的美食和餐厅。",
        instructions="你是一个美食搜索专家，请根据用户提供的地点，返回一个高评分的餐厅列表。",
        verbosity_level=0, # 通常我们不关心助手代理的详细日志
    )

    # --- 定义主代理 ---
    # 实例化回调类
    callbacks = MyCallbacks()

    # 主代理使用的工具
    main_tools = [WebSearchTool(max_results=10, engine="duckduckgo")]

    tokyo_trip_agent = CodeAgent(
        tools=main_tools,
        model=model,
        managed_agents=[restaurant_finder_agent], # <--- 在这里配置托管代理
        verbosity_level=2,
        stream_outputs=True,
        planning_interval=3,
        name="tokyo_trip_agent",
        description="Generate a 3-day Tokyo itinerary with attractions and restaurant recommendations.",
        max_steps=15, # 增加了步骤数以适应更复杂的任务
        return_full_result=True,
        instructions="你是一个旅行规划专家。你的主要任务是发现有趣的景点并制定合理的行程。为此，你可以使用 `WebSearchTool`。然而，你不是美食专家。对于所有的餐厅推荐，你**必须**通过调用 `restaurant_finder` 工具来委托给你的美食助手。这位助手是餐厅方面的专家，能提供最佳建议。**不要**使用你自己的 `WebSearchTool` 来搜索餐厅，那样得到的结果会比较差。请使用中文回答。",
        step_callbacks={
            PlanningStep: callbacks.on_planning_step,
            ActionStep: callbacks.on_action_step,
            FinalAnswerStep: callbacks.on_final_answer_step,
        },
        final_answer_checks=[validate_final_answer],
        use_structured_outputs_internally=False,
        additional_authorized_imports=["pandas"],
    )

    print("--- 开始运行 Agent ---")
    run_result = tokyo_trip_agent.run(PROMPT, stream=False)
    print("\n--- Agent 运行结束 ---")

    print("\n=== 最终结果 ===\n")
    if run_result:
        print(f"状态: {run_result.state}")
        print(f"输出: {run_result.output}")
        print(f"Token 使用情况: {run_result.token_usage}")
        print(f"运行时间: {run_result.timing.duration:.2f}秒")


if __name__ == "__main__":
    main()
