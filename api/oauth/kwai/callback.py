import os,json,requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
import sys; sys.path.insert(0,".")
from _helpers import save_token
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = parse_qs(urlparse(self.path).query).get("code",[None])[0]
        if not code: self._go("/?error=denied"); return
        r = requests.post("https://developers.kwai.com/oauth/token",json={
            "app_id":os.environ["KWAI_APP_ID"],"app_secret":os.environ["KWAI_APP_SECRET"],
            "code":code,"grant_type":"authorization_code",
            "redirect_uri":os.environ["BASE_URL"]+"/api/oauth/kwai/callback"})
        d = r.json()
        save_token("kwai",{"access_token":d["access_token"],
            "account_ids":[{"id":str(a),"name":str(a)} for a in d.get("advertiser_ids",[])]})
        self._go("/?connected=kwai")
    def _go(self,p):
        self.send_response(302); self.send_header("Location",os.environ["BASE_URL"]+p); self.end_headers()
app = handler
