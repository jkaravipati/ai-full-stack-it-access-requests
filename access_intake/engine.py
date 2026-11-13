"""Intake orchestration shared by CLI, HTTP service and browser dashboard."""
import hashlib
import json
import shlex
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from .pipeline import process_message
from .policy import WRAPPER_SCHEMA, ASSESSMENT_SCHEMA
from .providers import MockProvider, OpenAIProvider, ProviderError
from .store import Store, canonical
from .validation import RESOURCES, Source, load_source


def make_provider(config):
    if config['provider']=='mock':
        provider=MockProvider(config['mock_responses'])
        if provider.config!=config:
            raise ProviderError('changed_mock_configuration','Saved mock fixture configuration has changed; intake with the new configuration.')
        return provider
    return OpenAIProvider(config)


class DeadlineProvider:
    """Bound caller wait and total outstanding transports; late values are discarded."""
    def __init__(self,provider,timeout,slots):
        self.provider,self.timeout,self.slots=provider,timeout,slots

    def __getattr__(self,name): return getattr(self.provider,name)

    def call(self,operation,message,context):
        started=time.monotonic()
        if not self.slots.acquire(timeout=self.timeout):
            raise ProviderError('timeout','Provider capacity occupied by interrupted calls; retry later.',operation)
        result=queue.Queue(maxsize=1)
        def invoke():
            try: result.put((True,self.provider.call(operation,message,context)))
            except Exception as exc: result.put((False,exc))
            finally: self.slots.release()
        threading.Thread(target=invoke,daemon=True).start()
        remaining=max(0,self.timeout-(time.monotonic()-started))
        try: ok,value=result.get(timeout=remaining)
        except queue.Empty:
            raise ProviderError('timeout','Provider call deadline exceeded; retry this document.',operation) from None
        if not ok: raise value
        return value


class Intake:
    def __init__(self,path,provider=None,clock=None,policy_path=None,workers=4,call_timeout=None):
        self.store=Store(path,clock=clock)
        self.provider=provider
        if type(workers) is not int or not 1<=workers<=64: raise ValueError('workers must be between 1 and 64.')
        self.workers=workers
        self.call_timeout=call_timeout
        self._slots=threading.BoundedSemaphore(workers)
        root_policy=Path(__file__).resolve().parents[1]/'materials/office-policy.md'
        self.policy_path=Path(policy_path) if policy_path else (root_policy if root_policy.exists() else RESOURCES/'office-policy.md')

    def configuration(self,provider):
        provider_settings=dict(provider.config)
        relevant={k:v for k,v in provider_settings.items() if k not in ('timeout','workers')}
        def digest(data): return hashlib.sha256(data).hexdigest()
        return {'provider':provider_settings,'processing':{
            'provider':relevant,'version':__version__,
            'policy_sha256':digest(self.policy_path.read_bytes()),
            'policy_text':self.policy_path.read_text(),
            'prompts':{op:digest((RESOURCES/(op+'.txt')).read_bytes()) for op in ('extraction','override_assessment')},
            'schemas_sha256':digest(canonical([WRAPPER_SCHEMA,ASSESSMENT_SCHEMA]).encode())}}

    def accept(self,source,force=False,config=None):
        if config is None:
            if self.provider is None: raise ValueError('Intake requires an explicit provider.')
            config=self.configuration(self.provider)
        return self.store.accept(source,config,force=force)

    def ingest(self,sources,run=True):
        ids=[self.accept(source)[0] for source in sources]
        if run: self.run(ids)
        return self.store.current()

    def run(self,ids):
        with ThreadPoolExecutor(max_workers=self.workers) as workers:
            list(workers.map(self.process,dict.fromkeys(ids)))

    def ingest_directory(self,directory,run=True):
        paths=sorted(Path(directory).glob('*.json'))
        if not paths: raise ValueError('Input directory contains no JSON exports.')
        snapshots=[(path,path.read_bytes()) for path in paths]  # unreadable: reject before any acceptance
        sources=[]
        for path,raw in snapshots:
            try: sources.append(load_source(path,raw))
            except ValueError: sources.append(Source(path.name,raw,'',{'ingest_error':True}))
        return self.ingest(sources,run=run)

    def process(self,attempt_id):
        row=self.store.claim(attempt_id)
        if row is None: return False
        config=json.loads(row['config'])
        source=Source(row['document_id'],row['source'],'',json.loads(row['metadata']))
        done=threading.Event()
        def renew():
            while not done.wait(30):
                try:
                    if not self.store.heartbeat(row['id'],row['token']): return
                except Exception: return  # a final fenced commit still checks lease validity
        heartbeat=threading.Thread(target=renew,daemon=True)
        heartbeat.start()
        try:
            source=load_source(row['document_id'],row['source'])
            provider=self.provider if self.provider and dict(self.provider.config)==config['provider'] else make_provider(config['provider'])
            timeout=self.call_timeout or provider.config.get('timeout',60)
            result=process_message(source,DeadlineProvider(provider,timeout,self._slots))
        except Exception as exc:
            result=dict(source.context,extraction=None,status='error',owner='IT Service Desk',next_action='retry-extraction',
                        response_source='mock' if config['provider']['provider']=='mock' else 'openai:'+config['provider']['model'],
                        response_received=False,source_basis='attempted',provider_calls=[],
                        error={'stage':'ingest' if isinstance(exc,ValueError) else 'configuration',
                               'code':getattr(exc,'code','invalid_export'),'message':'Inspect the input export or saved provider configuration, then retry.',
                               'retry_command':''})
        finally:
            done.set()
            heartbeat.join(timeout=1)
        if result['error']:
            result['error']['retry_command']=shlex.join(['python3','-m','access_intake','retry',source.document_id,'--state',str(self.store.path)])
        return self.store.finish(row['id'],row['token'],result)

    def retry(self,document_id,run=True):
        current=self.store.inspect(document_id)
        if current is None: raise ValueError('Unknown document ID.')
        row=self.store.get(current['attempt_id'])
        source=Source(row['document_id'],row['source'],'',json.loads(row['metadata']))
        attempt_id,_=self.accept(source,force=True,config=json.loads(row['config']))
        if run: self.process(attempt_id)
        return self.store.inspect(document_id)

    def resume(self):
        self.run([current['attempt_id'] for current in self.store.current()])
        return self.store.current()
