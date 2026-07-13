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
:root{font-family:Inter,system-ui,sans-serif;color:#e5e7eb;background:#09090b}*{box-sizing:border-box}body{margin:0}header{height:64px;padding:0 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #27272a;background:#111113}h1{font-size:18px;margin:0}.meta{color:#a1a1aa;font-size:12px}button{border:0;border-radius:8px;padding:10px 16px;background:#7c3aed;color:white;font-weight:700;cursor:pointer}main{display:grid;grid-template-columns:minmax(360px,1fr) 320px;gap:20px;padding:20px}.stage-card,.panel,.timeline{background:#151518;border:1px solid #29292e;border-radius:14px}.stage-card{padding:18px}.stage{aspect-ratio:16/9;border-radius:10px;display:grid;place-items:center;box-shadow:0 20px 60px #0008;overflow:hidden}.screen{width:82%;height:78%;background:#f4f4f5;border-radius:8px;box-shadow:0 16px 35px #0008}.panel{padding:18px}.panel h2,.timeline h2{font-size:14px;margin:0 0 16px}.field{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:14px 0;color:#d4d4d8;font-size:13px}.field input[type=number]{width:100px}.field input[type=text]{width:160px}.field input[type=number],.field input[type=text]{background:#232329;color:#fff;border:1px solid #3f3f46;border-radius:6px;padding:7px}input[type=color]{width:48px;height:32px;border:0;background:none}.segment-editor{border-top:1px solid #29292e;margin-top:18px;padding-top:18px}.segment-editor[hidden],#camera-fields[hidden],#annotation-fields[hidden],#annotation-text-fields[hidden],#annotation-bounds-fields[hidden],#annotation-arrow-fields[hidden]{display:none}.timeline{grid-column:1/-1;padding:18px}.track{display:grid;grid-template-columns:150px 1fr;gap:12px;align-items:center;margin:10px 0}.track-name{font-size:12px;color:#d4d4d8}.lane{height:30px;border-radius:6px;background:#232329;position:relative;overflow:hidden}.segment{position:absolute;top:4px;height:22px;min-width:4px;border:0;padding:0;border-radius:5px;background:#8b5cf6}.segment.selected{outline:2px solid white;outline-offset:-2px}.status{font-size:12px;color:#a1a1aa;margin-top:12px}@media(max-width:800px){main{grid-template-columns:1fr}.timeline{grid-column:auto}}
</style></head><body><header><div><h1>Hermes Editor</h1><div class="meta" id="title">Loading…</div></div><button id="save">Save project</button></header><main><section class="stage-card"><div class="stage" id="stage"><div class="screen"></div></div></section><aside class="panel"><h2>Composition</h2><label class="field">Background <input id="background" type="color"></label><div class="field"><span>Canvas</span><span id="canvas"></span></div><div class="field"><span>Preset</span><span id="preset"></span></div><section class="segment-editor" id="segment-editor" hidden><h2 id="segment-title">Segment</h2><label class="field">Start <input id="segment-start" type="number" min="0" step="0.01"></label><label class="field">End <input id="segment-end" type="number" min="0" step="0.01"></label><div id="camera-fields" hidden><label class="field">Zoom scale <input id="zoom-scale" type="number" min="1" step="0.05"></label><label class="field">Focus X <input id="focus-x" type="number" min="0" step="1"></label><label class="field">Focus Y <input id="focus-y" type="number" min="0" step="1"></label></div><div id="annotation-fields" hidden><div class="field"><span>Annotation</span><span id="annotation-kind"></span></div><label class="field">Color <input id="annotation-color" type="text" maxlength="9"></label><label class="field">Opacity <input id="annotation-opacity" type="number" min="0" max="1" step="0.05"></label><div id="annotation-text-fields" hidden><label class="field">Text <input id="annotation-text" type="text"></label><label class="field">Position X <input id="annotation-x" type="number" min="0" step="1"></label><label class="field">Position Y <input id="annotation-y" type="number" min="0" step="1"></label><label class="field">Font size <input id="annotation-font-size" type="number" min="1" step="1"></label></div><div id="annotation-bounds-fields" hidden><label class="field">Bounds X <input id="bounds-x" type="number" min="0" step="1"></label><label class="field">Bounds Y <input id="bounds-y" type="number" min="0" step="1"></label><label class="field">Width <input id="bounds-width" type="number" min="1" step="1"></label><label class="field">Height <input id="bounds-height" type="number" min="1" step="1"></label></div><div id="annotation-arrow-fields" hidden><label class="field">From X <input id="arrow-from-x" type="number" min="0" step="1"></label><label class="field">From Y <input id="arrow-from-y" type="number" min="0" step="1"></label><label class="field">To X <input id="arrow-to-x" type="number" min="0" step="1"></label><label class="field">To Y <input id="arrow-to-y" type="number" min="0" step="1"></label></div></div><button id="apply-segment">Apply segment</button></section><div class="status" id="status">Loading project…</div></aside><section class="timeline"><h2>Timeline</h2><div id="tracks"></div></section></main><script>
let snapshot=null,selected=null;const colors=['#8b5cf6','#06b6d4','#f59e0b','#ef4444'];
async function load(){const r=await fetch('/api/project');snapshot=await r.json();render()}
function duration(){let d=1;for(const t of snapshot.project.timeline.tracks){if(t.summary?.estimated_duration_seconds)d=Math.max(d,t.summary.estimated_duration_seconds);for(const s of t.segments||[])d=Math.max(d,s.end_seconds||s.arrival_seconds||0)}return d}
function render(){const p=snapshot.project,c=p.composition,canvas=c.canvas;document.querySelector('#title').textContent=p.title+' · '+snapshot.etag.slice(0,10);document.querySelector('#canvas').textContent=canvas.width+' × '+canvas.height;document.querySelector('#preset').textContent=c.preset;const bg=c.background.type==='color'?c.background.value:'#111827';document.querySelector('#background').value=bg;document.querySelector('#stage').style.background=bg;const tracks=document.querySelector('#tracks');tracks.replaceChildren();const total=duration();p.timeline.tracks.forEach((t,i)=>{const row=document.createElement('div');row.className='track';const name=document.createElement('div');name.className='track-name';name.textContent=t.type;const lane=document.createElement('div'),segments=t.segments||[];lane.className='lane';lane.style.height=(8+Math.max(1,segments.length)*24)+'px';segments.forEach((s,j)=>{const start=s.start_seconds||0,end=s.end_seconds||s.arrival_seconds||start+.05;const bar=document.createElement('button');bar.className='segment'+(selected&&selected.track===i&&selected.segment===j?' selected':'');bar.setAttribute('aria-label',t.type+' segment '+(j+1));bar.style.top=(4+j*24)+'px';bar.style.left=(start/total*100)+'%';bar.style.width=(Math.max(.01,end-start)/total*100)+'%';bar.style.background=colors[i%colors.length];bar.addEventListener('click',()=>selectSegment(i,j));lane.append(bar)});row.append(name,lane);tracks.append(row)});document.querySelector('#status').textContent='Loaded safely'}
function selectSegment(track,segment){selected={track,segment};const t=snapshot.project.timeline.tracks[track],s=t.segments[segment],camera=t.type==='camera.zoom',annotation=t.type==='annotation.overlay';document.querySelector('#segment-editor').hidden=false;document.querySelector('#segment-title').textContent=t.type+' · segment '+(segment+1);document.querySelector('#segment-start').value=s.start_seconds;document.querySelector('#segment-end').value=s.end_seconds;document.querySelector('#camera-fields').hidden=!camera;document.querySelector('#annotation-fields').hidden=!annotation;if(camera){document.querySelector('#zoom-scale').value=s.scale;document.querySelector('#focus-x').value=s.focus.x;document.querySelector('#focus-y').value=s.focus.y}if(annotation){const text=s.kind==='text',bounds=s.kind==='box'||s.kind==='highlight',arrow=s.kind==='arrow';document.querySelector('#annotation-kind').textContent=s.kind;document.querySelector('#annotation-color').value=s.style.color;document.querySelector('#annotation-opacity').value=s.style.opacity;document.querySelector('#annotation-text-fields').hidden=!text;document.querySelector('#annotation-bounds-fields').hidden=!bounds;document.querySelector('#annotation-arrow-fields').hidden=!arrow;if(text){document.querySelector('#annotation-text').value=s.text;document.querySelector('#annotation-x').value=s.position.x;document.querySelector('#annotation-y').value=s.position.y;document.querySelector('#annotation-font-size').value=s.style.font_size}if(bounds){document.querySelector('#bounds-x').value=s.bounds.x;document.querySelector('#bounds-y').value=s.bounds.y;document.querySelector('#bounds-width').value=s.bounds.width;document.querySelector('#bounds-height').value=s.bounds.height}if(arrow){document.querySelector('#arrow-from-x').value=s.from.x;document.querySelector('#arrow-from-y').value=s.from.y;document.querySelector('#arrow-to-x').value=s.to.x;document.querySelector('#arrow-to-y').value=s.to.y}}render()}
document.querySelector('#apply-segment').addEventListener('click',()=>{if(!selected)return;const start=Number(document.querySelector('#segment-start').value),end=Number(document.querySelector('#segment-end').value),status=document.querySelector('#status'),track=snapshot.project.timeline.tracks[selected.track],s=track.segments[selected.segment],canvas=snapshot.project.composition.canvas;if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start){status.textContent='Segment end must be greater than start';return}if(track.type==='camera.zoom'){const scale=Number(document.querySelector('#zoom-scale').value),x=Number(document.querySelector('#focus-x').value),y=Number(document.querySelector('#focus-y').value);if(!Number.isFinite(scale)||scale<1||!pointFits(x,y,canvas)){status.textContent='Camera scale and focus must fit the canvas';return}s.scale=scale;s.focus={x,y}}if(track.type==='annotation.overlay'){const color=document.querySelector('#annotation-color').value.trim(),opacity=Number(document.querySelector('#annotation-opacity').value);if(!/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(color)||!Number.isFinite(opacity)||opacity<0||opacity>1){status.textContent='Annotation color or opacity is invalid';return}if(s.kind==='text'){const text=document.querySelector('#annotation-text').value.trim(),x=Number(document.querySelector('#annotation-x').value),y=Number(document.querySelector('#annotation-y').value),fontSize=Number(document.querySelector('#annotation-font-size').value);if(!text||!pointFits(x,y,canvas)||!Number.isFinite(fontSize)||fontSize<=0){status.textContent='Text annotation must fit the canvas';return}s.text=text;s.position={x,y};s.style.font_size=fontSize}else if(s.kind==='box'||s.kind==='highlight'){const x=Number(document.querySelector('#bounds-x').value),y=Number(document.querySelector('#bounds-y').value),width=Number(document.querySelector('#bounds-width').value),height=Number(document.querySelector('#bounds-height').value);if(!boundsFit(x,y,width,height,canvas)){status.textContent='Annotation bounds must fit the canvas';return}s.bounds={x,y,width,height}}else if(s.kind==='arrow'){const fromX=Number(document.querySelector('#arrow-from-x').value),fromY=Number(document.querySelector('#arrow-from-y').value),toX=Number(document.querySelector('#arrow-to-x').value),toY=Number(document.querySelector('#arrow-to-y').value);if(!pointFits(fromX,fromY,canvas)||!pointFits(toX,toY,canvas)){status.textContent='Annotation arrow must fit the canvas';return}s.from={x:fromX,y:fromY};s.to={x:toX,y:toY}}s.style.color=color.toUpperCase();s.style.opacity=opacity}s.start_seconds=start;s.end_seconds=end;render();status.textContent='Unsaved segment changes'});
function pointFits(x,y,canvas){return Number.isFinite(x)&&Number.isFinite(y)&&x>=0&&y>=0&&x<=canvas.width&&y<=canvas.height}
function boundsFit(x,y,width,height,canvas){return pointFits(x,y,canvas)&&Number.isFinite(width)&&Number.isFinite(height)&&width>0&&height>0&&x+width<=canvas.width&&y+height<=canvas.height}
document.querySelector('#background').addEventListener('input',e=>{snapshot.project.composition.background={type:'color',value:e.target.value.toUpperCase()};document.querySelector('#stage').style.background=e.target.value;document.querySelector('#status').textContent='Unsaved changes'});
document.querySelector('#save').addEventListener('click',async()=>{const status=document.querySelector('#status');status.textContent='Saving…';const r=await fetch('/api/project',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({etag:snapshot.etag,composition:snapshot.project.composition,timeline:snapshot.project.timeline})});const data=await r.json();if(!r.ok){status.textContent=r.status===409?'Conflict — reload required':data.message||'Save failed';return}snapshot=data;render();status.textContent='Saved'});load().catch(e=>document.querySelector('#status').textContent=e.message);
</script></body></html>'''
