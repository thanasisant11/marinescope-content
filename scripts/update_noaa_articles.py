#!/usr/bin/env python3
import json
import re
import time
import html
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import os

OUTPUT_PATH = "data/articles.json"

FEEDS = [
    ("NOAA PMEL – What’s New", "https://www.pmel.noaa.gov/feed/rss-feed-pmel-whats-new.xml"),
    ("NOAA PMEL – In the News", "https://www.pmel.noaa.gov/feed/rss-feed-pmel-in-the-news.xml"),
    ("NOAA PMEL – Featured Publications", "https://www.pmel.noaa.gov/feed/rss-feed-pmel-featured-publications.xml"),
    ("NOAA NOS – Making Waves", "https://oceanservice.noaa.gov/rss/makingwaves.xml"),
    ("NOAA Climate.gov – Highlights", "https://dev-01-alb-www-climate.woc.noaa.gov/feeds/news-features/highlights.rss"),
    ("NOAA Climate.gov – Beyond the Data", "https://dev-01-alb-www-climate.woc.noaa.gov/feeds/news-features/beyond-the-data.rss"),
    ("NOAA Climate.gov – ENSO Blog", "https://dev-01-alb-www-climate.woc.noaa.gov/feeds/news-features/enso.rss"),
]

ALLOWED_HOST_SUBSTRINGS = [
    "noaa.gov",
    "weather.gov",
    "oceanservice.noaa.gov",
    "pmel.noaa.gov",
    "fisheries.noaa.gov",
    "climate.gov",
]

MAX_ITEMS_TOTAL = 80
MAX_ITEMS_PER_FEED = 25

USER_AGENT = "MarineScopeAI/1.0 (+https://github.com/thanasisant1/marinescope-content)"
TAG_RE = re.compile(r"<[^>]+>")

def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def safe_get_text(elem, path_list):
    for p in path_list:
        found = elem.find(p)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""

def parse_date(s: str) -> str:
    if not s:
        return ""
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%Z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return dt.astimezone(timezone.utc).date().isoformat()
        except Exception:
            continue
    return s.strip()

def is_allowed_url(url: str) -> bool:
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
        return any(sub in host for sub in ALLOWED_HOST_SUBSTRINGS)
    except Exception:
        return False

def fetch_xml(url: str) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    with urlopen(req, timeout=25) as resp:
        return resp.read()

def parse_feed(feed_name: str, feed_url: str):
    raw = fetch_xml(feed_url)
    root = ET.fromstring(raw)

    items = []

    channel = root.find("channel")
    if channel is not None:
        for it in channel.findall("item")[:MAX_ITEMS_PER_FEED]:
            title = safe_get_text(it, ["title"])
            link = safe_get_text(it, ["link"])
            pub = safe_get_text(it, ["pubDate", "date"])
            desc = safe_get_text(it, ["description", "summary"])

            if not is_allowed_url(link):
                continue

            items.append({
                "title": strip_html(title),
                "url": link.strip(),
                "source": feed_name,
                "published_at": parse_date(pub),
                "summary": strip_html(desc)[:600],
            })
        return items

    # Atom fallback
    entries = [e for e in root.iter() if str(e.tag).lower().endswith("entry")]
    for e in entries[:MAX_ITEMS_PER_FEED]:
        title = ""
        link = ""
        updated = ""
        summary = ""

        for child in list(e):
            t = str(child.tag).lower()
            if t.endswith("title") and (child.text or "").strip():
                title = child.text.strip()
            elif t.endswith("updated") and (child.text or "").strip():
                updated = child.text.strip()
            elif t.endswith("published") and not updated and (child.text or "").strip():
                updated = child.text.strip()
            elif t.endswith("summary") and (child.text or "").strip():
                summary = child.text.strip()
            elif t.endswith("content") and not summary and (child.text or "").strip():
                summary = child.text.strip()
            elif t.endswith("link"):
                href = child.attrib.get("href", "").strip()
                rel = child.attrib.get("rel", "").strip().lower()
                if href and (not link) and (rel in ("", "alternate")):
                    link = href

        if not is_allowed_url(link):
            continue

        items.append({
            "title": strip_html(title) or "Untitled",
            "url": link,
            "source": feed_name,
            "published_at": parse_date(updated),
            "summary": strip_html(summary)[:600],
        })

    return items

def main():
    all_items = []
    seen_urls = set()

    for name, url in FEEDS:
        try:
            for it in parse_feed(name, url):
                u = it.get("url", "")
                if not u or u in seen_urls:
                    continue
                seen_urls.add(u)
                all_items.append(it)
        except Exception as ex:
            print(f"[WARN] Feed failed: {name} -> {ex}")

        time.sleep(0.3)

    all_items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    all_items = all_items[:MAX_ITEMS_TOTAL]

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": all_items,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[OK] Wrote {len(all_items)} items to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
