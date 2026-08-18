import json
import os
from datetime import datetime
import feedparser
import requests
from bs4 import BeautifulSoup
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

# 挨个抓取每个源，合并进一个大列表。中新网财经多取一些（15条），
# 因为宏观政策类新闻不是每条都有，候选池大一点，才更容易抓到货币政策/汇率这类内容
articles = []
for source_name, url in SOURCES:
    feed = feedparser.parse(url)
    count = 15 if source_name == "中新网财经" else 5
    for entry in feed.entries[:count]:
        articles.append({
            "source": source_name,
            "title": entry.title,
            "link": entry.link,
        })

print(f"一共抓到 {len(articles)} 条新闻:\n")
for i, art in enumerate(articles, start=1):
    print(f"{i}. [{art['source']}] {art['title']}")


def ask_claude_for_json(prompt, max_tokens):
    """把 prompt 发给 Claude，把它回复的文字解析成 JSON 数据后返回。"""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # 有时 AI 会把 JSON 包在 ```json ... ``` 这样的代码框里，这里把代码框标记去掉
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()

    return json.loads(text)


def pick_top_articles(candidates, count, check_duplicates=False, priority_hint=None):
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
    if priority_hint:
        instructions += f"\n{priority_hint}"

    prompt = f"""下面是一份新闻标题列表，每条前面是编号。

{listing}
{instructions}

只返回一个 JSON 数组，包含选中条目的编号，不要输出任何其他文字。"""

    indices = ask_claude_for_json(prompt, max_tokens=300)
    return [candidates[i - 1] for i in indices]


# 把中新网财经单独拎出来,保证它一定能选到 3 条,不会被其他源的新闻挤掉
china_articles = [a for a in articles if a["source"] == "中新网财经"]
other_articles = [a for a in articles if a["source"] != "中新网财经"]

china_selected = pick_top_articles(
    china_articles,
    count=3,
    priority_hint=(
        "优先选择跟货币政策、央行动向、人民币汇率、财政政策等宏观经济政策相关的新闻；"
        "如果这类新闻不够 3 条，再用其他重要的财经新闻补足。"
    ),
)
other_selected = pick_top_articles(other_articles, count=7, check_duplicates=True)

selected_articles = china_selected + other_selected

print(f"\nClaude 挑出的 {len(selected_articles)} 条:\n")
for art in selected_articles:
    print(f"- [{art['source']}] {art['title']}")

def extract_article_text(soup):
    """从网页里挑出正文段落。优先找 <article> 标签；如果里面没有正文
    （有些网站的 <article> 是空壳，正文在别的容器里），就退而求其次，
    在整个网页里找"直接包含最多 <p> 段落"的那个容器，通常那就是正文区域。"""
    article_tag = soup.find("article")
    paragraphs = article_tag.find_all("p") if article_tag else []

    if not paragraphs:
        best_container = None
        best_count = 0
        for container in soup.find_all(["div", "section"]):
            count = len(container.find_all("p", recursive=False))
            if count > best_count:
                best_container = container
                best_count = count
        paragraphs = best_container.find_all("p") if best_container else soup.find_all("p")

    return "\n".join(p.get_text().strip() for p in paragraphs if p.get_text().strip())


# 给选中的这 10 条，逐条抓取正文
request_headers = {"User-Agent": "Mozilla/5.0"}
for art in selected_articles:
    page = requests.get(art["link"], headers=request_headers, timeout=10)
    page.encoding = page.apparent_encoding  # 自动识别网页编码，避免中文乱码
    soup = BeautifulSoup(page.text, "html.parser")
    art["text"] = extract_article_text(soup)

print("\n抓正文结果预览:\n")
for art in selected_articles:
    print(f"[{art['source']}] {art['title']}")
    print(f"  正文长度: {len(art['text'])} 字")
    print(f"  开头: {art['text'][:60]}...")
    print()

# 把这 10 条的标题+正文一次性发给 Claude，生成中文摘要（一次调用生成全部，比调用 10 次更快更省）
articles_listing = ""
for i, art in enumerate(selected_articles, start=1):
    articles_listing += f"{i}. 标题: {art['title']}\n正文:\n{art['text']}\n\n"

summary_prompt = f"""下面是 10 条新闻，每条包含编号、标题和正文。

{articles_listing}
请为每一条新闻提供一个中文标题和一段中文摘要，要求：
- 标题：如果原标题本来就是中文，直接沿用（可以稍微精简）；如果是英文，翻译成简洁准确的中文标题
- 摘要：不管原文是什么语言，都必须用中文写，控制在两三句话以内，写成一段话，中间不要换行
- 摘要内容必须基于正文，不要编造

请严格按下面的格式输出，每条新闻占一行，编号、中文标题、摘要之间用三个竖线 ||| 分隔，
不要输出任何其他文字，不要用 markdown：
1|||中文标题|||摘要文字
2|||中文标题|||摘要文字
...依此类推，共 10 行"""

summary_response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1500,
    messages=[{"role": "user", "content": summary_prompt}],
)
summary_text = summary_response.content[0].text.strip()

summary_by_index = {}
for line in summary_text.split("\n"):
    line = line.strip()
    if "|||" not in line:
        continue
    number_part, title_part, summary_part = line.split("|||", 2)
    summary_by_index[int(number_part.strip())] = {
        "title": title_part.strip(),
        "summary": summary_part.strip(),
    }

for i, art in enumerate(selected_articles, start=1):
    art["title_zh"] = summary_by_index[i]["title"]
    art["summary"] = summary_by_index[i]["summary"]

print("\n最终摘要:\n")
for art in selected_articles:
    print(f"[{art['source']}] {art['title_zh']}")
    print(art["summary"])
    print()

# 整理成 JSON，存进 news.json
output = {
    "generated_at": datetime.now().isoformat(),
    "articles": [
        {
            "source": art["source"],
            "title": art["title_zh"],
            "link": art["link"],
            "summary": art["summary"],
        }
        for art in selected_articles
    ],
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# 另外按日期存一份存档，比如 archive/2026-08-17.json
os.makedirs("archive", exist_ok=True)
today = datetime.now().strftime("%Y-%m-%d")
archive_path = f"archive/{today}.json"
with open(archive_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"已保存到 news.json 和 {archive_path}")
