import base64
import json
import subprocess
import sys
import time
from tests.support import OfflineTest, ROOT, source


GUARDED_CLI = '''
import runpy,sys
from tests.support import OfflineTest
guard=OfflineTest(); guard.setUp()
sys.argv=['access_intake']+sys.argv[1:]
try: runpy.run_module('access_intake',run_name='__main__')
finally: guard.doCleanups()
'''


class InterfaceTests(OfflineTest):
    def cli(self,*args):
        result=subprocess.run([sys.executable,'-c',GUARDED_CLI,*map(str,args)],cwd=ROOT,
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        return json.loads(result.stdout)

    def test_T31_cli_intake_inspect_history_resume_and_export(self):
        inputs=self.dir/'inputs'
        inputs.mkdir()
        for n in [1,2,10]: (inputs/source(n).document_id).write_bytes(source(n).raw)
        state=self.dir/'cli.db'
        common=['--state',state]
        result=self.cli('intake',inputs,'--provider','mock','--mock-responses',ROOT/'tests/mock_responses',*common)
        self.assertEqual(result['count'],3)
        queue=self.cli('queue',*common)
        by_id={r['document_id']:r for r in queue['records']}
        self.assertEqual(by_id['IT-001.json']['next_action'],'review-request')
        self.assertEqual(by_id['IT-002.json']['next_action'],'review-risk-then-owner')
        self.assertEqual(by_id['IT-010.json']['next_action'],'clarify')
        details=self.cli('inspect','IT-001.json',*common)
        self.assertEqual(details['record']['extraction']['requester'],'Maya Chen')
        self.assertEqual(details['message'],source(1).message)
        self.cli('resume',*common)
        self.cli('retry','IT-001.json',*common)
        self.assertEqual(len(self.cli('history','IT-001.json',*common)['attempts']),2)
        exported=self.cli('export','--output',self.dir/'deliverables',*common)
        self.assertEqual(exported['document_count'],3)
        self.assertEqual(len(json.loads((self.dir/'deliverables/queue.json').read_text())),3)

    def test_T32_two_hundred_word_message(self):
        from access_intake.engine import Intake
        from access_intake.providers import MockProvider
        from access_intake.validation import load_source
        s=load_source(ROOT/'tests/inputs/200-words/IT-P01.json')
        self.assertEqual(len(s.message.split()),200)
        e=Intake(self.dir/'size.db',provider=MockProvider(ROOT/'tests/mock_responses'))
        e.ingest([s])
        r=e.store.inspect('IT-P01.json')
        self.assertEqual(r['next_action'],'review-request')
        self.assertEqual(r['extraction']['start_date'],'2026-10-23')

    def test_T40_service_background_intake_upload_retry_and_history(self):
        from access_intake.service import OperatorApp
        from access_intake.engine import Intake
        from access_intake.providers import MockProvider
        e=Intake(self.dir/'api.db',provider=MockProvider(ROOT/'tests/mock_responses'))
        app=OperatorApp(e,ROOT/'materials/requests',self.dir/'api-exports')
        app.start()
        try:
            status,data=app.dispatch('POST','/api/intake',{'exports':[{
                'filename':'IT-001.json','data_base64':base64.b64encode(source(1).raw).decode()}]})
            self.assertEqual(status,202)
            until=time.monotonic()+3
            while time.monotonic()<until:
                status,data=app.dispatch('GET','/api/queue')
                if data['records'] and data['records'][0]['status']=='review': break
                time.sleep(.01)
            self.assertEqual(data['records'][0]['next_action'],'review-request')
            self.assertEqual(app.dispatch('GET','/api/documents/IT-001.json')[1]['message'],source(1).message)
            self.assertEqual(app.dispatch('POST','/api/documents/IT-001.json/retry',{})[0],202)
            self.assertEqual(app.dispatch('POST','/api/resume',{})[0],202)
            self.assertEqual(app.dispatch('GET','/api/documents/IT-001.json/history')[0],200)
            self.assertEqual(app.dispatch('GET','/api/documents/unknown.json')[0],404)
            self.assertEqual(app.dispatch('POST','/api/intake',{'exports':[{'filename':'../escape.json','data_base64':'e30='}]})[0],400)
        finally: app.close()

    def test_T41_web_dashboard_is_served_and_untrusted_data_is_text(self):
        from access_intake.service import OperatorApp
        from access_intake.engine import Intake
        from access_intake.providers import MockProvider
        app=OperatorApp(Intake(self.dir/'web.db',provider=MockProvider(ROOT/'tests/mock_responses')),
                        ROOT/'materials/requests',self.dir/'web-exports')
        status,html=app.dispatch('GET','/')
        self.assertEqual(status,200)
        for label in ['Start intake','Upload exports','Resume unfinished','Export snapshot','History','Source message']:
            self.assertIn(label,html)
        status,script=app.dispatch('GET','/app.js')
        self.assertEqual(status,200)
        self.assertIn('/api/intake',script)
        self.assertIn('/api/queue',script)
        self.assertIn('textContent',script)
        self.assertNotIn('innerHTML',script)
        self.assertEqual(app.dispatch('GET','/../../etc/passwd')[0],404)
