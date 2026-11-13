import copy
import json
from tests.support import OfflineTest, ROOT, expected, source, body


def payload(file):
    response = json.loads((ROOT / 'tests/mock_responses' / file).read_text())
    return json.loads(response['output'][0]['content'][0]['text'])


class PolicyTests(OfflineTest):
    def prepare(self, n, assessment=None):
        from access_intake.policy import prepare
        s = source(n)
        return prepare(s, body(n), assessor=lambda: assessment)

    def assert_route(self, result, status, owner, action):
        self.assertEqual((result['status'],result['owner'],result['next_action']), (status,owner,action))

    def test_T04_complete_request(self):
        r = self.prepare(1)
        self.assertEqual(r['extraction'], expected(1)['extraction'])
        self.assert_route(r,'review','System Owner','review-request')

    def test_T05_missing_dates_precede_risk(self):
        r = self.prepare(10)
        self.assertIsNone(r['extraction']['end_date'])
        self.assert_route(r,'needs-information','IT Service Desk','clarify')

    def test_T06_conflicts_preserve_alternatives(self):
        for n, field in [(4,'environment'),(20,'manager')]:
            r = self.prepare(n)
            self.assertIsNone(r['extraction'][field])
            self.assertEqual(r['extraction']['supporting_quotes'],expected(n)['extraction']['supporting_quotes'])
            self.assertEqual(r['next_action'],'clarify')

    def test_T07_missed_override_is_assessed_with_context(self):
        from access_intake.policy import prepare
        for file in ['it-006.override.json','it-006.missed-override.json']:
            calls=[]
            def assess():
                calls.append('assessment')
                return payload('it-006.override-assessment.true.json')
            r=prepare(source(6),payload(file),assessor=assess)
            self.assertEqual(calls,['assessment'])
            self.assertEqual(r['extraction']['permission'],'read')
            self.assert_route(r,'review','IT Service Desk','inspect-message')
            self.assertTrue(r['extraction']['issues'])

    def test_T08_withdrawal_exception(self):
        from access_intake.policy import prepare
        r=self.prepare(5)
        self.assertEqual(r['next_action'],'confirm-withdrawal')
        from access_intake.validation import load_source
        s=load_source(ROOT/'tests/inputs/minimal-withdrawal/IT-005.json')
        b=payload('it-005.minimal-withdrawal.json')
        r=prepare(s,b)
        self.assertEqual(r['next_action'],'confirm-withdrawal')

    def test_T09_production_write_and_admin_risk(self):
        for n in [2,7,12,13]:
            self.assert_route(self.prepare(n),'review','Security Review','review-risk-then-owner')

    def test_T10_explicit_corrections(self):
        self.assertEqual(self.prepare(8)['extraction']['environment'],'staging')
        r=self.prepare(15)
        self.assertEqual(r['extraction']['start_date'],'2026-10-29')
        self.assertEqual(r['extraction']['end_date'],'2026-10-31')
        self.assertEqual(r['next_action'],'review-request')

    def test_T11_change_uses_new_permission(self):
        r=self.prepare(19)
        self.assertEqual(r['extraction']['kind'],'change')
        self.assertEqual(r['extraction']['permission'],'read')
        self.assertEqual(r['next_action'],'review-risk-then-owner')

    def test_T12_identifier_mismatch(self):
        r=self.prepare(16)
        self.assertEqual(r['extraction']['request_id'],'IT-061')
        self.assertEqual(r['next_action'],'clarify')

    def test_T13_reversed_date_range_is_not_swapped(self):
        r=self.prepare(14)
        self.assertEqual(r['extraction']['start_date'],'2026-11-05')
        self.assertEqual(r['next_action'],'clarify')

    def test_T14_each_required_fact_and_other_kind(self):
        from access_intake.policy import prepare
        # Independent oracle: office-policy.md, Review queue rule 3, and
        # planning/plan.md T-14. Never import the app's required-field list:
        # dropping a field from implementation must not also drop its test.
        required_facts = [
            'request_id', 'request_date', 'requester', 'team', 'system',
            'environment', 'permission', 'business_purpose', 'start_date',
            'end_date', 'manager',
        ]
        for n in [3,9,17]: self.assertEqual(self.prepare(n)['next_action'],'clarify')
        cases=json.loads((ROOT/'tests/mock_responses/required-fact-omissions.json').read_text())['cases']
        self.assertEqual(len(cases),22)
        self.assertEqual({case['omitted_field'] for case in cases},set(required_facts))
        for case in cases:
            s=self.variant(case['message'],case['document_id'])
            b=json.loads(case['response']['output'][0]['content'][0]['text'])
            r=prepare(s,b)
            self.assertIsNone(r['extraction'][case['omitted_field']])
            self.assertEqual(r['next_action'],'clarify',case['omitted_field'])
        from access_intake.validation import load_source
        s=load_source(ROOT/'tests/inputs/null-kind/IT-001.json')
        r=prepare(s,payload('it-001.null-kind.json'))
        self.assertIsNone(r['extraction']['kind'])
        self.assertEqual(r['next_action'],'clarify')

    def test_T15_relative_dates_not_anchored_to_export(self):
        r=self.prepare(11)
        self.assertIsNone(r['extraction']['start_date'])
        self.assertIsNone(r['extraction']['end_date'])
        self.assertEqual(r['next_action'],'clarify')

    def test_T16_priority_matrix(self):
        from access_intake.policy import prepare
        from access_intake.validation import load_source
        s=load_source(ROOT/'tests/inputs/withdrawal-override/IT-006.json')
        b=payload('it-006.withdrawal-override.json')
        r=prepare(s,b,assessor=lambda:payload('it-006.override-assessment.true.json'))
        self.assertEqual(r['next_action'],'inspect-message')
        s=self.variant(source(5).message,'different.json')
        self.assertEqual(prepare(s,body(5))['next_action'],'confirm-withdrawal')

    def edge(self, slug, assessor=None):
        from access_intake.validation import load_source
        from access_intake.policy import prepare
        s=load_source(ROOT/'tests/inputs'/slug/'IT-P01.json')
        return prepare(s,payload(f'it-p01.{slug}.json'),assessor=assessor)

    def test_T37_unusable_source_facts(self):
        for slug,field,code in [('invalid-date','start_date','invalid_date'),('ambiguous-date','start_date','ambiguous_date'),('blank-manager','manager','missing')]:
            r=self.edge(slug)
            self.assertIsNone(r['extraction'][field])
            self.assertEqual(r['next_action'],'clarify')
            self.assertIn(code,[a['code'] for a in r['review_evidence']['issue_annotations']])

    def test_T38_quoted_attack_is_not_an_actual_attempt(self):
        calls=[]
        def assess():
            calls.append(1)
            return payload('it-p01.assessment.false.json')
        r=self.edge('quoted-attack',assess)
        self.assertEqual(calls,[1])
        self.assertEqual(r['next_action'],'review-request')
        self.assertFalse(any(a['code']=='instruction_override' for a in r['review_evidence']['issue_annotations']))
        def failed(): raise ValueError('assessment unavailable')
        with self.assertRaises(ValueError): self.edge('quoted-attack',failed)

    def test_T39_correction_intent_and_invalid_replacement(self):
        self.assertEqual(self.edge('clear-correction')['extraction']['end_date'],'2026-11-07')
        r=self.edge('uncorrected-conflict')
        self.assertIsNone(r['extraction']['end_date'])
        self.assertEqual(r['next_action'],'clarify')
        r=self.edge('unusable-correction')
        self.assertIsNone(r['extraction']['end_date'])
        self.assertEqual(r['next_action'],'clarify')
