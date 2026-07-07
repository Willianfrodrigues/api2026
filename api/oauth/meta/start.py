import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = "https://www.facebook.com/v19.0/dialog/oauth?" + urlencode({
            "client_id": os.environ["META_APP_ID"],
            "redirect_uri": os.environ["BASE_URL"]+"/api/oauth/meta/callback",
            "scope": "ads_read,ads_management,business_management",
            "response_type": "code","state":"inflr"})
        self.send_response(302); self.send_header("Location",url); self.end_headers()
app = handler
