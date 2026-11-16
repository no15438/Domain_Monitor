"""Small localhost JSON adapter. No network clients, models, schedulers or env loader."""
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

from .store import Store

WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, store, **kwargs):
        self.store = store
        super().__init__(*args, **kwargs)

    def log_message(self, *_):
        pass

    def send(self, status, payload, content_type="application/json; charset=utf-8"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            # Reject DNS rebinding and cross-site mutations. Loopback only.
            if self.headers.get("Host", "").split(":")[0] not in ("localhost", "127.0.0.1"):
                return self.send(403,{"error":"localhost Host required"})
            origin = self.headers.get("Origin")
            if method == "POST" and origin and origin not in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
                return self.send(403,{"error":"cross-origin write rejected"})
            parsed = urlsplit(self.path)
            parts = parsed.path.strip("/").split("/")
            query = {k:v[-1] for k,v in parse_qs(parsed.query).items()}
            body = {}
            if method == "POST":
                if self.headers.get("Content-Type","").split(";")[0] != "application/json":
                    return self.send(415,{"error":"application/json required"})
                length = int(self.headers.get("Content-Length","0"))
                if not 0 < length <= 1_000_000:
                    return self.send(413,{"error":"JSON body must be 1..1000000 bytes"})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body,dict):
                    raise ValueError("JSON object required")
            if method == "GET" and parsed.path == "/":
                return self.send(200,WEB.read_bytes(),"text/html; charset=utf-8")
            if method == "GET" and parsed.path == "/health":
                return self.send(200,{"ok":True,"mode":"offline","schema_version":1})
            if parts == ["api","events"]:
                if method == "POST":
                    return self.send(201,self.store.create_event(**body))
                params = {k:query[k] for k in ("topic","valid_at","known_at") if k in query}
                return self.send(200,self.store.search(query.get("q",""),include_archived=query.get("include_archived")=="true",**params))
            if parts == ["api","evidence"] and method == "POST":
                return self.send(201,self.store.add_evidence(**body))
            if len(parts) == 4 and parts[:2] == ["api","events"]:
                event_id, action = parts[2:]
                params = {k:query[k] for k in ("valid_at","known_at") if k in query}
                if method == "GET" and action == "state":
                    return self.send(200,self.store.state(event_id,**params))
                if method == "GET" and action == "history":
                    return self.send(200,self.store.history(event_id,known_at=query.get("known_at")))
                if method == "POST" and action == "assertions":
                    return self.send(201,self.store.assert_fact(event_id,**body))
                if method == "POST" and action == "memory":
                    return self.send(200,self.store.set_memory(event_id,**body))
            self.send(404,{"error":"route not found"})
        except KeyError as exc:
            self.send(404,{"error":str(exc)})
        except (ValueError,TypeError,sqlite3.IntegrityError) as exc:
            self.send(400,{"error":str(exc)})
        except Exception:
            self.send(500,{"error":"internal error"})


def make_server(store: Store, port=8769):
    return ThreadingHTTPServer(("127.0.0.1",port),partial(Handler,store=store))
