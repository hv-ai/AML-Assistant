"""Single-instance feedback pilot. Run behind a hosting provider's HTTPS proxy.

No account routes, arbitrary model selection, or client-supplied source URLs.
Rate counters persist only as long as the hosting filesystem; configure provider
spending controls as well. This entry point does not expose the local server.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
import queue
import time
from urllib.parse import urlsplit
from flask import Flask, jsonify, request, session, send_file, Response, stream_with_context

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
import assistant_service as svc
import news_service
import hybrid_retrieval
from aml_research import load_index

AI_GATE=threading.BoundedSemaphore(3)
NEWS_LOCK=threading.Lock()

def create_app(test_config=None):
    app=Flask(__name__,static_folder=None)
    origin=(os.environ.get('PUBLIC_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL','')).rstrip('/')
    app.config.update(SECRET_KEY=os.environ.get('SESSION_SECRET',''),PUBLIC_ORIGIN=origin,
        MAX_CONTENT_LENGTH=12_000,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',BUDGET_PATH=ROOT/'.runtime/pilot_limits.sqlite3',
        PILOT_AI_DAILY=50,PILOT_VISITOR_DAILY=10)
    if test_config:app.config.update(test_config)

    @app.before_request
    def protect():
        if request.path=='/healthz':return None
        origin=app.config['PUBLIC_ORIGIN'];parsed=urlsplit(origin)
        if parsed.scheme!='https' or not parsed.hostname or not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY'])<32:
            return jsonify(error='Deployment configuration incomplete: set PUBLIC_ORIGIN and a strong SESSION_SECRET.'),503
        if request.host!=parsed.netloc:return jsonify(error='Unrecognized application host.'),403
        if request.method=='POST':
            if request.headers.get('Origin')!=origin:return jsonify(error='Cross-origin requests are blocked.'),403
            if not request.is_json:return jsonify(error='JSON required.'),415
        if request.method=='POST' and 'visitor' not in session:session['visitor']=secrets.token_hex(16)

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Referrer-Policy':'strict-origin-when-cross-origin',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'",
            'Strict-Transport-Security':'max-age=31536000'})
        if request.path in ('/app.js','/style.css','/web/coverage.css'):
            response.headers['Cache-Control']='public, max-age=3600'
        return response

    def budget(ai=False):
        path=Path(app.config['BUDGET_PATH']);path.parent.mkdir(parents=True,exist_ok=True)
        now=datetime.now(timezone.utc);visitor=hashlib.sha256(session['visitor'].encode()).hexdigest()
        day=now.date().isoformat();minute=now.strftime('%Y-%m-%dT%H:%M')
        limits=[('minute:'+minute+':'+visitor,30)]
        if ai:limits += [('ai:'+day,app.config['PILOT_AI_DAILY']),('visitor:'+day+':'+visitor,app.config['PILOT_VISITOR_DAILY'])]
        with closing(sqlite3.connect(path,timeout=5)) as conn, conn:
            conn.execute('CREATE TABLE IF NOT EXISTS counters (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL)')
            conn.execute('BEGIN IMMEDIATE')
            for bucket,limit in limits:
                row=conn.execute('SELECT count FROM counters WHERE bucket=?',(bucket,)).fetchone()
                if row and row[0]>=limit:return False
            for bucket,_ in limits:
                conn.execute('INSERT INTO counters VALUES (?,1) ON CONFLICT(bucket) DO UPDATE SET count=count+1',(bucket,))
            conn.execute('DELETE FROM counters WHERE substr(bucket, instr(bucket,\':\')+1,10) < ?',(day,))
        return True

    @app.get('/healthz')
    def health():return jsonify(status='ok')

    @app.get('/')
    def home():return send_file(ROOT/'web/index.html',mimetype='text/html')

    @app.get('/<name>')
    def static_asset(name):
        files={'app.js':('web/app.js','text/javascript'),'style.css':('web/style.css','text/css'),
            'retrieval-comparison.csv':('reports/retrieval_comparison.csv','text/csv'),
            'coverage.html':('reports/aml_typology_coverage.html','text/html')}
        if name not in files:return jsonify(error='Not found'),404
        file,kind=files[name];return send_file(ROOT/file,mimetype=kind)

    @app.get('/web/coverage.css')
    def coverage_css():return send_file(ROOT/'web/coverage.css',mimetype='text/css')

    @app.get('/api/status')
    def status():
        index=load_index();conf=svc.settings();hybrid=hybrid_retrieval.status()
        sources=list({c['source_id']:{k:c[k] for k in ('source_id','title','issuer','authority_type','url','captured_date','published_date')} for c in index.chunks}.values())
        return jsonify(hosted=True,key_configured=bool(conf.get('NEBIUS_API_KEY')),default_model=conf.get('NEBIUS_MODEL',''),
            sources=sources,chunks=len(index.chunks),cases=[],topics=json.loads((ROOT/'config/typology_topics.json').read_text()),additional_topics=json.loads((ROOT/'config/additional_research_topics.json').read_text()),
            usage={'attempts':0,'input_tokens':0,'output_tokens':0},call_limit=app.config['PILOT_VISITOR_DAILY'],
            retrieval=hybrid['method'],hybrid=hybrid)

    @app.get('/api/evaluation')
    def evaluation():return jsonify(json.loads((ROOT/'reports/retrieval_comparison.json').read_text()))

    @app.get('/api/answer-evaluation')
    def answer_evaluation():return jsonify(json.loads((ROOT/'reports/answer_comparison.json').read_text()))

    @app.post('/api/<path:action>')
    def api(action):
        if action not in ('ask','ask/stream','news','news/brief'):return jsonify(error='Not found'),404
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error='Invalid request.'),400
        if data.get('model'):return jsonify(error='The public pilot uses a fixed model.'),400
        ai=action=='news/brief' or action.startswith('ask') and data.get('generate',True) is not False
        if not budget(ai):return jsonify(error='Pilot request limit reached. Please return later or share feedback with the project owner.'),429
        reserved=ai and AI_GATE.acquire(blocking=False)
        if ai and not reserved:return jsonify(error='The research service is busy. Please try again shortly.'),429
        transferred=False
        try:
            if action=='news':
                return jsonify(news_service.news_snapshot())
            if action=='news/brief':return jsonify(news_service.brief(data.get('id')))
            if not isinstance(data.get('generate',True),bool):return jsonify(error='Invalid search option.'),400
            if action=='ask/stream':
                events=queue.Queue()
                def work():
                    try:
                        result=svc.ask(data.get('question',''),mode=data.get('mode','answer'),generate=data.get('generate',True),
                            on_stage=lambda stage:events.put({'type':'stage','stage':stage}))
                        events.put({'type':'result','result':result})
                    except Exception as exc:
                        events.put({'type':'error','error':str(exc) if isinstance(exc,svc.SetupError) else 'The research request could not be completed.'})
                    finally:
                        if reserved:AI_GATE.release()
                        events.put(None)
                transferred=True;threading.Thread(target=work,daemon=True).start()
                def stream():
                    while True:
                        try:event=events.get(timeout=2)
                        except queue.Empty:
                            yield json.dumps({'type':'heartbeat'})+'\n';continue
                        if event is None:break
                        yield json.dumps(event)+'\n'
                return Response(stream_with_context(stream()),mimetype='application/x-ndjson',headers={'X-Accel-Buffering':'no'})
            return jsonify(svc.ask(data.get('question',''),mode=data.get('mode','answer'),generate=data.get('generate',True)))
        except (svc.SetupError,ValueError) as exc:
            return jsonify(error=str(exc) if isinstance(exc,svc.SetupError) else 'Invalid request or model response.'),400
        except Exception:
            return jsonify(error='The request could not be completed. Please try again later.'),500
        finally:
            if reserved and not transferred:AI_GATE.release()
    return app

app=create_app()
