#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
智能体控制台调试演示
展示smolagents中控制台输出的各种情况和调试方法
"""

import sys
import time
from io import StringIO
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

# 尝试导入smolagents组件，如果不可用则使用模拟版本
try:
    from smolagents.monitoring import AgentLogger, LogLevel
    SMOLAGENTS_AVAILABLE = True
except ImportError:
    SMOLAGENTS_AVAILABLE = False
    print("⚠️ smolagents未安装，使用模拟版本")
    
    # 模拟smolagents的组件
    from enum import IntEnum
    
    class LogLevel(IntEnum):
        ERROR = 40
        WARNING = 30  
        INFO = 20
        DEBUG = 10
    
    class AgentLogger:
        def __init__(self, level=LogLevel.INFO, console=None):
            self.level = level
            if console is None:
                self.console = Console(highlight=False)
            else:
                self.console = console
        
        def log(self, *args, level=LogLevel.INFO, **kwargs):
            if level >= self.level:
                self.console.print(*args, **kwargs)


class ConsoleDebugDemo:
    """智能体控制台调试演示"""
    
    def demo_logger_levels(self):
        """演示不同日志级别的输出"""
        print("🎯 Demo 1: 日志级别过滤演示")
        print("=" * 40)
        
        # 创建不同级别的logger
        loggers = {
            "ERROR级": AgentLogger(level=LogLevel.ERROR),
            "INFO级": AgentLogger(level=LogLevel.INFO),
            "DEBUG级": AgentLogger(level=LogLevel.DEBUG)
        }
        
        for name, logger in loggers.items():
            print(f"\n【{name}别Logger输出】")
            logger.log("这是ERROR消息", level=LogLevel.ERROR, style="red bold")
            logger.log("这是INFO消息", level=LogLevel.INFO, style="blue")
            logger.log("这是DEBUG消息", level=LogLevel.DEBUG, style="dim")
            
            # 显示哪些消息被过滤了
            print(f"  当前级别: {logger.level.name}")
            filtered = []
            if LogLevel.ERROR > logger.level: filtered.append("ERROR")
            if LogLevel.INFO > logger.level: filtered.append("INFO") 
            if LogLevel.DEBUG > logger.level: filtered.append("DEBUG")
            
            if filtered:
                print(f"  被过滤: {', '.join(filtered)}")
            else:
                print("  所有消息都显示")
    
    def demo_console_capture(self):
        """演示控制台输出捕获"""
        print("\n🎯 Demo 2: 控制台输出捕获")
        print("=" * 40)
        
        # 正常输出到屏幕
        normal_console = Console()
        print("\n【正常输出到屏幕】")
        normal_console.print("✅ 这条消息显示在屏幕上", style="green")
        
        # 捕获输出到内存
        captured_output = StringIO()
        capture_console = Console(file=captured_output)
        
        print("\n【输出被捕获到内存（屏幕看不到）】")
        capture_console.print("❌ 这条消息被捕获，用户看不到", style="red")
        capture_console.print("❌ 这也是被捕获的消息", style="blue")
        
        print("\n【显示捕获的内容】")
        captured_content = captured_output.getvalue()
        print(f"内存中捕获的内容:\n{captured_content}")
        
        # 演示为什么会看不到输出
        print("\n💡 这就是为什么有时候看不到智能体输出的原因！")
    
    def demo_live_console_interaction(self):
        """演示Live组件与控制台的交互"""
        print("\n🎯 Demo 3: Live组件与控制台交互")
        print("=" * 40)
        
        # 创建共享控制台
        shared_console = Console()
        logger = AgentLogger(console=shared_console)
        
        print("\n【Live组件活跃期间】")
        print("注意观察：Live更新时，其他输出可能被覆盖")
        
        # 模拟smolagents中Live的使用
        with Live("", console=shared_console, vertical_overflow="visible") as live:
            content = ""
            steps = [
                "# 🤖 智能体规划中\n\n",
                "## 📋 第一步：分析任务\n",
                "- 理解用户需求\n",
                "- 确定解决路径\n\n",
                "## 🔧 第二步：制定方案\n",
                "- 选择合适的工具\n",
                "- 规划执行顺序\n\n",
                "## ✅ 规划完成\n",
                "准备开始执行...\n"
            ]
            
            for i, step in enumerate(steps):
                content += step
                live.update(Panel(
                    Markdown(content),
                    title=f"🤖 规划进度 {i+1}/{len(steps)}",
                    border_style="green"
                ))
                time.sleep(1)
        
        # Live结束后，logger可以正常输出
        logger.log("✅ Live演示完成！现在可以看到正常输出了", style="green bold")
    
    def demo_output_debugging_techniques(self):
        """输出调试技巧演示"""
        print("\n🎯 Demo 4: 输出调试技巧")
        print("=" * 40)
        
        # 技巧1: 检查控制台对象属性
        logger = AgentLogger()
        print("\n【技巧1：检查控制台对象】")
        print(f"控制台对象类型: {type(logger.console)}")
        print(f"输出文件对象: {logger.console.file}")
        print(f"是否为终端: {logger.console.is_terminal}")
        print(f"控制台宽度: {logger.console.width}")
        
        # 技巧2: 检查和修改日志级别
        print("\n【技巧2：动态调整日志级别】")
        print(f"初始日志级别: {logger.level.name} ({logger.level})")
        
        # 测试不同级别的输出
        logger.log("这是INFO级别消息", level=LogLevel.INFO)
        logger.log("这是DEBUG级别消息（可能看不到）", level=LogLevel.DEBUG, style="dim")
        
        # 动态降低级别
        original_level = logger.level
        logger.level = LogLevel.DEBUG
        print(f"调整后日志级别: {logger.level.name}")
        logger.log("现在DEBUG消息可见了！", level=LogLevel.DEBUG, style="cyan")
        
        # 恢复原级别
        logger.level = original_level
        print(f"恢复日志级别: {logger.level.name}")
        
        # 技巧3: 强制刷新输出
        print("\n【技巧3：强制刷新缓冲区】")
        logger.console.print("输出后立即刷新...", end="")
        logger.console.file.flush()  # 强制刷新
        time.sleep(1)
        print(" 完成！")
    
    def demo_console_redirection_detection(self):
        """检测控制台重定向的方法"""
        print("\n🎯 Demo 5: 控制台重定向检测")
        print("=" * 40)
        
        # 检测标准输出重定向
        print(f"stdout是否为终端: {sys.stdout.isatty()}")
        print(f"stderr是否为终端: {sys.stderr.isatty()}")
        
        # 创建不同类型的控制台
        console_types = {
            "默认控制台": Console(),
            "强制终端模式": Console(force_terminal=True),
            "强制非终端": Console(force_terminal=False),
            "输出到StringIO": Console(file=StringIO()),
            "输出到stderr": Console(file=sys.stderr)
        }
        
        for name, console in console_types.items():
            print(f"\n【{name}】")
            print(f"  是否为终端: {console.is_terminal}")
            print(f"  输出文件: {type(console.file).__name__}")
            print(f"  支持颜色: {console._color_system is not None}")
    
    def demo_smolagents_simulation(self):
        """模拟smolagents中的实际使用场景"""
        print("\n🎯 Demo 6: smolagents使用场景模拟")
        print("=" * 40)
        
        # 模拟智能体初始化
        agent_console = Console()
        agent_logger = AgentLogger(level=LogLevel.INFO, console=agent_console)
        
        print("\n【模拟智能体执行过程】")
        
        # 模拟规划阶段 - 使用Live组件
        def simulate_planning_phase():
            plan_content = ""
            
            with Live("", console=agent_logger.console, vertical_overflow="visible") as live:
                planning_steps = [
                    "# 📋 任务规划\n\n",
                    "**任务**: 分析数据并生成报告\n\n",
                    "## 🔍 分析阶段\n",
                    "1. 加载数据文件\n",
                    "2. 数据清洗和预处理\n",
                    "3. 探索性数据分析\n\n",
                    "## 📊 处理阶段\n", 
                    "1. 统计分析\n",
                    "2. 趋势识别\n",
                    "3. 异常检测\n\n",
                    "## 📝 报告阶段\n",
                    "1. 生成图表\n",
                    "2. 撰写分析结论\n",
                    "3. 格式化输出\n\n",
                    "✅ **规划完成**\n"
                ]
                
                for step in planning_steps:
                    plan_content += step
                    live.update(Markdown(plan_content))
                    time.sleep(0.8)
        
        # 执行规划
        simulate_planning_phase()
        
        # 规划完成后的日志输出
        agent_logger.log("🎯 开始执行任务...", style="bold blue")
        time.sleep(0.5)
        agent_logger.log("📁 正在加载数据文件...", level=LogLevel.INFO)
        time.sleep(0.5)
        agent_logger.log("✅ 数据加载完成，共1000条记录", style="green")
        time.sleep(0.5)
        agent_logger.log("🧹 开始数据清洗...", level=LogLevel.INFO)
        time.sleep(0.5)
        agent_logger.log("✅ 任务执行完成！", style="bold green")
    
    def demo_debugging_solutions(self):
        """常见问题的解决方案演示"""
        print("\n🎯 Demo 7: 常见问题解决方案")
        print("=" * 40)
        
        print("\n【问题1：看不到任何输出】")
        # 创建级别过高的logger
        silent_logger = AgentLogger(level=LogLevel.ERROR)
        silent_logger.log("这条INFO消息看不到", level=LogLevel.INFO)
        
        # 解决方案：降低日志级别
        silent_logger.level = LogLevel.INFO
        silent_logger.log("✅ 调整级别后，现在可以看到了！", level=LogLevel.INFO, style="green")
        
        print("\n【问题2：输出被重定向】")
        # 创建重定向的logger
        redirected_output = StringIO()
        redirected_logger = AgentLogger(console=Console(file=redirected_output))
        redirected_logger.log("这条消息被重定向了", style="red")
        
        # 解决方案：使用显式的标准输出
        visible_logger = AgentLogger(console=Console(file=sys.stdout))
        visible_logger.log("✅ 使用显式stdout，现在可见了！", style="green")
        
        print(f"重定向的内容: '{redirected_output.getvalue().strip()}'")
        
        print("\n【问题3：Live组件覆盖输出】")
        shared_console = Console()
        
        # 演示问题
        print("问题演示：Live活跃时的输出冲突")
        with Live("Live内容占用显示区域", console=shared_console) as live:
            # 这些输出可能被Live覆盖
            shared_console.print("这可能被覆盖")
            time.sleep(2)
        
        # 解决方案：Live结束后再输出
        shared_console.print("✅ Live结束后输出正常", style="green")
    
    def run_all_demos(self):
        """运行所有演示"""
        print("🚀 智能体控制台调试完整演示")
        print(f"smolagents可用: {'✅ 是' if SMOLAGENTS_AVAILABLE else '❌ 否（使用模拟版本）'}")
        print("=" * 50)
        
        demos = [
            ("日志级别过滤", self.demo_logger_levels),
            ("控制台输出捕获", self.demo_console_capture),
            ("Live组件交互", self.demo_live_console_interaction),
            ("调试技巧", self.demo_output_debugging_techniques),
            ("重定向检测", self.demo_console_redirection_detection),
            ("smolagents模拟", self.demo_smolagents_simulation),
            ("问题解决方案", self.demo_debugging_solutions),
        ]
        
        try:
            for i, (name, demo_func) in enumerate(demos, 1):
                print(f"\n🎬 第{i}个演示: {name}")
                demo_func()
                
                if i < len(demos):
                    input("\n按Enter继续下一个演示...")
            
            print("\n🎉 所有演示完成！")
            print("\n📝 关键要点总结:")
            print("1. 智能体的输出通过AgentLogger.console控制")
            print("2. 日志级别会过滤不同重要程度的消息") 
            print("3. Live组件会在同一区域更新，可能覆盖其他输出")
            print("4. 控制台可能被重定向到非显示设备")
            print("5. 调试时可以检查console对象的属性和状态")
            
        except KeyboardInterrupt:
            print("\n\n⏸️ 演示被用户中断")
        except Exception as e:
            print(f"\n\n❌ 演示过程中出错：{e}")


def main():
    """主函数"""
    print("🔍 智能体控制台调试演示程序")
    print("🎯 理解smolagents中console=self.logger.console的含义")
    print("🛠️ 学习调试智能体输出问题的方法")
    print("=" * 60)
    
    demo = ConsoleDebugDemo()
    demo.run_all_demos()


if __name__ == "__main__":
    main()