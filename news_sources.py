import datetime as dt
from typing import List, Dict, Optional
import feedparser
import trafilatura
import requests
from bs4 import BeautifulSoup


RSS_FEEDS = {
    "Reuters - Business": "https://feeds.reuters.com/reuters/businessNews",
    "Reuters - Markets":  "https://feeds.reuters.com/reuters/marketsNews",
    "AP News - Business": "https://apnews.com/hub/ap-top-news?utm_source=rss&utm_medium=referral",
    "SEC EDGAR - Latest Filings": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom",
    "AlphaStreet - Earnings Transcripts": "https://alphastreet.com/insights/category/transcripts/feed/",
    "Motley Fool - Earnings": "https://www.fool.com/feeds/index.aspx",
}

SOURCE_CREDIBILITY = {
    "Reuters": 1.00,
    "AP News": 0.95,
    "SEC EDGAR": 1.00,
    "AlphaStreet": 0.90,
    "Motley Fool": 0.85,
    # Default for unknown sources
    "_default": 0.70,
}


def _guess_source_weight(source_title: str) -> float:
    st = source_title.lower()
    if "reuters" in st:
        return SOURCE_CREDIBILITY["Reuters"]
    if "ap news" in st or "associated press" in st:
        return SOURCE_CREDIBILITY["AP News"]
    if "sec edgar" in st or "edgar" in st:
        return SOURCE_CREDIBILITY["SEC EDGAR"]
    if "alphastreet" in st:
        return SOURCE_CREDIBILITY["AlphaStreet"]
    if "motley" in st:
        return SOURCE_CREDIBILITY["Motley Fool"]
    return SOURCE_CREDIBILITY["_default"]


def _parse_published(entry) -> Optional[dt.datetime]:
    # Try multiple places for datetime
    for key in ("published_parsed", "updated_parsed"):
        if getattr(entry, key, None):
            return dt.datetime(*getattr(entry, key)[:6], tzinfo=dt.timezone.utc)
    return None


def _clean_text(html_or_text: str) -> str:
    # Strip HTML to text
    if not html_or_text:
        return ""
    soup = BeautifulSoup(html_or_text, "html.parser")
    return " ".join(soup.get_text(" ").split())


def fetch_rss_items() -> List[Dict]:
    items = []
    for src_name, url in RSS_FEEDS.items():
        feed = feedparser.parse(url)
        for e in feed.entries:
            published = _parse_published(e)
            link = getattr(e, "link", "")
            title = _clean_text(getattr(e, "title", ""))
            summary = _clean_text(getattr(e, "summary", ""))

            items.append({
                "source": src_name,
                "source_weight": _guess_source_weight(src_name),
                "title": title,
                "summary": summary,
                "link": link,
                "published_at": published.isoformat() if published else None,
                "raw": e,
            })
    return items


def fetch_full_text(url: str, timeout: int = 12) -> str:
    # Try trafilatura first; fallback to simple requests + strip
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=True)
        if downloaded:
            text = trafilatura.extract(
                downloaded, include_comments=False, include_tables=False)
            if text:
                return text.strip()
    except Exception:
        pass
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return _clean_text(r.text)
    except Exception:
        return ""
