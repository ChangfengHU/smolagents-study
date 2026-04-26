from __future__ import annotations

"""
一个最小可运行的“图文文章多 Agent 闭环”示例。

这个文件的目标不是模拟真实大模型推理，而是把工程骨架先搭清楚：
1. Planner 负责定大纲
2. Researcher 负责补充素材
3. Writer 负责产出初稿和修订稿
4. Visual Designer 负责给封面图和插图生成提示词
5. Reviewer 负责打回或通过
6. Manager 负责把上面的角色串成一个 REVISE -> PASS 的闭环

你后续如果要接入真实 smolagents / OpenAI / Qwen 模型，
最推荐的方式是保留这里的数据结构和 manager_run 的流程，
只把 planner_agent / writer_agent / reviewer_agent 这些函数替换成真正的 Agent 调用。
"""

from dataclasses import dataclass, field
from typing import Literal


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
class ImagePrompt:
    section_index: int
    purpose: str
    prompt: str
    style_note: str


@dataclass
class ImagePlan:
    cover_prompt: str
    inline_images: list[ImagePrompt]


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


def search_tool(query: str) -> str:
    """模拟搜索工具。

    真实项目里这里可以替换为：
    - 搜索 API
    - RAG 检索
    - 企业内部知识库
    """
    mock_search_db = {
        "AI painting definition": (
            "AI painting uses generative models to transform text prompts, sketches, or reference images "
            "into new visual outputs."
        ),
        "AI painting applications": (
            "Common use cases include ad concepts, game concept art, storyboard drafts, educational visuals, "
            "and rapid creative exploration."
        ),
        "AI painting risks": (
            "Key risks include copyright disputes, unclear training data provenance, style imitation, and "
            "misleading synthetic imagery."
        ),
    }
    return mock_search_db.get(query, f"Mock result for: {query}")


def image_prompt_tool(section_text: str, visual_style: str) -> str:
    """模拟图片提示词生成工具。

    当前只返回 prompt 文本。
    如果你后面要接图像模型，可以把这里替换成真正的出图接口。
    """
    summary = section_text.strip().replace("\n", " ")
    return f"{visual_style}; editorial illustration; {summary[:90]}"


def planner_agent(task: ArticleTask) -> ArticlePlan:
    """Planner：把用户需求拆成可执行的大纲与视觉方向。"""
    return ArticlePlan(
        title_direction=f"A publishable illustrated article about {task.topic} for {task.audience}",
        audience_takeaway="Readers should understand the concept, practical value, and boundaries of AI painting.",
        tone=task.style,
        outline=[
            "What AI painting is",
            "Where AI painting creates practical value",
            "What risks and boundaries must be considered",
        ],
        visual_style="clean modern editorial infographic",
        section_goals=[
            "Explain the concept in plain language.",
            "Connect capability to real usage scenarios.",
            "Show risks without turning the piece into fearmongering.",
        ],
    )


def researcher_agent(task: ArticleTask, plan: ArticlePlan) -> ResearchPack:
    """Researcher：围绕主题补充事实、案例、风险提醒。"""
    del task, plan
    facts = [
        FactItem(
            claim=search_tool("AI painting definition"),
            source="mock://definition",
            confidence=0.86,
        ),
        FactItem(
            claim=search_tool("AI painting applications"),
            source="mock://applications",
            confidence=0.84,
        ),
        FactItem(
            claim=search_tool("AI painting risks"),
            source="mock://risks",
            confidence=0.88,
        ),
    ]
    return ResearchPack(
        summary="Collected concise background material covering definition, applications, and risks.",
        facts=facts,
        examples=[
            "Design teams use it for fast concept exploration.",
            "Marketing teams use it to test multiple creative directions.",
            "Educators use it to visualize abstract concepts quickly.",
        ],
        warnings=[
            "Do not overclaim reliability or originality.",
            "Keep human review explicit when discussing publishing workflows.",
        ],
    )


def writer_agent(
    task: ArticleTask,
    plan: ArticlePlan,
    research: ResearchPack,
    previous_draft: ArticleDraft | None,
    review_history: list[ReviewResult],
    version: int,
) -> ArticleDraft:
    """Writer：第 1 轮写初稿，第 2 轮开始吸收 Reviewer 的反馈改稿。"""
    del plan, research, previous_draft

    if version == 1:
        return ArticleDraft(
            title="What Is AI Painting and Why Is Everyone Talking About It?",
            subtitle="A quick illustrated introduction to the tools changing image creation.",
            intro=(
                f"{task.topic} is showing up across design, marketing, and social content, but many readers still "
                "treat it as a novelty instead of a production tool."
            ),
            sections=[
                (
                    "AI painting refers to systems that generate images from prompts or references. In simple terms, "
                    "it lowers the barrier to visual expression by letting people describe what they want instead of "
                    "drawing every detail manually."
                ),
                (
                    "It is already used in creative work. Teams can explore ideas faster, produce drafts for campaigns, "
                    "and sketch visual directions before spending time on polished execution."
                ),
                (
                    "The technology also raises concerns. Copyright, imitation of artistic style, and fake images are "
                    "all part of the conversation, so teams should use it carefully."
                ),
            ],
            conclusion=(
                "The most useful way to understand AI painting is not as magic, but as a fast visual ideation tool "
                "that still needs human judgment."
            ),
            version=version,
        )

    latest_review = review_history[-1]
    focus_text = "; ".join(latest_review.revised_focus)
    return ArticleDraft(
        title="AI Painting: What It Is, Where It Helps, and Where Caution Matters",
        subtitle="An illustrated explainer that connects the technology to real workflows and real boundaries.",
        intro=(
            f"{task.topic} is no longer just an internet curiosity. It is becoming a working layer inside modern "
            "content production. This revised draft focuses on the previous review priorities: "
            f"{focus_text}."
        ),
        sections=[
            (
                "AI painting describes generative image systems that can turn text prompts, sketches, or reference "
                "images into new visuals. Its real significance is not that it can 'replace drawing', but that it "
                "converts visual ideation into a faster and more accessible process for non-specialists."
            ),
            (
                "Its strongest applications appear in workflows that value speed and option generation: advertising "
                "teams can test multiple campaign directions, game teams can explore world-building concepts, and "
                "educators can turn abstract ideas into visual teaching aids. In each case, the advantage is the same: "
                "rapid iteration before committing to final production quality."
            ),
            (
                "The benefits come with clear boundaries. If training data provenance is unclear, publication risk rises. "
                "If style imitation is used carelessly, brand and legal problems follow. If synthetic images are shared "
                "without review, they can distort public understanding. That is why the safest workflow treats AI "
                "painting as a draft-generation partner while leaving editorial, ethical, and publishing decisions to humans."
            ),
        ],
        conclusion=(
            "Used well, AI painting expands creative range and shortens early-stage production cycles. Used poorly, it "
            "creates trust and rights problems. The practical path is not blind automation, but controlled collaboration "
            "between generation systems and human review."
        ),
        version=version,
    )


def visual_designer_agent(task: ArticleTask, draft: ArticleDraft, plan: ArticlePlan) -> ImagePlan:
    """Visual Designer：根据文章内容给封面图和分段插图生成提示词。"""
    del task
    cover_prompt = image_prompt_tool(f"{draft.title}. {draft.subtitle}", plan.visual_style)
    inline_images: list[ImagePrompt] = []
    for idx, section in enumerate(draft.sections):
        inline_images.append(
            ImagePrompt(
                section_index=idx,
                purpose=f"Support section {idx + 1}",
                prompt=image_prompt_tool(section, plan.visual_style),
                style_note=plan.visual_style,
            )
        )
    return ImagePlan(cover_prompt=cover_prompt, inline_images=inline_images)


def reviewer_agent(
    task: ArticleTask,
    plan: ArticlePlan,
    research: ResearchPack,
    draft: ArticleDraft,
    image_plan: ImagePlan,
) -> ReviewResult:
    """Reviewer：给出结构化评审结论。

    这里故意设计为：
    - version 1 一定打回
    - version 2 通过

    这样可以稳定演示“初稿 -> 打回 -> 修订 -> 通过”的闭环。
    """
    del task, plan, research, image_plan

    if draft.version == 1:
        return ReviewResult(
            status="REVISE",
            score=72.0,
            issues=[
                ReviewIssue(
                    location="section_2",
                    issue_type="depth",
                    severity="medium",
                    description=(
                        "The applications section is too broad and does not explain why those workflows fit AI painting "
                        "especially well."
                    ),
                ),
                ReviewIssue(
                    location="section_3",
                    issue_type="argument",
                    severity="high",
                    description=(
                        "The risk discussion names problems but does not define operational boundaries for safe use."
                    ),
                ),
                ReviewIssue(
                    location="image_plan",
                    issue_type="image_text_alignment",
                    severity="medium",
                    description=(
                        "The visual directions are generic. They should map more tightly to each section's core idea."
                    ),
                ),
            ],
            suggestions=[
                "Strengthen section 2 by connecting each application scenario to the specific strengths of AI painting.",
                "Rewrite section 3 so that the article states concrete publishing boundaries and human review responsibilities.",
                "Make the visual prompts describe the narrative role of each image instead of only giving a broad art style.",
            ],
            revised_focus=[
                "Explain capability-to-scenario fit",
                "Add clear risk boundaries and human oversight",
                "Increase text-image alignment",
            ],
        )

    return ReviewResult(
        status="PASS",
        score=91.0,
        issues=[],
        suggestions=[
            "The article is now specific enough to publish as a high-quality illustrated explainer.",
        ],
        revised_focus=[],
    )


def manager_run(task: ArticleTask, max_rounds: int = 3) -> ArticleSessionState:
    """Manager：统一调度各角色，并保存每一轮的中间结果。

    闭环逻辑就是：
    1. Writer 产出 draft
    2. Visual Designer 生成图片方案
    3. Reviewer 评审
    4. 如果 review.status == PASS 就结束
    5. 否则进入下一轮继续改
    """
    state = ArticleSessionState(task=task)
    state.plan = planner_agent(task)
    state.research = researcher_agent(task, state.plan)

    review_history: list[ReviewResult] = []
    previous_draft: ArticleDraft | None = None

    for round_index in range(1, max_rounds + 1):
        state.round_index = round_index
        draft = writer_agent(
            task=task,
            plan=state.plan,
            research=state.research,
            previous_draft=previous_draft,
            review_history=review_history,
            version=round_index,
        )
        image_plan = visual_designer_agent(task, draft, state.plan)
        review = reviewer_agent(task, state.plan, state.research, draft, image_plan)

        state.current_draft = draft
        state.current_image_plan = image_plan
        state.current_review = review
        state.iterations.append(
            IterationRecord(
                round_index=round_index,
                draft=draft,
                image_plan=image_plan,
                review=review,
            )
        )

        review_history.append(review)
        previous_draft = draft

        if review.status == "PASS":
            state.final_status = "PASS"
            return state

    state.final_status = "MAX_ROUNDS_REACHED"
    return state


def _print_iteration(record: IterationRecord) -> None:
    """把每一轮结果打印得更适合人看。"""
    print(f"\n===== Round {record.round_index} =====")
    print(f"Title: {record.draft.title}")
    print(f"Subtitle: {record.draft.subtitle}")
    print(f"Intro: {record.draft.intro}")
    for idx, section in enumerate(record.draft.sections, start=1):
        print(f"Section {idx}: {section}")
    print(f"Conclusion: {record.draft.conclusion}")
    print(f"Cover prompt: {record.image_plan.cover_prompt}")
    for prompt in record.image_plan.inline_images:
        print(f"Image prompt {prompt.section_index + 1}: {prompt.prompt}")
    print(f"Review status: {record.review.status}")
    print(f"Review score: {record.review.score}")
    if record.review.issues:
        print("Issues:")
        for issue in record.review.issues:
            print(f"  - [{issue.severity}] {issue.location} / {issue.issue_type}: {issue.description}")
    print("Suggestions:")
    for suggestion in record.review.suggestions:
        print(f"  - {suggestion}")
    if record.review.revised_focus:
        print("Revised focus:")
        for focus in record.review.revised_focus:
            print(f"  - {focus}")


def build_wechat_task(
    topic: str,
    audience: str = "微信公众号读者",
    style: str = "专业但通俗，适合传播",
    word_count: int = 1500,
    image_count: int = 4,
    extra_requirements: str = "要有标题吸引力、结构清楚、适合公众号排版配图。",
) -> ArticleTask:
    """生成一个适合微信公众号图文文章的任务配置。

    你最常用的就是改这里的 topic。
    比如：
    - AI 绘画
    - AI Agent 入门
    - 为什么企业要做知识库
    """
    return ArticleTask(
        topic=topic,
        audience=audience,
        style=style,
        platform="微信公众号",
        word_count=word_count,
        need_images=True,
        image_count=image_count,
        extra_requirements=extra_requirements,
    )


def run_task(task: ArticleTask) -> ArticleSessionState:
    """统一入口：给一个任务，返回完整的闭环结果。"""
    state = manager_run(task)
    print("=== Multi-agent illustrated article workflow ===")
    print(f"Topic: {task.topic}")
    print(f"Audience: {task.audience}")
    print(f"Platform: {task.platform}")
    print(f"Style: {task.style}")
    print(f"Word count target: {task.word_count}")
    print(f"Extra requirements: {task.extra_requirements}")
    for record in state.iterations:
        _print_iteration(record)
    print(f"\nFinal status: {state.final_status}")
    return state


def demo() -> ArticleSessionState:
    """默认 demo：直接演示一个微信公众号图文主题。"""
    task = build_wechat_task(topic="AI 绘画")
    return run_task(task)


if __name__ == "__main__":
    demo()
