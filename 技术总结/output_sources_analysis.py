#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
smolagents输出源分析演示
展示不同输出来源和它们的区别
"""

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
import time

def demonstrate_output_sources():
    """演示不同的输出源"""
    
    print("🔍 smolagents输出源分析")
    print("=" * 50)
    
    # 模拟smolagents的数据结构
    class MockChatMessageStreamDelta:
        def __init__(self, content, token_usage=None):
            self.content = content
            self.token_usage = token_usage
        
        def __repr__(self):
            return f"ChatMessageStreamDelta(content='{self.content}', token_usage={self.token_usage})"
    
    class MockTokenUsage:
        def __init__(self, input_tokens, output_tokens):
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens
            self.total_tokens = input_tokens + output_tokens
        
        def __repr__(self):
            return f"TokenUsage(input_tokens={self.input_tokens}, output_tokens={self.output_tokens}, total_tokens={self.total_tokens})"
    
    # 模拟AI流式输出
    mock_events = [
        MockChatMessageStreamDelta("# Planning Phase\n\n"),
        MockChatMessageStreamDelta("## 1. Facts survey\n"),
        MockChatMessageStreamDelta("### 1.1. Facts given in the task\n"),
        MockChatMessageStreamDelta("- The task is to create a 3-day itinerary for Tokyo.\n"),
        MockChatMessageStreamDelta("- Each day should include 2 attractions.\n"),
        MockChatMessageStreamDelta("", MockTokenUsage(534, 389))  # 最后一个事件包含token统计
    ]
    
    print("\n【输出源1：调试打印】")
    print("这是你代码中的 print() 语句输出：")
    
    accumulated_content = ""
    console = Console()
    
    # 模拟你的代码逻辑
    with Live("", console=console, refresh_per_second=4) as live:
        for event in mock_events:
            # 🔥 输出源1：调试代码的打印
            print(f"收到步骤: {event}")
            
            # 🔥 输出源2：Live组件的渲染 
            if event.content:
                accumulated_content += event.content
                live.update(Panel(
                    Markdown(accumulated_content),
                    title="Live渲染内容",
                    border_style="blue"
                ))
            
            time.sleep(1)
    
    print("\n📝 分析结果：")
    print("1. '收到步骤:' 是调试代码打印的原始对象")
    print("2. 格式化的规划内容是Live组件渲染的Markdown")
    print("3. 两者是同时但独立进行的输出")


def analyze_smolagents_flow():
    """分析smolagents的具体流程"""
    
    print("\n🌊 smolagents流式输出流程")
    print("=" * 40)
    
    flow_diagram = """
AI模型生成 → ChatMessageStreamDelta对象 → yield event
    ↓                        ↓                    ↓
    content内容         调试代码打印          传递给上级
    ↓                        ↓                    ↓
    累积到变量          print(f"收到步骤: {event}")   用户代码接收
    ↓
    live.update(Markdown(...))
    ↓
    屏幕显示格式化内容
"""
    
    print(flow_diagram)
    
    print("\n🎯 关键理解：")
    print("1. ChatMessageStreamDelta 是原始数据对象")
    print("2. event.content 是具体的文本内容片段")
    print("3. Live组件将累积的内容渲染为格式化显示")
    print("4. 你的print语句显示的是原始对象信息")


def show_event_details():
    """展示事件对象的详细信息"""
    
    print("\n🔬 ChatMessageStreamDelta对象详解")
    print("=" * 45)
    
    print("这个对象包含：")
    print("• content: 本次新增的文本片段")
    print("• tool_calls: 工具调用信息（通常为None）")  
    print("• token_usage: token使用统计（最后一个事件才有）")
    
    print("\n📦 具体示例：")
    examples = [
        "ChatMessageStreamDelta(content='# Planning', tool_calls=None, token_usage=None)",
        "ChatMessageStreamDelta(content='\\n\\n## Step 1', tool_calls=None, token_usage=None)", 
        "ChatMessageStreamDelta(content='', tool_calls=None, token_usage=TokenUsage(...))",
    ]
    
    for i, example in enumerate(examples, 1):
        print(f"{i}. {example}")
    
    print("\n💡 为什么最后有空content的事件？")
    print("• 这是AI模型发送token统计信息的方式")
    print("• content为空，但包含了整个对话的token使用情况")
    print("• 这是流式API的标准模式")


def explain_accumulation():
    """解释内容累积过程"""
    
    print("\n📈 内容累积过程演示")
    print("=" * 30)
    
    events = [
        "# Planning",
        "\\n\\n## 1. Facts",
        "\\n### 1.1. Given",
        "\\n- Tokyo itinerary",
        "\\n- 2 attractions per day"
    ]
    
    accumulated = ""
    for i, event_content in enumerate(events, 1):
        accumulated += event_content
        print(f"步骤{i}:")
        print(f"  新增: '{event_content}'")
        print(f"  累积: '{accumulated}'")
        print()
    
    print("🎨 Live组件将最终累积的内容渲染为：")
    console = Console()
    final_content = """# Planning

## 1. Facts
### 1.1. Given
- Tokyo itinerary
- 2 attractions per day"""
    
    console.print(Panel(
        Markdown(final_content),
        title="最终渲染效果",
        border_style="green"
    ))


def main():
    """主函数"""
    try:
        demonstrate_output_sources()
        
        input("\n按Enter继续分析流程...")
        analyze_smolagents_flow()
        
        input("\n按Enter查看事件详情...")
        show_event_details()
        
        input("\n按Enter查看累积过程...")
        explain_accumulation()
        
        print("\n🎉 分析完成！")
        print("\n📋 总结：")
        print("1. '收到步骤:' 是你的调试代码打印的原始对象")
        print("2. 格式化内容是Live组件累积渲染的结果")
        print("3. 两者同时发生，但来源不同")
        print("4. 最后的空content事件用于传递token统计")
        
    except KeyboardInterrupt:
        print("\n⏸️ 分析被中断")
    except Exception as e:
        print(f"\n❌ 分析出错：{e}")


if __name__ == "__main__":
    main()