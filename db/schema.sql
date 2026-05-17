PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    content_hash    TEXT NOT NULL,         -- sha256(title + first 500 chars of summary)
    update_hash     TEXT NOT NULL,         -- sha256(body) — detects advisory revisions
    superseded_by   INTEGER REFERENCES items(id),     -- v4: advisory revision tracking
    duplicate_of_item_id INTEGER REFERENCES items(id),-- v4: source diversity preserved
    source          TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT,
    raw_blob        BLOB,                  -- zlib-compressed feed entry, capped 50 KB
    published_at    TIMESTAMP,
    ingested_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at    TIMESTAMP,

    status          TEXT DEFAULT 'new',
                    -- new | triaged | enriched | mapped | contextualized |
                    -- mitigated | composed | briefed | archived |
                    -- superseded | failed
    error           TEXT,

    triage_score    INTEGER,
    score_method    TEXT,                  -- 'rule' | 'rule+llm' | 'rule+enriched'
    sectors         TEXT,                  -- JSON
    cve_ids         TEXT,                  -- JSON
    mitre_techniques TEXT,                 -- JSON, post-validation
    rationale       TEXT,                  -- JSON array

    sector_context  TEXT,
    mitigation_block TEXT,
    mitigation_confidence REAL,

    feedback        TEXT,
    alerted_at      TIMESTAMP,

    briefing_date   DATE,
    enrichment_json TEXT
);

-- content_hash is NOT unique — duplicates land in their own rows with
-- duplicate_of_item_id set. URL is also not unique — supersession creates
-- new rows pointing at the old.
CREATE INDEX IF NOT EXISTS idx_items_url         ON items(url);
CREATE INDEX IF NOT EXISTS idx_items_hash        ON items(content_hash);
CREATE INDEX IF NOT EXISTS idx_items_update      ON items(update_hash);
CREATE INDEX IF NOT EXISTS idx_items_status      ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_score       ON items(triage_score);
CREATE INDEX IF NOT EXISTS idx_items_briefing    ON items(briefing_date);
CREATE INDEX IF NOT EXISTS idx_items_ingested    ON items(ingested_at);
CREATE INDEX IF NOT EXISTS idx_items_alerted     ON items(alerted_at);
CREATE INDEX IF NOT EXISTS idx_items_superseded  ON items(superseded_by);
CREATE INDEX IF NOT EXISTS idx_items_duplicate   ON items(duplicate_of_item_id);

CREATE TABLE IF NOT EXISTS cves (
    cve_id          TEXT PRIMARY KEY,
    cvss_v3         REAL,
    epss            REAL,
    epss_fetched_at TIMESTAMP,
    in_kev          INTEGER DEFAULT 0,
    kev_added_date  DATE,
    description     TEXT,
    refs_json       TEXT,
    fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS briefings (
    date                DATE PRIMARY KEY,
    item_count          INTEGER,
    markdown_path       TEXT,
    email_sent_at       TIMESTAMP,
    obsidian_written_at TIMESTAMP,
    git_committed_at    TIMESTAMP,
    git_sha             TEXT,
    duration_sec        INTEGER
);

CREATE TABLE IF NOT EXISTS overrides (
    pattern         TEXT PRIMARY KEY,
    action          TEXT NOT NULL,         -- 'suppress' | 'force_include' | 'boost_score'
    value           INTEGER,
    note            TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS run_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        DATE NOT NULL,
    stage           TEXT NOT NULL,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    status          TEXT,
    items_processed INTEGER,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_run_log_date ON run_log(run_date);
