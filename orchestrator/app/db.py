import os
import psycopg
from psycopg.rows import dict_row

POSTGRES_URL = os.environ.get("POSTGRES_URL", "postgresql://localhost/sentinel")

SCHEMA = """
CREATE TABLE IF NOT EXISTS environments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_url TEXT NOT NULL,
    project_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    public_url TEXT,
    status TEXT NOT NULL DEFAULT 'provisioning',
    is_demo BOOLEAN NOT NULL DEFAULT false,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    environment_id UUID REFERENCES environments(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,               -- 'kill' | 'load_spike'
    status TEXT NOT NULL DEFAULT 'running',
    down_at TIMESTAMPTZ,
    recovered_at TIMESTAMPTZ,
    mttr_seconds REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID REFERENCES experiments(id) ON DELETE CASCADE,
    type TEXT NOT NULL,               -- 'down' | 'up' | 'note'
    detail TEXT,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID REFERENCES experiments(id) ON DELETE CASCADE,
    log_excerpt TEXT,
    root_cause TEXT,
    proposed_fix TEXT,
    stage_verified BOOLEAN NOT NULL DEFAULT false,
    pr_url TEXT,
    is_sample BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

def get_conn():
    return psycopg.connect(POSTGRES_URL, row_factory=dict_row, autocommit=True)

def init_db():
    with get_conn() as conn:
        conn.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto;')
        conn.execute(SCHEMA)



