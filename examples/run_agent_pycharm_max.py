# !/usr/bin/env python
# -*- coding: utf-8 -*-

"""
smolagents CodeAgent 完整功能演示
包含所有可用参数和回调机制
用于调试和学习源码
"""

import os
from smolagents import CodeAgent, Tool
from smolagents.models import OpenAIServerModel
from smolagents.monitoring import LogLevel
from smolagents.memory import ActionStep, PlanningStep, FinalAnswerStep, TaskStep
from smolagents.tools import Tool
from dotenv import load_dotenv  # type: ignore
from smolagents import CodeAgent, OpenAIServerModel, WebSearchTool

import time

# 设置OpenAI API



def create_custom_tools():
    """创建自定义工具用于测试"""

    # 工具1：天气查询工具
    class WeatherTool(Tool):
        name = "weather_query"
        description = "查询指定城市的天气信息"
        inputs = {
            "city": {"type": "string", "description": "城市名称"}
        }
        output_type = "string"

        def forward(self, city: str) -> str:
            '''查询城市天气信息'''
            import random
            weather_conditions = ["晴天", "多云", "小雨", "阴天"]
            temperature = random.randint(15, 30)
            condition = random.choice(weather_conditions)
            return f"{city}的天气：{condition}，温度{temperature}°C"

    # 工具2：景点推荐工具
    class AttractionTool(Tool):
        name = "attraction_recommender"
        description = "推荐指定城市的热门景点"
        inputs = {
            "city": {"type": "string", "description": "城市名称"},
            "category": {"type": "string", "description": "景点类型", "default": "all", "nullable": True}
        }
        output_type = "string"

        def forward(self, city: str, category: str = "all") -> str:
            '''推荐城市景点'''
            tokyo_attractions = {
                "cultural": ["浅草寺", "明治神宫", "东京国立博物馆"],
                "modern": ["东京塔", "晴空塔", "涩谷十字路口"],
                "nature": ["上野公园", "皇居东御苑", "新宿御苑"],
                "shopping": ["银座", "原宿", "秋叶原"]
            }

            if city.lower() == "tokyo" or city == "东京":
                if category == "all":
                    all_attractions = []
                    for cat_attractions in tokyo_attractions.values():
                        all_attractions.extend(cat_attractions)
                    return f"东京热门景点：{', '.join(all_attractions[:6])}"
                else:
                    attractions = tokyo_attractions.get(category, ["暂无此类型景点"])
                    return f"东京{category}景点：{', '.join(attractions)}"
            else:
                return f"暂时只支持东京的景点推荐"

    # 工具3：餐厅推荐工具
    class RestaurantTool(Tool):
        name = "restaurant_finder"
        description = "查找指定区域的餐厅推荐"
        inputs = {
            "area": {"type": "string", "description": "区域名称"},
            "cuisine_type": {"type": "string", "description": "料理类型", "default": "japanese", "nullable": True}
        }
        output_type = "string"

        def forward(self, area: str, cuisine_type: str = "japanese") -> str:
            '''查找餐厅推荐'''
            restaurants = {
                "shibuya": ["一兰拉面", "寿司大", "烤肉横丁"],
                "shinjuku": ["思い出横丁", "新宿高岛屋餐厅街", "歌舞伎町美食"],
                "ginza": ["银座寿司", "高级和牛店", "米其林餐厅"]
            }

            area_restaurants = restaurants.get(area.lower(), ["当地特色餐厅"])
            return f"{area}地区{cuisine_type}料理推荐：{', '.join(area_restaurants)}"

    return [WeatherTool(), AttractionTool(), RestaurantTool()]


def create_comprehensive_callbacks():
    """创建全面的回调函数"""

    def detailed_action_callback(memory_step: ActionStep, agent=None):
        """详细的动作步骤回调"""
        print(f"\n🔧 [动作回调] 步骤 #{memory_step.step_number} 完成")
        print(f"   步骤类型: {type(memory_step).__name__}")

        # 显示工具调用信息
        if hasattr(memory_step, 'tool_calls') and memory_step.tool_calls:
            print(f"   工具调用数量: {len(memory_step.tool_calls)}")
            for i, tool_call in enumerate(memory_step.tool_calls, 1):
                print(f"     工具{i}: {tool_call.name}")
                if tool_call.arguments:
                    print(f"       参数: {tool_call.arguments}")

        # 显示代码执行信息
        if hasattr(memory_step, 'code_action') and memory_step.code_action:
            code_lines = memory_step.code_action.count('\n') + 1
            print(f"   执行代码行数: {code_lines}")

        # 显示观察结果
        if hasattr(memory_step, 'observations') and memory_step.observations:
            obs_length = len(memory_step.observations)
            print(f"   观察结果长度: {obs_length} 字符")

        # 显示时间信息
        if hasattr(memory_step, 'timing') and memory_step.timing:
            if memory_step.timing.end_time and memory_step.timing.start_time:
                duration = memory_step.timing.end_time - memory_step.timing.start_time
                print(f"   执行时间: {duration:.2f}秒")

        # 显示Token使用
        if hasattr(memory_step, 'token_usage') and memory_step.token_usage:
            print(
                f"   Token使用: 输入{memory_step.token_usage.input_tokens}, 输出{memory_step.token_usage.output_tokens}")

        # 检查是否是最终答案
        if hasattr(memory_step, 'is_final_answer') and memory_step.is_final_answer:
            print(f"   🎯 这是最终答案步骤！")

    def planning_callback(memory_step: PlanningStep, agent=None):
        """规划步骤回调"""
        print(f"\n📋 [规划回调] 规划步骤完成")
        print(f"   规划内容长度: {len(memory_step.plan)} 字符")

        if memory_step.token_usage:
            print(
                f"   规划Token使用: 输入{memory_step.token_usage.input_tokens}, 输出{memory_step.token_usage.output_tokens}")

        if hasattr(memory_step, 'timing') and memory_step.timing:
            if memory_step.timing.end_time and memory_step.timing.start_time:
                duration = memory_step.timing.end_time - memory_step.timing.start_time
                print(f"   规划时间: {duration:.2f}秒")

        # 显示规划内容摘要
        plan_preview = memory_step.plan[:200] + "..." if len(memory_step.plan) > 200 else memory_step.plan
        print(f"   规划预览: {plan_preview}")

    def final_answer_callback(memory_step: FinalAnswerStep, agent=None):
        """最终答案回调"""
        print(f"\n🎉 [最终答案回调] 任务完成！")
        print(f"   答案类型: {type(memory_step.output)}")

        if isinstance(memory_step.output, str):
            answer_length = len(memory_step.output)
            print(f"   答案长度: {answer_length} 字符")

            # 显示答案预览
            answer_preview = memory_step.output[:300] + "..." if len(memory_step.output) > 300 else memory_step.output
            print(f"   答案预览: {answer_preview}")

    def performance_monitor(memory_step, agent=None):
        """性能监控回调"""
        if hasattr(memory_step, 'timing') and memory_step.timing:
            if memory_step.timing.end_time and memory_step.timing.start_time:
                duration = memory_step.timing.end_time - memory_step.timing.start_time

                if duration > 5.0:
                    print(f"   ⚠️  性能警告: 步骤执行时间过长 ({duration:.2f}秒)")
                elif duration > 10.0:
                    print(f"   🚨 严重性能警告: 步骤执行时间严重超长 ({duration:.2f}秒)")

    def memory_tracker(memory_step, agent=None):
        """内存跟踪回调"""
        if agent and hasattr(agent, 'memory'):
            total_steps = len(agent.memory.steps)
            print(f"   📊 内存状态: 总步骤数 {total_steps}")

            # 统计不同类型的步骤
            step_types = {}
            for step in agent.memory.steps:
                step_type = type(step).__name__
                step_types[step_type] = step_types.get(step_type, 0) + 1

            print(f"   步骤类型统计: {step_types}")

    def state_tracker(memory_step, agent=None):
        """状态跟踪回调"""
        if agent and hasattr(agent, 'state'):
            state_keys = list(agent.state.keys())
            if state_keys:
                print(f"   🗂️  代理状态变量: {state_keys}")

    return {
        ActionStep: [detailed_action_callback, performance_monitor, memory_tracker, state_tracker],
        PlanningStep: [planning_callback, performance_monitor],
        FinalAnswerStep: [final_answer_callback],
    }


def create_final_answer_checks():
    """创建最终答案验证函数"""

    def check_itinerary_completeness(final_answer, memory):
        """检查行程是否完整"""
        answer_str = str(final_answer).lower()
        required_elements = ["day 1", "day 2", "day 3", "attraction", "reason"]

        missing_elements = [elem for elem in required_elements if elem not in answer_str]

        if missing_elements:
            print(f"❌ 行程完整性检查失败，缺少: {missing_elements}")
            return False
        else:
            print("✅ 行程完整性检查通过")
            return True

    def check_answer_length(final_answer, memory):
        """检查答案长度是否合理"""
        answer_length = len(str(final_answer))

        if answer_length < 500:
            print(f"❌ 答案长度检查失败，太短: {answer_length} 字符")
            return False
        elif answer_length > 5000:
            print(f"❌ 答案长度检查失败，太长: {answer_length} 字符")
            return False
        else:
            print(f"✅ 答案长度检查通过: {answer_length} 字符")
            return True

    def check_attractions_count(final_answer, memory):
        """检查景点数量"""
        answer_str = str(final_answer).lower()
        attraction_indicators = answer_str.count("attraction") + answer_str.count("景点")

        if attraction_indicators < 6:  # 3天每天2个景点
            print(f"❌ 景点数量检查失败，发现 {attraction_indicators} 个景点指示")
            return False
        else:
            print(f"✅ 景点数量检查通过，发现 {attraction_indicators} 个景点指示")
            return True

    return [check_itinerary_completeness, check_answer_length, check_attractions_count]


def main():
    """主函数 - 创建功能完整的CodeAgent"""
    # Load .env if present
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    # 创建模型
    model = OpenAIServerModel(
        model_id="gpt-5-nano",
        api_base="https://api.openai.com/v1",
        api_key=api_key,
    )

    # 创建工具
    # tools = create_custom_tools()
    tools = [WebSearchTool(max_results=10, engine="duckduckgo")]

    # 创建回调
    callbacks = create_comprehensive_callbacks()

    # 创建最终答案检查
    final_checks = create_final_answer_checks()

    print("🚀 创建功能完整的CodeAgent...")
    print("📋 包含的功能:")
    print("   ✅ 自定义工具 (天气、景点、餐厅)")
    print("   ✅ 完整回调系统 (动作、规划、最终答案)")
    print("   ✅ 性能监控")
    print("   ✅ 内存跟踪")
    print("   ✅ 状态监控")
    print("   ✅ 最终答案验证")
    print("   ✅ 流式输出")
    print("   ✅ 规划间隔")
    print("   ✅ 托管代理支持")
    print("   ✅ 额外授权导入")
    print()

    # 创建功能完整的CodeAgent
    agent = CodeAgent(
        # 核心参数
        tools=tools,
        model=model,

        # 提示和指令
        description="专业的杭州旅行规划助手，能够制定详细的3天行程安排，包括景点推荐、用餐建议和交通指南。",
        instructions="""你是一个专业的旅行规划助手。请用中文进行思考和回答。

        在解决任务时，请按照以下步骤进行：
        1. 在"思考："部分，用中文解释你的推理过程和要使用的工具
        2. 在代码部分编写Python代码来执行任务
        3. 在"观察："部分，用中文总结代码执行的结果
        4. 最后用中文提供最终答案

        请确保所有的思考过程、观察结果和最终答案都使用中文表达。""",

        # 执行控制
        max_steps=50,  # 增加最大步数以支持更复杂的任务
        planning_interval=2,  # 每2步进行一次规划

        # 输出控制
        verbosity_level=LogLevel.DEBUG,  # 最详细的日志级别
        stream_outputs=True,  # 启用流式输出
        return_full_result=True,  # 返回完整结果对象

        # 代理身份
        name="tokyo_expert_agent",
        provide_run_summary=True,  # 提供运行摘要

        # 回调和验证
        step_callbacks=callbacks,  # 完整的回调系统
        final_answer_checks=final_checks,  # 最终答案验证

        # 代码执行相关
        additional_authorized_imports=[
            "requests", "json", "datetime", "random", "re", "math",
            "collections", "itertools", "functools", "urllib"
        ],  # 额外授权的导入模块
        executor_type="local",  # 本地执行器
        max_print_outputs_length=2000,  # 打印输出最大长度
        use_structured_outputs_internally=False,  # 不使用结构化输出（更适合调试）
        code_block_tags="markdown",  # 使用markdown代码块标签

        # 工具相关
        add_base_tools=True,  # 添加基础工具
    )

    # 设置额外状态变量（用于测试状态跟踪）
    agent.state.update({
        "user_preferences": "喜欢诗词歌赋 才子佳人",
        "budget": "中等预算",
        "travel_style": "深度游",
        "language": "中文"
    })

    print("🎯 开始执行任务...")
    print("=" * 60)

    # 复杂任务，能触发多种功能
    complex_task = """
请为我制定一个详细的3天杭州旅行计划。要求：

1. 每天安排2个主要景点
2. 为每个景点提供选择理由
3. 包含天气查询和相应的建议
4. 推荐每个区域的特色餐厅
5. 提供交通建议
6. 考虑文化体验和现代科技的平衡

请使用工具查询相关信息，并生成结构化的行程表。
    """

    try:
        # 执行任务（流式模式）
        result = agent.run(
            task=complex_task,
            stream=False,  # 设为False以获得完整结果
            reset=True,
            return_full_result=True,
        )

        print("\n" + "=" * 60)
        print("🎉 任务执行完成!")
        print("=" * 60)

        if hasattr(result, 'output'):
            print(f"\n📋 最终输出:")
            print("-" * 40)
            print(result.output)

        if hasattr(result, 'token_usage') and result.token_usage:
            print(f"\n📊 Token使用统计:")
            print(f"   输入Token: {result.token_usage.input_tokens}")
            print(f"   输出Token: {result.token_usage.output_tokens}")
            print(f"   总计Token: {result.token_usage.input_tokens + result.token_usage.output_tokens}")

        if hasattr(result, 'timing'):
            duration = result.timing.end_time - result.timing.start_time
            print(f"\n⏱️  执行时间: {duration:.2f}秒")

        if hasattr(result, 'steps'):
            print(f"\n📈 执行步骤: 总共{len(result.steps)}个步骤")
            step_types = {}
            for step in result.steps:
                step_type = step.get('type', 'unknown')
                step_types[step_type] = step_types.get(step_type, 0) + 1
            print(f"   步骤类型统计: {step_types}")

        print(f"\n✅ 任务状态: {result.state}")

    except Exception as e:
        print(f"\n❌ 执行过程中出现错误: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 显示代理的最终状态
        print(f"\n🔍 代理最终状态:")
        print(f"   步骤编号: {agent.step_number}")
        print(f"   状态变量: {list(agent.state.keys())}")
        print(f"   内存步骤数: {len(agent.memory.steps)}")

        # 显示性能回放
        print(f"\n🎬 执行回放:")
        agent.replay(detailed=False)


if __name__ == "__main__":
    main()
"""
运行结果：

  🎯 新增功能

  1. 自定义工具: 天气查询、景点推荐、餐厅查找
  2. 完整回调系统:
    - 动作步骤详细回调
    - 规划步骤回调
    - 最终答案回调
    - 性能监控回调
    - 内存跟踪回调
    - 状态跟踪回调
  3. 最终答案验证:
    - 行程完整性检查
    - 答案长度验证
    - 景点数量验证
  4. 完整参数配置:
    - max_steps=15: 更多步骤支持复杂任务
    - planning_interval=2: 每2步规划一次
    - verbosity_level=LogLevel.DEBUG: 最详细日志
    - return_full_result=True: 返回完整结果
    - additional_authorized_imports: 额外导入权限
    - add_base_tools=True: 添加基础工具
  5. 状态管理: 预设状态变量用于测试
  6. 复杂任务: 设计的任务能触发多种功能
  7. 详细统计: Token使用、执行时间、步骤统计

  这样你就能体验到smolagents的完整功能，包括所有回调机制、性能监控、状态跟踪等特性！
  

"""