import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = "https://business-api.tiktok.com/portal/auth?" + urlencode({
            "app_id":os.environ["TIKTOK_APP_ID"],
            "redirect_uri":os.environ["BASE_URL"]+"/api/oauth/tiktok/callback",
            "scope":"campaign.read,adgroup.read,ad.read,report.read",
            "response_type":"code","state":"inflr"})
        self.send_response(302); self.send_header("Location",url); self.end_headers()
app = handler
