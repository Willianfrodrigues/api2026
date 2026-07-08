"""
DV360 usa service account — não tem callback OAuth.
Este endpoint nunca é chamado mas precisa existir.
"""
import os
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        base_url = os.environ.get("BASE_URL","")
        self.send_response(302)
        self.send_header("Location", f"{base_url}/")
        self.end_headers()

app = handler
