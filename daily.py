#!/usr/bin/env python3
"""Free RSS headline digest; no paid AI or API keys required."""
import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

GROUPS = [
 ("道具", '(cosplay 道具 OR cosplay props)'),
 ("3D打印", '(3D打印 OR "3D printing")'),
 ("跨境电商", '跨境电商'),
 ("电声/专业音频", '(专业音频 OR 调音台 OR "pro audio")'),
 ("SHEIN", '(SHEIN OR 希音)'),
 ("TikTok", '(TikTok Shop OR TikTok 电商)'),
 ("亚马逊", '(亚马逊 卖家 OR Amazon seller)'),
 ("天猫", '天猫 电商'),
 ("京东", '京东 电商'),
 ("拼多多", '拼多多'),
 ("Temu", 'Temu'),
 ("麦克风", '(无线麦克风 OR wireless microphone)'),
 ("发散：AI", '人工智能 AI 电商'),
 ("发散：物流", '跨境物流 运费'),
 ("发散：供应链", '电子元器件 供应链 成本'),
]
STATE = Path(".state/seen.json")

def fetch(label, query):
    params = urllib.parse.urlencode({"q": query + " when:7d",
        "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
    req = urllib.request.Request("https://news.google.com/rss/search?" + params,
        headers={"User-Agent": "IndustryDaily/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        root = ET.fromstring(response.read())
    result = []
    now = dt.datetime.now(dt.timezone.utc)
    for item in root.findall("./channel/item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        source = item.findtext("source", "").strip()
        try:
            published = email.utils.parsedate_to_datetime(item.findtext("pubDate", ""))
            if published.tzinfo is None:
                published = published.replace(tzinfo=dt.timezone.utc)
        except (ValueError, TypeError):
            continue
        if not title or not link.startswith("https://") or not (dt.timedelta(0) <= now-published <= dt.timedelta(days=7)):
            continue
        # Similar headline copies from different publishers share a key.
        canonical = re.sub(r"\s+", "", title.rsplit(" - ", 1)[0]).lower()
        key = hashlib.sha256(canonical.encode()).hexdigest()
        result.append({"title": title, "url": link, "source": source,
            "date": published.isoformat(), "key": key})
    return sorted(result, key=lambda x: x["date"], reverse=True)

def select(items, seen, now, limit):
    selected = []
    for item in items:
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        selected.append(item)
        if len(selected) == limit:
            break
    return selected

def pack(sections, limit=12000):
    chunks, current = [], ""
    for section in sections:
        if current and len((current + section).encode("utf-8")) > limit:
            chunks.append(current)
            current = ""
        current += section
    if current:
        chunks.append(current)
    return chunks

def send(token, title, content):
    payload = json.dumps({"token": token, "title": title,
        "content": content, "template": "html", "channel": "wechat"}).encode()
    req = urllib.request.Request("https://www.pushplus.plus/send", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=45) as response:
        result = json.load(response)
    if result.get("code") != 200:
        # Do not print provider responses that might contain credentials.
        raise RuntimeError("PushPlus rejected request, code=" + str(result.get("code")))
    print("PushPlus accepted message; final delivery is asynchronous.")

def main():
    token = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if not token and not dry_run:
        raise RuntimeError("Add the PUSHPLUS_TOKEN repository secret first.")
    now = dt.datetime.now(dt.timezone.utc)
    local = now.astimezone(dt.timezone(dt.timedelta(hours=8)))
    old = json.loads(STATE.read_text()) if STATE.exists() else {}
    cutoff = (now - dt.timedelta(days=14)).isoformat()
    old = {k: v for k, v in old.items() if v >= cutoff}
    seen = set(old)
    sections = ["<h2>行业新闻日报 " + local.strftime("%Y-%m-%d") + "</h2>"
        "<p>免费新闻线索版：标题来自Google新闻RSS，尚未逐篇核实；"
        "优先近24小时，不足补近7日未推送内容。日期为RSS所载报道时间。"
        "本版不生成AI摘要或事实判断。</p><h3>发生了什么</h3>"]
    successful, picked = 0, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {label: pool.submit(fetch, label, query) for label, query in GROUPS}
        for label, _ in GROUPS:
            section = "<h4>" + html.escape(label) + "</h4>"
            try:
                items = futures[label].result()
                successful += 1
                chosen = select(items, seen, now, 1 if label.startswith("发散") else 2)
            except Exception:
                sections.append(section + "<p>本次抓取失败，未判断是否有新闻。</p>")
                continue
            if not chosen:
                sections.append(section + "<p>近7日暂无未推送的匹配新闻。</p>")
                continue
            section += "<ul>"
            for item in chosen:
                published = dt.datetime.fromisoformat(item["date"])
                tag = "近24小时" if now-published <= dt.timedelta(days=1) else "近7日补充"
                section += '<li><a href="' + html.escape(item["url"], quote=True) + '">' + html.escape(item["title"]) + "</a><br>" + html.escape(published.astimezone(local.tzinfo).strftime("%m-%d %H:%M") + "｜" + tag + "｜" + item["source"]) + "</li>"
                picked.append(item)
            sections.append(section + "</ul>")
    if successful == 0:
        raise RuntimeError("All RSS requests failed; no report sent.")
    sections.append("<h3>为什么对我的工作很重要</h3><p>人工核查方向：平台政策看适用站点及生效日；新品看价格、功能和认证；道具看版权、材料和安全；物流看目的国和计费重量。以上为固定阅读提示，不是对本期新闻的分析。</p><h3>需要持续关注什么</h3><p>点击新闻链接核对原文及官方公告。免费定时任务可能晚于北京时间09:00送达。公开仓库长期无活动时，GitHub可能暂停定时任务。</p>")
    chunks = pack(sections)
    Path("daily-report.html").write_text("\n".join(chunks), encoding="utf-8")
    if dry_run:
        print("Dry run:", successful, "feeds,", len(picked), "headlines,", len(chunks), "messages")
        return
    for index, chunk in enumerate(chunks, 1):
        suffix = f"（{index}/{len(chunks)}）" if len(chunks) > 1 else ""
        send(token, "行业日报 " + local.strftime("%m-%d") + suffix, chunk)
    for item in picked:
        old[item["key"]] = now.isoformat()
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(old), encoding="utf-8")

if __name__ == "__main__":
    main()
