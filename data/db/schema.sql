-- telecare.db schema.   Owner: M3
-- Opened read-only by the Account Agent. Built by seed.py.
-- Name / email / NIC are Fernet-encrypted; msisdn is plain (it is the login ID).

CREATE TABLE IF NOT EXISTS plans (
    plan_id      INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,          -- must match package names in the corpus
    monthly_fee  INTEGER NOT NULL,
    data_gb      INTEGER NOT NULL,
    voice_min    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS subscribers (
    subscriber_id  TEXT PRIMARY KEY,
    msisdn         TEXT NOT NULL UNIQUE,
    full_name_enc  TEXT NOT NULL,
    email_enc      TEXT NOT NULL,
    nic_enc        TEXT NOT NULL,
    plan_id        INTEGER NOT NULL REFERENCES plans(plan_id)
);

CREATE TABLE IF NOT EXISTS bills (
    bill_id        INTEGER PRIMARY KEY,
    subscriber_id  TEXT NOT NULL REFERENCES subscribers(subscriber_id),
    period         TEXT NOT NULL,        -- YYYY-MM
    base_fee       INTEGER NOT NULL,
    addons         INTEGER NOT NULL DEFAULT 0,
    roaming        INTEGER NOT NULL DEFAULT 0,
    overage        INTEGER NOT NULL DEFAULT 0,
    tax            INTEGER NOT NULL DEFAULT 0,
    total          INTEGER NOT NULL,
    UNIQUE (subscriber_id, period)
);

CREATE TABLE IF NOT EXISTS bill_items (
    item_id      INTEGER PRIMARY KEY,
    bill_id      INTEGER NOT NULL REFERENCES bills(bill_id),
    item_date    TEXT NOT NULL,          -- YYYY-MM-DD
    type         TEXT NOT NULL,          -- addon | roaming | overage | base
    description  TEXT NOT NULL,
    amount       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS usage (
    subscriber_id   TEXT NOT NULL REFERENCES subscribers(subscriber_id),
    period          TEXT NOT NULL,
    data_used_gb    REAL NOT NULL,
    voice_used_min  INTEGER NOT NULL,
    PRIMARY KEY (subscriber_id, period)
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id     INTEGER PRIMARY KEY,
    subscriber_id  TEXT NOT NULL REFERENCES subscribers(subscriber_id),
    paid_on        TEXT NOT NULL,
    amount         INTEGER NOT NULL,
    method         TEXT NOT NULL
);
