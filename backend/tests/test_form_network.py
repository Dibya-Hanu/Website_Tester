"""Live browser proof that even on-input GET callbacks cannot send form cases."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.core.config import Settings
from app.core.guard import EgressGuard
from app.core.policy import TargetPolicy
from app.scanners.browser import BrowserSession, crawl, test_forms as validate_forms


async def test_native_form_cases_do_not_send_get_or_post_callbacks(tmp_path):
    callback_requests=[]
    html=b'''<!doctype html><html lang="en"><title>Owned test fixture</title><body>
      <form method="post"><label for="email">Email</label><input id="email" name="email" type="email" required><button>Submit</button></form>
      <script>document.querySelector('input').oninput=()=>fetch('/callback?q='+encodeURIComponent(document.querySelector('input').value)).catch(()=>{});</script>
    </body></html>'''
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/callback'):callback_requests.append(self.path)
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(html)));self.end_headers();self.wfile.write(html)
        def do_POST(self):
            callback_requests.append('POST');self.send_response(200);self.end_headers()
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/'
    settings=Settings(allowlist=url,data_dir=tmp_path,max_pages=1,max_forms=1)
    target=await TargetPolicy(settings).resolve(url)
    class ScopedAI:
        async def perform(self,name,instruction,data,schema):
            return schema.model_validate({'tests':[
                {'name':kind,'kind':kind,'inputs':{'field_1':value},'expected':'observe'}
                for kind,value in [('empty',''),('invalid','not-email'),('boundary','x'*128),('special','UWT_<>')]
            ]})
    try:
        async with EgressGuard(target,settings,tmp_path/'guard') as guard:
            async with BrowserSession(guard,settings) as session:
                mapped=await crawl(session,tmp_path,lambda message:None,True)
                result,cases=await validate_forms(session,ScopedAI(),mapped.pages,tmp_path,lambda message:None)
                assert result.metrics['mutation_submissions']==0
                assert len(cases)==4 and all(c['status']=='executed' for c in cases)
                assert all(c['source']=='Ollama-generated' for c in cases)
        assert callback_requests==[]
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
