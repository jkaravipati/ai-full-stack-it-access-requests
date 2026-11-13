"""Explicit local HTTP smoke against a MOCK service; never reads API_KEY.

Start a disposable mock server first; this intentionally changes its intake state.
This is separate from the socket-blocked unit/integration suite.
"""
import argparse
import base64
import http.client
import json
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()

    def request(method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',args.port,timeout=10)
        data=json.dumps(body) if body is not None else None
        h={'Content-Type':'application/json'} if body is not None else {}
        h.update(headers or {})
        connection.request(method,path,data,h)
        response=connection.getresponse()
        raw=response.read()
        status=response.status
        connection.close()
        return status,raw

    status,raw=request('GET','/api/config')
    assert status==200 and json.loads(raw)['provider']=='mock','Refusing smoke writes to a non-mock service.'
    for path in ['/','/app.js','/styles.css','/api/health']:
        assert request('GET',path)[0]==200,path
    assert request('POST','/api/intake',{})[0]==202

    def wait_for(n):
        until=time.monotonic()+15
        while time.monotonic()<until:
            status,raw=request('GET','/api/queue')
            value=json.loads(raw)
            if value['counts']['total']>=n and value['counts']['pending']==0:
                return value
            time.sleep(.05)
        raise AssertionError('Mock intake did not finish.')

    wait_for(20)
    raw=(ROOT/'tests/inputs/IT-P01.json').read_bytes()
    assert request('POST','/api/intake',{'exports':[{
        'filename':'IT-P01.json','data_base64':base64.b64encode(raw).decode()}]})[0]==202
    queue=wait_for(21)
    expected={json.loads(p.read_text())['document_id']:json.loads(p.read_text())
              for p in (ROOT/'tests/expected').glob('*.json')}
    assert len(queue['records'])==21,'Use a disposable server state containing only the supplied examples.'
    for row in queue['records']:
        oracle=expected[row['document_id']]
        for field in ('status','owner','next_action','source_sha256'):
            assert row[field]==oracle[field],(row['document_id'],field)
    for path in ['/api/documents/IT-001.json','/api/documents/IT-001.json/history']:
        assert request('GET',path)[0]==200
    assert request('POST','/api/intake',{}, {'Origin':'http://untrusted.invalid'})[0]==403
    assert request('GET','/api/queue',headers={'Host':'untrusted.invalid'})[0]==403
    status,raw=request('POST','/api/export',{})
    assert status==200 and json.loads(raw)['document_count']==21
    assert request('GET','/api/exports/queue.json')[0]==200
    assert request('GET','/../../etc/passwd')[0]==404
    report={'origin':'mock; local HTTP smoke, no live model',
            'base_url':f'http://127.0.0.1:{args.port}','counts':queue['counts'],
            'checks':['HTML/JS/CSS served','HTTP intake accepted','21 background results match source-derived routes/hashes',
                      'base64 upload preserves original bytes','detail/history endpoints','cross-origin POST blocked',
                      'unrecognized Host blocked','snapshot export/download','path traversal rejected'],
            'browser_interaction_tested':False}
    (ROOT/'planning/http-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
