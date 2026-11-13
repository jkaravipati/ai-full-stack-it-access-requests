"""Loopback HTTP API and browser assets backed by the same durable intake."""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .validation import Source, load_source, strict_json

WEB = Path(__file__).parent/'web'
MAX_BODY = 8*1024*1024


def queue_payload(store):
    rows=store.current()
    return {'records':rows,'counts':{
        'total':len(rows),'review':sum(r['status']=='review' for r in rows),
        'needs_information':sum(r['status']=='needs-information' for r in rows),
        'errors':sum(r['status']=='error' for r in rows),
        'pending':sum(r['processing_state'] in ('queued','running') for r in rows)}}


def detail(store,document_id):
    record=store.inspect(document_id)
    if record is None: return None
    row=store.get(record['attempt_id'])
    try: message=load_source(document_id,row['source']).message
    except ValueError: message='This export could not be decoded as a valid message.'
    return {'record':record,'message':message}


class OperatorApp:
    def __init__(self,intake,input_root,output):
        self.intake=intake
        self.input_root=Path(input_root).resolve()
        self.output=Path(output).resolve()
        self.closed=threading.Event()
        self.wake=threading.Event()
        self.worker=None
        self.last_error=None

    def start(self):
        if self.worker: return
        def background():
            while not self.closed.is_set():
                try:
                    self.intake.resume()
                    self.last_error=None
                except Exception:
                    self.last_error='Worker could not complete processing; inspect local state and resume.'
                self.wake.wait(.5)
                self.wake.clear()
        self.worker=threading.Thread(target=background,daemon=True)
        self.worker.start()

    def close(self):
        self.closed.set()
        self.wake.set()
        if self.worker: self.worker.join(timeout=2)

    def dispatch(self,method,path,body=None):
        path=urlsplit(path).path
        try:
            if method=='GET':
                if path in ('/','/index.html','/app.js','/styles.css'):
                    return 200,(WEB/('index.html' if path=='/' else path[1:])).read_text()
                if path=='/api/health': return 200,{'status':'ok','worker_error':self.last_error}
                if path=='/api/config':
                    provider=self.intake.provider
                    return 200,{'provider':provider.config['provider'] if provider else 'saved',
                                'model':provider.config.get('model') if provider else None,
                                'source_label':self.input_root.name,'max_upload_bytes':MAX_BODY}
                if path=='/api/queue': return 200,queue_payload(self.intake.store)
                if path.startswith('/api/documents/'):
                    part=path[len('/api/documents/'):]
                    if part.endswith('/history'):
                        document_id=unquote(part[:-len('/history')])
                        if self.intake.store.inspect(document_id) is None: return 404,{'error':'Unknown document.'}
                        return 200,{'attempts':self.intake.store.history(document_id)}
                    result=detail(self.intake.store,unquote(part))
                    return (200,result) if result else (404,{'error':'Unknown document.'})
                if path.startswith('/api/exports/'):
                    name=path[len('/api/exports/'):]
                    if name not in ('extractions.jsonl','queue.json','history.jsonl','manifest.json'):
                        return 404,{'error':'Unknown export.'}
                    generation=(self.output/'current').resolve(strict=True)
                    return 200,(generation/name).read_bytes()
                return 404,{'error':'Not found.'}
            if method!='POST': return 405,{'error':'Use GET or POST.'}
            if not isinstance(body,dict): return 400,{'error':'A JSON object is required.'}
            if path=='/api/intake':
                if set(body)-{'exports'}: raise ValueError('Only exports may be supplied; server paths are configured at startup.')
                if 'exports' not in body:
                    self.intake.ingest_directory(self.input_root,run=False)
                else:
                    exports=body['exports']
                    if not isinstance(exports,list) or not 1<=len(exports)<=2000:
                        raise ValueError('Upload between 1 and 2000 exports.')
                    sources=[]
                    names=set()
                    total=0
                    for item in exports:
                        if not isinstance(item,dict) or set(item)!={'filename','data_base64'}:
                            raise ValueError('Each upload needs filename and data_base64.')
                        name=item['filename']
                        if not isinstance(name,str) or not name.endswith('.json') or len(name)>255 or any(c in name for c in ('/','\\','\x00')) or name in names:
                            raise ValueError('Export filenames must be unique JSON basenames.')
                        names.add(name)
                        raw=base64.b64decode(item['data_base64'],validate=True)
                        total+=len(raw)
                        if len(raw)>128*1024 or total>MAX_BODY: raise ValueError('Upload exceeds the supported size.')
                        try: sources.append(load_source(name,raw))
                        except ValueError: sources.append(Source(name,raw,'',{'ingest_error':True}))
                    self.intake.ingest(sources,run=False)
                self.wake.set()
                return 202,{'message':'Intake accepted. Inspect the queue while processing continues.'}
            if path=='/api/resume':
                if body: raise ValueError('Resume expects an empty object.')
                self.wake.set()
                return 202,{'message':'Unfinished work scheduled for resume.'}
            if path=='/api/export':
                if body: raise ValueError('Export expects an empty object.')
                return 200,self.intake.store.export(self.output)
            if path.startswith('/api/documents/') and path.endswith('/retry'):
                if body: raise ValueError('Retry expects an empty object.')
                document_id=unquote(path[len('/api/documents/'):-len('/retry')])
                result=self.intake.retry(document_id,run=False)
                self.wake.set()
                return 202,{'attempt_id':result['attempt_id'],'message':'New attempt queued.'}
            return 404,{'error':'Not found.'}
        except FileNotFoundError: return 404,{'error':'Requested input or published snapshot is not available.'}
        except (ValueError,TypeError,KeyError) as exc:
            return (409 if path=='/api/export' else 400),{'error':str(exc) if isinstance(exc,ValueError) else 'Invalid request fields.'}


def serve(app,host='127.0.0.1',port=8000):
    if host not in ('127.0.0.1','localhost'): raise ValueError('This local service binds to 127.0.0.1 or localhost.')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass

        def respond(self,status,value):
            if isinstance(value,bytes): data,kind=value,'application/octet-stream'
            elif isinstance(value,str):
                data=value.encode('utf-8')
                kind='text/javascript' if self.path.startswith('/app.js') else 'text/css' if self.path.startswith('/styles.css') else 'text/html'
            else: data,kind=json.dumps(value,ensure_ascii=False).encode(),'application/json'
            self.send_response(status)
            self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            actual_port=self.server.server_address[1]
            return self.headers.get('Host') in (f'127.0.0.1:{actual_port}',f'localhost:{actual_port}')

        def do_GET(self):
            if not self.valid_host(): return self.respond(403,{'error':'Unrecognized local host.'})
            try: self.respond(*app.dispatch('GET',self.path))
            except Exception: self.respond(500,{'error':'Local service operation failed.'})

        def do_POST(self):
            if not self.valid_host(): return self.respond(403,{'error':'Unrecognized local host.'})
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+self.headers['Host']:
                return self.respond(403,{'error':'Cross-origin changes are not allowed.'})
            if self.headers.get_content_type()!='application/json':
                return self.respond(415,{'error':'Use application/json.'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=MAX_BODY: return self.respond(413,{'error':'JSON body is empty or too large.'})
                body=strict_json(self.rfile.read(length).decode('utf-8'))
                self.respond(*app.dispatch('POST',self.path,body))
            except (ValueError,UnicodeError): self.respond(400,{'error':'Invalid JSON body.'})
            except Exception: self.respond(500,{'error':'Local service operation failed.'})

    server=ThreadingHTTPServer((host,port),Handler)
    server.daemon_threads=True
    app.start()
    print(f'Northstar intake: http://{host}:{server.server_address[1]}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        app.close()
        server.server_close()
