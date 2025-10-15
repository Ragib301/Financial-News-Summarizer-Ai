import datetime as dt
from typing import Dict, List, Tuple
import yfinance as yf

# Weights for the composite score
W_SOURCE = 0.35
W_SENTIMENT = 0.20
W_CATALYST = 0.20
W_RECENCY = 0.15
W_MARKET_REACTION = 0.10  # price/volume confirmation


def recency_weight(published_iso: str, now: dt.datetime) -> float:
    try:
        published = dt.datetime.fromisoformat(
            published_iso.replace("Z", "+00:00"))
    except Exception:
        return 0.7
    hours = max(0.0, (now - published).total_seconds()/3600.0)
    # decay after ~48h
    if hours <= 2:
        return 1.0
    if hours <= 24:
        return 0.9
    if hours <= 48:
        return 0.75
    return 0.5


def market_reaction_signal(ticker: str) -> float:
    """
    Quick confirmation via yfinance:
    - +0.5 if today's %ch > +1.5%
    - +0.5 if today's volume > 1.5x 20-day avg
    - negative mirror for downside
    """
    try:
        data = yf.download(ticker, period="1mo", interval="1d", progress=False)
        if data is None or len(data) < 21:
            return 0.0
        today = data.iloc[-1]
        prev = data.iloc[-2]
        avg_vol = data["Volume"].iloc[-21:-1].mean()
        pct = (today["Close"]/prev["Close"] - 1.0) * 100.0
        vol_mult = (today["Volume"]/max(1, avg_vol))
        score = 0.0
        if pct > 1.5:
            score += 0.5
        if pct < -1.5:
            score -= 0.5
        if vol_mult > 1.5:
            score += 0.5
        if vol_mult < 0.6:
            score -= 0.3
        return max(-1.0, min(1.0, score))
    except Exception:
        return 0.0


def score_articles_by_ticker(articles: List[dict]) -> Dict[str, Dict]:
    """
    Aggregate per ticker into a composite score.
    """
    now = dt.datetime.now(dt.timezone.utc)
    per_ticker: Dict[str, Dict] = {}
    for a in articles:
        if not a["tickers"]:
            continue
        r_w = recency_weight(a["published_at"], now)
        art_score = (
            W_SOURCE * float(a["source_weight"]) +
            W_SENTIMENT * float(a["sentiment"]) +
            W_CATALYST * float(a["catalyst_score"]) +
            W_RECENCY * r_w
        )
        for t in a["tickers"]:
            bucket = per_ticker.setdefault(t, {"score": 0.0, "articles": []})
            bucket["score"] += art_score
            bucket["articles"].append(a)

    # Add market reaction confirmation
    for t, bucket in per_ticker.items():
        bucket["score"] += W_MARKET_REACTION * market_reaction_signal(t)

    # Sort articles by recency inside each bucket
    for t, bucket in per_ticker.items():
        bucket["articles"].sort(key=lambda x: x.get(
            "published_at") or "", reverse=True)

    return per_ticker


def to_ranked_list(per_ticker: Dict[str, Dict], top_n: int = 10) -> List[Tuple[str, float, Dict]]:
    ranked = sorted(
        [(t, v["score"], v) for t, v in per_ticker.items()],
        key=lambda x: x[1],
        reverse=True
    )
    return ranked[:top_n]
