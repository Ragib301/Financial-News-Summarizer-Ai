import re
import hashlib
from typing import Dict, List, Tuple
from pydantic import BaseModel
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from openai import OpenAI


_vader = SentimentIntensityAnalyzer()

IMPACT_KEYWORDS = {
    # positive catalysts
    "raises guidance": 1.2, "beat estimates": 1.1, "beats estimates": 1.1,
    "above consensus": 1.0, "buyback": 1.0, "acquires": 0.9, "acquisition": 0.9,
    "partnership": 0.6, "contract award": 0.8, "fda approval": 1.2,
    # negative catalysts
    "lowers guidance": -1.1, "misses estimates": -1.0, "sec investigation": -1.3,
    "probe": -0.7, "downgrade": -0.6, "guidance cut": -1.0, "recall": -0.8,
}

CASHTAG_RE = re.compile(r"\$[A-Z]{1,5}\b")

class ArticleAnalysis(BaseModel):
    title: str
    url: str
    source: str
    published_at: str
    source_weight: float
    summary: str
    full_text: str
    tickers: List[str]
    sentiment: float
    catalyst_score: float
    key_points: List[str]


def extract_tickers(text: str) -> List[str]:
    # Find $AAPL-style cashtags and unique them
    tags = set(x[1:] for x in CASHTAG_RE.findall(text or ""))
    return sorted(tags)


def naive_catalyst_score(text: str) -> float:
    if not text:
        return 0.0
    t = text.lower()
    score = 0.0
    for k, w in IMPACT_KEYWORDS.items():
        if k in t:
            score += w
    return score


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def summarize_with_openai(_client: OpenAI, title: str, text: str) -> Tuple[List[str], List[str]]:
    """
    Returns (key_points, model_found_tickers)
    """
    prompt = f"""
You are an equity news analyst. Given the article below, extract:
1) 3-5 bullet key points (short, factual, investor-relevant)
2) Tickers mentioned or clearly implicated (US tickers, 1-5 chars), no duplicates.

Return JSON with keys: key_points[], tickers[].

TITLE: {title}
ARTICLE:
{text[:5000]}
"""
    resp = _client.chat.completions.create(
        model="gpt-5-mini-2025-08-07",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        data = resp.choices[0].message.parsed if hasattr( # type: ignore
            resp.choices[0].message, "parsed") else None
    except Exception:
        data = None
    if not data:
        import json
        data = json.loads(resp.choices[0].message.content) # type: ignore
    key_points = data.get("key_points", [])
    tickers = data.get("tickers", [])
    return key_points, tickers


def analyze_article(client: OpenAI, item: Dict, full_text: str) -> ArticleAnalysis:
    base_text = " ".join([item.get("title", ""), item.get(
        "summary", ""), full_text or ""]).strip()
    vader = _vader.polarity_scores(base_text)["compound"]  # -1..1
    cashtags = extract_tickers(base_text)
    key_points, llm_tickers = summarize_with_openai(
        client, item["title"], full_text or item.get("summary", ""))
    tickers = sorted(set(cashtags) | set(
        [t.strip().upper() for t in llm_tickers if t.strip()]))
    cat_score = naive_catalyst_score(base_text)

    return ArticleAnalysis(
        title=item["title"],
        url=item["link"],
        source=item["source"],
        published_at=item.get("published_at") or "",
        source_weight=item.get("source_weight", 0.7),
        summary=item.get("summary") or "",
        full_text=full_text or "",
        tickers=tickers,
        sentiment=vader,
        catalyst_score=cat_score,
        key_points=key_points[:5] if key_points else [],
    )
