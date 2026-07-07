import os,json,requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
import sys; sys.path.insert(0,".")
from _helpers import save_token
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = parse_qs(urlparse(self.path).query).get("code",[None])[0]
        if not code: self._go("/?error=denied"); return
        r = requests.post("https://graph.facebook.com/v19.0/oauth/access_token",params={
            "client_id":os.environ["META_APP_ID"],"client_secret":os.environ["META_APP_SECRET"],
            "redirect_uri":os.environ["BASE_URL"]+"/api/oauth/meta/callback","code":code})
        d = r.json()
        if "error" in d: self._go(f"/?error={d['error']['message']}"); return
        tok = d["access_token"]
        accs = requests.get("https://graph.facebook.com/v19.0/me/adaccounts",
            params={"access_token":tok,"fields":"id,name,account_status","limit":200}).json().get("data",[])
        save_token("meta",{"access_token":tok,"account_ids":accs})
        self._go("/?connected=meta")
    def _go(self,p):
        self.send_response(302); self.send_header("Location",os.environ["BASE_URL"]+p); self.end_headers()
app = handler
