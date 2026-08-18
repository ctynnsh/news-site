import json
import os
import feedparser
from dotenv import load_dotenv
from anthropic import Anthropic

# 从 .env 文件里读取 ANTHROPIC_API_KEY
load_dotenv()
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# 五个新闻源：(显示名字, RSS 地址)
SOURCES = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("联合国新闻", "https://news.un.org/feed/subscribe/zh/news/all/rss.xml"),
    ("The Guardian World", "https://www.theguardian.com/world/rss"),
    ("Google News 中国-财经", "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
    ("Google News 中国-头条", "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
]

# 挨个抓取每个源，每个源只取最新 5 条，合并进一个大列表
articles = []
for source_name, url in SOURCES:
    feed = feedparser.parse(url)
    for entry in feed.entries[:5]:
        articles.append({
            "source": source_name,
            "title": entry.title,
            "link": entry.link,
        })

print(f"一共抓到 {len(articles)} 条新闻:\n")
numbered_list = ""
for i, art in enumerate(articles, start=1):
    line = f"{i}. [{art['source']}] {art['title']}"
    print(line)
    numbered_list += line + "\n"

# 让 Claude 从这些标题里挑出最重要的 10 条
selection_prompt = f"""下面是一份新闻标题列表，每条前面是编号。

{numbered_list}

请你按以下规则挑选出 10 条最重要的新闻：
1. 先仔细检查列表里是否有多条报道的是同一件事——即使标题文字不完全一样，只要说的是同一个事件，也算重复。这种情况下只能选其中一条（优先选信息更完整、来源更权威的），绝对不能让同一件事出现两次。
2. 去重之后，从剩下的候选里挑出最重要的 10 条。

只返回一个 JSON 数组，包含选中条目的编号，不要输出任何其他文字。例如：[1, 3, 5, 7, 9, 11, 13, 15, 17, 19]"""

selection_response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=300,
    messages=[{"role": "user", "content": selection_prompt}],
)

selection_text = selection_response.content[0].text.strip()

# 有时 AI 会把 JSON 包在 ```json ... ``` 这样的代码框里，这里把代码框标记去掉
if selection_text.startswith("```"):
    selection_text = selection_text.strip("`")
    selection_text = selection_text.removeprefix("json").strip()

selected_indices = json.loads(selection_text)

selected_articles = [articles[i - 1] for i in selected_indices]

print(f"\nClaude 挑出的 {len(selected_articles)} 条:\n")
for art in selected_articles:
    print(f"- [{art['source']}] {art['title']}")
