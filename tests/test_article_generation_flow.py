import sys
from pathlib import Path

import requests


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

import grok_wechat_article as article  # noqa: E402
import grok_wechat_server as server  # noqa: E402


def _draft(title: str = "旧标题") -> article.ArticleDraft:
    return article.ArticleDraft(
        title=title,
        subtitle="一个女孩靠学习改变命运",
        summary="从农村困境到大学和模特舞台的成长故事。",
        cover_image_prompt="editorial portrait of a young Chinese woman, no text overlay",
        cover_image_alt="年轻女性肖像",
        intro_paragraphs=["她的故事不是逆袭神话，而是一次次选择的结果。"],
        sections=[
            article.ArticleSection(
                heading="农村童年",
                hook="苦日子最先教会她观察世界。",
                paragraphs=["小时候的生活很窄。", "但她一直保留着读书的念头。"],
                bullets=["家务很重", "资源很少", "学习是出口"],
                takeaway="困境没有定义她。",
                image_prompt="young rural Chinese girl studying beside a wooden desk, no text overlay",
                image_alt="农村女孩学习",
                image_caption="她在有限条件里寻找机会。",
            )
        ],
        conclusion_title="把人生走成自己的样子",
        conclusion_paragraphs=["真正的改变来自长期选择。"],
        call_to_action="愿每个普通女孩都看见自己的可能。",
        tags=["成长", "女性故事", "教育"],
    )


def test_article_prompt_includes_expanded_planning_fields() -> None:
    request = article.ArticleRequest(
        topic="农村女孩靠学习改变命运，最终成为模特",
        audience="关注女性成长的公众号读者",
        tone="克制、温暖、真实",
        sections=4,
        outline="1. 苦涩童年 2. 学习突围 3. 大学重塑 4. 模特舞台",
        key_points=["不要写成爽文", "突出长期努力", "保留农村生活细节"],
        story_type="story",
        reference_image_url="https://example.com/person.jpg",
    )

    prompt = article.XAITextGenerationTool._build_user_prompt(request)

    assert "Story type: story" in prompt
    assert "1. 苦涩童年" in prompt
    assert "不要写成爽文" in prompt
    assert "https://example.com/person.jpg" in prompt
    assert "Follow the outline order and cover every key point explicitly" in prompt


def test_generation_profiles_prefer_vertex_models() -> None:
    for profile in article.SCRIPT_GENERATION_PROFILES.values():
        assert profile["text_candidates"][0].startswith("vertex:")
        assert profile["image_candidates"][0].startswith("vertex:")
    assert article.SCRIPT_TEXT_GATEWAY_CANDIDATES[0].startswith("vertex:")
    assert article.SCRIPT_IMAGE_FALLBACK_CANDIDATES[0].startswith("vertex:")


def test_server_default_text_priority_prefers_vertex(monkeypatch) -> None:
    captured: list[tuple[str, str]] = []

    def fake_post(url, json, timeout):
        captured.append((json["provider"], json["model"]))
        raise RuntimeError("stop after first candidate")

    monkeypatch.setattr(requests, "post", fake_post)

    try:
        server._call_text_generation_api("test", race_mode=False)
    except RuntimeError:
        pass

    assert captured[0][0] == "vertex"


def test_balanced_or_quality_generation_revises_after_failed_review() -> None:
    original = _draft()
    revised = _draft("新标题")

    class FakeTool(article.UnifiedTextGenerationTool):
        def _generate_fastest_valid_draft(self, request: article.ArticleRequest) -> article.ArticleDraft:
            return original

        def _request_draft_review(
            self,
            candidate: article.TextGatewayCandidate,
            request: article.ArticleRequest,
            draft: article.ArticleDraft,
        ) -> dict[str, object]:
            return {
                "passes": False,
                "score": 60,
                "issues": ["没有覆盖关键要点"],
                "revision_instructions": "补足学习和大学阶段",
            }

        def _request_draft_revision(
            self,
            candidate: article.TextGatewayCandidate,
            request: article.ArticleRequest,
            draft: article.ArticleDraft,
            review: dict[str, object],
        ) -> article.ArticleDraft:
            return revised

    tool = FakeTool(
        api_url="http://example.test",
        candidates=[article.TextGatewayCandidate("vertex", "gemini-2.5-pro")],
        timeout_seconds=1,
        retry_attempts=1,
        retry_backoff_seconds=0,
        prompt_profile="quality",
    )

    result = tool.generate_article_draft(article.ArticleRequest(topic="测试"))

    assert result.title == "新标题"


def test_status_mapping_exposes_quality_flow_phases() -> None:
    assert server.status_for_generation_log("Reviewing article draft") == "reviewing"
    assert server.status_for_generation_log("Generating 5 images concurrently (workers=5)") == "generating_images"
    assert server.status_for_generation_log("Rendering markdown and html") == "rendering"
    assert server.status_for_generation_log("Uploading output files to OSS") == "uploading"
