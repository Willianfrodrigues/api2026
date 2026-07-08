import os
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import (
    get_logs_by_transfer,
    list_tokens, delete_token,
    save_destination, list_destinations, delete_destination, test_bq_connection,
    save_table_group, list_table_groups, delete_table_group,
    save_table, list_tables, delete_table,
    save_transfer, list_transfers, get_transfer_full, delete_transfer,
    get_logs
)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        qs   = parse_qs(urlparse(self.path).query)
        if "/api/connections"  in path: self._j(list_tokens())
        elif "/api/destinations" in path: self._j(list_destinations())
        elif "/api/tablegroups"  in path: self._j(list_table_groups(qs.get("platform",[""])[0] or None))
        elif "/api/tables"       in path: self._j(list_tables(int(qs.get("group_id",[0])[0])) if qs.get("group_id") else [])
        elif "/api/transfers"    in path:
            tid = qs.get("id",[""])[0]
            self._j(get_transfer_full(int(tid)) if tid else list_transfers())
        elif "/api/logs"         in path:
            tid = qs.get('transfer_id',[''])[0]
            self._j(get_logs_by_transfer(int(tid),30) if tid else get_logs(300))
        else: self._j({"error":"not found"},404)

    def do_POST(self):
        body = self._body()
        path = urlparse(self.path).path
        if "/api/destinations/test" in path:
            ok, msg = test_bq_connection(body["service_account"], body["bq_project"], body["bq_dataset"])
            self._j({"ok":ok,"message":msg})
        elif "/api/destinations" in path: save_destination(body); self._j({"ok":True})
        elif "/api/tablegroups"  in path: self._j({"ok":True,"id":save_table_group(body)})
        elif "/api/tables"       in path: self._j({"ok":True,"id":save_table(body)})
        elif "/api/transfers"    in path: self._j({"ok":True,"id":save_transfer(body)})
        else: self._j({"error":"not found"},404)

    def do_PATCH(self):
        body = self._body()
        path = urlparse(self.path).path
        if "/api/destinations" in path: save_destination(body); self._j({"ok":True})
        elif "/api/tables"     in path: save_table(body); self._j({"ok":True})
        elif "/api/transfers"  in path: save_transfer(body); self._j({"ok":True})
        else: self._j({"error":"not found"},404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        qs   = parse_qs(urlparse(self.path).query)
        if "/api/connections"  in path: delete_token(qs.get("platform",[""])[0])
        elif "/api/destinations" in path: delete_destination(int(qs.get("id",[0])[0]))
        elif "/api/tablegroups"  in path: delete_table_group(int(qs.get("id",[0])[0]))
        elif "/api/tables"       in path: delete_table(int(qs.get("id",[0])[0]))
        elif "/api/transfers"    in path: delete_transfer(int(qs.get("id",[0])[0]))
        self._j({"ok":True})

    def do_OPTIONS(self):
        self.send_response(204)
        for h,v in [("Access-Control-Allow-Origin","*"),
                    ("Access-Control-Allow-Methods","GET,POST,PATCH,DELETE,OPTIONS"),
                    ("Access-Control-Allow-Headers","Content-Type")]:
            self.send_header(h,v)
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
