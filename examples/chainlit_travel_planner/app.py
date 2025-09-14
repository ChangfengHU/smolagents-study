import os
from typing import Optional

import chainlit as cl

from smolagents import CodeAgent, LiteLLMModel, WebSearchTool


SYSTEM_GUIDANCE = (
    "You are an expert travel planner. Build practical, day-by-day itineraries "
    "based on the user's preferences (dates, budget, trip length, interests, pace). "
    "Use the web_search tool to gather up-to-date facts (top sights, transit, opening hours). "
    "Respond in clear markdown with sections: Overview, Daily Plan, Logistics (transport, tickets), "
    "Dining Suggestions, and Tips. Be concise and specific."
)


def _select_model() -> LiteLLMModel:
    """Select a provider based on available API keys.

    Priority: OPENAI -> GROQ. Raise if none present.
    """
    openai_key = os.getenv("OPENAI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")

    if openai_key:
        return LiteLLMModel(model_id="gpt-4o-mini", api_key=openai_key)
    if groq_key:
        return LiteLLMModel(model_id="groq/llama-3.3-70b-versatile", api_key=groq_key)

    raise RuntimeError(
        "No API key found. Please set either OPENAI_API_KEY or GROQ_API_KEY in your environment."
    )


def _build_agent() -> CodeAgent:
    tools = [WebSearchTool(max_results=6, engine="duckduckgo")]
    model = _select_model()
    # stream_outputs=False to simplify Chainlit integration; we return a single message
    return CodeAgent(tools=tools, model=model, stream_outputs=False)


@cl.on_chat_start
async def on_start():
    try:
        agent = await cl.make_async(_build_agent)()
    except Exception as e:
        await cl.Message(
            content=f"Failed to initialize agent: {e}.\n\nSet OPENAI_API_KEY or GROQ_API_KEY and restart."
        ).send()
        return

    cl.user_session.set("agent", agent)

    await cl.Message(
        content=(
            "Hi! I plan trips using live web search.\n\n"
            "Tell me: destination, dates (or month), trip length, budget, pace, and interests.\n"
            "Example: '7 days in Japan in October, food + culture focus, mid-budget.'"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    agent: Optional[CodeAgent] = cl.user_session.get("agent")
    if agent is None:
        await cl.Message(content="Agent not ready. Please refresh the app.").send()
        return

    task = f"{SYSTEM_GUIDANCE}\n\nUser request: {message.content.strip()}"
    try:
        result = await cl.make_async(agent.run)(task)
    except Exception as e:
        await cl.Message(content=f"Error while planning: {e}").send()
        return

    # agent.run can return a string or a structured result; we normalize to string
    output = result if isinstance(result, str) else str(result)
    await cl.Message(content=output).send()

