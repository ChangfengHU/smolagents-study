"""
故事分镜图片提示词生成器
Story Storyboard Image Prompt Generator

输入一段故事叙事文本，自动完成：
  1. 角色提取    → 生成每个角色的固定外貌描述（Character Card）
  2. 场景拆帧    → 按关键动作节点将故事拆成 N 帧
  3. 提示词生成  → 为每帧生成英文图片生成提示词（保证角色一致性）

[TODO] 第 4 步：调用图像生成 API（SD / DALL-E / Midjourney）
       接入方式见文件底部 generate_images_todo() 的说明注释

依赖：
  pip install python-dotenv
  项目 src/ 目录已在 sys.path 中（见下方路径设置）

环境变量（.env 或 PyCharm Run Configuration）：
  OPENAI_API_KEY=<your key>
  OPENAI_API_BASE=https://api.openai.com/v1   # 可选，默认值
  OPENAI_MODEL_ID=gpt-4.1-nano                # 可选，默认值
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 让本地 src/ 目录可直接 import，无需 pip install（PyCharm 快速运行用）
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # type: ignore
from smolagents import OpenAIServerModel  # type: ignore


# ===========================================================================
# 数据结构
# ===========================================================================

@dataclass
class Character:
    """角色卡：固定外貌描述，跨帧复用，保证角色一致性。"""
    name: str
    appearance: str        # 中文外貌描述
    appearance_en: str     # 英文外貌描述（用于 prompt）


@dataclass
class StoryFrame:
    """单帧分镜：一个关键动作节点。"""
    index: int
    description_zh: str    # 这一帧发生了什么（中文）
    setting: str           # 场景环境（中文）
    characters: list[str]  # 涉及哪些角色名
    action: str            # 核心动作（中文）
    mood: str              # 氛围/情绪（中文）
    camera: str            # 镜头构图建议（中文）


@dataclass
class ImagePrompt:
    """一帧对应的图片生成提示词。"""
    frame_index: int
    frame_desc: str        # 帧描述（中文，便于阅读）
    prompt_en: str         # 英文提示词（送入图像 API）
    # TODO: generated_image_url: str = ""  # 第 4 步接图像 API 后填入


@dataclass
class StoryboardResult:
    """完整分镜结果。"""
    story: str
    art_style: str
    characters: list[Character] = field(default_factory=list)
    frames: list[StoryFrame] = field(default_factory=list)
    image_prompts: list[ImagePrompt] = field(default_factory=list)


# ===========================================================================
# LLM 调用封装
# ===========================================================================

def _call_model(model: OpenAIServerModel, system: str, user: str) -> str:
    """向模型发送一次对话，返回纯文本响应。"""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    response = model(messages)
    # OpenAIServerModel 返回 ChatMessage，content 为字符串
    return response.content.strip()


def _parse_json(text: str) -> object:
    """从模型输出中提取 JSON（兼容 ```json ... ``` 包裹的格式）。"""
    # 去掉可能的 markdown 代码块
    if "```" in text:
        lines = text.split("\n")
        json_lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(json_lines)
    return json.loads(text.strip())


# ===========================================================================
# Step 1：角色提取
# ===========================================================================

EXTRACT_CHARACTERS_SYSTEM = """你是一个专业的故事分析师。
用户会给你一段故事文本，请提取所有出现的角色，并为每个角色生成固定的外貌描述。

输出严格为 JSON 数组，每个元素包含：
- name: 角色名（中文）
- appearance: 外貌描述（中文，30字以内，包含发型/服装/体型等视觉特征）
- appearance_en: 外貌描述（英文，用于 AI 图像生成，50词以内，具体且可视化）

示例输出：
[
  {
    "name": "小红",
    "appearance": "18岁女孩，扎双马尾，穿白色校服，背红色书包，圆脸",
    "appearance_en": "18-year-old girl, twin ponytails, white school uniform, red backpack, round face, cheerful expression"
  }
]

只输出 JSON，不要任何解释。"""


def extract_characters(model: OpenAIServerModel, story: str) -> list[Character]:
    """Step 1：从故事中提取角色并生成角色卡。"""
    print("\n[Step 1] 提取角色...")
    raw = _call_model(model, EXTRACT_CHARACTERS_SYSTEM, f"故事文本：\n{story}")
    data = _parse_json(raw)
    characters = [
        Character(
            name=item["name"],
            appearance=item["appearance"],
            appearance_en=item["appearance_en"],
        )
        for item in data
    ]
    for c in characters:
        print(f"  角色: {c.name} — {c.appearance}")
    return characters


# ===========================================================================
# Step 2：场景拆帧
# ===========================================================================

DECOMPOSE_FRAMES_SYSTEM = """你是一个专业的分镜师。
用户会给你一段故事文本和角色列表，请将故事拆分为 3~6 个关键分镜帧。

拆帧原则：
- 每帧对应一个情绪转折点或关键动作
- 不是每句话都需要一帧，要抓重点
- 镜头要有变化（远景/中景/特写交替）

输出严格为 JSON 数组，每个元素包含：
- index: 帧编号（从 1 开始）
- description_zh: 这一帧发生了什么（中文，20字以内）
- setting: 场景环境（中文，如"卧室，清晨，阳光透过窗帘"）
- characters: 涉及的角色名列表（如 ["小红"]）
- action: 核心动作（中文，如"小红伸了个懒腰，坐起身"）
- mood: 氛围情绪（中文，如"温暖慵懒"）
- camera: 镜头构图（中文，如"中景，侧面视角"）

只输出 JSON，不要任何解释。"""


def decompose_frames(
    model: OpenAIServerModel,
    story: str,
    characters: list[Character],
) -> list[StoryFrame]:
    """Step 2：将故事拆分为分镜帧。"""
    print("\n[Step 2] 拆分分镜帧...")
    char_desc = "\n".join(f"- {c.name}: {c.appearance}" for c in characters)
    user_msg = f"故事文本：\n{story}\n\n角色列表：\n{char_desc}"
    raw = _call_model(model, DECOMPOSE_FRAMES_SYSTEM, user_msg)
    data = _parse_json(raw)
    frames = [
        StoryFrame(
            index=item["index"],
            description_zh=item["description_zh"],
            setting=item["setting"],
            characters=item["characters"],
            action=item["action"],
            mood=item["mood"],
            camera=item["camera"],
        )
        for item in data
    ]
    for f in frames:
        print(f"  帧{f.index}: {f.description_zh}（{f.camera}）")
    return frames


# ===========================================================================
# Step 3：图片提示词生成
# ===========================================================================

GENERATE_PROMPTS_SYSTEM = """你是一个专业的 AI 图像提示词工程师。
用户会给你分镜帧信息和角色描述，请为每帧生成高质量的英文图像生成提示词。

提示词要求：
- 50~80 个英文单词
- 包含：画风 + 角色完整外貌描述 + 场景环境 + 角色动作 + 镜头构图 + 光线氛围
- 角色描述必须使用提供的固定外貌描述（保证跨帧一致性）
- 画风统一为：anime style, high quality, detailed illustration

输出严格为 JSON 数组，每个元素包含：
- frame_index: 帧编号
- frame_desc: 帧描述（中文，直接复制 description_zh）
- prompt_en: 英文提示词

只输出 JSON，不要任何解释。"""


def generate_prompts(
    model: OpenAIServerModel,
    frames: list[StoryFrame],
    characters: list[Character],
) -> list[ImagePrompt]:
    """Step 3：为每帧生成图片提示词。"""
    print("\n[Step 3] 生成图片提示词...")

    # 构建角色查找表
    char_map = {c.name: c for c in characters}

    frames_info = []
    for f in frames:
        # 为这帧涉及的角色附上英文外貌描述
        chars_en = "; ".join(
            f"{name}: {char_map[name].appearance_en}"
            for name in f.characters
            if name in char_map
        )
        frames_info.append({
            "index": f.index,
            "description_zh": f.description_zh,
            "setting": f.setting,
            "characters_en": chars_en,
            "action": f.action,
            "mood": f.mood,
            "camera": f.camera,
        })

    user_msg = f"分镜帧信息：\n{json.dumps(frames_info, ensure_ascii=False, indent=2)}"
    raw = _call_model(model, GENERATE_PROMPTS_SYSTEM, user_msg)
    data = _parse_json(raw)
    prompts = [
        ImagePrompt(
            frame_index=item["frame_index"],
            frame_desc=item["frame_desc"],
            prompt_en=item["prompt_en"],
        )
        for item in data
    ]
    return prompts


# ===========================================================================
# TODO: Step 4 — 图像生成 API（下次开发）
# ===========================================================================

def generate_images_todo(prompts: list[ImagePrompt]) -> None:
    """
    [TODO] 接入图像生成 API，为每条 prompt 生成实际图片。

    候选方案：

    方案 A — OpenAI DALL-E 3
    -------------------------
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    for p in prompts:
        response = client.images.generate(
            model="dall-e-3",
            prompt=p.prompt_en,
            size="1024x1024",
            quality="standard",
        )
        p.generated_image_url = response.data[0].url

    方案 B — Stable Diffusion (本地 AUTOMATIC1111 API)
    ---------------------------------------------------
    import requests
    for p in prompts:
        resp = requests.post("http://127.0.0.1:7860/sdapi/v1/txt2img", json={
            "prompt": p.prompt_en,
            "negative_prompt": "blurry, deformed, ugly",
            "steps": 25,
            "width": 768,
            "height": 512,
        })
        # resp.json()["images"][0] 是 base64 图片

    方案 C — Midjourney (第三方 API 封装)
    -------------------------------------
    需要第三方服务，如 useapi.net 或 replicate.com
    """
    print("\n[TODO] Step 4: 图像生成 API 尚未接入，将在下次开发中实现。")
    print(f"       共 {len(prompts)} 条提示词待生成图片。")


# ===========================================================================
# 结果打印
# ===========================================================================

def print_result(result: StoryboardResult) -> None:
    """格式化打印最终分镜结果。"""
    print("\n" + "=" * 60)
    print("故事分镜结果")
    print("=" * 60)
    print(f"原始故事：{result.story}")
    print(f"画风：{result.art_style}")

    print("\n--- 角色卡 ---")
    for c in result.characters:
        print(f"  [{c.name}]")
        print(f"    中文描述: {c.appearance}")
        print(f"    英文描述: {c.appearance_en}")

    print("\n--- 分镜帧 + 图片提示词 ---")
    prompt_map = {p.frame_index: p for p in result.image_prompts}
    for f in result.frames:
        p = prompt_map.get(f.index)
        print(f"\n  帧 {f.index}: {f.description_zh}")
        print(f"    场景: {f.setting}")
        print(f"    动作: {f.action}")
        print(f"    氛围: {f.mood}")
        print(f"    镜头: {f.camera}")
        if p:
            print(f"    提示词: {p.prompt_en}")

    print("\n" + "=" * 60)


# ===========================================================================
# 主流程
# ===========================================================================

def run_storyboard(story: str, art_style: str = "anime style") -> StoryboardResult:
    """
    完整分镜生成流程。

    Args:
        story:     故事叙事文本（中文）
        art_style: 图片整体画风（默认 anime style）

    Returns:
        StoryboardResult 包含角色卡、分镜帧、图片提示词
    """
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    model_id = os.getenv("OPENAI_MODEL_ID", "gpt-4.1-nano")

    if not api_key:
        print("[dry-run] 未检测到 OPENAI_API_KEY，请配置后重试。")
        print("  PyCharm Run/Debug Configuration -> Environment variables:")
        print("    OPENAI_API_KEY=<your_key>")
        print("    OPENAI_API_BASE=https://api.openai.com/v1")
        print("    OPENAI_MODEL_ID=gpt-4.1-nano")
        return StoryboardResult(story=story, art_style=art_style)

    model = OpenAIServerModel(
        model_id=model_id,
        api_base=api_base,
        api_key=api_key,
    )

    result = StoryboardResult(story=story, art_style=art_style)

    # Step 1: 提取角色
    result.characters = extract_characters(model, story)

    # Step 2: 拆分分镜帧
    result.frames = decompose_frames(model, story, result.characters)

    # Step 3: 生成图片提示词
    result.image_prompts = generate_prompts(model, result.frames, result.characters)

    # Step 4: TODO 图像生成
    generate_images_todo(result.image_prompts)

    return result


def main() -> None:
    # 示例故事，可以替换成任意叙事文本
    story = (
        "小红早上被闹钟吵醒，揉了揉眼睛坐起来。"
        "她洗漱完毕，背上书包出了门。"
        "走在上学的路上，阳光很好。"
        "突然，迎面走来了她的同学小明，两人相视一笑，打了招呼，然后并肩继续走向学校。"
    )

    result = run_storyboard(story, art_style="anime style")

    if result.image_prompts:
        print_result(result)


if __name__ == "__main__":
    main()
