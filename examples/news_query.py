# 导入所需的库和模块
from smolagents.agents import ToolCallingAgent
from smolagents import tool, LiteLLMModel
from serpapi import GoogleSearch
import os
from google.colab import userdata

os.environ["OPENAI_API_KEY"] = userdata.get('OPENAI_API_KEY')

model = LiteLLMModel(model_id="gpt-4o-mini")

# # 初始化LLM模型
# model = LiteLLMModel(
#     model_id="ollama/mistral-nemo",
#     api_base="http://127.0.0.1:11434",
#     api_key="ollama",
# )


@tool
def search_ai_news(query: str) -> str:
    """
    搜索AI相关新闻并返回结果。

    Args:
        query: 要搜索的AI新闻关键词

    Returns:
        新闻搜索结果的字符串
    """
    params = {
        "engine": "google_news",
        "q": query,
        "gl": "us",
        "hl": "en",
        "api_key": "Your_API_KEY"  # 替换为你的 SerpAPI key
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

        if "news_results" not in results:
            return "No news results found."

        news_articles = results["news_results"][:3]  # 获取前3条新闻

        formatted_results = []
        for article in news_articles:
            title = article.get("title", "No title")
            source = article.get("source", {}).get("name", "Unknown source")
            date = article.get("date", "No date")
            link = article.get("link", "No link")

            formatted_results.append(
                f"Title: {title}\n"
                f"Source: {source}\n"
                f"Date: {date}\n"
                f"Link: {link}\n"
            )

        return "\n".join(formatted_results)

    except Exception as e:
        return f"Error occurred while fetching news: {str(e)}"


agent = ToolCallingAgent(tools=[search_ai_news], model=model)

# 执行
print(agent.run("What are the latest news about artificial intelligence?"))
