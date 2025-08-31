#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Live组件输出机制详解
展示为什么Live和print不会交叉显示
"""

import time
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

def demonstrate_live_behavior():
    """演示Live组件的独占行为"""
    
    print("🎭 Live组件的'独占'机制演示")
    print("=" * 40)
    
    console = Console()
    
    print("开始演示...")
    print("注意观察：Live期间的print输出去哪了？")
    
    with Live("", console=console, refresh_per_second=2) as live:
        for i in range(5):
            # 这些print在Live期间不会立即显示
            print(f"🔍 调试信息 {i+1}: Live期间的输出")
            
            # 只有Live的内容会显示
            live_content = f"""
# Live演示 - 第{i+1}步

当前时间: {time.strftime('%H:%M:%S')}

**观察要点:**
- 你现在只能看到Live的内容
- print的调试信息被"藏"起来了
- 等Live结束后才会一起显示
"""
            live.update(Panel(
                Markdown(live_content),
                title=f"Live独占区域 {i+1}/5",
                border_style="blue"
            ))
            
            time.sleep(1)
    
    print("🎉 Live结束！现在可以看到之前的print输出了")
    print("这就是为什么你看到'先后关系'而不是'交叉打印'")


def demonstrate_console_capture():
    """演示控制台输出捕获机制"""
    
    print("\n📺 控制台输出捕获原理")
    print("=" * 30)
    
    console = Console()
    
    print("Live如何'隐藏'其他输出：")
    
    # 模拟Live的工作原理
    print("\n1. Live启动前 - 正常输出")
    console.print("这是正常的输出")
    
    print("\n2. Live期间 - 控制台被接管")
    
    with Live("", console=console) as live:
        # Live接管了控制台
        console.print("这个输出被Live管理")  # 可能不会立即显示
        
        for i in range(3):
            live.update(f"Live控制中 - 第{i+1}步")
            time.sleep(0.8)
    
    print("3. Live结束后 - 恢复正常输出")
    console.print("Live结束，恢复正常")


def show_buffering_effect():
    """展示输出缓冲效应"""
    
    print("\n🔄 输出缓冲效应演示")
    print("=" * 25)
    
    import sys
    console = Console()
    
    print("测试不同的输出缓冲模式：")
    
    print("\n方案A: 立即刷新（交叉显示）")
    with Live("", console=console, refresh_per_second=1) as live:
        for i in range(3):
            print(f"调试信息 {i+1}", flush=True)  # 强制刷新
            sys.stdout.flush()  # 确保立即输出
            
            live.update(f"Live内容 {i+1}")
            time.sleep(1)
    
    print("\n方案B: 默认缓冲（批量显示）")
    with Live("", console=console, refresh_per_second=1) as live:
        for i in range(3):
            print(f"缓冲信息 {i+1}")  # 不强制刷新
            
            live.update(f"Live内容 {i+1}")
            time.sleep(1)
    
    print("可以看到两种模式的不同表现")


def explain_smolagents_behavior():
    """解释smolagents的具体行为"""
    
    print("\n🤖 smolagents的具体情况")
    print("=" * 30)
    
    print("在smolagents中发生的事情：")
    
    flow_explanation = """
1. Live组件启动 (with Live(...) as live:)
   └─ 接管控制台输出区域

2. 循环处理AI事件 (for event in output_stream:)
   ├─ print(f"收到步骤: {event}")     ← 被缓冲，不立即显示
   ├─ live.update(Markdown(...))     ← 立即更新Live显示
   └─ yield event                    ← 传递给上级

3. Live组件结束
   └─ 释放控制台，缓冲的print内容一起显示

时间线：
T1: Live开始  |████ Live显示区域 ████|  缓冲区: [print1]
T2: 更新Live  |████ 更新内容     ████|  缓冲区: [print1, print2]
T3: 继续更新  |████ 继续更新     ████|  缓冲区: [print1, print2, print3]
T4: Live结束  |                      |  缓冲区: [] → 全部输出到屏幕
"""
    
    print(flow_explanation)


def create_crossover_demo():
    """创建交叉显示的演示"""
    
    print("\n🔄 如何实现交叉显示")
    print("=" * 25)
    
    console = Console()
    
    print("方法1: 使用不同的控制台")
    
    # 为Live创建专用控制台
    live_console = Console()
    debug_console = Console()
    
    print("开始交叉显示演示...")
    
    with Live("", console=live_console, refresh_per_second=2) as live:
        for i in range(3):
            # 使用不同的控制台，可以实现交叉显示
            debug_console.print(f"🔍 调试 {i+1}: 使用独立控制台", style="dim")
            
            live.update(Panel(
                f"Live内容 {i+1}\n\n使用独立控制台避免冲突",
                title="Live专用显示",
                border_style="green"
            ))
            
            time.sleep(1)
    
    print("方法2: 在Live外部输出")
    for i in range(3):
        print(f"📤 Live外部输出 {i+1}")
        time.sleep(0.5)


def main():
    """主函数"""
    print("🎬 Live组件输出机制完整分析")
    print("🎯 解答为什么是先后关系而非交叉打印")
    print("=" * 50)
    
    try:
        demonstrate_live_behavior()
        
        input("\n按Enter继续...")
        demonstrate_console_capture()
        
        input("\n按Enter查看缓冲效应...")
        show_buffering_effect()
        
        input("\n按Enter了解smolagents行为...")
        explain_smolagents_behavior()
        
        input("\n按Enter查看交叉显示方案...")
        create_crossover_demo()
        
        print("\n🎉 分析完成！")
        
        print("\n📋 核心答案：")
        print("1. Live组件在活跃期间'独占'控制台输出区域")
        print("2. print输出被缓冲，等Live结束后一起显示")
        print("3. 这是Rich Live的设计机制，确保显示清洁")
        print("4. 要实现交叉显示需要使用不同的控制台或强制刷新")
        
    except KeyboardInterrupt:
        print("\n⏸️ 演示被中断")
    except Exception as e:
        print(f"\n❌ 演示出错：{e}")


if __name__ == "__main__":
    main()