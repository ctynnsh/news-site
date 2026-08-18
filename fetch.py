import os
import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from anthropic import Anthropic

BBC_WORLD_RSS = "https://feeds.bbci.co.uk/news/world/rss.xml"

# 从 .env 文件里读取 ANTHROPIC_API_KEY，放进环境变量
load_dotenv()

feed = feedparser.parse(BBC_WORLD_RSS)
latest = feed.entries[0]

print("标题:", latest.title)
print("链接:", latest.link)

# 把新闻网页下载下来，并从中挑出正文文字
# 加 User-Agent 是为了让请求看起来像正常浏览器访问，避免被网站拒绝
headers = {"User-Agent": "Mozilla/5.0"}
page = requests.get(latest.link, headers=headers)
soup = BeautifulSoup(page.text, "html.parser")

article_tag = soup.find("article")
paragraphs = article_tag.find_all("p") if article_tag else soup.find_all("p")
article_text = "\n".join(p.get_text() for p in paragraphs)

print("\n抓到的正文:")
print(article_text)

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

message = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=300,
    messages=[
        {
            "role": "user",
            "content": (
                "请根据下面的新闻正文，用中文写三句话总结，不要分点，直接写成一段话。"
                "正文里如果混有和这篇新闻无关的其他标题或推荐链接文字，请忽略它们。\n\n"
                f"标题: {latest.title}\n\n"
                f"正文:\n{article_text}"
            ),
        }
    ],
)

summary = message.content[0].text

print("\n中文摘要:")
print(summary)
