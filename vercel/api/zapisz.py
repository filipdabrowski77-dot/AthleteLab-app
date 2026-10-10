"""POST /api/zapisz?plan=<token>[&ws=…] {ops:[…]} — wpisy z telefonu."""
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aph_api import obsluz_zapisz  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        obsluz_zapisz(self)

    def log_message(self, *a):
        pass
