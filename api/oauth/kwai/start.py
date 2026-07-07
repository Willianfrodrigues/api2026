import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = "https://developers.kwai.com/oauth/authorize?" + urlencode({
            "app_id":os.environ["KWAI_APP_ID"],
            "redirect_uri":os.environ["BASE_URL"]+"/api/oauth/kwai/callback",
            "response_type":"code","scope":"ADVERTISER_INFO,REPORT_DATA","state":"inflr"})
        self.send_response(302); self.send_header("Location",url); self.end_headers()
app = handler
