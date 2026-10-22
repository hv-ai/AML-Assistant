"""Local-only UI server. Python 3.10+, no package installation required."""
import argparse
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import json
from pathlib import Path
import sys
import threading
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from aml_research import build_index, load_index
from assistant_service import ask, models, settings, usage_state, CALL_LIMIT, SetupError
import accounts
import news_service
import hybrid_retrieval
GATE = threading.BoundedSemaphore(3)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # No questions or credentials in access logs.

    def send(self, body, code=200, kind='application/json', cookie=None):
        data = json.dumps(body).encode() if kind == 'application/json' else body
        self.send_response(code)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def session_token(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie',''))
            return cookie['aml_session'].value if 'aml_session' in cookie else ''
        except Exception:
            return ''

    def local_request(self):
        host = self.headers.get('Host', '')
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if host not in allowed:
            self.send({'error':'Local access only.'},403)
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://{x}' for x in allowed}:
            self.send({'error':'Cross-origin requests are blocked.'},403)
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        path = urlparse(self.path).path
        if path == '/api/session':
            self.send({'user':accounts.current_user(self.session_token()), 'storage':'local_account_database'})
        elif path == '/retrieval-comparison.csv':
            report=ROOT/'reports/retrieval_comparison.csv'
            self.send(report.read_bytes() if report.exists() else b'No report yet',kind='text/csv')
        elif path == '/api/answer-evaluation':
            report=ROOT/'reports/answer_comparison.json'
            self.send(json.loads(report.read_text()) if report.exists() else {'samples':[]})
        elif path == '/api/evaluation':
            report=ROOT/'reports/retrieval_comparison.json'
            self.send(json.loads(report.read_text()) if report.exists() else {'status':'not_run','message':'Retrieval comparison has not been run yet.'})
        elif path == '/api/history':
            user=accounts.current_user(self.session_token())
            self.send({'history':accounts.history(user['id'])} if user else {'error':'Sign in to load account history.'},200 if user else 401)
        elif path in ('/', '/app.js', '/style.css'):
            name, kind = {'/':('index.html','text/html'), '/app.js':('app.js','text/javascript'), '/style.css':('style.css','text/css')}[path]
            self.send((ROOT/'web'/name).read_bytes(),kind=kind)
        elif path == '/web/coverage.css':
            self.send((ROOT/'web/coverage.css').read_bytes(),kind='text/css')
        elif path == '/coverage.html':
            self.send((ROOT/'reports/aml_typology_coverage.html').read_bytes(),kind='text/html')
        elif path == '/api/status':
            conf = settings()
            index = load_index()
            sources = list({c['source_id']:{k:c[k] for k in ('source_id','title','issuer','authority_type','url','captured_date','published_date')} for c in index.chunks}.values())
            cases = list(csv.DictReader((ROOT/'evaluation/retrieval_cases.csv').open()))
            self.send({'key_configured':bool(conf.get('NEBIUS_API_KEY')), 'default_model':conf.get('NEBIUS_MODEL',''),
                       'sources':sources,'chunks':len(index.chunks),'cases':cases,
                       'topics':json.loads((ROOT/'config/typology_topics.json').read_text()),'additional_topics':json.loads((ROOT/'config/additional_research_topics.json').read_text()),
                       'usage':usage_state(),'call_limit':CALL_LIMIT,'retrieval':hybrid_retrieval.status()['method'],'hybrid':hybrid_retrieval.status()})
        else:
            self.send({'error':'Not found'},404)

    def do_POST(self):
        if not self.local_request():
            return
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            self.send({'error':'JSON required'},415); return
        reserved=self.path in ('/api/ask','/api/news/brief','/api/models')
        if reserved and not GATE.acquire(blocking=False):
            self.send({'error':'All three AI request slots are busy. Please try again shortly.'},429); return
        try:
            length = int(self.headers.get('Content-Length','0'))
            limit = 200000 if self.path == '/api/history' else 12000
            if not 0 < length <= limit:
                self.send({'error':'Request too large or empty.'},400); return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Invalid request')
            if self.path in ('/api/register','/api/login'):
                action=accounts.register if self.path=='/api/register' else accounts.login
                user,token=action(body.get('username'),body.get('password'))
                # HTTP is permitted only for this loopback prototype. A hosted
                # deployment requires HTTPS, Secure cookies and managed identity.
                cookie=f'aml_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={accounts.SESSION_SECONDS}'
                self.send({'user':user},cookie=cookie)
            elif self.path == '/api/logout':
                accounts.logout(self.session_token())
                self.send({'user':None},cookie='aml_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            elif self.path == '/api/history':
                user=accounts.current_user(self.session_token())
                if not user:
                    self.send({'error':'Sign in to save account history.'},401)
                else:
                    self.send({'work':accounts.save_work(user['id'],body.get('work'))})
            elif self.path == '/api/news':
                if not isinstance(body.get('refresh',False),bool):raise ValueError('Invalid refresh')
                self.send(news_service.news_snapshot())
            elif self.path == '/api/news/brief':
                if not isinstance(body.get('model',''),str):raise ValueError('Invalid model')
                self.send(news_service.brief(body.get('id'),body.get('model',''),body.get('category','aml')))
            elif self.path == '/api/models':
                self.send({'models':models()})
            elif self.path == '/api/ask':
                if not isinstance(body.get('generate',True),bool) or not isinstance(body.get('model',''),str):
                    raise ValueError('Invalid options')
                self.send(ask(body.get('question',''),body.get('model',''),body.get('mode','answer'),body.get('generate',True)))
            else:
                self.send({'error':'Not found'},404)
        except (SetupError,ValueError) as e:
            # ValueError messages originate only from local validation or sanitized provider errors.
            message = str(e) if isinstance(e,(SetupError,accounts.AccountError)) else 'Invalid request or model response.'
            self.send({'error':message},400)
        except Exception:
            self.send({'error':'Request failed. Check local configuration and retry.'},500)
        finally:
            if reserved:GATE.release()

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8000); args=parser.parse_args()
    if not (ROOT/'data/processed/chunks.json').exists():
        build_index()
    print(f'AML Research Assistant: http://127.0.0.1:{args.port}',flush=True)
    print('Local prototype. Stop with Ctrl+C. Keys remain server-side.',flush=True)
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
