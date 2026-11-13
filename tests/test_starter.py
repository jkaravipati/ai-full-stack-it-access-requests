"""Starter tests: the supplied files load, and a test can use a mock response with no network.

Run from the repository root with API_KEY unset:

    env -u API_KEY python3 -m unittest discover -s tests

Your own tests go beside this file. Keep them on mock responses (tests/mock_responses/), so they
run the same way every time, with no model key and no network.
"""
import hashlib
import json
import unittest
from pathlib import Path
from tests.support import OfflineTest

ROOT = Path(__file__).resolve().parents[1]
MOCKS = ROOT / "tests" / "mock_responses"


def canned_reply(name: str) -> dict:
    """What a mock provider returns: the saved reply, read from disk instead of asking a model."""
    return json.loads((MOCKS / f"{name}.json").read_text(encoding="utf-8"))


class SuppliedFiles(OfflineTest):
    def test_each_request_export_has_message_text_and_a_hash(self):
        exports = sorted((ROOT / "materials" / "requests").glob("*.json"))
        self.assertEqual(len(exports), 20)
        entries = canned_reply('manifest')['entries']
        for path in exports:
            raw = path.read_bytes()
            self.assertIsInstance(json.loads(raw.decode("utf-8"))["message"], str, path.name)
            digest = hashlib.sha256(raw).hexdigest()
            self.assertEqual(len(digest), 64)
            self.assertTrue(any(entry['document_id'] == path.name
                                and entry['source_sha256'] == digest
                                and entry['operation'] == 'extraction'
                                for entry in entries), path.name)

    def test_the_schema_names_the_fields_it_requires(self):
        schema = json.loads((ROOT / "snapshot.schema.json").read_text(encoding="utf-8"))
        self.assertIn("request_id", schema["required"])
        reply = canned_reply('it-001.complete')
        extraction = json.loads(reply['output'][0]['content'][0]['text'])['extraction']
        self.assertEqual(set(extraction), set(schema['required']))


class MockResponse(OfflineTest):
    def test_a_mock_reply_is_read_with_no_key_and_no_network(self):
        reply = canned_reply("canned-reply")
        self.assertEqual(reply["response_source"], "mock")
        self.assertTrue(reply["output_text"])


if __name__ == "__main__":
    unittest.main()
