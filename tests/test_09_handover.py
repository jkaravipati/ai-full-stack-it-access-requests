import json
import subprocess
import sys
from tests.support import OfflineTest,ROOT
from tests.test_07_interfaces import GUARDED_CLI


class HandoverTests(OfflineTest):
    def test_T36_documented_offline_workflow_and_deliverable_contract(self):
        readme=(ROOT/'README.md').read_text()
        for text in ['serve','/api/intake','/api/queue','requirements.lock','API_KEY','mock','accuracy','resume','retry','history']:
            self.assertIn(text,readme)
        for name in ['accuracy.md','request-evidence.json','verification.md']:
            self.assertTrue((ROOT/'deliverables'/name).is_file(),name)
        evidence=json.loads((ROOT/'deliverables/request-evidence.json').read_text())
        self.assertEqual(evidence['configuration']['model'],'gpt-5.6-terra')
        self.assertEqual({r['operation'] for r in evidence['requests']},{'extraction','override_assessment'})
        self.assertIn('[REDACTED]',json.dumps(evidence))
        self.assertNotIn('test-only-credential',json.dumps(evidence))
        self.assertEqual((ROOT/'snapshot.schema.json').read_bytes(),(ROOT/'access_intake/resources/snapshot.schema.json').read_bytes())
        for resource in ['extraction.txt','override_assessment.txt','office-policy.md']:
            self.assertTrue((ROOT/'access_intake/resources'/resource).is_file())
        state=self.dir/'fresh.db'
        def cli(*args):
            completed=subprocess.run([sys.executable,'-c',GUARDED_CLI,*map(str,args),'--state',str(state)],
                                     cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertEqual(completed.returncode,0,completed.stderr)
            return json.loads(completed.stdout)
        cli('intake','materials/requests','--provider','mock')
        inputs=self.dir/'extra'
        inputs.mkdir()
        (inputs/'IT-P01.json').write_bytes((ROOT/'tests/inputs/IT-P01.json').read_bytes())
        cli('intake',inputs,'--provider','mock')
        cli('export','--output',self.dir/'outputs')
        report=cli('accuracy','--expected','tests/expected','--actual',self.dir/'outputs/extractions.jsonl')
        self.assertEqual(report['scalar_matches'],252)
        self.assertEqual(report['route_matches'],63)
        self.assertEqual(report['purpose_review']['unassessed'],21)
