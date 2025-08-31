import os
import sys
from pathlib import Path

# Make local "src" importable without installing the package (useful for quick local runs / PyCharm)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # type: ignore
from smolagents import CodeAgent, OpenAIServerModel, WebSearchTool, Tool
from smolagents.memory import ActionStep, FinalAnswerStep, PlanningStep, AgentMemory


PROMPT = "给我一个 3 天东京行程，每天 2 个景点并给出理由。对于每个景点，请推荐一个附近的高分餐厅。"

# --- 1. 定义一个新的、具有更复杂逻辑的自定义工具类 ---
class AttractionInfoTool(Tool):
    """一个专门用于获取东京景点信息的自定义工具。"""
    name = "attraction_info_retriever"
    description = "获取东京特定景点的详细信息，如描述、区域和建议游玩时间。只用于获取景点信息，不能用于搜索餐厅。"
    inputs = {
        "attraction_name": {
            "type": "string",
            "description": "需要查询的景点名称，例如 '东京塔' 或 '浅草寺'。",
        }
    }
    output_type = "string"

    def __init__(self):
        super().__init__()
        self.knowledge_base = {
            "东京塔": "东京的标志性建筑，是一座位于港区的红色铁塔，可以俯瞰整个城市。建议傍晚去，可以同时看到日景和夜景。",
            "浅草寺": "东京最古老的寺庙之一，位于台东区，入口处的雷门灯笼非常有名。周围有很多传统小吃和商店。",
            "涩谷交叉路口": "世界上最繁忙的十字路口，位于涩谷区，是体验东京现代都市脉搏的绝佳地点。",
            "新宿御苑": "一个融合了日式、法式和英式风格的大型公园，位于新宿区，是赏樱和放松的好去处。",
            "明治神宫": "为纪念明治天皇和昭宪皇太后而建的神社，位于涩谷区，被大片宁静的森林环绕。",
            "秋叶原": "著名的电器街和动漫文化中心，位于千代田区，是动漫迷和游戏玩家的天堂。",
        }

    def forward(self, attraction_name: str) -> str:
        """工具的核心逻辑。"""
        print(f"\n[Custom Tool] AttractionInfoTool 被调用，查询景点: {attraction_name}")
        return self.knowledge_base.get(attraction_name, f"抱歉，我的知识库中没有关于'{attraction_name}'的信息。")


class MyCallbacks:
    """一个用于处理代理步骤回调的示例类。"""
    def on_planning_step(self, step: PlanningStep, agent: CodeAgent):
        print(f"\n[Callback] 代理 '{agent.name}' 正在执行计划步骤...")
        print(f"  - 计划内容: {step.plan[:100]}...")

    def on_action_step(self, step: ActionStep, agent: CodeAgent):
        print(f"\n[Callback] 代理 '{agent.name}' 正在执行动作步骤 {step.step_number}...")
        if step.tool_calls:
            tool_names = [tool.name for tool in step.tool_calls]
            print(f"  - 尝试调用: {tool_names}")

def validate_final_answer(final_answer: str | dict, memory: AgentMemory) -> bool:
    """一个更灵活的最终答案验证函数，可以处理字符串或字典。"""
    print("\n[Final Answer Check] 正在验证最终答案...")
    if isinstance(final_answer, str):
        is_valid = bool(final_answer)
    elif isinstance(final_answer, dict):
        is_valid = bool(final_answer)
    else:
        is_valid = False
    print(f"  - 答案是否有效: {is_valid}")
    return is_valid


def main() -> None:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    model_id = os.getenv("OPENAI_MODEL_ID", "gpt-4o-mini")

    if not api_key:
        return

    model = OpenAIServerModel(
        model_id=model_id, 
        api_base=api_base, 
        api_key=api_key,
        client_kwargs={
            "max_retries": 5, # 增加重试次数
            "timeout": 30.0, # 延长超时时间
        }
    )

    # 主代理现在同时拥有自定义工具和通用的网页搜索工具
    main_tools = [AttractionInfoTool(), WebSearchTool(max_results=5, engine="duckduckgo")]

    tokyo_trip_agent = CodeAgent(
        tools=main_tools,
        model=model,
        # managed_agents=[restaurant_finder_agent], # 暂时移除托管代理以简化流程
        verbosity_level=2,
        planning_interval=3,
        name="tokyo_trip_agent",
        description="生成包含景点和餐厅推荐的3日东京行程。",
        max_steps=20,
        return_full_result=True,
        instructions=(
            "你是一个旅行规划专家。你有两个工具：\n"
            "1. `attraction_info_retriever`: 用它来获取特定景点的详细信息。\n"
            "2. `web_search`: 用它来进行通用的网络搜索，比如查找高分餐厅。\n"
            "请先规划好行程，然后一步步完成任务。请使用中文回答。"
        ),
        step_callbacks={
            PlanningStep: MyCallbacks().on_planning_step,
            ActionStep: MyCallbacks().on_action_step,
        },
        final_answer_checks=[validate_final_answer],
    )

    print("--- 开始运行 Agent ---")
    run_result = tokyo_trip_agent.run(PROMPT, stream=False)
    print("\n--- Agent 运行结束 ---")

    print("\n=== 最终结果 ===\n")
    if run_result:
        print(f"状态: {run_result.state}")
        print(f"输出: \n{run_result.output}")
        print(f"\nToken 使用情况: {run_result.token_usage}")
        print(f"运行时间: {run_result.timing.duration:.2f}秒")


if __name__ == "__main__":
    main()
