#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
smolagents Live输出修复补丁
直接修复Live组件看不到输出的问题
"""

import sys
import os
from rich.console import Console

def fix_smolagents_live_output():
    """修复smolagents Live输出的函数"""
    
    # 设置环境变量强制启用颜色
    os.environ['FORCE_COLOR'] = '1'
    os.environ['TERM'] = 'xterm-256color'
    
    # 创建强制终端模式的控制台
    fixed_console = Console(
        force_terminal=True,       # 🔥 强制终端模式
        file=sys.stdout,           # 🔥 明确输出到stdout  
        width=100,                 # 🔥 设置合适的宽度
        legacy_windows=False       # 🔥 禁用legacy模式
    )
    
    return fixed_console

def apply_fix_to_agent(agent):
    """将修复应用到已存在的智能体"""
    
    # 备份原始控制台
    original_console = agent.logger.console
    
    # 应用修复
    fixed_console = fix_smolagents_live_output()
    agent.logger.console = fixed_console
    
    print("✅ 已应用Live输出修复")
    print(f"修复前终端检测: {original_console.is_terminal}")
    print(f"修复后终端检测: {fixed_console.is_terminal}")
    
    return agent

# 具体修复代码示例
def demo_fixed_live():
    """演示修复后的Live效果"""
    
    fixed_console = fix_smolagents_live_output()
    
    print("🚀 测试修复后的Live组件")
    print("现在应该能看到动态更新了！")
    
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    import time
    
    # 使用修复后的控制台
    with Live("", console=fixed_console, refresh_per_second=4, vertical_overflow="visible") as live:
        content = ""
        steps = [
            "# 🤖 修复测试\n\n",
            "Live组件现在应该正常工作了！\n\n",
            "## ✅ 修复要点\n",
            "- 强制终端模式\n",
            "- 明确输出流\n", 
            "- 环境变量设置\n\n",
            "🎉 **修复完成！**\n"
        ]
        
        for step in steps:
            content += step
            # 🔥 这就是你的问题代码，现在应该能看到了
            live.update(Markdown(content))
            time.sleep(1)
    
    print("✅ 修复测试完成！")

if __name__ == "__main__":
    print("🔧 smolagents Live输出修复工具")
    print("=" * 40)
    
    # 演示修复效果
    demo_fixed_live()
    
    print("\n📝 如何在你的代码中使用:")
    print("""
# 方法1: 修复已有智能体
from smolagents import CodeAgent
agent = CodeAgent(...)
agent = apply_fix_to_agent(agent)  # 应用修复

# 方法2: 直接替换控制台
from rich.console import Console
import os, sys

os.environ['FORCE_COLOR'] = '1'
fixed_console = Console(force_terminal=True, file=sys.stdout)

# 在你的Live代码中使用
with Live("", console=fixed_console, vertical_overflow="visible") as live:
    live.update(Markdown(content))  # 现在应该能看到了！
""")