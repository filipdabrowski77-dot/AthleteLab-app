"""GET /api/plan?plan=<token>[&ws=…] — plan zawodnika dla strony."""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aph_api import obsluz_plan  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        obsluz_plan(self)

    def log_message(self, *a):   # Vercel loguje sam
        pass
