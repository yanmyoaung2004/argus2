from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA cache_size = -64000;

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'unknown',
    description TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    attributes TEXT DEFAULT '{}',
    task_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_task_id ON entities(task_id);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    entity_id INTEGER REFERENCES entities(id),
    attribute TEXT,
    source_urls TEXT DEFAULT '[]',
    task_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_claims_entity_id ON claims(entity_id);
CREATE INDEX IF NOT EXISTS idx_claims_task_id ON claims(task_id);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT,
    content_hash TEXT,
    credibility_score REAL NOT NULL DEFAULT 0.5,
    task_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sources_url ON sources(url);
CREATE INDEX IF NOT EXISTS idx_sources_task_id ON sources(task_id);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    task_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_task_id ON edges(task_id);

CREATE TABLE IF NOT EXISTS processed_keys (
    key_hash TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_sources (
    claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    task_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (claim_id, source_url)
);

CREATE INDEX IF NOT EXISTS idx_claim_sources_url ON claim_sources(source_url);
CREATE INDEX IF NOT EXISTS idx_claim_sources_task_id ON claim_sources(task_id);

CREATE TABLE IF NOT EXISTS stream_cursors (
    stream_name TEXT PRIMARY KEY,
    last_id TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    statement, entity_name, content='claims', content_rowid='id'
);

-- FTS triggers removed for performance; batch sync happens in KGWriter flush()
"""


def init_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
