#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
smolagents Live输出问题诊断工具
专门用于排查为什么live.update()看不到输出的问题
"""

import sys
import os
import time
from io import StringIO
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

def diagnose_live_output_issue():
    """诊断Live输出问题的完整流程"""
    
    print("🔍 smolagents Live输出问题诊断")
    print("=" * 50)
    
    # 1. 检查基本环境
    print("\n📋 第1步：检查基本环境")
    print(f"Python版本: {sys.version}")
    print(f"当前工作目录: {os.getcwd()}")
    print(f"终端类型: {os.environ.get('TERM', '未知')}")
    print(f"是否在IDE中运行: {'VSCODE_PID' in os.environ or 'PYCHARM_HOSTED' in os.environ}")
    
    # 2. 检查标准输出
    print("\n📋 第2步：检查标准输出")
    print(f"stdout是终端: {sys.stdout.isatty()}")
    print(f"stderr是终端: {sys.stderr.isatty()}")
    print(f"stdout类型: {type(sys.stdout)}")
    
    # 3. 测试基本Rich输出
    print("\n📋 第3步：测试基本Rich输出")
    basic_console = Console()
    print(f"Rich控制台是终端: {basic_console.is_terminal}")
    print(f"Rich控制台文件: {basic_console.file}")
    print(f"Rich控制台颜色系统: {basic_console._color_system}")
    
    basic_console.print("✅ 基本Rich输出测试", style="green bold")
    
    # 4. 测试Markdown渲染
    print("\n📋 第4步：测试Markdown渲染")
    test_markdown = """
# 测试标题
这是一个**粗体**文本。

## 子标题
- 列表项1
- 列表项2
"""
    basic_console.print(Markdown(test_markdown))
    
    # 5. 测试Live组件（这是关键！）
    print("\n📋 第5步：测试Live组件")
    print("如果下面看不到动态更新的内容，就是问题所在！")
    
    try:
        with Live("", console=basic_console, refresh_per_second=4) as live:
            for i in range(5):
                content = f"""
# Live测试 - 第{i+1}次更新

当前时间: {time.strftime('%H:%M:%S')}

这个内容应该在**同一位置**不断更新，而不是向下滚动。

如果你看到多行重复内容，说明Live没有正常工作！
"""
                live.update(Panel(
                    Markdown(content),
                    title=f"Live测试 {i+1}/5",
                    border_style="blue"
                ))
                time.sleep(1)
        
        print("✅ Live组件测试完成")
        
    except Exception as e:
        print(f"❌ Live组件测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 6. 模拟smolagents的具体场景
    print("\n📋 第6步：模拟smolagents场景")
    
    # 模拟AgentLogger
    class MockAgentLogger:
        def __init__(self):
            self.console = Console(file=sys.stdout)  # 明确使用stdout
    
    mock_logger = MockAgentLogger()
    
    print("开始模拟smolagents的Live使用...")
    
    try:
        # 这就是smolagents中的代码逻辑
        plan_message_content = ""
        
        with Live("", console=mock_logger.console, vertical_overflow="visible") as live:
            plan_steps = [
                "# 任务规划\n\n",
                "正在分析用户需求...\n\n",
                "## 执行步骤\n",
                "1. 收集信息\n",
                "2. 处理数据\n",
                "3. 生成结果\n\n",
                "✅ 规划完成！"
            ]
            
            for step in plan_steps:
                plan_message_content += step
                # 🔥 这就是你提到的代码行！
                live.update(Markdown(plan_message_content))
                time.sleep(1)
        
        print("✅ smolagents场景模拟完成")
        
    except Exception as e:
        print(f"❌ smolagents场景模拟失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 7. 检查可能的干扰因素
    print("\n📋 第7步：检查可能的干扰因素")
    
    # 检查环境变量
    problematic_env_vars = [
        'NO_COLOR', 'FORCE_COLOR', 'TERM_PROGRAM', 
        'JUPYTER_COLUMNS', 'JUPYTER_LINES',
        'PYCHARM_HOSTED', 'VSCODE_PID'
    ]
    
    for var in problematic_env_vars:
        value = os.environ.get(var)
        if value:
            print(f"环境变量 {var}: {value}")
    
    # 8. 给出诊断结论和建议
    print("\n🎯 诊断结论和建议")
    print("=" * 30)
    
    if not sys.stdout.isatty():
        print("❌ 问题：stdout不是终端")
        print("💡 建议：你可能在IDE中运行，尝试在真实终端中运行")
    
    if not basic_console.is_terminal:
        print("❌ 问题：Rich检测不到终端环境") 
        print("💡 建议：尝试设置环境变量 FORCE_COLOR=1")
    
    if 'PYCHARM_HOSTED' in os.environ:
        print("⚠️  检测到PyCharm环境")
        print("💡 建议：在PyCharm的Terminal标签页中运行，而不是在Run窗口")
    
    if 'VSCODE_PID' in os.environ:
        print("⚠️  检测到VSCode环境")
        print("💡 建议：在VSCode的Terminal面板中运行")
    
    print("\n🛠️  立即修复方案：")
    print("1. 在真实终端（Terminal.app/CMD）中运行")
    print("2. 设置环境变量：export FORCE_COLOR=1")
    print("3. 使用强制终端模式：Console(force_terminal=True)")


def test_live_with_force_terminal():
    """使用强制终端模式测试Live"""
    print("\n🚀 测试强制终端模式")
    print("=" * 30)
    
    # 强制终端模式
    force_console = Console(force_terminal=True, width=80)
    
    print("强制终端模式测试...")
    
    with Live("", console=force_console, refresh_per_second=4) as live:
        for i in range(3):
            content = f"""
# 强制终端模式测试

更新次数: {i+1}
时间: {time.strftime('%H:%M:%S')}

如果这个内容在同一位置更新，说明强制模式生效了！
"""
            live.update(Markdown(content))
            time.sleep(1)
    
    print("强制终端模式测试完成")


def provide_immediate_fix():
    """提供立即修复的代码示例"""
    print("\n💊 立即修复代码")
    print("=" * 20)
    
    fix_code = '''
# 修复smolagents Live不显示的问题

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

# 方案1：强制终端模式
console = Console(force_terminal=True, file=sys.stdout)

# 方案2：检查并设置环境
import os
os.environ['FORCE_COLOR'] = '1'
console = Console()

# 方案3：在你的smolagents代码中
# 找到这行：with Live("", console=self.logger.console, vertical_overflow="visible") as live:
# 替换为：
self.logger.console = Console(force_terminal=True, file=sys.stdout)
with Live("", console=self.logger.console, vertical_overflow="visible") as live:
    # 你的代码...
'''
    
    print(fix_code)


def main():
    """主函数"""
    try:
        diagnose_live_output_issue()
        
        print("\n" + "="*50)
        response = input("是否测试强制终端模式？(y/n): ")
        if response.lower() == 'y':
            test_live_with_force_terminal()
        
        provide_immediate_fix()
        
        print("\n🎉 诊断完成！")
        print("如果问题依然存在，请在真实终端中运行此脚本。")
        
    except KeyboardInterrupt:
        print("\n⏸️ 诊断被中断")
    except Exception as e:
        print(f"\n❌ 诊断过程出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()