import feedparser

# 三个新闻源：(显示名字, RSS 地址)
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
for i, art in enumerate(articles, start=1):
    print(f"{i}. [{art['source']}] {art['title']}")
