import os,json,requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import save_token
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = parse_qs(urlparse(self.path).query).get("code",[None])[0]
        if not code: self._go("/?error=denied"); return
        r = requests.post("https://oauth2.googleapis.com/token",data={
            "code":code,"client_id":os.environ["GOOGLE_CLIENT_ID"],
            "client_secret":os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uri":os.environ["BASE_URL"]+"/api/oauth/dv360/callback","grant_type":"authorization_code"})
        tok = r.json()
        if "error" in tok: self._go(f"/?error={tok['error']}"); return
        hdrs = {"Authorization":f"Bearer {tok['access_token']}"}
        pid = os.environ.get("DV360_PARTNER_ID","")
        advs = requests.get(f"https://displayvideo.googleapis.com/v2/advertisers?partnerId={pid}",headers=hdrs).json().get("advertisers",[])
        save_token("dv360",{"access_token":tok["access_token"],"refresh_token":tok.get("refresh_token"),
            "account_ids":[{"id":str(a["advertiserId"]),"name":a["displayName"]} for a in advs]})
        self._go("/?connected=dv360")
    def _go(self,p):
        self.send_response(302); self.send_header("Location",os.environ["BASE_URL"]+p); self.end_headers()
app = handler
