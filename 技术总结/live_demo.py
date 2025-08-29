#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Rich Live组件完整演示
展示Live组件在AI流式输出中的各种应用场景
"""

import time
import random
from rich.live import Live
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn
from rich.table import Table
from rich.text import Text

class LiveDemo:
    """Rich Live组件完整演示"""
    
    def __init__(self):
        self.console = Console()
    
    def demo_basic_live(self):
        """基础Live使用 - 模拟AI生成文本"""
        print("🎯 Demo 1: 基础Live文本更新")
        print("=" * 40)
        
        with Live("", console=self.console, refresh_per_second=10) as live:
            content = ""
            ai_response = [
                "我正在", "分析", "你的", "问题", "...\n\n",
                "经过", "深入", "思考", "，我", "认为", "...\n\n",
                "最终", "的", "解决", "方案", "是", "..."
            ]
            
            for word in ai_response:
                content += word
                # 实时更新显示内容
                live.update(Panel(content, title="AI思考中...", border_style="blue"))
                time.sleep(1)
        
        print("\n✅ 演示完成！\n")
    
    def demo_markdown_live(self):
        """Markdown Live渲染 - 模拟smolagents场景"""
        print("🎯 Demo 2: Markdown实时渲染（smolagents模式）")
        print("=" * 40)
        
        with Live("", console=self.console, vertical_overflow="visible") as live:
            plan_content = ""
            
            # 模拟AI逐步生成计划的Markdown内容
            plan_steps = [
                "# 任务执行计划\n\n",
                "## 分析阶段\n",
                "- 理解用户需求\n",
                "- 确定解决路径\n\n",
                "## 执行阶段\n",
                "### 步骤1：数据收集\n",
                "- 使用搜索工具获取相关信息\n",
                "- 筛选和验证数据准确性\n\n",
                "### 步骤2：数据分析\n", 
                "- 运行统计分析\n",
                "- 识别关键模式和趋势\n\n",
                "### 步骤3：结果生成\n",
                "- 整理分析结果\n",
                "- 生成最终报告\n\n",
                "## 预期输出\n",
                "完整的数据分析报告，包含图表和结论。"
            ]
            
            for step in plan_steps:
                plan_content += step
                # 🔥 关键：使用Markdown渲染，就像smolagents一样
                live.update(Markdown(plan_content))
                time.sleep(0.5)
        
        print("\n✅ Markdown演示完成！\n")
    
    def demo_progress_live(self):
        """进度条Live更新"""
        print("🎯 Demo 3: 进度条实时更新")
        print("=" * 40)
        
        with Live("", console=self.console) as live:
            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            ) as progress:
                
                task = progress.add_task("处理数据中...", total=100)
                
                for i in range(100):
                    # 模拟处理过程
                    time.sleep(0.05)
                    progress.update(task, advance=1)
                    
                    # 实时更新Live显示
                    live.update(progress)
        
        print("\n✅ 进度条演示完成！\n")
    
    def demo_table_live(self):
        """表格Live更新 - 模拟实时数据"""
        print("🎯 Demo 4: 表格实时更新")
        print("=" * 40)
        
        with Live("", console=self.console, refresh_per_second=2) as live:
            for i in range(10):
                table = Table(title=f"实时数据监控 - 第{i+1}秒")
                table.add_column("指标", style="cyan")
                table.add_column("当前值", style="green")
                table.add_column("变化", style="red")
                
                # 模拟实时数据
                cpu_usage = random.randint(20, 80)
                memory_usage = random.randint(40, 90)
                network_speed = random.randint(100, 1000)
                
                table.add_row("CPU使用率", f"{cpu_usage}%", "+2%")
                table.add_row("内存使用率", f"{memory_usage}%", "-1%")
                table.add_row("网络速度", f"{network_speed}MB/s", "+15MB/s")
                
                live.update(table)
                time.sleep(1)
        
        print("\n✅ 表格演示完成！\n")
    
    def demo_ai_stream_simulation(self):
        """完整AI流式输出模拟 - 最接近smolagents的实现"""
        print("🎯 Demo 5: AI流式输出完整模拟")
        print("=" * 40)
        
        def simulate_ai_stream():
            """模拟AI流式响应生成器"""
            responses = [
                "我需要", "分析", "这个", "复杂", "的", "问题", "。\n\n",
                "首先", "，让", "我", "制定", "一个", "详细", "的", "计划", "：\n\n",
                "**步骤", "1**", "：", "收集", "相关", "信息\n",
                "**步骤", "2**", "：", "分析", "数据", "模式\n", 
                "**步骤", "3**", "：", "生成", "解决", "方案\n\n",
                "现在", "开始", "执行", "这些", "步骤", "...\n"
            ]
            
            for response in responses:
                yield response
        
        # 模拟smolagents的实现方式
        with Live("", console=self.console, vertical_overflow="visible") as live:
            accumulated_content = ""
            
            for chunk in simulate_ai_stream():
                accumulated_content += chunk
                
                # 🔥 核心：累积内容并实时渲染Markdown
                live.update(Panel(
                    Markdown(accumulated_content),
                    title="🤖 AI智能体思考中...",
                    border_style="green"
                ))
                
                time.sleep(0.2)
        
        print("\n✅ AI流式输出演示完成！\n")
    
    def demo_smolagents_exact_simulation(self):
        """精确模拟smolagents的Live使用方式"""
        print("🎯 Demo 6: 精确模拟smolagents实现")
        print("=" * 40)
        
        def mock_model_generate_stream():
            """模拟model.generate_stream()的返回"""
            class MockEvent:
                def __init__(self, content):
                    self.content = content
                    self.token_usage = None
            
            plan_fragments = [
                "# 任务分析\n\n",
                "根据用户的需求，", "我需要执行", "以下步骤：\n\n",
                "## 第一步：", "信息收集\n",
                "- 搜索相关", "资料\n",
                "- 验证信息", "准确性\n\n",
                "## 第二步：", "数据分析\n", 
                "- 处理收集到的", "数据\n",
                "- 提取关键", "信息\n\n",
                "## 第三步：", "生成结果\n",
                "- 整理分析", "结果\n",
                "- 形成最终", "报告\n\n",
                "<end_plan>"
            ]
            
            for fragment in plan_fragments:
                if fragment != "<end_plan>":
                    yield MockEvent(fragment)
                time.sleep(0.3)
        
        # 精确模拟smolagents的实现
        stream_outputs = True
        
        if stream_outputs:
            plan_message_content = ""
            output_stream = mock_model_generate_stream()
            
            print("开始生成规划...")
            with Live("", console=self.console, vertical_overflow="visible") as live:
                for event in output_stream:
                    if event.content is not None:
                        plan_message_content += event.content
                        # 🔥 这就是smolagents的核心逻辑
                        live.update(Markdown(plan_message_content))
        
        print("\n✅ smolagents模拟演示完成！\n")
    
    def demo_comparison(self):
        """对比演示：传统print vs Live"""
        print("🎯 Demo 7: 传统print vs Live对比")
        print("=" * 40)
        
        # 传统print方式
        print("【传统print方式】")
        content = ""
        words = ["正在", "分析", "问题", "并", "生成", "解决", "方案"]
        
        for word in words:
            content += word
            print(f"传统方式: {content}")
            time.sleep(0.5)
        
        print("\n" + "="*30 + "\n")
        
        # Live方式
        print("【Live方式 - 同一位置更新】")
        content = ""
        
        with Live("", console=self.console) as live:
            for word in words:
                content += word
                live.update(f"Live方式: {content}")
                time.sleep(0.5)
        
        print("\n✅ 对比演示完成！可以看出Live方式更加清洁\n")
    
    def run_all_demos(self):
        """运行所有演示"""
        print("🚀 Rich Live组件完整演示")
        print("=" * 50)
        
        demos = [
            ("基础Live使用", self.demo_basic_live),
            ("Markdown实时渲染", self.demo_markdown_live),
            ("进度条更新", self.demo_progress_live),
            ("表格实时更新", self.demo_table_live),
            ("AI流式输出模拟", self.demo_ai_stream_simulation),
            ("smolagents精确模拟", self.demo_smolagents_exact_simulation),
            ("对比演示", self.demo_comparison),
        ]
        
        for i, (name, demo_func) in enumerate(demos, 1):
            print(f"\n🎬 第{i}个演示: {name}")
            demo_func()
            
            if i < len(demos):
                input("按Enter继续下一个演示...")
        
        print("🎉 所有演示完成！")
        print("\n📝 总结:")
        print("- Live组件实现了在同一位置更新内容")
        print("- 配合Markdown可以实现富文本实时渲染") 
        print("- 相比传统print，Live提供了更好的用户体验")
        print("- smolagents使用Live来展示AI的思考过程")


def main():
    """主函数"""
    print("🌟 Rich Live组件演示程序")
    print("🎯 展示Live在AI流式输出中的应用")
    print("📝 基于smolagents源码分析")
    print("=" * 50)
    
    demo = LiveDemo()
    
    try:
        demo.run_all_demos()
    except KeyboardInterrupt:
        print("\n\n⏸️ 演示被用户中断")
    except Exception as e:
        print(f"\n\n❌ 演示过程中出错：{e}")


if __name__ == "__main__":
    main()