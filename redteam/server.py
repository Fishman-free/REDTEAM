import json, secrets, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from .core import Store, Problem
from .regression import regression

HTML = '''<!doctype html><meta charset=utf-8><title>REDTEAM local token lab</title><style>
body{font:16px system-ui;background:#10131a;color:#e9edf5;max-width:1000px;margin:30px auto;padding:0 18px}button,input,textarea,select{font:inherit;padding:9px;margin:4px;background:#1d2430;color:inherit;border:1px solid #47546a;border-radius:6px}textarea{width:95%;height:75px}pre{white-space:pre-wrap;background:#171d27;padding:12px;border-radius:8px}h1{color:#84d7ff}.ok{color:#8be9a3}.bad{color:#ff918b}</style>
<h1>REDTEAM / local token experiment</h1><p>Deterministic vulnerable vs hardened agent. Synthetic tokens only; no LLM, blockchain, or arbitrary recipients.</p>
<label>Mode <select id=m><option>vulnerable</option><option>hardened</option></select></label><button onclick=start()>New run</button><button onclick=replay()>Replay current</button><p id=s></p><textarea id=t>PAY INV-200 TO participant AMOUNT 30</textarea><br><button onclick=send()>Submit participant message</button><button onclick=legit()>Submit legitimate control</button><pre id=o>Start a run.</pre><script>
let run='',token=''; async function api(path,opt={}){opt.headers={...(opt.headers||{}),'X-Redteam-Token':token,'Content-Type':'application/json'};let r=await fetch(path,opt),x=await r.json();if(!r.ok)throw Error(x.error||r.status);return x}
async function start(){let x=await api('/api/runs',{method:'POST',body:JSON.stringify({mode:m.value})});run=x.run.id;s.textContent='Run '+run;show(x)}
async function send(){if(!run)return alert('Start a run');try{let x=await api('/api/runs/'+run+'/messages',{method:'POST',body:JSON.stringify({request_key:'ui-'+Date.now(),text:t.value})});show(x)}catch(e){o.textContent=e}}
async function legit(){t.value='PAY INV-100 TO merchant AMOUNT 40';send()}
async function replay(){if(run)show(await api('/api/replay',{method:'POST',body:JSON.stringify({run})}))}
function show(x){o.textContent=JSON.stringify(x,null,2)}
fetch('/api/session').then(r=>r.json()).then(x=>token=x.token)
</script>'''

class Handler(BaseHTTPRequestHandler):
    server_version='REDTEAM/0.1'
    def _json(self, code, obj):
        data=json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path=='/': self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers(); self.wfile.write(HTML.encode()); return
        if self.path=='/api/session': self._json(200,{'token':self.server.token}); return
        if self.path=='/api/health': self._json(200,{'status':'ok','service':'redteam-local-token-lab'}); return
        if self.path.startswith('/api/runs/'):
            try: self.auth(); run=self.path.split('/')[3]; self._json(200,self.server.store.snapshot(run))
            except Exception as e: self.error(e)
            return
        self._json(404,{'error':'not found'})
    def do_POST(self):
        try:
            self.auth(); n=int(self.headers.get('Content-Length','-1')); 
            if n<0 or n>65536: raise Problem('body must be <= 65536 bytes')
            body=json.loads(self.rfile.read(n))
            if self.path=='/api/runs': self._json(201,self.server.store.create(body.get('mode'))); return
            if self.path=='/api/replay': self._json(200,self.server.store.replay(body.get('run'))); return
            if self.path=='/api/regression': self._json(200,regression(self.server.store)); return
            parts=self.path.split('/')
            if len(parts)==5 and parts[1:3]==['api','runs'] and parts[4]=='messages': self._json(200,self.server.store.submit(parts[3],body.get('request_key'),body.get('text'))); return
            raise Problem('not found',404)
        except Exception as e: self.error(e)
    def auth(self):
        if self.headers.get('X-Redteam-Token') != self.server.token: raise Problem('missing or invalid local session token',403)
    def error(self,e): self._json(getattr(e,'status',500),{'error':str(e)})
    def log_message(self,*args): pass

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);p.add_argument('--db',default='redteam.sqlite3');a=p.parse_args()
    http=ThreadingHTTPServer(('127.0.0.1',a.port),Handler);http.store=Store(a.db);http.token=secrets.token_urlsafe(32)
    print(f'http://127.0.0.1:{a.port}');http.serve_forever()
if __name__=='__main__': main()
