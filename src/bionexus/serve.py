"""bn serve — the scientist workbench.

Everything a non-coding scientist does, through one local web page:

  /            workbench: pending approvals, running campaigns, quick links
  /read        analyze an instrument export (table + fitted curves + CSV download)
  /campaigns   start a campaign from a template (form), watch its status
  /diary/<b>   provenance as a lab-notebook narrative
  /report/<b>  tamper-evident audit report
  /decide      approve/deny (the gate)

Stdlib http.server only; data never leaves the machine.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bionexus.approvals import DEFAULT_INBOX, ApprovalInbox
from bionexus.paths import CAMPAIGN_DIR, EXPORT_DIR, ensure_dirs

CSS = """
:root{--bg:#f3f1ea;--paper:#faf8f2;--line:#c9c2b0;--ink:#2a2823;--dim:#6b6558;
--green:#2f6b38;--red:#8a4034;--amber:#8a6a2c;--teal:#1f7a86;
--mono:'IBM Plex Mono',ui-monospace,Consolas,monospace;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;padding:36px 20px}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:22px;margin:0 0 2px}
.nav{margin:0 0 26px;font-size:13px}
.nav a{color:var(--teal);text-decoration:none;margin-right:16px}
h2{font-size:12.5px;font-family:var(--mono);letter-spacing:.12em;text-transform:uppercase;
color:var(--dim);border-bottom:1px solid var(--line);padding-bottom:8px;margin:30px 0 12px}
.card{background:var(--paper);border:1px solid var(--line);padding:14px 16px;margin:10px 0}
button,.btn{font:inherit;font-size:13px;padding:6px 14px;border-radius:4px;cursor:pointer;
border:1px solid var(--line);background:#fff;text-decoration:none;color:var(--ink);display:inline-block}
button.ok{border-color:var(--green);color:var(--green)}
button.no{border-color:var(--red);color:var(--red)}
input,select,textarea{font:inherit;font-size:13px;padding:7px 9px;border:1px solid var(--line);
background:#fff;width:100%;margin:4px 0 10px;border-radius:4px}
label{font-size:12px;color:var(--dim);font-family:var(--mono);text-transform:uppercase;letter-spacing:.06em}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--paper);border:1px solid var(--line)}
td,th{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left}
th{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim)}
.mono{font-family:var(--mono);font-size:12px}
.run{color:var(--green);font-weight:600}.pend{color:var(--amber);font-weight:600}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
"""


def _esc(s: str) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _page(title: str, body: str, refresh: int | None = None) -> str:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    nav = ('<div class="nav"><a href="/">workbench</a><a href="/read">read results</a>'
           '<a href="/campaigns">campaigns</a><a href="/diary">diary</a></div>')
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'>{meta}"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>BioNexus — {_esc(title)}</title><style>{CSS}</style></head>"
            f"<body><div class='wrap'><h1>BioNexus</h1>{nav}{body}</div></body></html>")


# ------------------------------------------------------------------- state

def campaign_index() -> dict:
    f = CAMPAIGN_DIR / "index.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_campaign_index(idx: dict) -> None:
    CAMPAIGN_DIR.mkdir(parents=True, exist_ok=True)
    (CAMPAIGN_DIR / "index.json").write_text(json.dumps(idx, indent=1))


def campaign_running(meta: dict) -> bool:
    pid = meta.get("pid")
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ pages

def page_home(inbox: ApprovalInbox, db_path: str | None) -> str:
    pending = inbox.pending()
    rows = "".join(
        f"<div class='card'><b>{_esc(p['title'])}</b> <span class='pend'>awaiting you</span>"
        f"<div style='margin-top:8px'>"
        f"<form class='inline' method='post' action='/decide' style='display:inline'>"
        f"<input type='hidden' name='id' value='{p['id']}'>"
        f"<button class='ok' name='action' value='approve'>Approve</button></form>"
        f"<form method='post' action='/decide' style='display:inline'>"
        f"<input type='hidden' name='id' value='{p['id']}'>"
        f"<button class='no' name='action' value='deny'>Deny</button></form></div></div>"
        for p in pending) or "<p class='mono' style='color:#6b6558'>nothing pending</p>"
    idx = campaign_index()
    crows = "".join(
        f"<tr><td class='mono'><a href='/campaigns/{_esc(cid)}'>{_esc(cid)}</a></td>"
        f"<td>{'&#9679; running' if campaign_running(m) else 'finished'} </td>"
        f"<td class='mono'>{_esc(m.get('autonomy',''))}</td>"
        f"<td class='mono'>{_esc(m.get('objective','')[:60])}</td></tr>"
        for cid, m in list(idx.items())[-10:][::-1])
    recent = ""
    if db_path and Path(db_path).exists():
        try:
            from bionexus.adapters.store.sqlite import SqliteProvenanceStore
            ev = SqliteProvenanceStore(db_path).recent_records(10)
            recent = "".join(
                f"<tr><td class='mono'>{_esc(r.event_type.value)}</td>"
                f"<td class='mono'>{_esc(json.dumps(r.decision)[:80] if r.decision else '')}</td></tr>"
                for r in ev)
        except Exception:
            recent = ""
    return _page("workbench", f"""
<h2>Awaiting your decision ({len(pending)})</h2>{rows}
<h2>Campaigns</h2>
<table><tr><th>id</th><th>status</th><th>autonomy</th><th>objective</th></tr>{crows or
'<tr><td colspan=4 class="mono">none started yet — <a href="/campaigns">start one</a></td></tr>'}</table>
<h2>Recent provenance</h2>
<table><tr><th>event</th><th>detail</th></tr>{recent or '<tr><td colspan=2 class="mono">no records yet</td></tr>'}</table>
""", refresh=5)


def page_read_form() -> str:
    return _page("read results", """
<h2>Analyze an instrument export</h2>
<form method="post" action="/read">
<label>path to file on this machine (csv/tsv/xlsx/npy)</label>
<input name="path" placeholder="/path/to/synergy_export.csv" required>
<label>known maximal response (optional, for IC50 vs fixed max)</label>
<input name="max_response" placeholder="e.g. 600">
<button>Read &amp; analyze</button>
</form>""")


def page_read_result(result, path: str) -> str:
    svg = ""
    for sample, r in list(result.analysis["compounds"].items())[:6]:
        if r.get("ic50_um") is not None or r["n_points"] > 1:
            svg += f"<div style='margin:14px 0'>{result.curve_svg(sample)}</div>"
    export_name = f"{Path(path).stem}_export.csv"
    result.to_csv(EXPORT_DIR / export_name)
    return _page("results", f"""
<h2>{_esc(Path(path).name)}</h2>
<div class="card mono">{_esc(str(result))}</div>
{svg}
<p><a class="btn" href="/export/{_esc(export_name)}">download CSV (Excel-ready)</a></p>""")


def page_campaign(cid: str, meta: dict) -> str:
    running = campaign_running(meta)
    log_path = Path(meta.get("log", ""))
    tail_lines = 120
    if log_path.exists():
        lines = log_path.read_text(errors="replace").splitlines()[-tail_lines:]
        log_html = "\n".join(_esc(ln) for ln in lines) or "(empty so far)"
    else:
        log_html = "(no log written yet)"
    status = ("&#9679; running" if running else "finished")
    return _page(f"campaign {cid}", f"""
<h2>Campaign <span class="mono">{_esc(cid)}</span> — {status}</h2>
<p class="mono">autonomy: {_esc(meta.get('autonomy', ''))} ·
objective: {_esc(meta.get('objective', '')[:80])}</p>
<h3>Live activity</h3>
<pre class="mono" style="background:#f6f4ee;padding:12px;border-radius:6px;
overflow:auto;max-height:60vh">{log_html}</pre>
<p><a class="btn" href="/campaigns">all campaigns</a>
<a class="btn" href="/diary">diary</a></p>""", refresh=3 if running else None)


def page_campaigns_form() -> str:
    from bionexus.templates import list_templates
    opts = "".join(f"<option value='{t['name']}'>{t['name']} — {_esc(t['description'])}</option>"
                   for t in list_templates())
    return _page("campaigns", f"""
<h2>Start a campaign</h2>
<form method="post" action="/campaigns">
<label>template</label><select name="template">{opts}</select>
<label>compounds (comma-separated)</label><input name="compounds" required>
<label>potency threshold (uM)</label><input name="threshold" value="20">
<label>how much may the agent do?</label>
<select name="autonomy"><option value="gate">gate — I approve each experiment</option>
<option value="observe">observe — analysis only</option>
<option value="act">act — autonomous within safety rules</option></select>
<button>Start campaign</button></form>
<table><tr><th>id</th><th>status</th><th>autonomy</th><th>objective</th></tr>
{''.join(f"<tr><td class='mono'><a href='/campaigns/{_esc(cid)}'>{_esc(cid)}</a></td><td>{'&#9679; running' if campaign_running(m) else 'finished'}</td><td class='mono'>{_esc(m.get('autonomy',''))}</td><td class='mono'>{_esc(m.get('objective','')[:60])}</td></tr>" for cid, m in campaign_index().items())}
</table>""")


def page_diary(db_path: str | None, branch: str | None) -> str:
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.diary import build_diary_html
    if not db_path or not Path(db_path).exists():
        return _page("diary", "<p>no provenance database yet</p>")
    store = SqliteProvenanceStore(db_path)
    branches = [b for b in store.branches() if b.startswith(("problem/", "campaign-root",
                "branch-root", "case-study", "blind-paper", "autonomous"))]
    if not branch:
        opts = "".join(f"<div class='card'><a class='mono' href='/diary/{_esc(b)}'>{_esc(b)}</a></div>"
                       for b in branches) or "<p>nothing yet — run a campaign first</p>"
        return _page("diary", f"<h2>Campaign diaries</h2>{opts}")
    recs = store.branch_records(branch)
    from bionexus.diary import _CSS as DIARY_CSS
    inner = (build_diary_html(recs, branch)
             .split("<body><div class=\"wrap\">", 1)[-1]
             .split("</div></body></html>", 1)[0])
    return _page("diary", f"<style>{DIARY_CSS}</style>{inner}")


# ------------------------------------------------------------------ server

class Handler(BaseHTTPRequestHandler):
    inbox: ApprovalInbox
    db_path: str | None = None

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _form(self):
        length = int(self.headers.get("Content-Length", 0))
        return parse_qs(self.rfile.read(length).decode())

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, page_home(self.inbox, self.db_path))
        elif path == "/read":
            self._send(200, page_read_form())
        elif path == "/campaigns":
            self._send(200, page_campaigns_form())
        elif path.startswith("/campaigns/"):
            cid = path[len("/campaigns/"):]
            meta = campaign_index().get(cid)
            if meta:
                self._send(200, page_campaign(cid, meta))
            else:
                self._send(404, "unknown campaign", "text/plain")
        elif path == "/diary":
            self._send(200, page_diary(self.db_path, None))
        elif path.startswith("/diary/"):
            self._send(200, page_diary(self.db_path, path[len("/diary/"):]))
        elif path.startswith("/export/"):
            f = EXPORT_DIR / Path(path).name
            if f.exists():
                self._send(200, f.read_bytes(), "text/csv")
            else:
                self._send(404, "gone", "text/plain")
        elif path == "/api/pending":
            self._send(200, json.dumps(self.inbox.pending(), indent=1), "application/json")
        elif path == "/healthz":
            self._send(200, "ok", "text/plain")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        path = urlparse(self.path).path
        form = self._form()
        if path == "/decide":
            aid = (form.get("id") or [""])[0]
            action = (form.get("action") or [""])[0]
            if aid and action in ("approve", "deny"):
                self.inbox.decide(aid, action == "approve")
            self._redirect("/")
        elif path == "/read":
            from bionexus.labread import read_plate
            f = (form.get("path") or [""])[0]
            try:
                mr = (form.get("max_response") or [""])[0]
                result = read_plate(f, max_response=float(mr) if mr else None)
                self._send(200, page_read_result(result, f))
            except Exception as exc:
                self._send(400, _page("error", f"<div class='card'>could not read: {_esc(exc)}</div>"))
        elif path == "/campaigns":
            self._start_campaign(form)
        else:
            self._send(404, "not found", "text/plain")

    def _redirect(self, loc):
        self.send_response(303)
        self.send_header("Location", loc)
        self.end_headers()

    def _start_campaign(self, form):
        from bionexus.templates import build_campaign, fill, load_template
        tpl = (form.get("template") or ["dose-response-screen"])[0]
        fields = {"compounds": (form.get("compounds") or [""])[0],
                  "threshold": (form.get("threshold") or ["20"])[0]}
        autonomy = (form.get("autonomy") or ["gate"])[0]
        cfg = build_campaign(fill(load_template(tpl), fields, prompt_missing=False))
        cfg["autonomy"] = autonomy
        ensure_dirs()
        import uuid as _uuid
        cid = f"cmp-{int(time.time())}-{_uuid.uuid4().hex[:4]}"
        cfgpath = CAMPAIGN_DIR / f"{cid}.json"
        cfgpath.write_text(json.dumps(cfg, indent=1))
        log = open(CAMPAIGN_DIR / f"{cid}.log", "ab", buffering=0)
        proc = subprocess.Popen(
            [sys.executable, "-m", "bionexus.cli", "auto", str(cfgpath),
             "--db", self.db_path or "bionexus.db", "--inbox", str(self.inbox.path),
             "--yes"],
            stdout=log, stderr=subprocess.STDOUT, cwd=str(Path.cwd()))
        idx = campaign_index()
        idx[cid] = {"pid": proc.pid, "autonomy": autonomy,
                    "objective": cfg["problem"]["objective"], "log": str(log.name)}
        save_campaign_index(idx)
        try:  # one registry: the experiment also lands in the wizard store
            from bionexus.wizard_store import WizardStore
            WizardStore().register_agent(
                cid, cfg["problem"]["objective"], str(log.name),
                autonomy=autonomy, pid=proc.pid)
        except Exception:
            pass
        self._redirect("/")


def make_server(port: int, inbox: str, db_path: str | None) -> ThreadingHTTPServer:
    box = ApprovalInbox(inbox)
    handler = type("H", (Handler,), {"inbox": box, "db_path": db_path})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(port: int = 8080, inbox: str = DEFAULT_INBOX, db_path: str | None = None) -> None:
    ensure_dirs()
    httpd = make_server(port, inbox, db_path)
    print(f"[bn serve] workbench at http://127.0.0.1:{httpd.server_address[1]}/")
    httpd.serve_forever()


def serve_in_thread(port: int = 0, inbox: str = DEFAULT_INBOX,
                    db_path: str | None = None):
    httpd = make_server(port, inbox, db_path)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, t
