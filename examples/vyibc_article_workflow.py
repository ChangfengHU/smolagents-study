from __future__ import annotations

"""
集成 Vyibc (Auto Content API) 的真实“图文文章多 Agent 闭环”示例。

1. Planner (Grok-4.20) 负责定大纲
2. Researcher (Grok-4.20) 负责补充素材
3. Writer (Grok-4.20) 负责产出和修订
4. Visual Designer (Vertex Imagen 4 Ultra) 负责生成真实图片
5. Reviewer (Grok-4.20) 负责评审
6. Manager 负责闭环控制
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Literal, Any

# 确保可以导入 src 中的 smolagents
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from smolagents.vyibc_provider import VyibcModel, VyibcImageTool

ReviewStatus = Literal["PASS", "REVISE"]

@dataclass
class ArticleTask:
    topic: str
    audience: str
    style: str
    platform: str
    word_count: int
    need_images: bool = True
    image_count: int = 3
    extra_requirements: str = ""

@dataclass
class ArticlePlan:
    title_direction: str
    audience_takeaway: str
    tone: str
    outline: list[str]
    visual_style: str
    section_goals: list[str]

@dataclass
class FactItem:
    claim: str
    source: str
    confidence: float

@dataclass
class ResearchPack:
    summary: str
    facts: list[FactItem]
    examples: list[str]
    warnings: list[str]

@dataclass
class ArticleDraft:
    title: str
    subtitle: str
    intro: str
    sections: list[str]
    conclusion: str
    version: int

@dataclass
class ImageInfo:
    section_index: int
    prompt: str
    url: str

@dataclass
class ImagePlan:
    cover_info: ImageInfo
    inline_infos: list[ImageInfo]

@dataclass
class ReviewIssue:
    location: str
    issue_type: str
    severity: Literal["low", "medium", "high"]
    description: str

@dataclass
class ReviewResult:
    status: ReviewStatus
    score: float
    issues: list[ReviewIssue]
    suggestions: list[str]
    revised_focus: list[str]

@dataclass
class IterationRecord:
    round_index: int
    draft: ArticleDraft
    image_plan: ImagePlan
    review: ReviewResult

@dataclass
class ArticleSessionState:
    task: ArticleTask
    plan: ArticlePlan | None = None
    research: ResearchPack | None = None
    current_draft: ArticleDraft | None = None
    current_image_plan: ImagePlan | None = None
    current_review: ReviewResult | None = None
    iterations: list[IterationRecord] = field(default_factory=list)
    round_index: int = 0
    final_status: str = "IN_PROGRESS"

# 初始化真实模型和工具
# 文本模型使用 Grok-4.20
text_model = VyibcModel(provider="grok", model="grok-4.20")
# 图片工具
image_tool = VyibcImageTool()

def _parse_json(text: str) -> Any:
    """从 LLM 回复中提取并解析 JSON。"""
    try:
        # 寻找 ```json ... ```
        if "```json" in text:
            content = text.split("```json")[1].split("```")[0].strip()
        else:
            content = text.strip()
        return json.loads(content)
    except Exception as e:
        print(f"JSON 解析失败: {e}\n原文内容: {text}")
        return None

def planner_agent(task: ArticleTask) -> ArticlePlan:
    """Planner：使用 Grok-4.20 制定计划。"""
    prompt = f"""
    作为一名资深内容策划，请为以下任务制定文章计划：
    主题: {task.topic}
    受众: {task.audience}
    风格: {task.style}
    平台: {task.platform}
    字数目标: {task.word_count}
    额外要求: {task.extra_requirements}

    请输出 JSON 格式，结构如下：
    {{
      "title_direction": "标题方向",
      "audience_takeaway": "受众核心收获",
      "tone": "语气偏好",
      "outline": ["目录1", "目录2", ...],
      "visual_style": "视觉风格描述（用于后续生图）",
      "section_goals": ["第一段目标", "第二段目标", ...]
    }}
    """
    response = text_model([{"role": "user", "content": prompt}])
    data = _parse_json(response.content)
    return ArticlePlan(**data)

def researcher_agent(task: ArticleTask, plan: ArticlePlan) -> ResearchPack:
    """Researcher：搜集素材。"""
    prompt = f"""
    针对文章《{plan.title_direction}》，请搜集相关的关键事实、真实案例和风险警告。
    主题背景: {task.topic}
    计划大纲: {plan.outline}

    请输出 JSON 格式，结构如下：
    {{
      "summary": "背景综述",
      "facts": [
        {{"claim": "事实声明", "source": "来源描述", "confidence": 0.9}}
      ],
      "examples": ["案例1", "案例2"],
      "warnings": ["风险点1", "风险点2"]
    }}
    """
    response = text_model([{"role": "user", "content": prompt}])
    data = _parse_json(response.content)
    facts = [FactItem(**f) for f in data["facts"]]
    return ResearchPack(
        summary=data["summary"],
        facts=facts,
        examples=data["examples"],
        warnings=data["warnings"]
    )

def writer_agent(
    task: ArticleTask,
    plan: ArticlePlan,
    research: ResearchPack,
    previous_draft: ArticleDraft | None,
    review_history: list[ReviewResult],
    version: int,
) -> ArticleDraft:
    """Writer：撰写或修改初稿。"""
    mode = "初稿撰写" if version == 1 else "根据反馈修改"
    feedback = ""
    if review_history:
        latest = review_history[-1]
        feedback = f"上轮评审状态: {latest.status}, 建议: {latest.suggestions}, 修改重点: {latest.revised_focus}"

    prompt = f"""
    作为一名优秀作家，请执行【{mode}】。
    文章计划: {plan}
    调研素材: {research}
    受众: {task.audience}
    风格: {task.style}
    当前版本: {version}
    {f"历史反馈: {feedback}" if feedback else ""}

    要求：标题要吸引人，正文要有深度。
    请输出 JSON 格式，结构如下：
    {{
      "title": "最终标题",
      "subtitle": "副标题",
      "intro": "引言",
      "sections": ["正文第1段", "正文第2段", "正文第3段"],
      "conclusion": "结语"
    }}
    """
    response = text_model([{"role": "user", "content": prompt}])
    data = _parse_json(response.content)
    return ArticleDraft(**data, version=version)

def visual_designer_agent(task: ArticleTask, draft: ArticleDraft, plan: ArticlePlan) -> ImagePlan:
    """Visual Designer：生成真实图片。"""
    print(f"正在为文章《{draft.title}》生成图片...")
    
    # 封面图
    cover_prompt = f"Magazine cover illustration, {plan.visual_style}, theme: {draft.title}, cinematic lighting"
    cover_urls = image_tool(prompt=cover_prompt, provider="vertex", model="imagen-4.0-ultra-generate-001")
    cover_info = ImageInfo(section_index=-1, prompt=cover_prompt, url=cover_urls[0] if cover_urls else "ERR_NO_IMAGE")

    inline_infos = []
    # 为每段正文配一张图
    for idx, section in enumerate(draft.sections):
        inline_prompt = f"Editorial illustration, {plan.visual_style}, centered composition: {section[:80]}"
        print(f"  - 生成第 {idx+1} 段配图...")
        urls = image_tool(prompt=inline_prompt, provider="vertex", model="imagen-4.0-ultra-generate-001")
        inline_infos.append(ImageInfo(section_index=idx, prompt=inline_prompt, url=urls[0] if urls else "ERR_NO_IMAGE"))

    return ImagePlan(cover_info=cover_info, inline_infos=inline_infos)

def reviewer_agent(
    task: ArticleTask,
    plan: ArticlePlan,
    research: ResearchPack,
    draft: ArticleDraft,
    image_plan: ImagePlan,
) -> ReviewResult:
    """Reviewer：评审文章。"""
    prompt = f"""
    作为文章主编，请对以下草稿进行严格评审：
    草稿标题: {draft.title}
    正文内容: {draft.sections}
    图片方案: {image_plan}
    
    评审标准：
    1. 是否符合受众 {task.audience} 的品位？
    2. 是否涵盖了调研中的事实？
    3. 逻辑是否通顺？

    请输出 JSON 格式，结构如下：
    {{
      "status": "PASS" 或 "REVISE",
      "score": 评分(0-100),
      "issues": [
        {{"location": "具体位置", "issue_type": "问题类型", "severity": "low/medium/high", "description": "详细描述"}}
      ],
      "suggestions": ["修改建议1", "修改建议2"],
      "revised_focus": ["下轮修改的具体重点领域"]
    }}
    """
    response = text_model([{"role": "user", "content": prompt}])
    data = _parse_json(response.content)
    issues = [ReviewIssue(**i) for i in data.get("issues", [])]
    return ReviewResult(
        status=data["status"],
        score=data["score"],
        issues=issues,
        suggestions=data["suggestions"],
        revised_focus=data.get("revised_focus", [])
    )

def manager_run(task: ArticleTask, max_rounds: int = 2) -> ArticleSessionState:
    """统一调度。"""
    state = ArticleSessionState(task=task)
    print("\n[Planner] 正在制定计划...")
    state.plan = planner_agent(task)
    
    print("[Researcher] 正在搜集资料...")
    state.research = researcher_agent(task, state.plan)

    review_history: list[ReviewResult] = []
    previous_draft: ArticleDraft | None = None

    for round_index in range(1, max_rounds + 1):
        state.round_index = round_index
        print(f"\n--- Round {round_index} ---")
        
        print("[Writer] 正在撰写内容...")
        draft = writer_agent(task, state.plan, state.research, previous_draft, review_history, round_index)
        
        print("[Visual Designer] 正在生成视觉方案...")
        image_plan = visual_designer_agent(task, draft, state.plan)
        
        print("[Reviewer] 正在盲审...")
        review = reviewer_agent(task, state.plan, state.research, draft, image_plan)

        state.current_draft = draft
        state.current_image_plan = image_plan
        state.current_review = review
        state.iterations.append(IterationRecord(round_index, draft, image_plan, review))

        print(f"当前评审状态: {review.status}, 评分: {review.score}")
        if review.status == "PASS":
            print("\n[Manager] 审核通过！")
            state.final_status = "PASS"
            return state
        
        review_history.append(review)
        previous_draft = draft

    state.final_status = "MAX_ROUNDS_REACHED"
    return state

def _print_final(state: ArticleSessionState):
    """打印最终结果。"""
    print("\n" + "="*50)
    print(" 任务最终报告 ")
    print("="*50)
    if state.current_draft:
        print(f"标题: {state.current_draft.title}")
        print(f"副标题: {state.current_draft.subtitle}")
        print(f"封面图 URL: {state.current_image_plan.cover_info.url}")
        print("-" * 20)
        print(f"引言: {state.current_draft.intro}")
        for idx, section in enumerate(state.current_draft.sections):
            print(f"\n[段落 {idx+1}]")
            print(section)
            print(f"配图 URL: {state.current_image_plan.inline_infos[idx].url}")
        print("\n" + state.current_draft.conclusion)
    print("="*50)

def demo():
    task = ArticleTask(
        topic="AI 代理 (Agent) 如何改变程序员的职业生涯",
        audience="资深开发者与技术管理者",
        style="专业、前瞻、带一点幽默感",
        platform="微信公众号/掘金",
        word_count=1200,
        extra_requirements="强调 Agent 不是替代猎头或老板，而是变成了你的『数字孪生』同事。"
    )
    state = manager_run(task)
    _print_final(state)

if __name__ == "__main__":
    demo()
