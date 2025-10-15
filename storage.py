import sqlite3
from typing import List, Dict, Any
import json
import os

DB_PATH = os.environ.get("DB_PATH", "news.db")

DDL = """
CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT UNIQUE,
  title TEXT,
  source TEXT,
  published_at TEXT,
  source_weight REAL,
  summary TEXT,
  full_text TEXT,
  tickers TEXT,         -- JSON array
  sentiment REAL,
  catalyst_score REAL,
  key_points TEXT,      -- JSON array
  created_at TEXT DEFAULT (datetime('now'))
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = get_conn()
    conn.execute(DDL)
    conn.commit()
    conn.close()


def article_exists(url: str) -> bool:
    conn = get_conn()
    cur = conn.execute("SELECT 1 FROM articles WHERE url = ? LIMIT 1", (url,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def save_article(a: Dict[str, Any]):
    conn = get_conn()
    conn.execute(
        """INSERT OR IGNORE INTO articles
        (url, title, source, published_at, source_weight, summary, full_text,
         tickers, sentiment, catalyst_score, key_points)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            a["url"], a["title"], a["source"], a["published_at"], a["source_weight"],
            a["summary"], a["full_text"], json.dumps(a["tickers"]),
            a["sentiment"], a["catalyst_score"], json.dumps(a["key_points"]),
        )
    )
    conn.commit()
    conn.close()


def recent_articles(limit: int = 200) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.execute(
        """SELECT url, title, source, published_at, source_weight, summary, full_text,
                  tickers, sentiment, catalyst_score, key_points
           FROM articles ORDER BY datetime(published_at) DESC NULLS LAST, id DESC LIMIT ?""",
        (limit,)
    )
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "url": r[0], "title": r[1], "source": r[2], "published_at": r[3],
            "source_weight": r[4], "summary": r[5], "full_text": r[6],
            "tickers": json.loads(r[7] or "[]"),
            "sentiment": r[8], "catalyst_score": r[9],
            "key_points": json.loads(r[10] or "[]"),
        })
    return out
