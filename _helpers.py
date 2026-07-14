import os, json, psycopg2
from datetime import datetime, timezone, timedelta

DATABASE_URL = os.environ["DATABASE_URL"]

def get_db():
    return psycopg2.connect(DATABASE_URL)

def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pipe_tokens (
        platform     TEXT PRIMARY KEY,
        access_token TEXT NOT NULL,
        refresh_token TEXT,
        expires_at   TIMESTAMPTZ,
        account_ids  JSONB DEFAULT '[]',
        updated_at   TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS pipe_destinations (
        id              SERIAL PRIMARY KEY,
        name            TEXT NOT NULL,
        platform        TEXT NOT NULL UNIQUE,
        bq_project      TEXT NOT NULL,
        bq_dataset      TEXT NOT NULL,
        service_account JSONB NOT NULL DEFAULT '{}',
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS pipe_table_groups (
        id          SERIAL PRIMARY KEY,
        name        TEXT NOT NULL,
        platform    TEXT NOT NULL,
        description TEXT DEFAULT '',
        created_at  TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS pipe_tables (
        id           SERIAL PRIMARY KEY,
        group_id     INT REFERENCES pipe_table_groups(id) ON DELETE CASCADE,
        name         TEXT NOT NULL,
        bq_table     TEXT NOT NULL,
        dimensions   JSONB NOT NULL DEFAULT '[]',
        metrics      JSONB NOT NULL DEFAULT '[]',
        breakdown    TEXT NOT NULL DEFAULT 'campaign',
        created_at   TIMESTAMPTZ DEFAULT NOW(),
        updated_at   TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS pipe_transfers (
        id              SERIAL PRIMARY KEY,
        name            TEXT NOT NULL,
        platform        TEXT NOT NULL,
        destination_id  INT REFERENCES pipe_destinations(id) ON DELETE SET NULL,
        group_id        INT REFERENCES pipe_table_groups(id) ON DELETE SET NULL,
        account_ids     JSONB NOT NULL DEFAULT '[]',
        slots           JSONB NOT NULL DEFAULT '[{"time":"00:00","window":3,"type":"daily"}]',
        alert_email     TEXT,
        active          BOOLEAN NOT NULL DEFAULT TRUE,
        last_run        TIMESTAMPTZ,
        last_status     TEXT,
        last_rows       INT DEFAULT 0,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS pipe_logs (
        id           SERIAL PRIMARY KEY,
        transfer_id  INT REFERENCES pipe_transfers(id) ON DELETE CASCADE,
        bq_table     TEXT,
        slot_time    TEXT,
        status       TEXT,
        rows         INT DEFAULT 0,
        error        TEXT,
        duration_ms  INT DEFAULT 0,
        ran_at       TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    conn.commit()
    cur.close()

# ── TOKENS ───────────────────────────────────────────────────────────────────

def save_token(platform, data):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pipe_tokens (platform,access_token,refresh_token,expires_at,account_ids)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (platform) DO UPDATE SET
            access_token=EXCLUDED.access_token, refresh_token=EXCLUDED.refresh_token,
            expires_at=EXCLUDED.expires_at, account_ids=EXCLUDED.account_ids, updated_at=NOW()
    """, (platform, data["access_token"], data.get("refresh_token"),
          data.get("expires_at"), json.dumps(data.get("account_ids", []))))
    conn.commit(); cur.close(); conn.close()

def get_token(platform):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("SELECT access_token,refresh_token,expires_at,account_ids FROM pipe_tokens WHERE platform=%s", (platform,))
    row = cur.fetchone(); cur.close(); conn.close()
    if not row: return None
    return {"access_token":row[0],"refresh_token":row[1],"expires_at":row[2],"account_ids":row[3] or []}

def list_tokens():
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("SELECT platform,account_ids,updated_at FROM pipe_tokens ORDER BY platform")
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"platform":r[0],"accounts":r[1] or [],"updated_at":str(r[2])} for r in rows]

def delete_token(platform):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipe_tokens WHERE platform=%s", (platform,))
    conn.commit(); cur.close(); conn.close()

# ── DESTINATIONS ─────────────────────────────────────────────────────────────

def save_destination(data):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    sa = data["service_account"]
    if isinstance(sa, str) and sa.strip():
        sa = json.loads(sa)
    elif not sa:
        sa = {}
    if data.get("id"):
        cur.execute("""UPDATE pipe_destinations SET name=%s,platform=%s,bq_project=%s,
                       bq_dataset=%s,service_account=%s,updated_at=NOW() WHERE id=%s""",
                    (data["name"],data["platform"],data["bq_project"],
                     data["bq_dataset"],json.dumps(sa),data["id"]))
    else:
        cur.execute("""INSERT INTO pipe_destinations (name,platform,bq_project,bq_dataset,service_account)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (platform) DO UPDATE SET
                       name=EXCLUDED.name,bq_project=EXCLUDED.bq_project,
                       bq_dataset=EXCLUDED.bq_dataset,service_account=EXCLUDED.service_account,
                       updated_at=NOW()""",
                    (data["name"],data["platform"],data["bq_project"],
                     data["bq_dataset"],json.dumps(sa)))
    conn.commit(); cur.close(); conn.close()

def list_destinations():
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("SELECT id,name,platform,bq_project,bq_dataset,updated_at FROM pipe_destinations ORDER BY platform")
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"id":r[0],"name":r[1],"platform":r[2],"bq_project":r[3],"bq_dataset":r[4],"updated_at":str(r[5])} for r in rows]

def get_destination_by_platform(platform):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("SELECT id,name,bq_project,bq_dataset,service_account FROM pipe_destinations WHERE platform=%s", (platform,))
    row = cur.fetchone(); cur.close(); conn.close()
    if not row: return None
    return {"id":row[0],"name":row[1],"bq_project":row[2],"bq_dataset":row[3],"service_account":row[4]}

def delete_destination(dest_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipe_destinations WHERE id=%s", (dest_id,))
    conn.commit(); cur.close(); conn.close()

def test_bq_connection(sa_json, project, dataset):
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account as sa_mod
        sa = sa_json if isinstance(sa_json, dict) else json.loads(sa_json)
        creds = sa_mod.Credentials.from_service_account_info(sa)
        bq = bigquery.Client(credentials=creds, project=project)
        bq.get_dataset(f"{project}.{dataset}")
        return True, "Conexão OK"
    except Exception as e:
        return False, str(e)

# ── TABLE GROUPS ──────────────────────────────────────────────────────────────

def save_table_group(data):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("INSERT INTO pipe_table_groups (name,platform,description) VALUES (%s,%s,%s) RETURNING id",
                (data["name"], data["platform"], data.get("description","")))
    new_id = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    return new_id

def list_table_groups(platform=None):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    if platform:
        cur.execute("SELECT id,name,platform,description,created_at FROM pipe_table_groups WHERE platform=%s ORDER BY id", (platform,))
    else:
        cur.execute("SELECT id,name,platform,description,created_at FROM pipe_table_groups ORDER BY platform,id")
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"id":r[0],"name":r[1],"platform":r[2],"description":r[3],"created_at":str(r[4])} for r in rows]

def delete_table_group(group_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipe_table_groups WHERE id=%s", (group_id,))
    conn.commit(); cur.close(); conn.close()

# ── TABLES ────────────────────────────────────────────────────────────────────

def save_table(data):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    if data.get("id"):
        cur.execute("""UPDATE pipe_tables SET name=%s,bq_table=%s,dimensions=%s,metrics=%s,
                       breakdown=%s,updated_at=NOW() WHERE id=%s""",
                    (data["name"], data["bq_table"], json.dumps(data.get("dimensions",[])),
                     json.dumps(data.get("metrics",[])), data.get("breakdown","campaign"), data["id"]))
        new_id = data["id"]
    else:
        cur.execute("""INSERT INTO pipe_tables (group_id,name,bq_table,dimensions,metrics,breakdown)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (data["group_id"], data["name"], data["bq_table"],
                     json.dumps(data.get("dimensions",[])), json.dumps(data.get("metrics",[])),
                     data.get("breakdown","campaign")))
        new_id = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    return new_id

def list_tables(group_id):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("SELECT id,name,bq_table,dimensions,metrics,breakdown FROM pipe_tables WHERE group_id=%s ORDER BY id", (group_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"id":r[0],"name":r[1],"bq_table":r[2],"dimensions":r[3] or [],"metrics":r[4] or [],"breakdown":r[5]} for r in rows]

def delete_table(table_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipe_tables WHERE id=%s", (table_id,))
    conn.commit(); cur.close(); conn.close()

# ── TRANSFERS ─────────────────────────────────────────────────────────────────

def save_transfer(data):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    slots = data.get("slots", [{"time":"00:00","window":3,"type":"daily"}])
    if data.get("id"):
        cur.execute("""UPDATE pipe_transfers SET name=%s,platform=%s,destination_id=%s,
                       group_id=%s,account_ids=%s,slots=%s,alert_email=%s,active=%s WHERE id=%s""",
                    (data["name"], data["platform"], data.get("destination_id"),
                     data.get("group_id"), json.dumps(data.get("account_ids",[])),
                     json.dumps(slots), data.get("alert_email"), data.get("active",True), data["id"]))
        new_id = data["id"]
    else:
        cur.execute("""INSERT INTO pipe_transfers (name,platform,destination_id,group_id,
                       account_ids,slots,alert_email) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (data["name"], data["platform"], data.get("destination_id"),
                     data.get("group_id"), json.dumps(data.get("account_ids",[])),
                     json.dumps(slots), data.get("alert_email")))
        new_id = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    return new_id

def list_transfers():
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""SELECT t.id,t.name,t.platform,d.name,d.bq_dataset,g.name,
                          t.slots,t.active,t.last_run,t.last_status,t.last_rows,t.account_ids
                   FROM pipe_transfers t
                   LEFT JOIN pipe_destinations d ON t.destination_id=d.id
                   LEFT JOIN pipe_table_groups g ON t.group_id=g.id
                   ORDER BY t.id""")
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"id":r[0],"name":r[1],"platform":r[2],"destination_name":r[3],"bq_dataset":r[4],
             "group_name":r[5],"slots":r[6] or [],"active":r[7],
             "last_run":str(r[8]) if r[8] else None,"last_status":r[9],
             "last_rows":r[10],"account_ids":r[11] or []} for r in rows]

def get_transfer_full(transfer_id):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""SELECT t.id,t.name,t.platform,t.destination_id,t.group_id,t.account_ids,
                          t.slots,t.alert_email,t.active,
                          d.bq_project,d.bq_dataset,d.service_account
                   FROM pipe_transfers t
                   LEFT JOIN pipe_destinations d ON t.destination_id=d.id
                   WHERE t.id=%s""", (transfer_id,))
    r = cur.fetchone(); cur.close(); conn.close()
    if not r: return None
    return {"id":r[0],"name":r[1],"platform":r[2],"destination_id":r[3],"group_id":r[4],
            "account_ids":r[5] or [],"slots":r[6] or [],"alert_email":r[7],"active":r[8],
            "bq_project":r[9],"bq_dataset":r[10],"service_account":r[11]}

def get_active_transfers_for_slot(slot_time):
    """Retorna transfers ativos que têm um slot configurado para este horário (HH:MM)."""
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""SELECT t.id,t.name,t.platform,t.group_id,t.account_ids,t.slots,
                          d.bq_project,d.bq_dataset,d.service_account
                   FROM pipe_transfers t
                   LEFT JOIN pipe_destinations d ON t.destination_id=d.id
                   WHERE t.active=TRUE""")
    rows = cur.fetchall(); cur.close(); conn.close()
    result = []
    for r in rows:
        slots = r[5] or []
        matching = [s for s in slots if s.get("time","") == slot_time]
        if matching:
            result.append({
                "id":r[0],"name":r[1],"platform":r[2],"group_id":r[3],
                "account_ids":r[4] or [],"slot":matching[0],
                "bq_project":r[6],"bq_dataset":r[7],"service_account":r[8]
            })
    return result

def update_transfer_run(transfer_id, status, rows, error=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE pipe_transfers SET last_run=NOW(),last_status=%s,last_rows=%s WHERE id=%s",
                (status, rows, transfer_id))
    conn.commit(); cur.close(); conn.close()

def delete_transfer(transfer_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipe_transfers WHERE id=%s", (transfer_id,))
    conn.commit(); cur.close(); conn.close()


def get_logs_by_transfer(transfer_id, limit=30):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""SELECT status, rows, ran_at, duration_ms, error
                   FROM pipe_logs WHERE transfer_id=%s
                   ORDER BY ran_at DESC LIMIT %s""", (transfer_id, limit))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"status":r[0],"rows":r[1],"ran_at":str(r[2]),"duration_ms":r[3],"error":r[4]} for r in rows]

def add_log(transfer_id, bq_table, slot_time, status, rows, error, duration_ms):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("INSERT INTO pipe_logs (transfer_id,bq_table,slot_time,status,rows,error,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (transfer_id, bq_table, slot_time, status, rows, error, duration_ms))
    conn.commit(); cur.close(); conn.close()

def get_logs(limit=200):
    conn = get_db(); ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""SELECT l.id,t.name,l.bq_table,l.slot_time,l.status,l.rows,l.error,l.duration_ms,l.ran_at,t.platform
                   FROM pipe_logs l LEFT JOIN pipe_transfers t ON l.transfer_id=t.id
                   ORDER BY l.ran_at DESC LIMIT %s""", (limit,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [{"id":r[0],"transfer_name":r[1],"bq_table":r[2],"slot_time":r[3],"status":r[4],
             "rows":r[5],"error":r[6],"duration_ms":r[7],"ran_at":str(r[8]),"platform":r[9]} for r in rows]

# ── BIGQUERY ──────────────────────────────────────────────────────────────────

def get_bq_client(sa_json, project):
    from google.cloud import bigquery
    from google.oauth2 import service_account as sa_mod
    sa = sa_json if isinstance(sa_json, dict) else json.loads(sa_json)
    creds = sa_mod.Credentials.from_service_account_info(sa)
    return bigquery.Client(credentials=creds, project=project)

def ensure_bq_dataset(bq, project, dataset):
    """Cria o dataset no BigQuery se não existir."""
    from google.cloud import bigquery
    from google.api_core.exceptions import NotFound
    dataset_ref = f"{project}.{dataset}"
    try:
        bq.get_dataset(dataset_ref)
    except NotFound:
        ds = bigquery.Dataset(dataset_ref)
        ds.location = "US"
        bq.create_dataset(ds, exists_ok=True)

import re as _re

def _sanitize_col(name):
    """Sanitiza nome de coluna para BigQuery: remove parênteses, caracteres inválidos e underscores múltiplos."""
    clean = _re.sub(r'\s*\([^)]*\)', '', str(name))  # remove (conteúdo)
    clean = _re.sub(r'[^a-zA-Z0-9]', '_', clean)     # invalidos → _
    clean = _re.sub(r'_+', '_', clean).strip('_').lower()
    return clean or 'col'

def upsert_bq(bq, project, dataset, table_name, rows):
    from google.cloud import bigquery
    if not rows: return 0

    # Sanitiza nomes de colunas e limpa valores
    clean_rows = []
    for r in rows:
        clean = {}
        for k, v in r.items():
            if k == "_synced_at":
                continue
            col = _sanitize_col(k)
            if isinstance(v, float) and v == int(v):
                clean[col] = int(v)
            else:
                clean[col] = v
        clean_rows.append(clean)

    # Garante que o dataset existe
    ensure_bq_dataset(bq, project, dataset)

    full = f"{project}.{dataset}.{table_name}"

    job = bq.load_table_from_json(clean_rows, full, job_config=bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        autodetect=True
    ))
    job.result()
    return len(clean_rows)
