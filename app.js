// 每日问候语：按日期算出固定的一句，同一天刷新不会变，隔天自然换掉。
// 想改的话直接编辑这个列表——加一行就是多一句备选，删一行就是去掉一句。
const GREETINGS = [
  "吃了吗？",
  "今天天气怎么样，记得多出去走走。",
  "喝水了没有？",
  "眼睛累了的话，往窗外看看。",
  "今天也要好好吃饭呀。",
  "别忘了伸个懒腰。",
  "世界很大，先看看今天发生了什么。",
  "慢慢看，不着急。",
  "十条新闻，读完正好歇一会儿。",
  "今天也是普通但重要的一天。",
  "早饭好好吃了吗？",
  "走两步，看看云。",
  "手机放一会儿，也看看外面。",
  "今天，也要照顾好自己。",
  "十条，刚刚好，别读太多。",
];

function pickGreeting(dateStr) {
  let sum = 0;
  for (let i = 0; i < dateStr.length; i++) sum += dateStr.charCodeAt(i);
  return GREETINGS[sum % GREETINGS.length];
}

function formatDateCN(dateStr) {
  const [y, m, d] = dateStr.split("-");
  return `${y}年${Number(m)}月${Number(d)}日`;
}

// 中新网的两个源算"中国"，其余都算"国际"
function regionLabel(source) {
  return source.includes("中新网") ? "中国" : "国际";
}

function renderItem(article) {
  const details = document.createElement("details");
  details.className = "item";

  const summary = document.createElement("summary");

  const label = regionLabel(article.source);
  const tag = document.createElement("span");
  tag.className = "tag" + (label === "中国" ? " china" : "");
  tag.textContent = label;

  const headline = document.createElement("span");
  headline.className = "headline";
  headline.textContent = article.title;

  const chev = document.createElement("span");
  chev.className = "chev";

  summary.append(tag, headline, chev);

  const detail = document.createElement("div");
  detail.className = "detail";
  const inner = document.createElement("div");
  inner.className = "detail-inner";

  // summary 字段已经在生成的时候把来源拼进去了（"摘要...【来源】"），这里直接用，不用再拼一次
  const summaryText = document.createElement("p");
  summaryText.className = "summary-text";
  summaryText.textContent = article.summary;

  const metaRow = document.createElement("div");
  metaRow.className = "meta-row";
  const link = document.createElement("a");
  link.className = "read-link";
  link.href = article.link;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "阅读原文 ↗";
  metaRow.append(link);

  inner.append(summaryText, metaRow);
  detail.append(inner);
  details.append(summary, detail);
  return details;
}

async function loadIndexPage() {
  const list = document.getElementById("list");
  const dateEl = document.getElementById("issue-date");
  const greetingEl = document.getElementById("greeting");
  const backLink = document.getElementById("back-to-latest");

  const params = new URLSearchParams(location.search);
  const dateParam = params.get("date");
  const dataUrl = dateParam ? `archive/${dateParam}.json` : "news.json";

  try {
    const res = await fetch(dataUrl);
    if (!res.ok) throw new Error(`读取 ${dataUrl} 失败：${res.status}`);
    const data = await res.json();

    const issueDate = dateParam || data.generated_at.slice(0, 10);
    dateEl.textContent = formatDateCN(issueDate);
    greetingEl.textContent = pickGreeting(issueDate);

    if (dateParam) {
      backLink.hidden = false;
    }

    data.articles.forEach((article) => {
      list.appendChild(renderItem(article));
    });
  } catch (err) {
    console.error(err);
    dateEl.textContent = "读取失败";
    list.innerHTML = "";
    const p = document.createElement("p");
    p.className = "error-note";
    p.textContent = dateParam
      ? "没找到这一天的存档，可能日期不对，或者这天还没有新闻。"
      : "没读到 news.json，先确认这个文件在不在网站根目录下。";
    list.appendChild(p);
  }
}

async function loadArchivePage() {
  const container = document.getElementById("archive-groups");

  try {
    const res = await fetch("archive/index.json");
    if (!res.ok) throw new Error(`读取 archive/index.json 失败：${res.status}`);
    const data = await res.json();

    if (data.dates.length === 0) {
      container.innerHTML = '<p class="error-note">还没有存档，明天再来看看。</p>';
      return;
    }

    const groups = new Map();
    data.dates.forEach((entry) => {
      const monthKey = entry.date.slice(0, 7); // "2026-08"
      if (!groups.has(monthKey)) groups.set(monthKey, []);
      groups.get(monthKey).push(entry);
    });

    groups.forEach((entries, monthKey) => {
      const [y, m] = monthKey.split("-");

      const group = document.createElement("div");
      group.className = "archive-group";

      const monthLabel = document.createElement("p");
      monthLabel.className = "archive-month";
      monthLabel.textContent = `${y} 年 ${Number(m)} 月`;

      const rows = document.createElement("div");
      rows.className = "archive-rows";

      entries.forEach(({ date, count }) => {
        const a = document.createElement("a");
        a.className = "archive-row";
        a.href = `index.html?date=${date}`;

        const day = Number(date.slice(8, 10));
        const dateSpan = document.createElement("span");
        dateSpan.className = "archive-date";
        dateSpan.textContent = `${day} 日`;

        const countSpan = document.createElement("span");
        countSpan.className = "archive-count";
        countSpan.textContent = `${count} 条`;

        a.append(dateSpan, countSpan);
        rows.appendChild(a);
      });

      group.append(monthLabel, rows);
      container.appendChild(group);
    });
  } catch (err) {
    console.error(err);
    container.innerHTML = '<p class="error-note">存档清单读取失败，先确认 archive/index.json 在不在。</p>';
  }
}

// 靠页面里有没有对应的元素，判断现在是首页还是往期归档页
if (document.getElementById("list")) {
  loadIndexPage();
}
if (document.getElementById("archive-groups")) {
  loadArchivePage();
}
