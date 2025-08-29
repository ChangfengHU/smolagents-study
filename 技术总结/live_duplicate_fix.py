#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
正确修复smolagents Live重复输出问题
只在Live组件使用时应用修复，不影响其他输出
"""

import sys
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

def demo_wrong_fix():
    """演示错误修复方式的问题"""
    print("❌ 错误修复方式演示")
    print("=" * 40)
    
    # 错误：全局修改所有Console
    global_console = Console(force_terminal=True)
    
    print("Live开始前的输出")
    global_console.print("这是常规输出1")
    
    with Live("", console=global_console, refresh_per_second=4) as live:
        global_console.print("Live期间的输出 - 这会冲突！")
        live.update("Live内容")
        # 这两个输出会互相干扰，造成重复显示
    
    global_console.print("Live结束后的输出")
    print("可以看到输出混乱了！")


def demo_correct_fix():
    """演示正确修复方式"""
    print("\n✅ 正确修复方式演示") 
    print("=" * 40)
    
    # 正确：为Live专门创建控制台
    regular_console = Console()  # 常规输出用普通控制台
    live_console = Console(force_terminal=True, file=sys.stdout)  # Live专用
    
    print("Live开始前的输出")
    regular_console.print("这是常规输出1")
    
    with Live("", console=live_console, refresh_per_second=4) as live:
        # 常规输出继续使用普通控制台
        regular_console.print("Live期间的常规输出")
        
        # Live使用专用控制台
        content = ""
        steps = ["第一步", "第二步", "第三步完成"]
        
        for step in steps:
            content += f"{step}\n"
            live.update(Markdown(f"# Live内容\n{content}"))
            import time
            time.sleep(1)
    
    regular_console.print("Live结束后的输出")
    print("这样就不会冲突了！")


def create_proper_smolagents_fix():
    """创建适用于smolagents的正确修复"""
    print("\n🔧 smolagents正确修复方案")
    print("=" * 40)
    
    fix_code = """
# 🔥 正确修复：只在Live使用时创建专用控制台

# 方案1：在agents.py中修改Live使用的地方
def _generate_planning_step(self, ...):
    # 创建Live专用控制台，不影响logger.console
    live_console = Console(force_terminal=True, file=sys.stdout, width=100)
    
    with Live("", console=live_console, vertical_overflow="visible") as live:
        for event in output_stream:
            if event.content is not None:
                plan_message_content += event.content
                live.update(Markdown(plan_message_content))
            yield event

# 方案2：临时替换控制台
def _generate_planning_step(self, ...):
    # 备份原控制台
    original_console = self.logger.console
    
    # 临时使用Live专用控制台
    self.logger.console = Console(force_terminal=True, file=sys.stdout)
    
    try:
        with Live("", console=self.logger.console, vertical_overflow="visible") as live:
            # Live代码...
            pass
    finally:
        # 恢复原控制台
        self.logger.console = original_console

# 方案3：智能检测（推荐）
def _generate_planning_step(self, ...):
    # 如果当前控制台不是终端，为Live创建专用控制台
    if not self.logger.console.is_terminal:
        live_console = Console(force_terminal=True, file=sys.stdout)
    else:
        live_console = self.logger.console
    
    with Live("", console=live_console, vertical_overflow="visible") as live:
        # Live代码...
        pass
"""
    
    print(fix_code)


def demonstrate_console_isolation():
    """演示控制台隔离的重要性"""
    print("\n🔬 控制台隔离演示")
    print("=" * 30)
    
    import time
    from rich.panel import Panel
    
    # 创建两个独立的控制台
    logger_console = Console()  # 模拟AgentLogger的控制台
    live_console = Console(force_terminal=True, file=sys.stdout)  # Live专用
    
    print("开始演示控制台隔离...")
    
    # 模拟smolagents的实际使用场景
    with Live("", console=live_console, refresh_per_second=2) as live:
        for i in range(5):
            # Live内容更新
            live_content = f"""
# Planning Step {i+1}

正在生成计划...

## 当前进度
- 步骤 {i+1}/5 完成
- 状态：正在处理
"""
            live.update(Panel(Markdown(live_content), title="AI Planning"))
            
            # 模拟其他日志输出（使用独立控制台）
            if i == 2:
                logger_console.print(f"[dim]后台日志：步骤{i+1}处理完成[/dim]")
            
            time.sleep(1)
    
    # Live结束后的输出
    logger_console.print("✅ 规划完成，开始执行任务")
    print("演示完成：可以看到Live和日志输出互不干扰")


def main():
    """主函数"""
    print("🛠️ smolagents Live重复输出修复指南")
    print("🎯 解决force_terminal=True导致的输出冲突问题")
    print("=" * 60)
    
    try:
        # 演示问题
        demo_wrong_fix()
        
        input("\n按Enter查看正确修复方式...")
        
        # 演示正确修复
        demo_correct_fix()
        
        input("\n按Enter查看控制台隔离演示...")
        
        # 演示控制台隔离
        demonstrate_console_isolation()
        
        # 显示修复代码
        create_proper_smolagents_fix()
        
        print("\n🎉 修复指南完成！")
        print("\n📝 关键要点：")
        print("1. 不要全局修改AgentLogger.console")
        print("2. 只为Live组件创建专用的force_terminal控制台")
        print("3. 保持日志输出和Live输出的控制台分离")
        print("4. Live结束后，其他输出继续使用原控制台")
        
    except KeyboardInterrupt:
        print("\n⏸️ 演示被中断")
    except Exception as e:
        print(f"\n❌ 演示出错：{e}")


if __name__ == "__main__":
    main()