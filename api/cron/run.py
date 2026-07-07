import os
"""
inflr pipe — Cron endpoint
Pode ser chamado por qualquer scheduler externo (cron-job.org, EasyCron, etc.)
ou pelo cron diário do Vercel Hobby (uma vez por dia às 00:00 BRT).

Proteção: Bearer token via CRON_SECRET no header Authorization.

Quando chamado com ?slot=HH:MM executa só aquele slot.
Quando chamado sem parâmetro, executa todos os slots que batem com o
horário atual (BRT = UTC-3), permitindo múltiplas chamadas por dia
via scheduler externo.
"""
import json, os, sys, requests
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import get_active_transfers_for_slot

BRT = timedelta(hours=-3)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Autenticação
        secret = os.environ.get("CRON_SECRET", "")
        auth   = self.headers.get("Authorization", "")
        if secret and auth != f"Bearer {secret}":
            self._j({"error": "unauthorized"}, 401)
            return

        qs = parse_qs(urlparse(self.path).query)
        slot_override = qs.get("slot", [None])[0]  # ex: ?slot=08:00

        now_brt   = datetime.now(timezone.utc) + BRT
        slot_time = slot_override or now_brt.strftime("%H:00")

        transfers = get_active_transfers_for_slot(slot_time)

        if not transfers:
            self._j({"slot": slot_time, "fired": 0, "message": "Nenhum transfer neste horário"})
            return

        base_url = os.environ.get("BASE_URL", "")
        results  = []
        for tr in transfers:
            try:
                resp = requests.post(
                    f"{base_url}/api/sync",
                    json={"transfer_id": tr["id"], "slot_time": slot_time},
                    timeout=55
                )
                results.append({"transfer_id": tr["id"], "name": tr["name"],
                                 "status": "fired", "http": resp.status_code})
            except Exception as e:
                results.append({"transfer_id": tr["id"], "name": tr["name"],
                                 "status": "error", "error": str(e)})

        self._j({"slot": slot_time, "fired": len(results), "results": results})

    def _j(self, data, status=200):
        b = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

app = handler
