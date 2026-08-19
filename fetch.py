import json
import os
import random
import re
import socket
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from anthropic import Anthropic

# feedparser 内部没有单独的超时设置，靠这一行给所有网络请求定一个上限（秒），
# 避免某个网站卡住不响应时，程序一直傻等
socket.setdefaulttimeout(15)

# 从 .env 文件里读取 ANTHROPIC_API_KEY
load_dotenv()
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# 新闻源：(显示名字, RSS 地址)
# 中新网财经 + 中新网国内 两个算"中国候选池"：前者管宏观经济政策，后者管重大时政外事
CHINA_SOURCE_NAMES = ("中新网财经", "中新网国内")
SOURCES = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("联合国新闻", "https://news.un.org/feed/subscribe/zh/news/all/rss.xml"),
    ("The Guardian World", "https://www.theguardian.com/world/rss"),
    ("中新网财经", "http://www.chinanews.com/rss/finance.xml"),
    ("中新网国内", "https://www.chinanews.com.cn/rss/china.xml"),
]

def get_published_time(entry):
    """把 RSS 里的发布时间统一转换成标准格式；如果解析不了，就用原始文字。"""
    if entry.get("published_parsed"):
        return datetime(*entry.published_parsed[:6]).isoformat()
    return entry.get("published", "")


# 挨个抓取每个源，合并进一个大列表。中国候选池两个源多取一些（15条），
# 因为宏观政策/重大时政新闻不是每条都有，候选池大一点，才更容易抓到合适的内容
# 单个源抓取失败（网络超时等）不影响其他源，打印提示后跳过继续
articles = []
for source_name, url in SOURCES:
    try:
        feed = feedparser.parse(url)
        count = 15 if source_name in CHINA_SOURCE_NAMES else 5
        for entry in feed.entries[:count]:
            # RSS 自带的简介，先清掉里面可能混着的 HTML 标签，留着当"抓正文失败"时的备用素材
            rss_summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text().strip()
            articles.append({
                "source": source_name,
                "title": entry.title,
                "link": entry.link,
                "published": get_published_time(entry),
                "rss_summary": rss_summary,
            })
    except Exception as e:
        print(f"抓取信源失败，跳过: [{source_name}] ({e})")

print(f"一共抓到 {len(articles)} 条新闻:\n")


def title_similarity(title_a, title_b):
    """算两个标题有多像，返回 0~1 之间的数字，1 表示完全一样。不调用 AI，纯算法比对文字。"""
    return SequenceMatcher(None, title_a, title_b).ratio()


SIMILARITY_THRESHOLD = 0.6


def dedupe_similar_titles(candidates):
    """同一个来源里，如果标题高度相似（很可能是同一件事被反复更新报道，
    比如"XX举行会谈"和"XX会谈"），只保留先抓到的那条。"""
    kept = []
    for art in candidates:
        is_dup = any(
            art["source"] == other["source"] and title_similarity(art["title"], other["title"]) > SIMILARITY_THRESHOLD
            for other in kept
        )
        if not is_dup:
            kept.append(art)
    return kept


def load_recent_archive_titles(days=3):
    """读取最近几天的存档，收集已经发布过的标题，用来避免连着好几天报道同一件事。"""
    titles = []
    today = datetime.now().date()
    for i in range(1, days + 1):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        path = f"archive/{date_str}.json"
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            titles.extend(a["title"] for a in data["articles"])
    return titles


def is_already_covered(title, recent_titles):
    return any(title_similarity(title, prev_title) > SIMILARITY_THRESHOLD for prev_title in recent_titles)


recent_titles = load_recent_archive_titles(days=3)
before_count = len(articles)
articles = [a for a in articles if not is_already_covered(a["title"], recent_titles)]
if before_count != len(articles):
    print(f"（排除了 {before_count - len(articles)} 条最近几天报道过的重复新闻）")

articles = dedupe_similar_titles(articles)

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


def pick_top_articles(candidates, count=None, count_range=None, check_duplicates=False, priority_hint=None):
    """让 Claude 从 candidates 这份候选列表里挑新闻，返回挑中的那些。
    count：挑固定数量；count_range：挑一个区间内的数量，比如 (2, 5)。两个参数二选一。"""
    listing = ""
    for i, art in enumerate(candidates, start=1):
        listing += f"{i}. [{art['source']}] {art['title']}\n"

    if count_range:
        min_count, max_count = count_range
        count_instruction = (
            f"挑选出最重要的新闻，数量控制在 {min_count} 到 {max_count} 条之间——"
            "根据实际重要性判断，不要为了凑数选进不够重要的新闻，但也不能少于下限"
        )
    else:
        count_instruction = f"挑选出最重要的 {count} 条"

    if check_duplicates:
        instructions = (
            "请先检查列表里是否有多条报道的是同一件事——即使标题文字不完全一样，"
            "只要说的是同一个事件，也算重复。这种情况下只能选其中一条"
            "（优先选信息更完整、来源更权威的），绝对不能让同一件事出现两次。\n"
            f"去重之后，请{count_instruction}。"
        )
    else:
        instructions = f"请{count_instruction}。"

    if priority_hint:
        instructions += f"\n{priority_hint}"

    prompt = f"""下面是一份新闻标题列表，每条前面是编号。

{listing}
{instructions}

只返回一个 JSON 数组，包含选中条目的编号，不要输出任何其他文字。"""

    indices = ask_claude_for_json(prompt, max_tokens=300)
    selected = [candidates[i - 1] for i in indices]

    if count_range:
        selected = selected[:count_range[1]]  # 防止 Claude 没听话选太多，做个保险

    return selected


# 把中国候选池（财经+国内两个源）单独拎出来，挑 2~5 条最重要的（不强求固定数量），
# 剩下的名额再让其他源去挑
china_articles = [a for a in articles if a["source"] in CHINA_SOURCE_NAMES]
other_articles = [a for a in articles if a["source"] not in CHINA_SOURCE_NAMES]

china_selected = pick_top_articles(
    china_articles,
    count_range=(2, 5),
    check_duplicates=True,
    priority_hint=(
        "优先选择以下两类新闻，两类同等重要，不要偏废其中一类：\n"
        "1) 货币政策、央行动向、人民币汇率、财政政策等宏观经济政策新闻；\n"
        "2) 国家领导人重大外事活动、国事访问、重要政治新闻（比如高层会晤、国家追悼活动等）。\n"
        "如果这两类新闻数量不够，再用其他重要新闻补足到下限。"
    ),
)
remaining_count = 10 - len(china_selected)
other_selected = pick_top_articles(other_articles, count=remaining_count, check_duplicates=True)

combined_selected = china_selected + other_selected


def remove_cross_duplicates(articles):
    """china_selected 和 other_selected 是分开选的，各自去重不知道对方选了什么。
    这里把两边合并后的最终名单再整体检查一遍，防止同一件事跨来源重复出现。"""
    listing = ""
    for i, art in enumerate(articles, start=1):
        listing += f"{i}. [{art['source']}] {art['title']}\n"

    prompt = f"""下面是一份新闻标题列表，每条前面是编号。

{listing}
请检查列表里是否有多条报道的是同一件事——即使来源不同、标题文字不完全一样，
只要说的是同一个事件，也算重复。这种情况下只保留其中一条（优先选信息更完整、来源更权威的）。

请返回一个 JSON 数组，包含去重后应该保留的条目编号，按原来的顺序排列，不要输出任何其他文字。"""

    indices = ask_claude_for_json(prompt, max_tokens=300)
    return [articles[i - 1] for i in indices]


selected_articles = remove_cross_duplicates(combined_selected)

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


# 给选中的这 10 条，逐条抓取正文。单条抓取失败不影响其他条，
# 抓不到（或抓到空的）就退回用 RSS 自带的简介凑合用；每条之间歇 1~2 秒，别太快地反复访问同一网站
request_headers = {"User-Agent": "Mozilla/5.0"}
for art in selected_articles:
    try:
        page = requests.get(art["link"], headers=request_headers, timeout=10)
        page.encoding = page.apparent_encoding  # 自动识别网页编码，避免中文乱码
        soup = BeautifulSoup(page.text, "html.parser")
        text = extract_article_text(soup)
        art["text"] = text if text else art["rss_summary"]
    except Exception as e:
        print(f"  抓正文失败，改用 RSS 简介代替: [{art['source']}] {art['title']} ({e})")
        art["text"] = art["rss_summary"]

    time.sleep(random.uniform(1, 2))

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
- 摘要内容必须基于正文，不要编造，这一条最重要：宁可写得模糊，也不能编造正文里没有的具体信息（日期、数字、人名都算）
- 如果正文明确给出了具体日期，摘要里要写出完整的时间（比如"2026年8月17日"），不能用
  "近日、日前、最近、上周、本月"这类相对时间词，读者不知道你写摘要那天是哪天；
  但如果正文没有给出具体日期（比如只说"即将到期""不久前"这种模糊说法），
  就如实按正文的模糊程度来写，绝对不能为了凑一个"完整日期"而编造一个正文没提过的具体日期

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


# 程序化兜底：提示词里提了要求，但 AI 不一定每次都听话，
# 生成完之后用代码扫一遍常见问题，扫到就单独把这一条打回去重新生成
BANNED_TIME_WORDS = ["近日", "日前", "最近", "上周", "本月"]
NON_CHINESE_SCRIPT_PATTERN = re.compile(r"[가-힣぀-ヿ]")  # 韩文、日文假名的字符范围


def find_summary_issues(text):
    """检查摘要文字有没有已知问题，返回问题描述列表（没问题就是空列表）。"""
    issues = []
    banned = [w for w in BANNED_TIME_WORDS if w in text]
    if banned:
        issues.append(f'出现了相对时间词"{"、".join(banned)}"，必须改成完整的年份+月份/日期')
    if NON_CHINESE_SCRIPT_PATTERN.search(text):
        issues.append("人名或专有名词里疑似混入了韩文/日文字符，必须改成正确的中文")
    return issues


def regenerate_summary(art, issues):
    """针对单条新闻重新生成标题+摘要，明确指出这次要修正哪些问题。"""
    issues_text = "\n".join(f"  - {issue}" for issue in issues)
    prompt = f"""标题: {art['title']}
正文:
{art['text']}

请重新为这条新闻写一个中文标题和一段中文摘要，要求：
- 标题：如果原标题本来就是中文，直接沿用；如果是英文，翻译成简洁准确的中文标题
- 摘要：用中文写，控制在两三句话以内，写成一段话，中间不要换行，内容必须基于正文，不要编造
- 涉及时间：正文明确给了具体日期才写完整日期；正文没给具体日期的话，就按正文的模糊程度如实写，
  绝对不能为了凑一个"完整日期"而编造正文没提过的具体日期
- 你刚才写的版本有以下问题，这次必须修正：
{issues_text}

请严格按下面的格式输出，不要输出任何其他文字：
中文标题|||摘要文字"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    title_part, summary_part = text.split("|||", 1)
    return title_part.strip(), summary_part.strip()


for art in selected_articles:
    issues = find_summary_issues(art["title_zh"] + art["summary"])
    attempts = 0
    while issues and attempts < 2:
        print(f"  摘要有问题 {issues}，重新生成: [{art['source']}] {art['title']}")
        art["title_zh"], art["summary"] = regenerate_summary(art, issues)
        issues = find_summary_issues(art["title_zh"] + art["summary"])
        attempts += 1
    if issues:
        print(f"  警告：重试 2 次后仍有问题 {issues}，先保留这版: [{art['source']}] {art['title']}")

# 把来源拼进摘要末尾，方便网页直接显示，不用额外拼接
for art in selected_articles:
    art["summary"] = f"{art['summary']}【{art['source']}】"

print("\n最终摘要:\n")
for art in selected_articles:
    print(art["title_zh"])
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
            "published": art["published"],
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
