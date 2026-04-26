from __future__ import annotations

"""
集成 Vyibc (Auto Content API) 的真实“微信视觉故事创作室”。

1. 热点抓取 (DailyHot API)
2. 故事角度与脚本生成 (Grok-4.20)
3. 真实图像生成 (Vertex Imagen 4 Ultra)
4. 长图合成 (PIL)
"""

import json
import os
import sys
import requests
from io import BytesIO
from datetime import datetime
from pathlib import Path
from textwrap import fill
from typing import Literal, Any
from dataclasses import dataclass, field
from PIL import Image, ImageDraw, ImageFont

# 确保可以导入 src 中的 smolagents
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from smolagents.vyibc_provider import VyibcModel, VyibcImageTool

# 配置路径
HOT_API_BASE = "https://dailyhotapi-hazel.vercel.app"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "vyibc_visual_story"
CANVAS_WIDTH = 1080
MARGIN = 64
GAP = 28
PANEL_HEIGHT = 800  # 增加高度以容纳真实图片
COVER_HEIGHT = 620
ENDING_HEIGHT = 280
BG_COLOR = "#f6f0e5"
TEXT_COLOR = "#1f1a17"
ACCENT_COLOR = "#d26a2e"
FRAME_BG = "#fffaf4"
FRAME_BORDER = "#2d241f"

# 初始化模型
text_model = VyibcModel(provider="grok", model="grok-4.20")
image_tool = VyibcImageTool()

@dataclass
class HotTopic:
    title: str
    source: str
    summary: str
    timestamp: str

@dataclass
class StoryAngle:
    angle_title: str
    hook: str
    core_viewpoint: str
    tone: str

@dataclass
class Storybeat:
    index: int
    narration: str
    dialogue: str
    image_prompt: str

@dataclass
class Storyboard:
    angle: StoryAngle
    beats: list[Storybeat]

def _parse_json(text: str) -> Any:
    try:
        if "```json" in text:
            content = text.split("```json")[1].split("```")[0].strip()
        else:
            content = text.strip()
        return json.loads(content)
    except Exception as e:
        print(f"JSON 解析失败: {e}\n原文内容: {text}")
        return None

def fetch_hot_topics(route: str = "zhihu", limit: int = 5) -> list[HotTopic]:
    """从 DailyHot API 获取热点。"""
    try:
        url = f"{HOT_API_BASE}/{route}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        topics = []
        for item in data[:limit]:
            topics.append(HotTopic(
                title=item.get("title", ""),
                source=route,
                summary=item.get("desc", ""),
                timestamp=datetime.now().isoformat()
            ))
        return topics
    except Exception as e:
        print(f"热点抓取失败: {e}")
        return [HotTopic("AI Agent 开发热潮", "manual", "全球开发者正投身于 AI Agent 的生态建设。", datetime.now().isoformat())]

def story_architect(topic: HotTopic) -> Storyboard:
    """使用 Grok-4.20 构思角度并生成分镜脚本。"""
    prompt = f"""
    热点主题: {topic.title}
    摘要: {topic.summary}
    目标：创作一个适合微信公众号发布的视觉故事（通常是 6-8 格长图）。
    要求：语气幽默诙谐、有反转、有共鸣。

    请输出 JSON 格式，结构如下：
    {{
      "angle": {{
        "angle_title": "故事标题",
        "hook": "开篇钩子",
        "core_viewpoint": "核心观点",
        "tone": "语气偏好"
      }},
      "beats": [
        {{
          "index": 1,
          "narration": "叙述文字",
          "dialogue": "角色对白",
          "image_prompt": "详细的绘图提示词(英文)"
        }}
      ]
    }}
    """
    response = text_model([{"role": "user", "content": prompt}])
    data = _parse_json(response.content)
    angle = StoryAngle(**data["angle"])
    beats = [Storybeat(**b) for b in data["beats"]]
    return Storyboard(angle, beats)

def _load_font(size: int) -> ImageFont.ImageFont:
    for path in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", # Linux fallback
    ]:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()

def _wrap(text: str, width: int) -> str:
    return fill(text, width=width)

def render_panel(beat: Storybeat) -> Image.Image:
    """调用 Vyibc 生图并渲染成板卡。"""
    print(f"  - 正在生成第 {beat.index} 格图片...")
    urls = image_tool(prompt=beat.image_prompt, provider="vertex", model="imagen-4.0-ultra-generate-001")
    img_url = urls[0] if urls else None
    
    panel = Image.new("RGB", (CANVAS_WIDTH, PANEL_HEIGHT), FRAME_BG)
    draw = ImageDraw.Draw(panel)
    font_body = _load_font(32)
    font_dialogue = _load_font(36)

    # 边框
    draw.rounded_rectangle((20, 20, CANVAS_WIDTH - 20, PANEL_HEIGHT - 20), radius=20, outline=FRAME_BORDER, width=4)

    # 绘制图片
    if img_url:
        try:
            resp = requests.get(img_url, timeout=20)
            beat_img = Image.open(BytesIO(resp.content))
            # 缩放图片适应宽度，保留边距
            target_w = CANVAS_WIDTH - 80
            target_h = 450
            beat_img.thumbnail((target_w, target_h))
            # 居中粘贴
            panel.paste(beat_img, ( (CANVAS_WIDTH-beat_img.width)//2 , 40))
        except Exception as e:
            print(f"图片下载/处理失败: {e}")

    # 文字区域
    text_y = 520
    draw.multiline_text((40, text_y), _wrap(beat.narration, 35), fill=TEXT_COLOR, font=font_body, spacing=10)
    text_y += 120
    draw.text((40, text_y), f"“{beat.dialogue}”", fill=ACCENT_COLOR, font=font_dialogue)
    
    return panel

def compose_story(board: Storyboard, topic: HotTopic) -> Path:
    """合成长图。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    num_beats = len(board.beats)
    total_height = COVER_HEIGHT + (PANEL_HEIGHT + GAP) * num_beats + ENDING_HEIGHT + MARGIN * 2
    
    canvas = Image.new("RGB", (CANVAS_WIDTH, total_height), BG_COLOR)
    draw = ImageDraw.Draw(canvas)
    font_title = _load_font(72)
    font_sub = _load_font(36)

    # 封面
    draw.rounded_rectangle((MARGIN, MARGIN, CANVAS_WIDTH-MARGIN, COVER_HEIGHT), radius=30, fill="#fff", outline=FRAME_BORDER, width=6)
    draw.text((MARGIN+40, MARGIN+60), _wrap(board.angle.angle_title, 12), fill=TEXT_COLOR, font=font_title)
    draw.text((MARGIN+40, MARGIN+300), f"来源: {topic.source} | 话题: {topic.title}", fill="#666", font=font_sub)
    draw.text((MARGIN+40, MARGIN+400), _wrap(board.angle.hook, 30), fill=ACCENT_COLOR, font=font_sub)

    curr_y = COVER_HEIGHT + GAP
    for beat in board.beats:
        panel = render_panel(beat)
        canvas.paste(panel, (0, curr_y))
        curr_y += PANEL_HEIGHT + GAP
    
    # 结尾
    draw.rounded_rectangle((MARGIN, curr_y, CANVAS_WIDTH-MARGIN, curr_y + ENDING_HEIGHT), radius=20, fill="#eee", outline=FRAME_BORDER, width=4)
    draw.text((MARGIN+40, curr_y+60), "真正的智者，从不只看热闹。", fill=TEXT_COLOR, font=font_sub)
    draw.text((MARGIN+40, curr_y+140), "关注我们，获取更多 AI 洞察。", fill=ACCENT_COLOR, font=font_sub)

    out_path = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    canvas.save(out_path)
    return out_path

def main():
    print("=== Vyibc Visual Story Studio ===")
    topics = fetch_hot_topics("zhihu", 1)
    topic = topics[0]
    print(f"目标话题: {topic.title}")
    
    print("正在构思故事脚本...")
    board = story_architect(topic)
    
    print(f"正在生成 {len(board.beats)} 格长图内容...")
    final_path = compose_story(board, topic)
    
    print(f"\n创作完成！长图已保存至: {final_path}")

if __name__ == "__main__":
    main()
