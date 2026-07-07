import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id":os.environ["GOOGLE_CLIENT_ID"],
            "redirect_uri":os.environ["BASE_URL"]+"/api/oauth/dv360/callback",
            "scope":"https://www.googleapis.com/auth/display-video",
            "response_type":"code","access_type":"offline","prompt":"consent","state":"inflr"})
        self.send_response(302); self.send_header("Location",url); self.end_headers()
app = handler
