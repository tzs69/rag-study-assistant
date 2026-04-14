CREATE TABLE IF NOT EXISTS collection_term_stats (
    term TEXT PRIMARY KEY,
    collection_tf INTEGER NOT NULL DEFAULT 0,
    doc_freq INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_collection_term_stats ON collection_term_stats (collection_tf DESC);

CREATE TABLE IF NOT EXISTS doc_term_stats (
    doc_id TEXT NOT NULL,
    term TEXT NOT NULL,
    doc_tf INTEGER NOT NULL,
    PRIMARY KEY (doc_id, term)
);
CREATE INDEX IF NOT EXISTS idx_doc_term_stats ON doc_term_stats (doc_tf);