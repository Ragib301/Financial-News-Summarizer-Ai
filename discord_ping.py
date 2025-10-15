import os
import requests
from datetime import datetime, timedelta
import pytz

NEWS_WEBHOOK = os.getenv("DISCORD_NEWS_WEBHOOK")
RANK_WEBHOOK = os.getenv("DISCORD_RANKINGS_WEBHOOK")
MARKET_TZ = os.getenv("MARKET_TZ", "US/Eastern")
WINDOW_HOURS = int(os.getenv("DISCORD_WINDOW_HOURS", "8"))


def _tznow():
    tz = pytz.timezone(MARKET_TZ)
    return datetime.now(tz)


def _fmt_dt(dt_obj):
    # e.g., "Oct 14, 2025 09:15 AM EDT"
    return dt_obj.strftime("%b %d, %Y %I:%M %p %Z")


def _join(*parts):
    return "\n".join([p for p in parts if p])


def _post_discord_chunked(webhook_url: str, content: str, max_len: int = 1900):
    if not webhook_url:
        return False, "Webhook not set"
    lines = (content or "").splitlines()
    chunks, buf = [], ""
    for ln in lines:
        if len(buf) + len(ln) + 1 > max_len:
            chunks.append(buf)
            buf = ln
        else:
            buf = f"{buf}\n{ln}" if buf else ln
    if buf:
        chunks.append(buf)

    all_ok = True
    last_info = ""
    for ch in chunks:
        try:
            r = requests.post(webhook_url, json={"content": ch}, timeout=10)
            ok = 200 <= r.status_code < 300
            all_ok = all_ok and ok
            last_info = f"{r.status_code} {r.text[:120]}"
        except Exception as e:
            all_ok = False
            last_info = str(e)
    return all_ok, f"sent {len(chunks)} chunk(s): {last_info}"


def send_news_digest(articles: list):
    """
    articles: list of dicts like your storage.recent_articles() returns
    Filters to WINDOW_HOURS in MARKET_TZ and posts a compact digest to NEWS_WEBHOOK.
    """
    now = _tznow()
    cutoff = now - timedelta(hours=WINDOW_HOURS)

    # Convert article time strings (UTC ISO) to MARKET_TZ-aware dt for filtering + display
    def _to_local(iso_str):
        # Example: "2025-10-14T13:10:00+00:00"
        try:
            dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        except Exception:
            return None, None
        tz = pytz.timezone(MARKET_TZ)
        dt_local = dt_utc.astimezone(tz)
        return dt_utc, dt_local

    recent = []
    for a in articles:
        if not a.get("published_at"):
            continue
        _utc, loc = _to_local(a["published_at"])
        if not loc:
            continue
        if loc >= cutoff:
            recent.append((loc, a))

    if not recent:
        header = f"**Daily Financial News — {_fmt_dt(now)}**"
        body = "_No new articles in the last {}h_".format(WINDOW_HOURS)
        return _post_discord_chunked(NEWS_WEBHOOK, _join(header, body))  # type: ignore

    # Sort newest first
    recent.sort(key=lambda x: x[0], reverse=True)

    # Build lines (keep it tight)
    lines = []
    for loc_dt, a in recent[:20]:  # cap to avoid exceeding Discord length
        tickers = ", ".join(a.get("tickers", [])[:5]) or "—"
        time_str = loc_dt.strftime("%H:%M")
        title = a.get("title", "")[:140]
        src = a.get("source", "")
        lines.append(f"• [{time_str}] {src}: {title} — ({tickers})")

    header = f"**Daily Financial News — {_fmt_dt(now)}**"
    footer = f"_Window: last {WINDOW_HOURS}h • TZ: {MARKET_TZ}_"
    # type: ignore
    return _post_discord_chunked(NEWS_WEBHOOK, _join(header, *lines, footer)) # type: ignore


def send_rankings_digest(ranked: list, verdict: dict | None):
    """
    ranked: list of tuples (ticker, score, bucket) from scorer.to_ranked_list(...)
    verdict: dict with keys { picks: [...], verdict: "..." } or None
    """
    now = _tznow()
    header = f"**Daily Rankings — {_fmt_dt(now)}**"

    if not ranked:
        # type: ignore
        return _post_discord_chunked(RANK_WEBHOOK, _join(header, "_No ranked tickers yet_")) # type: ignore

    lines = []
    for i, (t, score, bucket) in enumerate(ranked[:10], start=1):
        s = f"{score:.3f}"
        # include a short recent headline for context if present
        hl = bucket["articles"][0]["title"] if bucket.get("articles") else ""
        hl = (hl[:90] + "…") if len(hl) > 93 else hl
        lines.append(f"{i}. **{t}** — score {s} — {hl}")

    msg_parts = [header, *lines]

    if verdict:
        picks = verdict.get("picks", [])[:6]
        if picks:
            msg_parts.append("\n**LLM Watchlist**")
            for p in picks:
                th = p.get("thesis", "")
                th = (th[:110] + "…") if len(th) > 113 else th
                msg_parts.append(f"• **{p.get('ticker', '?')}** — {th}")
        vtxt = verdict.get("verdict", "")
        if vtxt:
            vtxt = (vtxt[:400] + "…") if len(vtxt) > 403 else vtxt
            msg_parts.append(f"\n**Verdict:** {vtxt}")

    return _post_discord_chunked(RANK_WEBHOOK, _join(*msg_parts))  # type: ignore
