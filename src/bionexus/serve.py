"""bn serve — the scientist's cockpit: approvals, campaign status, audit.

Local web app on stdlib http (no framework, no accounts, data stays on the
machine). Endpoints:

    GET  /              dashboard (pending approvals, recent provenance)
    POST /decide        form: id + approve|deny
    GET  /api/pending   JSON list of pending approvals (for scripts/agents)

Style: the same light-blueprint look as the diagrams.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from bionexus.approvals import DEFAULT_INBOX, ApprovalInbox

CSS = """
:root{--bg:#f3f1ea;--paper:#faf8f2;--line:#c9c2b0;--ink:#2a2823;--dim:#6b6558;
--green:#2f6b38;--red:#8a4034;--amber:#8a6a2c;--teal:#1f7a86;
--mono:'IBM Plex Mono',ui-monospace,Consolas,monospace;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;padding:40px 20px}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px} .sub{color:var(--dim);font-size:13px;margin:0 0 28px}
h2{font-size:13px;font-family:var(--mono);letter-spacing:.12em;text-transform:uppercase;
color:var(--dim);border-bottom:1px solid var(--line);padding-bottom:8px;margin:32px 0 14px}
.card{background:var(--paper);border:1px solid var(--line);padding:16px 18px;margin:10px 0}
.empty{color:var(--dim);font-size:14px;padding:14px;border:1px dashed var(--line);
background:var(--paper)}
form.inline{display:inline}
button{font:inherit;font-size:13px;padding:6px 16px;border-radius:4px;cursor:pointer;
border:1px solid var(--line);background:#fff;margin-right:8px}
button.ok{border-color:var(--green);color:var(--green)}
button.no{border-color:var(--red);color:var(--red)}
.mono{font-family:var(--mono);font-size:12px}
.badge{display:inline-block;font-family:var(--mono);font-size:10.5px;padding:2px 8px;
border-radius:999px;border:1px solid var(--line);color:var(--dim);margin-left:8px}
.pending{color:var(--amber);border-color:var(--amber)}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--paper);
border:1px solid var(--line)}
td,th{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}
th{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
color:var(--dim)}
"""


def render_dashboard(inbox: ApprovalInbox, db_path: str | None) -> str:
    pending = inbox.pending()
    rows = []
    for p in pending:
        rows.append(f"""
        <div class="card"><b>{_esc(p['title'])}</b>
          <span class="badge pending">pending</span>
          <div class="sub mono" style="margin:6px 0 10px">{_esc(p.get('detail',''))}</div>
          <form class="inline" method="post" action="/decide">
            <input type="hidden" name="id" value="{p['id']}">
            <button class="ok" name="action" value="approve">Approve</button>
            <button class="no" name="action" value="deny">Deny</button>
          </form>
        </div>""")
    approvals_html = "\n".join(rows) or \
        '<div class="empty">Nothing awaiting you. Campaigns in <span class="mono">gate</span> ' \
        'autonomy will pause here for your decision.</div>'

    prov_rows = ""
    if db_path:
        try:
            from bionexus.adapters.store.sqlite import SqliteProvenanceStore
            store = SqliteProvenanceStore(db_path)
            events = store.recent_records(15)
            prov_rows = "".join(
                f"<tr><td class='mono'>{r.event_type.value}</td>"
                f"<td class='mono'>{_esc(json.dumps(r.decision)[:90] if r.decision else '')}</td>"
                f"<td class='mono'>{r.record_hash[:10] if r.record_hash else ''}…</td></tr>"
                for r in events[:15])
            if not prov_rows:
                prov_rows = "<tr><td colspan=3 class='mono'>no records yet</td></tr>"
        except Exception:
            prov_rows = "<tr><td colspan=3>database unavailable</td></tr>"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="5">
<title>BioNexus — Cockpit</title><style>{CSS}</style></head><body><div class="wrap">
<h1>BioNexus</h1><p class="sub">the cockpit — approvals, decisions, audit.
Data never leaves this machine.</p>
<h2>Awaiting your decision ({len(pending)})</h2>
{approvals_html}
<h2>Recent provenance</h2>
<table><tr><th>event</th><th>detail</th><th>hash</th></tr>{prov_rows}</table>
</div></body></html>"""


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Handler(BaseHTTPRequestHandler):
    inbox: ApprovalInbox = None      # set via class attrs below
    db_path: str | None = None

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, render_dashboard(self.inbox, self.db_path))
        elif self.path == "/api/pending":
            self._send(200, json.dumps(self.inbox.pending(), indent=1),
                       "application/json")
        elif self.path == "/healthz":
            self._send(200, "ok", "text/plain")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path == "/decide":
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode())
            aid = (form.get("id") or [""])[0]
            action = (form.get("action") or [""])[0]
            if aid and action in ("approve", "deny"):
                self.inbox.decide(aid, action == "approve")
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self._send(404, "not found", "text/plain")


def serve(port: int = 8080, inbox: str = DEFAULT_INBOX,
          db_path: str | None = None) -> None:
    """Blocking: run the cockpit on http://127.0.0.1:{port}."""
    httpd = make_server(port, inbox, db_path)
    print(f"[bn serve] cockpit at http://127.0.0.1:{httpd.server_address[1]}/ "
          f"(inbox {inbox})")
    httpd.serve_forever()


def make_server(port: int = 8080, inbox: str = DEFAULT_INBOX,
                db_path: str | None = None) -> ThreadingHTTPServer:
    box = ApprovalInbox(inbox)
    handler = type("BoundHandler", (Handler,), {"inbox": box, "db_path": db_path})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    return httpd


def serve_in_thread(port: int = 0, inbox: str = DEFAULT_INBOX,
                    db_path: str | None = None) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """For tests/embedding: returns (server, thread); port 0 = ephemeral."""
    httpd = make_server(port, inbox, db_path)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, t
