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
        slot_time = body.get("slot_time")  # "HH:MM" — se omitido usa o primeiro slot

        if tid:
            transfers = [get_transfer_full(tid)]
        else:
            transfers = [get_transfer_full(t["id"]) for t in list_transfers() if t["active"]]

        results = []
        for tr in transfers:
            if not tr: continue
            # Determina qual slot executar
            slots = tr.get("slots") or [{"time":"00:00","window":3,"type":"daily"}]
            slot = next((s for s in slots if s.get("time")==slot_time), slots[0]) if slot_time else slots[0]
            results.append(run_transfer(tr, slot))

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

def run_transfer(tr, slot):
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

    # Janela de datas baseada no slot
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
            rows = fetch_platform(platform, token, accounts, tbl, date_start, date_end)
            n = upsert_bq(bq, tr["bq_project"], tr["bq_dataset"], tbl["bq_table"], rows)
            ms = int((time.time()-t1)*1000)
            total_rows += n
            add_log(tid, tbl["bq_table"], slot.get("time","—"), "ok", n, None, ms)
            table_results.append({"table":tbl["bq_table"],"rows":n,"status":"ok"})
        except Exception as e:
            ms = int((time.time()-t1)*1000)
            add_log(tid, tbl["bq_table"], slot.get("time","—"), "error", 0, str(e), ms)
            table_results.append({"table":tbl["bq_table"],"status":"error","error":str(e)})

    status = "ok" if all(r["status"]=="ok" for r in table_results) else "partial"
    update_transfer_run(tid, status, total_rows)
    return {"transfer_id":tid,"status":status,"total_rows":total_rows,
            "tables":table_results,"duration_ms":int((time.time()-t0)*1000)}

# ── FETCHERS ─────────────────────────────────────────────────────────────────

def fetch_platform(platform, token, accounts, tbl, date_start, date_end):
    return {"meta":fetch_meta,"tiktok":fetch_tiktok,"dv360":fetch_dv360,"kwai":fetch_kwai}[platform](
        token, accounts, tbl, date_start, date_end)

def fetch_meta(token, accounts, tbl, date_start, date_end):
    dims = tbl.get("dimensions",[])
    mets = tbl.get("metrics",[])
    breakdown = tbl.get("breakdown","campaign")
    level = {"campaign":"campaign","adgroup":"adset","ad":"ad"}.get(breakdown,"campaign")
    api_fields = list(dict.fromkeys([f for f in dims+mets if f not in ("account_id","account_name")]))
    breakdown_dims = [d for d in dims if d in ("age","gender","country","region","publisher_platform","platform_position","impression_device")]
    rows = []
    for acc in accounts:
        acc_id = acc["id"] if isinstance(acc,dict) else str(acc)
        acc_name = acc.get("name","") if isinstance(acc,dict) else ""
        params = {"access_token":token["access_token"],"level":level,
                  "fields":",".join(api_fields) if api_fields else "impressions,spend,clicks",
                  "time_range":json.dumps({"since":date_start,"until":date_end}),
                  "time_increment":1,"limit":500}
        if breakdown_dims: params["breakdowns"] = ",".join(breakdown_dims)
        resp = requests.get(f"https://graph.facebook.com/v19.0/{acc_id}/insights", params=params)
        data = resp.json()
        if "error" in data: raise Exception(f"Meta API: {data['error']['message']}")
        for d in data.get("data",[]):
            row = {"date":d.get("date_start",""),"platform":"facebook ads","account_id":acc_id,"account_name":acc_name}
            for f in api_fields:
                v = d.get(f)
                if isinstance(v,list) and v and isinstance(v[0],dict): row[f] = float(v[0].get("value",0))
                elif v is not None:
                    try: row[f] = float(v)
                    except: row[f] = v
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
    headers = {"Authorization":f"Bearer {token['access_token']}"}
    rows = []
    import time as _t
    for acc in accounts:
        acc_id = acc["id"] if isinstance(acc,dict) else str(acc)
        ds=date_start.split("-"); de=date_end.split("-")
        body={"metadata":{"title":f"inflr_{int(_t.time())}","dataRange":{"range":"CUSTOM_DATES",
              "customStartDate":{"year":int(ds[0]),"month":int(ds[1]),"day":int(ds[2])},
              "customEndDate":{"year":int(de[0]),"month":int(de[1]),"day":int(de[2])}}},
              "params":{"type":"STANDARD","groupBys":dims,"metrics":mets,
              "filters":[{"type":"FILTER_ADVERTISER","value":acc_id}]}}
        cr=requests.post("https://doubleclickbidmanager.googleapis.com/v2/queries",headers=headers,json=body)
        qid=cr.json().get("queryId")
        if not qid: continue
        for _ in range(15):
            _t.sleep(4)
            rr=requests.get(f"https://doubleclickbidmanager.googleapis.com/v2/queries/{qid}/reports",headers=headers)
            reports=rr.json().get("reports",[])
            if reports and reports[-1].get("metadata",{}).get("status",{}).get("state")=="DONE":
                lines=requests.get(reports[-1]["metadata"]["googleCloudStoragePath"]).text.strip().split("\n")
                if len(lines)<2: break
                hdrs=lines[0].split(",")
                for line in lines[1:]:
                    row=dict(zip(hdrs,line.split(","))); row["platform"]="google dv360"; rows.append(row)
                break
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
