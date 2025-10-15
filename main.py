import os
import json
import pytz
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from openai import OpenAI

import news_sources as ns
import analyzer as az
import storage as db
import scorer as sc
import discord_ping as dn


load_dotenv()
db.init_db()

st.set_page_config(page_title="AI News Automation - Wharton", layout="wide")

MARKET_TZ = os.getenv("MARKET_TZ", "US/Eastern")
CRONS = os.getenv("SCHEDULE_CRONS", "9:15,12:30,16:10")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")


def start_scheduler():
    if st.session_state.scheduler_started:
        return
    scheduler = BackgroundScheduler(timezone=pytz.timezone(MARKET_TZ))
    times = [t.strip() for t in CRONS.split(",") if t.strip()]
    for t in times:
        hh, mm = [int(x) for x in t.split(":")]
        scheduler.add_job(lambda: do_scheduled_run(send_discord=True),
                          "cron", hour=hh, minute=mm, misfire_grace_time=600)
    scheduler.start()
    st.session_state.scheduler_started = True


if os.getenv("AUTO_START_SCHEDULER", "1") == "1":
    try:
        start_scheduler()
    except Exception as e:
        st.warning(f"Scheduler failed: {e}")

if "scheduler_started" not in st.session_state:
    st.session_state.scheduler_started = False


def do_scheduled_run(send_discord: bool = True):
    # 1) fetch/analyze/save
    added = run_pipeline()

    # 2) build ranking + verdict
    top, verdict = build_ranking_and_verdict()
    st.session_state["top"] = top
    st.session_state["verdict"] = verdict

    # 3) Discord pings (two channels)
    if send_discord:
        arts = db.recent_articles(limit=200)
        ok1, info1 = dn.send_news_digest(arts)
        ok2, info2 = dn.send_rankings_digest(top, verdict)
        st.toast(
            f"Discord news: {'OK' if ok1 else 'ERR'} | rankings: {'OK' if ok2 else 'ERR'}", icon="📣")
    return added


def run_pipeline():
    st.toast("Fetching feeds…", icon="📰")
    items = ns.fetch_rss_items()
    st.toast(
        f"Fetched {len(items)} items. Pulling full text + summarizing…", icon="⏳")
    added = 0

    for it in items:
        if db.article_exists(it["link"]):
            continue
        full_text = ns.fetch_full_text(it["link"])
        analysis = az.analyze_article(client, it, full_text).model_dump()
        db.save_article(analysis)
        added += 1
    st.toast(f"Saved {added} new articles.", icon="✅")
    return added


def build_ranking_and_verdict():
    arts = db.recent_articles(limit=300)
    per_ticker = sc.score_articles_by_ticker(arts)
    top = sc.to_ranked_list(per_ticker, top_n=10)

    # Compose a compact context for the LLM verdict
    context = []
    for t, score, bucket in top:
        ctx = {
            "ticker": t,
            "score": round(score, 3),
            "latest_headlines": [
                {
                    "title": a["title"],
                    "source": a["source"],
                    "published_at": a["published_at"],
                    "sentiment": a["sentiment"],
                    "catalyst_score": a["catalyst_score"],
                    "url": a["url"],
                    "key_points": a["key_points"][:3],
                }
                for a in bucket["articles"][:3]
            ],
        }
        context.append(ctx)

    prompt = f"""
You are a cautious but opportunistic equity strategist for a Wharton competition.
Given the aggregated news ranking (growth horizon 1–3 months), produce:

- A ranked list of 5–8 **watchlist candidates** (ticker + 1-sentence thesis).
- For each: top 2 upcoming catalysts or risks (short bullets).
- One-paragraph **verdict** summarizing the theme (e.g., AI hardware tailwinds, biotech approvals, etc.).
- Keep it concise; do NOT give price targets; do NOT claim certainty.

Return JSON with keys:
  picks: [{{ticker, thesis, bullets: [..]}}]
  verdict: "..."

CONTEXT (top signals):
{json.dumps(context, indent=2)}
    """
    resp = client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        data = resp.choices[0].message.parsed  # type: ignore
    except Exception:
        data = json.loads(resp.choices[0].message.content)  # type: ignore
    return top, data


# --- UI ---
st.title("AI Financial News Automation")
st.caption(
    "Pulls credible news 3×/day, scores by ticker, and produces watchlist + verdict (1–3 mo).")

colA, colB, colC = st.columns([1, 1, 2])
with colA:
    if st.button("▶ Run now", use_container_width=True):
        added = do_scheduled_run(send_discord=True)
        st.success(f"Run complete. Added {added} new items. Discord pinged.")

with colB:
    if st.button("Build ranking + verdict", use_container_width=True):
        top, verdict = build_ranking_and_verdict()
        st.session_state["top"] = top
        st.session_state["verdict"] = verdict
        st.success("Verdict ready below.")

    if st.button("Send Discord now", use_container_width=True):
        arts = db.recent_articles(limit=200)
        ok1, info1 = dn.send_news_digest(arts)
        top = st.session_state.get("top", [])
        verdict = st.session_state.get("verdict", {})
        ok2, info2 = dn.send_rankings_digest(top, verdict)
        st.success(
            f"Discord news: {'OK' if ok1 else 'ERR'}; rankings: {'OK' if ok2 else 'ERR'}")

with colC:
    st.write(
        f"🕒 Schedule ({MARKET_TZ}): **{CRONS}** — *auto-runs in background while app is live*")
    if st.button("⏱ Start scheduler", use_container_width=True, disabled=st.session_state.scheduler_started):
        start_scheduler()
        st.success("Scheduler started.")

st.divider()

# Latest articles
arts = db.recent_articles(limit=50)
st.subheader("Latest news (most recent first)")
if arts:
    df = pd.DataFrame([{
        "Time (UTC)": a["published_at"],
        "Source": a["source"],
        "Title": a["title"],
        "Tickers": ", ".join(a["tickers"]),
        "Sentiment": round(a["sentiment"], 3),
        "Catalyst": round(a["catalyst_score"], 3),
        "URL": a["url"],
    } for a in arts])
    st.dataframe(df, use_container_width=True, height=420)
else:
    st.info("No articles saved yet. Click **Run now** to fetch.")

st.subheader("Top signals & verdict")
if "top" in st.session_state and st.session_state["top"]:
    top = st.session_state["top"]
    rows = []
    for t, score, bucket in top:
        rows.append({
            "Ticker": t,
            "CompositeScore": round(score, 3),
            "Headlines": "; ".join(h["title"] for h in bucket["articles"][:2])
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=320)

if "verdict" in st.session_state and st.session_state["verdict"]:
    v = st.session_state["verdict"]
    st.markdown("### Watchlist candidates (LLM synthesis)")
    for p in v.get("picks", []):
        st.markdown(f"**{p.get('ticker', '?')}** — {p.get('thesis', '')}")
        for b in p.get("bullets", [])[:2]:
            st.markdown(f"- {b}")
    st.markdown("**Verdict (1–3 mo):** " + v.get("verdict", ""))

st.caption(
    "Educational use only. Not investment advice. Always do your own research and manage risk.")
