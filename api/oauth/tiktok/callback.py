import os,json,requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
import sys; sys.path.insert(0,".")
from _helpers import save_token
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = parse_qs(urlparse(self.path).query).get("auth_code",[None])[0]
        if not code: self._go("/?error=denied"); return
        r = requests.post("https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",json={
            "app_id":os.environ["TIKTOK_APP_ID"],"secret":os.environ["TIKTOK_APP_SECRET"],
            "auth_code":code,"grant_type":"authorization_code"})
        d = r.json()
        if d.get("code",0)!=0: self._go(f"/?error={d.get('message')}"); return
        info = d["data"]
        save_token("tiktok",{"access_token":info["access_token"],
            "account_ids":[{"id":str(a),"name":str(a)} for a in info.get("advertiser_ids",[])]})
        self._go("/?connected=tiktok")
    def _go(self,p):
        self.send_response(302); self.send_header("Location",os.environ["BASE_URL"]+p); self.end_headers()
app = handler
