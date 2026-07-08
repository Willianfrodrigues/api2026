import os, json, hashlib, secrets
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "inflr2024")

def check_credentials(user, password):
    return user == ADMIN_USER and password == ADMIN_PASS

def generate_token():
    return secrets.token_hex(32)

# Token simples em memória (reseta no redeploy — ok para uso interno)
VALID_TOKENS = set()

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()

        if "/api/auth/login" in path:
            user = body.get("user","")
            password = body.get("password","")
            if check_credentials(user, password):
                token = generate_token()
                VALID_TOKENS.add(token)
                self._j({"ok": True, "token": token})
            else:
                self._j({"ok": False, "error": "Usuário ou senha incorretos"}, 401)

        elif "/api/auth/logout" in path:
            token = body.get("token","")
            VALID_TOKENS.discard(token)
            self._j({"ok": True})

        elif "/api/auth/verify" in path:
            token = body.get("token","")
            self._j({"ok": token in VALID_TOKENS})

        else:
            self._j({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()

    def _body(self):
        n = int(self.headers.get("Content-Length",0))
        return json.loads(self.rfile.read(n)) if n else {}

    def _j(self, data, status=200):
        b = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(b)

app = handler
