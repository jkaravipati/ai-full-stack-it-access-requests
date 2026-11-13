import copy
import json
from tests.support import OfflineTest, ROOT, expected, source


class AccuracyTests(OfflineTest):
    def engine(self):
        from access_intake.engine import Intake
        from access_intake.providers import MockProvider
        return Intake(self.dir/'accuracy.db',provider=MockProvider(ROOT/'tests/mock_responses'))

    def test_T33_paraphrase_retains_source_grounded_facts(self):
        from access_intake.validation import load_source
        e=self.engine()
        e.ingest([load_source(ROOT/'tests/inputs/IT-P01.json')])
        r=e.store.inspect('IT-P01.json')
        self.assertEqual(r['extraction'],expected('IT-P01.json')['extraction'])
        self.assertEqual(r['next_action'],'review-request')
        self.assertEqual(r['response_source'],'mock')

    def test_T34_all_supplied_messages_match_independent_source_oracles(self):
        from access_intake.accuracy import compare_records
        e=self.engine()
        e.ingest([source(n) for n in range(1,21)])
        oracle=[expected(n) for n in range(1,21)]
        report=compare_records(oracle,e.store.current())
        self.assertEqual(report['scalar_total'],240)
        self.assertEqual(report['scalar_matches'],240)
        self.assertEqual(report['route_matches'],60)
        self.assertEqual(report['structural_errors'],[])
        self.assertEqual(report['quote_errors'],[])
        self.assertEqual(report['issue_errors'],[])

    def test_T35_fixed_denominators_and_wording_not_automatically_factual_error(self):
        from access_intake.accuracy import compare_records
        from access_intake.validation import load_source
        e=self.engine()
        e.ingest([source(n) for n in range(1,21)]+[load_source(ROOT/'tests/inputs/IT-P01.json')])
        actual=e.store.current()
        oracle=[expected(n) for n in range(1,21)]+[expected('IT-P01.json')]
        baseline=compare_records(oracle,actual)
        self.assertEqual((baseline['scalar_matches'],baseline['scalar_total']),(252,252))
        self.assertEqual((baseline['route_matches'],baseline['route_total']),(63,63))
        faithful=json.loads((ROOT/'tests/mock_responses/accuracy.faithful-summary.json').read_text())
        actual[0]['extraction']['business_purpose']=faithful['purpose']
        report=compare_records(oracle,actual,reviews={'IT-001.json':faithful['review']})
        self.assertEqual(report['scalar_matches'],251)
        self.assertEqual(report['purpose_review']['correct'],1)
        self.assertEqual(report['purpose_review']['unassessed'],20)
        self.assertEqual(report['purpose_review']['total'],21)
        self.assertEqual(report['factual_errors'],[])
        false=json.loads((ROOT/'tests/mock_responses/accuracy.false-summary.json').read_text())
        actual[0]['extraction']['business_purpose']=false['purpose']
        report=compare_records(oracle,actual,reviews={'IT-001.json':false['review']})
        self.assertEqual(report['purpose_review']['incorrect'],1)
        self.assertTrue(report['factual_errors'])
        actual[0]['extraction']=None
        report=compare_records(oracle,actual)
        self.assertEqual(report['scalar_total'],252)
        self.assertEqual(report['scalar_matches'],240)
        duplicated=actual+[actual[1]]
        self.assertTrue(compare_records(oracle,duplicated)['structural_errors'])
