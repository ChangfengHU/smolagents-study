from __future__ import annotations

"""
微信公众号视觉故事原型。

这个版本聚焦一个独立方向：
1. 输入一个热点主题，或者从 dailyhotapi 拉一个热点标题
2. 生成适合公众号的“幽默诙谐、有剧情吸引力”的视觉故事
3. 输出为一张竖版 PNG 长图

当前实现是企业级产品的原型骨架：
- 结构、状态和产物已经按产品思路拆开
- 文本生成和图片生成先用本地规则引擎与 mock 渲染器完成
- 后续可以把 angle / script / storyboard / image generation 分别替换成真实模型服务
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from textwrap import fill
from typing import Literal

import requests
from PIL import Image, ImageDraw, ImageFont


HOT_API_BASE = "https://dailyhotapi-hazel.vercel.app"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "wechat_visual_story"
CANVAS_WIDTH = 1080
MARGIN = 64
GAP = 28
PANEL_HEIGHT = 540
COVER_HEIGHT = 620
ENDING_HEIGHT = 280
BG_COLOR = "#f6f0e5"
TEXT_COLOR = "#1f1a17"
ACCENT_COLOR = "#d26a2e"
FRAME_BG = "#fffaf4"
FRAME_BORDER = "#2d241f"


StoryTone = Literal["humorous", "playful", "satirical"]


@dataclass
class HotTopic:
    title: str
    source: str
    summary: str
    timestamp: str
    raw_payload: dict = field(default_factory=dict)


@dataclass
class StoryAngle:
    angle_title: str
    hook: str
    core_viewpoint: str
    why_shareable: str
    tone: StoryTone


@dataclass
class StoryBeat:
    beat_index: int
    purpose: str
    narration: str
    dialogue: str
    scene_description: str
    transition: str


@dataclass
class StoryboardFrame:
    frame_index: int
    caption: str
    dialogue: str
    scene_description: str
    image_prompt: str
    layout_hint: str
    palette_hint: str


@dataclass
class ReviewIssue:
    severity: Literal["low", "medium", "high"]
    location: str
    description: str


@dataclass
class ReviewResult:
    status: Literal["PASS", "REVISE", "BLOCK"]
    score: float
    issues: list[ReviewIssue]
    suggestions: list[str]
    retry_stage: str | None = None


@dataclass
class LongImagePackage:
    title: str
    subtitle: str
    cover_hook: str
    frames: list[StoryboardFrame]
    outro_text: str
    output_file_path: Path


def fetch_hot_topics(route: str = "zhihu", limit: int = 5) -> list[HotTopic]:
    """从 dailyhotapi 拉热点，结构不稳定时做宽松兼容。"""
    url = f"{HOT_API_BASE}/{route}"
    response = requests.get(url, timeout=12)
    response.raise_for_status()
    payload = response.json()

    candidates: list[dict] = []
    if isinstance(payload, dict):
        for key in ("data", "list", "items", "result", "news"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if not candidates and isinstance(payload.get("data"), dict):
            nested = payload["data"]
            for key in ("list", "items"):
                value = nested.get(key)
                if isinstance(value, list):
                    candidates = value
                    break
    elif isinstance(payload, list):
        candidates = payload

    topics: list[HotTopic] = []
    for item in candidates[:limit]:
        if not isinstance(item, dict):
            continue
        title = (
            item.get("title")
            or item.get("name")
            or item.get("hotWord")
            or item.get("desc")
            or item.get("content")
            or "未命名热点"
        )
        summary = (
            item.get("desc")
            or item.get("summary")
            or item.get("excerpt")
            or item.get("hot")
            or item.get("content")
            or title
        )
        source = item.get("source") or route
        timestamp = str(item.get("timestamp") or item.get("time") or datetime.now().isoformat())
        topics.append(
            HotTopic(
                title=str(title).strip(),
                source=str(source).strip(),
                summary=str(summary).strip(),
                timestamp=timestamp,
                raw_payload=item,
            )
        )
    return topics


def build_manual_topic(title: str, summary: str = "") -> HotTopic:
    return HotTopic(
        title=title,
        source="manual",
        summary=summary or f"{title} 正在成为讨论焦点。",
        timestamp=datetime.now().isoformat(),
    )


def angle_selector(topic: HotTopic) -> StoryAngle:
    """选择一个更适合视觉故事传播的表达角度。"""
    return StoryAngle(
        angle_title=f"当热点闯进普通人的一天：{topic.title}",
        hook="大家以为自己只是围观热点，结果发现热点已经改写了自己的生活。",
        core_viewpoint="真正值得讲的，不是热点有多炸，而是普通人会在什么时候突然意识到自己已经身处变化之中。",
        why_shareable="读者容易代入自己，故事化表达比直接讲道理更容易被看完和转发。",
        tone="humorous",
    )


def story_planner(topic: HotTopic, angle: StoryAngle) -> list[StoryBeat]:
    """把热点组织成一条适合公众号长图的 8 格故事弧线。"""
    return [
        StoryBeat(1, "开场钩子", "主角刷到热点，以为又是一次普通围观。", "“这又和我有什么关系？”", "清晨地铁上，手机弹出热点提醒。", "进入日常场景"),
        StoryBeat(2, "第一层反差", "评论区吵得飞起，但主角还在喝豆浆。", "“先让我把早饭吃明白。”", "地铁摇晃，热搜标题在屏幕上放大。", "热点进入视野"),
        StoryBeat(3, "热点入侵现实", "到了工位，主角发现同事已经把热点变成了工作任务。", "“不是吧，这就轮到我加班了？”", "办公桌上同时摆着咖啡、电脑和会议通知。", "从围观变成参与"),
        StoryBeat(4, "荒诞升级", "每个人都说自己只是跟进趋势，结果谁都停不下来。", "“趋势的意思，是大家一起没空吃午饭吗？”", "会议室里 PPT 一页页飞过去，人物表情夸张。", "把抽象热点变成荒诞戏剧"),
        StoryBeat(5, "真正问题出现", "主角突然意识到，大家讨论的不是技术本身，而是自己会不会被重新定义。", "“原来我怕的不是新东西，是旧位置突然不稳了。”", "喧闹背景里主角表情停住，镜头拉近。", "从搞笑转入有分量的一击"),
        StoryBeat(6, "观点展开", "故事开始把热闹翻译成人话：热点最可怕的地方，是它总以新闻的形式出现，却以生活的形式落地。", "“新闻是别人的，后果是自己的。”", "画面切成三联：工作、创作、社交都被影响。", "把观点藏进情节"),
        StoryBeat(7, "幽默收束", "主角决定不再假装旁观，而是开始认真补课。", "“行吧，先学，不然下一次连吐槽都跟不上。”", "主角打开学习文档，表情又无奈又认命。", "把焦虑转成行动"),
        StoryBeat(8, "结尾余味", f"热点散了，但 {topic.title} 留下的问题还在。真正的分水岭，不是看见没看见，而是看见之后你准备怎么活。", "“热搜会下去，时代不会。”", "夜晚窗边，城市灯光与手机屏幕一起亮着。", "留下分享价值"),
    ]


def script_writer(topic: HotTopic, angle: StoryAngle, beats: list[StoryBeat]) -> list[StoryboardFrame]:
    """把剧情节点写成适合长图阅读的分镜脚本。"""
    frames: list[StoryboardFrame] = []
    palette_cycle = ["warm amber", "tea green", "dusty blue", "soft orange"]
    for beat in beats:
        frames.append(
            StoryboardFrame(
                frame_index=beat.beat_index,
                caption=(
                    f"{beat.narration} 这背后真正想说的是：{angle.core_viewpoint}"
                    if beat.beat_index in (5, 6)
                    else beat.narration
                ),
                dialogue=beat.dialogue,
                scene_description=f"{beat.scene_description} 主题关联：{topic.title}",
                image_prompt=(
                    "humorous visual story for WeChat long image, cinematic comic panel, "
                    f"{beat.scene_description}, subtle satire, expressive characters, {palette_cycle[(beat.beat_index - 1) % len(palette_cycle)]}"
                ),
                layout_hint="image_top_text_bottom" if beat.beat_index % 2 else "split_text_image",
                palette_hint=palette_cycle[(beat.beat_index - 1) % len(palette_cycle)],
            )
        )
    return frames


def visual_director(frames: list[StoryboardFrame]) -> list[StoryboardFrame]:
    """统一视觉规则，真实产品里这里应该接风格控制和角色一致性模型。"""
    updated: list[StoryboardFrame] = []
    for frame in frames:
        updated.append(
            StoryboardFrame(
                frame_index=frame.frame_index,
                caption=frame.caption,
                dialogue=frame.dialogue,
                scene_description=frame.scene_description,
                image_prompt=frame.image_prompt + ", coherent character design, vertical composition, readable text area",
                layout_hint=frame.layout_hint,
                palette_hint=frame.palette_hint,
            )
        )
    return updated


def story_reviewer(topic: HotTopic, angle: StoryAngle, frames: list[StoryboardFrame]) -> ReviewResult:
    del topic
    issues: list[ReviewIssue] = []
    if len(frames) < 6:
        issues.append(ReviewIssue("high", "global", "故事格数太少，不足以形成公众号长图的阅读节奏。"))
    if "humorous" not in angle.tone:
        issues.append(ReviewIssue("medium", "angle", "当前表达不够轻巧，不符合视觉故事的趣味传播目标。"))
    if not any("真正想说的是" in frame.caption for frame in frames):
        issues.append(ReviewIssue("medium", "script", "剧情有趣，但观点层没有被明确托出来。"))

    if issues:
        return ReviewResult(
            status="REVISE",
            score=74.0,
            issues=issues,
            suggestions=[
                "补足故事推进层次，让前后格之间更有连续性。",
                "把观点藏进剧情，但至少要有一两格明确点题。",
            ],
            retry_stage="script_writer",
        )

    return ReviewResult(
        status="PASS",
        score=90.0,
        issues=[],
        suggestions=["故事节奏、趣味性和公众号传播结构已达标。"],
        retry_stage=None,
    )


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(text: str, width: int) -> str:
    return fill(text, width=width, break_long_words=False, break_on_hyphens=False)


def render_panel_image(frame: StoryboardFrame, width: int = CANVAS_WIDTH) -> Image.Image:
    """用本地渲染器生成一格视觉故事图。

    当前不是调用真正的图片模型，而是先生成具有产品形态的图文 panel。
    后续替换点：
    - 真实图片模型生成画面
    - 再把文案叠到图片上
    """
    image = Image.new("RGB", (width, PANEL_HEIGHT), FRAME_BG)
    draw = ImageDraw.Draw(image)
    title_font = _load_font(42)
    body_font = _load_font(30)
    quote_font = _load_font(36)
    small_font = _load_font(24)

    draw.rounded_rectangle((18, 18, width - 18, PANEL_HEIGHT - 18), radius=28, outline=FRAME_BORDER, width=4)

    scene_box = (44, 44, width - 44, 300)
    draw.rounded_rectangle(scene_box, radius=30, fill=_palette_color(frame.palette_hint), outline=None)

    # 简单画几个拟人化元素，确保成图不是纯文字。
    _draw_scene_shapes(draw, scene_box, frame.frame_index)

    text_y = 330
    draw.text((54, text_y), f"第 {frame.frame_index} 格", fill=ACCENT_COLOR, font=title_font)
    text_y += 60
    draw.multiline_text((54, text_y), _wrap(frame.caption, 23), fill=TEXT_COLOR, font=body_font, spacing=12)
    text_y += 112
    draw.multiline_text((54, text_y), f"“{frame.dialogue}”", fill="#5c4033", font=quote_font, spacing=10)
    draw.text((width - 360, PANEL_HEIGHT - 52), frame.layout_hint, fill="#8c7c70", font=small_font)
    return image


def _palette_color(name: str) -> str:
    palette = {
        "warm amber": "#f4d2a1",
        "tea green": "#d8e5c0",
        "dusty blue": "#c9d9ea",
        "soft orange": "#f5c4a6",
    }
    return palette.get(name, "#e6dccf")


def _draw_scene_shapes(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], seed: int) -> None:
    left, top, right, bottom = box
    width = right - left
    height = bottom - top
    # 背景建筑/屏幕
    draw.rounded_rectangle((left + 38, top + 32, left + width - 38, top + 92), radius=18, fill="#fff7ec")
    draw.rectangle((left + 80, top + 110, left + 220, top + 245), fill="#fff2d9", outline="#8d6f57", width=3)
    # 人物头
    circle_x = left + 340 + seed * 8
    draw.ellipse((circle_x, top + 96, circle_x + 96, top + 192), fill="#f7e0c5", outline="#694a36", width=3)
    # 身体
    draw.rounded_rectangle((circle_x - 18, top + 180, circle_x + 112, top + 258), radius=20, fill="#7b98b6")
    # 对话气泡
    draw.rounded_rectangle((left + 520, top + 86, right - 50, top + 196), radius=24, fill="#fffaf2", outline="#6d5647", width=3)
    draw.polygon([(left + 560, top + 196), (left + 590, top + 196), (left + 570, top + 222)], fill="#fffaf2", outline="#6d5647")
    # 一些表情线条增加喜剧感
    draw.arc((circle_x + 24, top + 128, circle_x + 44, top + 148), 0, 180, fill="#3a2a21", width=2)
    draw.arc((circle_x + 54, top + 128, circle_x + 74, top + 148), 0, 180, fill="#3a2a21", width=2)
    draw.arc((circle_x + 30, top + 154, circle_x + 74, top + 176), 0, 180, fill="#a24f32", width=3)


def compose_long_image(
    title: str,
    subtitle: str,
    cover_hook: str,
    frames: list[StoryboardFrame],
    outro_text: str,
    output_path: Path,
) -> LongImagePackage:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total_height = COVER_HEIGHT + len(frames) * (PANEL_HEIGHT + GAP) + ENDING_HEIGHT + MARGIN * 2
    canvas = Image.new("RGB", (CANVAS_WIDTH, total_height), BG_COLOR)
    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(68)
    subtitle_font = _load_font(34)
    body_font = _load_font(30)
    small_font = _load_font(22)

    # Cover
    cover_box = (MARGIN, MARGIN, CANVAS_WIDTH - MARGIN, MARGIN + COVER_HEIGHT)
    draw.rounded_rectangle(cover_box, radius=44, fill="#fff9f2", outline=FRAME_BORDER, width=5)
    draw.text((MARGIN + 36, MARGIN + 36), "微信视觉故事", fill=ACCENT_COLOR, font=subtitle_font)
    draw.multiline_text((MARGIN + 36, MARGIN + 112), _wrap(title, 14), fill=TEXT_COLOR, font=title_font, spacing=12)
    draw.multiline_text((MARGIN + 40, MARGIN + 286), _wrap(subtitle, 34), fill="#5a4639", font=subtitle_font, spacing=10)
    draw.multiline_text((MARGIN + 40, MARGIN + 404), _wrap(cover_hook, 34), fill="#7d4a2b", font=body_font, spacing=10)
    draw.text((CANVAS_WIDTH - 340, MARGIN + COVER_HEIGHT - 52), datetime.now().strftime("%Y-%m-%d"), fill="#8c7c70", font=small_font)

    current_y = MARGIN + COVER_HEIGHT + GAP
    for frame in frames:
        panel = render_panel_image(frame)
        canvas.paste(panel, (0, current_y))
        current_y += PANEL_HEIGHT + GAP

    # Ending
    ending_box = (MARGIN, current_y, CANVAS_WIDTH - MARGIN, current_y + ENDING_HEIGHT)
    draw.rounded_rectangle(ending_box, radius=36, fill="#fff7ee", outline=FRAME_BORDER, width=4)
    draw.text((MARGIN + 36, current_y + 34), "结尾", fill=ACCENT_COLOR, font=subtitle_font)
    draw.multiline_text((MARGIN + 36, current_y + 94), _wrap(outro_text, 34), fill=TEXT_COLOR, font=body_font, spacing=12)

    canvas.save(output_path)
    return LongImagePackage(
        title=title,
        subtitle=subtitle,
        cover_hook=cover_hook,
        frames=frames,
        outro_text=outro_text,
        output_file_path=output_path,
    )


def build_visual_story(topic: HotTopic) -> tuple[LongImagePackage, ReviewResult]:
    angle = angle_selector(topic)
    beats = story_planner(topic, angle)
    frames = visual_director(script_writer(topic, angle, beats))
    review = story_reviewer(topic, angle, frames)
    if review.status != "PASS":
        raise RuntimeError(f"Story review failed: {review}")

    safe_stem = "".join(ch if ch.isalnum() else "_" for ch in topic.title)[:60].strip("_") or "visual_story"
    output_path = OUTPUT_DIR / f"{safe_stem}.png"
    package = compose_long_image(
        title=angle.angle_title,
        subtitle=f"来源：{topic.source} | 风格：幽默诙谐有趣 | 形式：公众号视觉长图",
        cover_hook=angle.hook,
        frames=frames,
        outro_text=(
            "这不是在劝你害怕热点，而是提醒你：真正能拉开差距的，从来不是谁先刷到消息，"
            "而是谁更早把消息翻译成自己的行动。"
        ),
        output_path=output_path,
    )
    return package, review


def demo_from_manual_topic() -> LongImagePackage:
    topic = build_manual_topic(
        title="AI 代理开始接管越来越多白领工作流",
        summary="从写方案到做汇报，越来越多过去由白领完成的流程正被 AI Agent 介入。",
    )
    package, review = build_visual_story(topic)
    print("=== Visual Story Studio Demo ===")
    print(f"Topic: {topic.title}")
    print(f"Source: {topic.source}")
    print(f"Review: {review.status} / {review.score}")
    print(f"Output: {package.output_file_path}")
    return package


if __name__ == "__main__":
    demo_from_manual_topic()
