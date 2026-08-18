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
    ("中新网财经", "http://www.chinanews.com/rss/finance.xml"),
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
for i, art in enumerate(articles, start=1):
    print(f"{i}. [{art['source']}] {art['title']}")


def pick_top_articles(candidates, count, check_duplicates=False):
    """让 Claude 从 candidates 这份候选列表里，挑出最重要的 count 条，返回挑中的那些新闻。"""
    listing = ""
    for i, art in enumerate(candidates, start=1):
        listing += f"{i}. [{art['source']}] {art['title']}\n"

    instructions = f"请从中挑选出最重要的 {count} 条。"
    if check_duplicates:
        instructions = (
            "请先检查列表里是否有多条报道的是同一件事——即使标题文字不完全一样，"
            "只要说的是同一个事件，也算重复。这种情况下只能选其中一条"
            "（优先选信息更完整、来源更权威的），绝对不能让同一件事出现两次。\n"
            f"去重之后，从剩下的候选里挑选出最重要的 {count} 条。"
        )

    prompt = f"""下面是一份新闻标题列表，每条前面是编号。

{listing}
{instructions}

只返回一个 JSON 数组，包含选中条目的编号，不要输出任何其他文字。"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # 有时 AI 会把 JSON 包在 ```json ... ``` 这样的代码框里，这里把代码框标记去掉
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()

    indices = json.loads(text)
    return [candidates[i - 1] for i in indices]


# 把中新网财经单独拎出来,保证它一定能选到 3 条,不会被其他源的新闻挤掉
china_articles = [a for a in articles if a["source"] == "中新网财经"]
other_articles = [a for a in articles if a["source"] != "中新网财经"]

china_selected = pick_top_articles(china_articles, count=3)
other_selected = pick_top_articles(other_articles, count=7, check_duplicates=True)

selected_articles = china_selected + other_selected

print(f"\nClaude 挑出的 {len(selected_articles)} 条:\n")
for art in selected_articles:
    print(f"- [{art['source']}] {art['title']}")
