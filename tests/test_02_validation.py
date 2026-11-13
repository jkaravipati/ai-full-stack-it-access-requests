import copy
import hashlib
import json
from tests.support import OfflineTest, body, source, ROOT


class ValidationTests(OfflineTest):
    def test_T02_schema_required_types_enums_and_arrays(self):
        from access_intake.validation import validate_extraction
        e = body()['extraction']
        validate_extraction(e, source().message)
        for field in e:
            missing = copy.deepcopy(e)
            del missing[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                validate_extraction(missing, source().message)
            wrong = copy.deepcopy(e)
            wrong[field] = 123
            with self.subTest(type=field), self.assertRaises(ValueError):
                validate_extraction(wrong, source().message)
        for invalid in [[], None, 'text', dict(e, extra=True)]:
            with self.assertRaises(ValueError):
                validate_extraction(invalid, source().message)
        for field, values in [('kind',['new','change','withdrawal','other',None]),
                              ('environment',['staging','production',None]),
                              ('permission',['read','write','admin',None])]:
            for value in values:
                validate_extraction(dict(e, **{field:value}), source().message)
            with self.assertRaises(ValueError):
                validate_extraction(dict(e, **{field:'unexpected'}), source().message)
        for field in ['supporting_quotes','issues']:
            with self.assertRaises(ValueError):
                validate_extraction(dict(e, **{field:[False]}), source().message)
        for field in [k for k in e if k not in ('issues','supporting_quotes')]:
            validate_extraction(dict(e, **{field:None}), source().message)

    def test_T03_bytes_filename_metadata_decoding_and_invalid_inputs(self):
        from access_intake.validation import load_source, validate_extraction
        original = source()
        source_message = json.loads(original.raw.decode('utf-8'))['message']
        self.assertEqual(original.message, source_message)
        self.assertEqual(original.source_sha256, hashlib.sha256(original.raw).hexdigest())
        self.assertEqual(original.document_id, 'IT-001.json')
        altered = self.variant(original.message)
        self.assertEqual(altered.message, source_message)
        self.assertNotEqual(altered.source_sha256, original.source_sha256)
        self.assertEqual(altered.metadata['exported_at'], '2099-01-01T00:00:00Z')
        escaped = original.raw.replace(b'Maya', b'\\u004daya')
        self.assertEqual(load_source('IT-001.json', escaped).message, source_message)
        e = body()['extraction']
        with self.assertRaises(ValueError):
            validate_extraction(dict(e, supporting_quotes=['fabricated quote']), original.message)
        for raw in [b'\xff', b'{', b'[]', b'{}', b'{"message":42}', b'{"message":"a","message":"b"}']:
            with self.assertRaises(ValueError):
                load_source('bad.json', raw)
        with self.assertRaises(OSError):
            load_source(self.dir / 'unreadable.json')
