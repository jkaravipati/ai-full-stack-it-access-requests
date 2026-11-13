"""Operator CLI. Run python3 -m access_intake --help."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .engine import Intake
from .providers import MockProvider,OpenAIProvider
from .service import OperatorApp,detail,queue_payload,serve


def parser():
    p=argparse.ArgumentParser(description='Northstar access-request intake for human review.')
    p.add_argument('--version',action='version',version=__version__)
    commands=p.add_subparsers(dest='command',required=True)
    for name in ('intake','queue','inspect','resume','retry','history','export','serve','accuracy'):
        q=commands.add_parser(name)
        q.add_argument('--state',default='.state/intake.sqlite3',help='Shared local SQLite file')
        if name in ('intake','serve'):
            q.add_argument('--provider',choices=('mock','openai'),default='mock')
            q.add_argument('--mock-responses',default='tests/mock_responses')
            q.add_argument('--config',type=Path,help='Nonsecret provider JSON settings')
            q.add_argument('--workers',type=int,default=4)
        if name=='intake': q.add_argument('directory',type=Path)
        if name in ('inspect','retry','history'): q.add_argument('document_id')
        if name in ('export','serve'): q.add_argument('--output',default='deliverables',type=Path)
        if name=='serve':
            q.add_argument('--input-root',default='materials/requests',type=Path)
            q.add_argument('--host',default='127.0.0.1')
            q.add_argument('--port',default=8000,type=int)
        if name=='accuracy':
            q.add_argument('--expected',default='tests/expected',type=Path)
            q.add_argument('--actual',default='deliverables/extractions.jsonl',type=Path)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command=='accuracy':
            from .accuracy import compare_files
            result=compare_files(args.expected,args.actual)
            print(json.dumps(result,indent=2,ensure_ascii=False))
            return 0 if not result['structural_errors'] and result['scalar_matches']==result['scalar_total'] and result['route_matches']==result['route_total'] else 1
        provider=None
        if args.command in ('intake','serve'):
            config=json.loads(args.config.read_text()) if args.config else {}
            provider=MockProvider(args.mock_responses) if args.provider=='mock' else OpenAIProvider(config)
        engine=Intake(args.state,provider=provider,workers=getattr(args,'workers',4))
        if args.command=='serve':
            serve(OperatorApp(engine,args.input_root,args.output),args.host,args.port)
            return 0
        if args.command=='intake':
            engine.ingest_directory(args.directory)
            data=queue_payload(engine.store)
            result=dict(count=len(data['records']),**data['counts'])
        elif args.command=='queue': result=queue_payload(engine.store)
        elif args.command=='inspect':
            result=detail(engine.store,args.document_id)
            if result is None: raise ValueError('Unknown document ID.')
        elif args.command=='history': result={'attempts':engine.store.history(args.document_id)}
        elif args.command=='resume':
            engine.resume()
            result=queue_payload(engine.store)
        elif args.command=='retry': result=engine.retry(args.document_id)
        elif args.command=='export': result=engine.store.export(args.output)
        print(json.dumps(result,indent=2,ensure_ascii=False))
        if args.command=='intake' and result['errors']: return 1
        return 0
    except (ValueError,OSError,KeyError,sqlite3.Error) as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
