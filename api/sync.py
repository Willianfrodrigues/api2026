import os
import json, time, requests
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import (get_token, get_transfer_full, list_tables, list_transfers,
                      get_bq_client, upsert_bq, update_transfer_run, add_log)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self._body()
        tid  = body.get("transfer_id")
        slot_time   = body.get("slot_time")
        custom_start = body.get("date_start")
        custom_end   = body.get("date_end")
        is_backfill  = body.get("backfill", False)

        if tid:
            transfers = [get_transfer_full(tid)]
        else:
            transfers = [get_transfer_full(t["id"]) for t in list_transfers() if t["active"]]

        results = []
        for tr in transfers:
            if not tr: continue
            slots = tr.get("slots") or [{"time":"00:00","window":3,"type":"daily"}]
            slot = next((s for s in slots if s.get("time")==slot_time), slots[0]) if slot_time else slots[0]
            results.append(run_transfer(tr, slot, custom_start=custom_start, custom_end=custom_end, is_backfill=is_backfill))

        self._j({"results": results})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length",0))
        return json.loads(self.rfile.read(n)) if n else {}

    def _j(self, data, status=200):
        b = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers(); self.wfile.write(b)

app = handler

# ── EXECUTOR ─────────────────────────────────────────────────────────────────

def run_transfer(tr, slot, custom_start=None, custom_end=None, is_backfill=False):
    t0 = time.time()
    tid = tr["id"]
    platform = tr["platform"]
    token = get_token(platform)

    if not token:
        update_transfer_run(tid, "skipped", 0)
        return {"transfer_id":tid,"status":"skipped","reason":"not_connected"}

    if not tr.get("bq_project"):
        update_transfer_run(tid, "error", 0)
        return {"transfer_id":tid,"status":"error","error":"Destino BQ não configurado"}

    try:
        bq = get_bq_client(tr["service_account"], tr["bq_project"])
    except Exception as e:
        update_transfer_run(tid, "error", 0)
        return {"transfer_id":tid,"status":"error","error":f"BQ auth: {e}"}

    # Janela de datas — usa customizada (backfill) ou baseada no slot
    if custom_start and custom_end:
        date_start = custom_start
        date_end   = custom_end
    else:
        window = int(slot.get("window", 3))
        date_end   = datetime.today().strftime("%Y-%m-%d")
        date_start = (datetime.today() - timedelta(days=window)).strftime("%Y-%m-%d")

    # Filtra contas
    all_accounts  = token["account_ids"] or []
    selected_ids  = {(a["id"] if isinstance(a,dict) else str(a)) for a in (tr["account_ids"] or [])}
    accounts = [a for a in all_accounts if (a["id"] if isinstance(a,dict) else str(a)) in selected_ids] if selected_ids else all_accounts

    tables = list_tables(tr["group_id"]) if tr.get("group_id") else []
    if not tables:
        update_transfer_run(tid, "error", 0)
        return {"transfer_id":tid,"status":"error","error":"Sem tabelas no grupo"}

    total_rows = 0
    table_results = []

    for tbl in tables:
        t1 = time.time()
        try:
            print(f"[SYNC] Buscando dados: {tbl['bq_table']} | contas: {len(accounts)} | {date_start} -> {date_end}")
            rows = fetch_platform(platform, token, accounts, tbl, date_start, date_end)
            print(f"[SYNC] Linhas buscadas: {len(rows)}")
            n = upsert_bq(bq, tr["bq_project"], tr["bq_dataset"], tbl["bq_table"], rows)
            ms = int((time.time()-t1)*1000)
            print(f"[SYNC] BQ ok: {n} linhas em {ms}ms")
            total_rows += n
            add_log(tid, tbl["bq_table"], slot.get("time","—"), "ok", n, None, ms)
            table_results.append({"table":tbl["bq_table"],"rows":n,"status":"ok"})
        except Exception as e:
            import traceback
            err_detail = traceback.format_exc()
            print(f"[SYNC ERROR] {tbl['bq_table']}: {err_detail}")
            ms = int((time.time()-t1)*1000)
            add_log(tid, tbl["bq_table"], slot.get("time","—"), "error", 0, str(e), ms)
            table_results.append({"table":tbl["bq_table"],"status":"error","error":str(e)})

    status = "ok" if all(r["status"]=="ok" for r in table_results) else "partial"
    errors = [r.get("error","") for r in table_results if r.get("status")=="error"]
    error_msg = " | ".join(errors) if errors else None
    update_transfer_run(tid, status, total_rows)
    return {"transfer_id":tid,"status":status,"total_rows":total_rows,
            "tables":table_results,"duration_ms":int((time.time()-t0)*1000)}

# ── FETCHERS ─────────────────────────────────────────────────────────────────

# Campos que vêm dentro do array "actions" na Meta API — não podem ir no fields= direto
META_ACTIONS_MAP = {
    "landing_page_views":    ("actions", "landing_page_view"),
    "inline_link_clicks":    ("actions", "link_click"),
    "outbound_clicks":       ("actions", "outbound_click"),
    "purchase":              ("actions", "purchase"),
    "lead":                  ("actions", "lead"),
    "complete_registration": ("actions", "complete_registration"),
    "add_to_cart":           ("actions", "add_to_cart"),
    "initiate_checkout":     ("actions", "initiate_checkout"),
    "add_payment_info":      ("actions", "add_payment_info"),
    "view_content":          ("actions", "view_content"),
    "search":                ("actions", "search"),
    "subscribe":             ("actions", "subscribe"),
    "start_trial":           ("actions", "start_trial"),
    "mobile_app_install":    ("actions", "app_install"),
    "video_view":            ("actions", "video_view"),
    "contact":               ("actions", "contact"),
    "donate":                ("actions", "donate"),
    "find_location":         ("actions", "find_location"),
    "schedule":              ("actions", "schedule"),
    "submit_application":    ("actions", "submit_application"),
    "customize_product":     ("actions", "customize_product"),
    # Vídeo — vêm como arrays próprios com action_type="video_view"
    "video_thruplay_watched_actions":          ("video_thruplay_watched_actions", "video_view"),
    "video_30_sec_watched_actions":            ("video_30_sec_watched_actions", "video_view"),
    "video_p25_watched_actions":               ("video_p25_watched_actions", "video_view"),
    "video_p50_watched_actions":               ("video_p50_watched_actions", "video_view"),
    "video_p75_watched_actions":               ("video_p75_watched_actions", "video_view"),
    "video_p95_watched_actions":               ("video_p95_watched_actions", "video_view"),
    "video_p100_watched_actions":              ("video_p100_watched_actions", "video_view"),
    "video_continuous_2_sec_watched_actions":  ("video_continuous_2_sec_watched_actions", "video_view"),
    "video_avg_time_watched_actions":          ("video_avg_time_watched_actions", "video_view"),
}

def extract_action_value(data_row, arr_field, action_type_key):
    """Extrai valor de um action_type específico do array indicado."""
    arr = data_row.get(arr_field, [])
    if isinstance(arr, list):
        for item in arr:
            if isinstance(item, dict) and item.get("action_type") == action_type_key:
                try: return float(item.get("value", 0))
                except: return 0
    return None

def fetch_platform(platform, token, accounts, tbl, date_start, date_end):
    return {"meta":fetch_meta,"tiktok":fetch_tiktok,"dv360":fetch_dv360,"kwai":fetch_kwai}[platform](
        token, accounts, tbl, date_start, date_end)

def fetch_meta(token, accounts, tbl, date_start, date_end):
    dims = tbl.get("dimensions",[])
    mets = tbl.get("metrics",[])

    # Auto-detecta level baseado nas dimensões selecionadas
    AD_DIMS    = {"ad_id","ad_name","ad_creative_id","ad_creative_name","creative_id","creative_name"}
    ADSET_DIMS = {"adset_id","adset_name"}
    if any(d in AD_DIMS for d in dims):
        level = "ad"
    elif any(d in ADSET_DIMS for d in dims):
        level = "adset"
    else:
        level = "campaign"

    # Campos que NÃO vão no params fields= da insights API
    # São campos de nível de objeto (ad/adset/campaign) ou inválidos no insights
    NON_INSIGHTS_FIELDS = {
        "account_id","account_name","campaign_id","campaign_name",
        "adset_id","adset_name","ad_id","ad_name",
        "ad_creative_id","ad_creative_name","creative_id","creative_name",
        "ad_title","ad_body","ad_status","ad_configured_status",
        "adset_status","adset_configured_status","campaign_status","campaign_configured_status",
        "campaign_objective","campaign_buying_type","bid_type","bid_amount","bid_strategy",
        "optimization_goal","daily_budget","lifetime_budget","targeting",
        "targeting_age_min","targeting_age_max","targeting_country","targeting_location_type",
        "page_id","page_name","post_id","post_type","post_name","product_id",
        "quality_ranking","engagement_rate_ranking","conversion_rate_ranking",
        "attribution_setting","account_currency","account_timezone",
        "data_source","business_name","destination_url","promoted_post_url",
        "external_destination_url","url_tags","tracking_template",
        "image_url","thumbnail_url","object_type","call_to_action_type",
        "year","month","quarter","week","year_month","hour",
        "action_type","day_of_week",
    }

    # Campos de breakdowns (passados via params["breakdowns"])
    BREAKDOWN_FIELDS = {
        "age","gender","country","region","country_code",
        "publisher_platform","platform_position","impression_device","device_platform",
    }

    # Campos de lead form (incompatíveis com métricas normais)
    LEAD_FIELDS = {"lead_form_id","lead_form_name","lead_form_status"}

    has_lead = any(d in LEAD_FIELDS for d in dims)

    # Monta lista de fields para a API de insights
    insights_fields = []
    breakdown_dims = []

    for f in dims + mets:
        if f in NON_INSIGHTS_FIELDS:
            continue
        elif f in BREAKDOWN_FIELDS:
            breakdown_dims.append(f)
        elif f in LEAD_FIELDS:
            if has_lead:
                insights_fields.append(f)
        else:
            insights_fields.append(f)

    # Remove duplicatas mantendo ordem
    insights_fields = list(dict.fromkeys(insights_fields))
    breakdown_dims = list(dict.fromkeys(breakdown_dims))

    # Campos de hierarquia — sempre inclui baseado no level
    HIERARCHY_FIELDS = ["campaign_id","campaign_name"]
    if level in ("adset","ad"):
        HIERARCHY_FIELDS += ["adset_id","adset_name"]
    if level == "ad":
        HIERARCHY_FIELDS += ["ad_id","ad_name"]

    # Garante que campos de hierarquia estão nos insights_fields
    for f in HIERARCHY_FIELDS:
        if f not in insights_fields:
            insights_fields.insert(0, f)

    if not insights_fields:
        insights_fields = ["impressions","spend","clicks","cpm","ctr","reach"]

    # Separa campos que vêm de actions dos campos diretos da API
    action_fields = [f for f in insights_fields if f in META_ACTIONS_MAP]
    direct_fields = [f for f in insights_fields if f not in META_ACTIONS_MAP]

    # Se tem campos de actions, adiciona os arrays necessários no request
    if action_fields:
        needed_arrays = set()
        for f in action_fields:
            arr_field, _ = META_ACTIONS_MAP[f]
            needed_arrays.add(arr_field)
        for arr in needed_arrays:
            if arr not in direct_fields:
                direct_fields.append(arr)
        if "action_values" not in direct_fields:
            direct_fields.append("action_values")

    api_fields = direct_fields

    rows = []
    # Processa em batches de 10 contas por vez para não estourar timeout
    BATCH_SIZE = 10
    for i in range(0, len(accounts), BATCH_SIZE):
        batch = accounts[i:i+BATCH_SIZE]
        
        # Monta batch request da Meta API
        batch_requests = []
        for acc in batch:
            acc_id = acc["id"] if isinstance(acc,dict) else str(acc)
            import urllib.parse
            p = {
                "level": level,
                "fields": ",".join(api_fields),
                "time_range": json.dumps({"since":date_start,"until":date_end}),
                "time_increment": 1,
                "limit": 500
            }
            if breakdown_dims:
                p["breakdowns"] = ",".join(breakdown_dims)
            batch_requests.append({
                "method": "GET",
                "relative_url": f"{acc_id}/insights?{urllib.parse.urlencode(p)}"
            })

        resp = requests.post(
            "https://graph.facebook.com/v19.0/",
            params={"access_token": token["access_token"]},
            json={"batch": batch_requests},
            timeout=55
        )
        batch_results = resp.json()
        if isinstance(batch_results, dict) and "error" in batch_results:
            raise Exception(f"Meta Batch API: {batch_results['error']['message']}")

        for idx, result in enumerate(batch_results):
            if not result or result.get("code") != 200:
                continue
            acc = batch[idx]
            acc_id = acc["id"] if isinstance(acc,dict) else str(acc)
            acc_name = acc.get("name","") if isinstance(acc,dict) else ""
            body = json.loads(result.get("body","{}"))
            if "error" in body:
                print(f"[SYNC] Conta {acc_id} erro: {body['error']['message']}")
                continue
            for d in body.get("data",[]):
                row = {
                    "date": d.get("date_start",""),
                    "platform": "facebook ads",
                    "account_id": acc_id,
                    "account_name": acc_name,
                }
                # Adiciona campos de hierarquia baseado no level
                for hf in HIERARCHY_FIELDS:
                    v = d.get(hf,"")
                    if v: row[hf] = v
                for f in direct_fields:
                    if f in ("actions","action_values","date_start","date_stop"): continue
                    v = d.get(f)
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        try: row[f] = float(v[0].get("value", 0))
                        except: row[f] = 0
                    elif v is not None:
                        try:
                            fv = float(v)
                            row[f] = int(fv) if fv == int(fv) else fv
                        except: row[f] = v
                # Extrai campos de actions
                for f in action_fields:
                    arr_field, action_type = META_ACTIONS_MAP[f]
                    v = extract_action_value(d, arr_field, action_type)
                    row[f] = int(v) if v is not None and isinstance(v, float) and v == int(v) else (v or 0)
                for bd in breakdown_dims:
                    if bd in d:
                        row[bd] = d[bd]
                rows.append(row)
    return rows

def fetch_tiktok(token, accounts, tbl, date_start, date_end):
    dims = tbl.get("dimensions",[])
    mets = tbl.get("metrics",[])
    breakdown = tbl.get("breakdown","campaign")
    level_dim = {"campaign":"campaign_id","adgroup":"adgroup_id","ad":"ad_id"}.get(breakdown,"campaign_id")
    all_dims = list(dict.fromkeys(["stat_time_day",level_dim]+[d for d in dims if d not in ["stat_time_day",level_dim]]))
    rows = []
    headers = {"Access-Token":token["access_token"]}
    for acc in accounts:
        acc_id = acc["id"] if isinstance(acc,dict) else str(acc)
        params = {"advertiser_id":acc_id,"report_type":"BASIC","dimensions":json.dumps(all_dims),
                  "metrics":json.dumps(mets or ["impressions","clicks","spend","cpm","ctr"]),
                  "start_date":date_start,"end_date":date_end,"page_size":1000}
        resp = requests.get("https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/",
                            headers=headers,params=params)
        data = resp.json()
        if data.get("code",0)!=0: raise Exception(f"TikTok API: {data.get('message')}")
        for item in data.get("data",{}).get("list",[]):
            d=item.get("dimensions",{}); m=item.get("metrics",{})
            row={"date":d.get("stat_time_day","")[:10],"platform":"tiktok ads","account_id":acc_id}
            row.update(d); row.update(m); rows.append(row)
    return rows

def fetch_dv360(token, accounts, tbl, date_start, date_end):
    dims = tbl.get("dimensions",["FILTER_DATE","FILTER_INSERTION_ORDER","FILTER_LINE_ITEM"])
    mets = tbl.get("metrics",["METRIC_IMPRESSIONS","METRIC_CLICKS","METRIC_REVENUE_ADVERTISER"])
    import time as _t

    # Refresh do token se necessário (o token pode ter expirado)
    access_token = token['access_token']
    refresh_token = token.get('refresh_token')
    if refresh_token:
        try:
            r = requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": os.environ.get("GOOGLE_CLIENT_ID",""),
                "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET",""),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            })
            new_tok = r.json()
            if "access_token" in new_tok:
                access_token = new_tok["access_token"]
                print(f"[DV360] Token refreshed OK")
            else:
                print(f"[DV360] Token refresh falhou: {new_tok}")
        except Exception as e:
            print(f"[DV360] Token refresh erro: {e}")

    # Bid Manager exige FILTER_ADVERTISER_CURRENCY quando há métricas de custo em moeda do anunciante
    COST_METRICS = {
        "METRIC_MEDIA_COST_ADVERTISER","METRIC_TOTAL_MEDIA_COST_ADVERTISER",
        "METRIC_REVENUE_ADVERTISER","METRIC_BILLABLE_COST_ADVERTISER",
        "METRIC_PROFIT_ADVERTISER","METRIC_MEDIA_COST_ECPM_ADVERTISER",
        "METRIC_CPM_FEE1_ADVERTISER","METRIC_PLATFORM_FEE_ADVERTISER",
        "METRIC_CLIENT_COST_ADVERTISER_CURRENCY",
    }
    needs_currency = any(m in COST_METRICS for m in mets)
    if needs_currency and "FILTER_ADVERTISER_CURRENCY" not in dims:
        dims = dims + ["FILTER_ADVERTISER_CURRENCY"]

    # Garante que FILTER_DATE está sempre presente
    if "FILTER_DATE" not in dims:
        dims = ["FILTER_DATE"] + dims

    # Métricas de Unique Reach só funcionam com dimensões específicas
    REACH_METRICS = {m for m in mets if "UNIQUE_REACH" in m or "COOKIE_REACH" in m}
    STANDARD_METRICS = [m for m in mets if m not in REACH_METRICS]

    # Se tem métricas de Reach, remove dimensões incompatíveis
    if REACH_METRICS:
        REACH_INCOMPAT_DIMS = {
            "FILTER_CAMPAIGN","FILTER_INSERTION_ORDER","FILTER_LINE_ITEM",
            "FILTER_CREATIVE","FILTER_CREATIVE_ID","FILTER_APP_URL",
            "FILTER_SITE_ID","FILTER_EXCHANGE_ID","FILTER_KEYWORD",
        }
        reach_dims = [d for d in dims if d not in REACH_INCOMPAT_DIMS]
        if not reach_dims:
            reach_dims = ["FILTER_DATE","FILTER_ADVERTISER_NAME"]
        # FILTER_UNIQUE_REACH_SAMPLE_SIZE_ID é obrigatório para métricas de Unique Reach
        if "FILTER_UNIQUE_REACH_SAMPLE_SIZE_ID" not in reach_dims:
            reach_dims = reach_dims + ["FILTER_UNIQUE_REACH_SAMPLE_SIZE_ID"]
        mets_to_use = list(REACH_METRICS)
        dims_to_use = reach_dims
        use_advertiser_filter = True  # Reach pode usar filtro de advertiser
    else:
        mets_to_use = STANDARD_METRICS if STANDARD_METRICS else mets
        dims_to_use = dims
        use_advertiser_filter = True

    print(f"[DV360] dims_final={dims_to_use} | mets_final={mets_to_use}")

    headers = {"Authorization":f"Bearer {access_token}"}
    rows = []

    for acc in accounts:
        acc_id = acc["id"] if isinstance(acc,dict) else str(acc)
        print(f"[DV360] Buscando advertiser {acc_id} | {date_start} → {date_end}")
        ds=date_start.split("-"); de=date_end.split("-")
        body={
            "metadata":{
                "title":f"inflr_{int(_t.time())}",
                "dataRange":{
                    "range":"CUSTOM_DATES",
                    "customStartDate":{"year":int(ds[0]),"month":int(ds[1]),"day":int(ds[2])},
                    "customEndDate":{"year":int(de[0]),"month":int(de[1]),"day":int(de[2])}
                }
            },
            "params":{
                "type":"STANDARD",
                "groupBys":dims_to_use,
                "metrics":mets_to_use,
                "filters":[{"type":"FILTER_ADVERTISER","value":acc_id}] if use_advertiser_filter else []
            }
        }
        cr = requests.post(
            "https://doubleclickbidmanager.googleapis.com/v2/queries",
            headers=headers, json=body, timeout=30
        )
        print(f"[DV360] Create query status={cr.status_code} body={cr.text[:300]}")
        qid = cr.json().get("queryId")
        if not qid:
            print(f"[DV360] Sem queryId — pulando conta {acc_id}")
            continue

        # Roda o query
        run_r = requests.post(
            f"https://doubleclickbidmanager.googleapis.com/v2/queries/{qid}:run",
            headers=headers, json={}, timeout=30
        )
        print(f"[DV360] Run query status={run_r.status_code}")

        # Polling — até 50s (10 tentativas × 5s)
        for attempt in range(10):
            _t.sleep(5)
            rr = requests.get(
                f"https://doubleclickbidmanager.googleapis.com/v2/queries/{qid}/reports",
                headers=headers, timeout=15
            )
            reports = rr.json().get("reports",[])
            print(f"[DV360] Poll {attempt+1}: {len(reports)} reports, status={rr.status_code}")
            if not reports:
                continue
            state = reports[-1].get("metadata",{}).get("status",{}).get("state","")
            print(f"[DV360] Report state={state}")
            if state == "DONE":
                gcs_path = reports[-1].get("metadata",{}).get("googleCloudStoragePath","")
                if not gcs_path:
                    print("[DV360] Sem GCS path")
                    break
                csv_r = requests.get(gcs_path, timeout=30)
                csv_text = csv_r.text.strip()
                all_lines = csv_text.split("\n")
                print(f"[DV360] CSV total linhas={len(all_lines)} primeiras={all_lines[:3]}")

                import re
                # DV360 CSV tem metadados no topo — encontra a linha do header real
                # O header real começa com um campo de dimensão (não com "Report")
                header_idx = None
                for i, line in enumerate(all_lines):
                    stripped = line.strip().strip('"')
                    if stripped and not stripped.startswith("Report") and not stripped.startswith("Filter"):
                        header_idx = i
                        break

                if header_idx is None or header_idx >= len(all_lines) - 1:
                    print("[DV360] Não encontrou header real no CSV")
                    break

                lines = all_lines[header_idx:]
                print(f"[DV360] CSV dados linhas={len(lines)} (pulou {header_idx} linhas de metadados)")

                # Sanitiza headers para BigQuery (só letras, números e _)
                raw_hdrs = [h.strip().strip('"') for h in lines[0].split(",")]
                hdrs = [re.sub(r'[^a-zA-Z0-9_]', '_', h).strip('_').lower() or f"col_{i}"
                        for i, h in enumerate(raw_hdrs)]

                for line in lines[1:]:
                    if not line.strip() or line.strip().startswith("Total"):
                        continue  # pula linhas vazias e totais
                    vals = [v.strip().strip('"') for v in line.split(",")]
                    if len(vals) < len(hdrs):
                        continue  # pula linhas incompletas
                    row = dict(zip(hdrs, vals))
                    row["platform"] = "google dv360"
                    rows.append(row)
                break
            elif state == "FAILED":
                print(f"[DV360] Report FAILED: {reports[-1]}")
                break

    print(f"[DV360] Total linhas coletadas: {len(rows)}")
    return rows

def fetch_kwai(token, accounts, tbl, date_start, date_end):
    mets = tbl.get("metrics",["show","click","charge","avcpm","ctr"])
    breakdown = tbl.get("breakdown","campaign")
    level = {"campaign":"campaign","adgroup":"unit","ad":"creative"}.get(breakdown,"campaign")
    headers = {"Access-Token":token["access_token"]}
    rows = []
    for acc in accounts:
        acc_id = acc["id"] if isinstance(acc,dict) else str(acc)
        resp = requests.get(f"https://developers.kwai.com/rest/n/mapi/report/dsp/{level}/effectGet",
                            headers=headers,
                            params={"advertiser_id":acc_id,"start_date":date_start,"end_date":date_end,
                                    "time_granularity":"STAT_TIME_GRANULARITY_DAILY"})
        data = resp.json()
        if data.get("result") not in (None,1): raise Exception(f"Kwai API: {data.get('desc','unknown')}")
        for item in data.get("data",{}).get("details",[]):
            row={"date":item.get("date",""),"platform":"kwai","account_id":acc_id}
            for m in mets: row[m]=item.get(m)
            row["campaign_id"]=str(item.get("campaign_id","")); row["campaign_name"]=item.get("campaign_name","")
            if breakdown in ("adgroup","ad"): row["adset_id"]=str(item.get("unit_id","")); row["adset_name"]=item.get("unit_name","")
            rows.append(row)
    return rows
