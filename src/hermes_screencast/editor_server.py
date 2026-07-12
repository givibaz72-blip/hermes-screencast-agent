from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hermes_screencast.editor import (
    ProjectEditConflictError,
    read_editor_project,
    save_editor_project,
)


MAX_REQUEST_BYTES = 2 * 1024 * 1024


def create_editor_server(
    project_directory: str | Path,
    *, host: str = "127.0.0.1", port: int = 0,
) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Hermes editor server must bind to a loopback host")
    root = Path(project_directory).expanduser().resolve()
    read_editor_project(root)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/":
                self._send(200, EDITOR_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/project":
                self._json(200, read_editor_project(root).to_dict())
            else:
                self._json(404, {"error": "not_found"})

        def do_PUT(self) -> None:
            if urlsplit(self.path).path != "/api/project":
                self._json(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._json(413, {"error": "request_too_large"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Editor update must be an object")
                snapshot = save_editor_project(
                    root, composition=payload["composition"],
                    timeline=payload["timeline"], expected_etag=payload["etag"],
                )
            except ProjectEditConflictError as exc:
                self._json(409, {"error": "conflict", "message": str(exc)})
                return
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._json(400, {"error": "invalid_request", "message": str(exc)})
                return
            self._json(200, snapshot.to_dict())

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(
                status,
                (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


EDITOR_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hermes Editor</title><style>
:root{font-family:Inter,system-ui,sans-serif;color:#e5e7eb;background:#09090b}*{box-sizing:border-box}body{margin:0}header{height:64px;padding:0 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #27272a;background:#111113}h1{font-size:18px;margin:0}.meta{color:#a1a1aa;font-size:12px}button{border:0;border-radius:8px;padding:10px 16px;background:#7c3aed;color:white;font-weight:700;cursor:pointer}main{display:grid;grid-template-columns:minmax(360px,1fr) 320px;gap:20px;padding:20px}.stage-card,.panel,.timeline{background:#151518;border:1px solid #29292e;border-radius:14px}.stage-card{padding:18px}.stage{aspect-ratio:16/9;border-radius:10px;display:grid;place-items:center;box-shadow:0 20px 60px #0008;overflow:hidden}.screen{width:82%;height:78%;background:#f4f4f5;border-radius:8px;box-shadow:0 16px 35px #0008}.panel{padding:18px}.panel h2,.timeline h2{font-size:14px;margin:0 0 16px}.field{display:flex;align-items:center;justify-content:space-between;margin:14px 0;color:#d4d4d8;font-size:13px}input[type=color]{width:48px;height:32px;border:0;background:none}.timeline{grid-column:1/-1;padding:18px}.track{display:grid;grid-template-columns:150px 1fr;gap:12px;align-items:center;margin:10px 0}.track-name{font-size:12px;color:#d4d4d8}.lane{height:30px;border-radius:6px;background:#232329;position:relative;overflow:hidden}.segment{position:absolute;top:4px;height:22px;min-width:4px;border-radius:5px;background:#8b5cf6}.status{font-size:12px;color:#a1a1aa;margin-top:12px}@media(max-width:800px){main{grid-template-columns:1fr}.timeline{grid-column:auto}}
</style></head><body><header><div><h1>Hermes Editor</h1><div class="meta" id="title">Loading…</div></div><button id="save">Save project</button></header><main><section class="stage-card"><div class="stage" id="stage"><div class="screen"></div></div></section><aside class="panel"><h2>Composition</h2><label class="field">Background <input id="background" type="color"></label><div class="field"><span>Canvas</span><span id="canvas"></span></div><div class="field"><span>Preset</span><span id="preset"></span></div><div class="status" id="status">Loading project…</div></aside><section class="timeline"><h2>Timeline</h2><div id="tracks"></div></section></main><script>
let snapshot=null;const colors=['#8b5cf6','#06b6d4','#f59e0b','#ef4444'];
async function load(){const r=await fetch('/api/project');snapshot=await r.json();render()}
function duration(){let d=1;for(const t of snapshot.project.timeline.tracks){if(t.summary?.estimated_duration_seconds)d=Math.max(d,t.summary.estimated_duration_seconds);for(const s of t.segments||[])d=Math.max(d,s.end_seconds||s.arrival_seconds||0)}return d}
function render(){const p=snapshot.project,c=p.composition,canvas=c.canvas;document.querySelector('#title').textContent=p.title+' · '+snapshot.etag.slice(0,10);document.querySelector('#canvas').textContent=canvas.width+' × '+canvas.height;document.querySelector('#preset').textContent=c.preset;const bg=c.background.type==='color'?c.background.value:'#111827';document.querySelector('#background').value=bg;document.querySelector('#stage').style.background=bg;const tracks=document.querySelector('#tracks');tracks.replaceChildren();const total=duration();p.timeline.tracks.forEach((t,i)=>{const row=document.createElement('div');row.className='track';const name=document.createElement('div');name.className='track-name';name.textContent=t.type;const lane=document.createElement('div');lane.className='lane';(t.segments||[]).forEach(s=>{const start=s.start_seconds||0,end=s.end_seconds||s.arrival_seconds||start+.05;const bar=document.createElement('div');bar.className='segment';bar.style.left=(start/total*100)+'%';bar.style.width=(Math.max(.01,end-start)/total*100)+'%';bar.style.background=colors[i%colors.length];lane.append(bar)});row.append(name,lane);tracks.append(row)});document.querySelector('#status').textContent='Loaded safely'}
document.querySelector('#background').addEventListener('input',e=>{snapshot.project.composition.background={type:'color',value:e.target.value.toUpperCase()};document.querySelector('#stage').style.background=e.target.value;document.querySelector('#status').textContent='Unsaved changes'});
document.querySelector('#save').addEventListener('click',async()=>{const status=document.querySelector('#status');status.textContent='Saving…';const r=await fetch('/api/project',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({etag:snapshot.etag,composition:snapshot.project.composition,timeline:snapshot.project.timeline})});const data=await r.json();if(!r.ok){status.textContent=r.status===409?'Conflict — reload required':data.message||'Save failed';return}snapshot=data;render();status.textContent='Saved'});load().catch(e=>document.querySelector('#status').textContent=e.message);
</script></body></html>'''
