import copy
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from crw.extraction import (NOTES, DEMO, demo_extraction, validate_extraction,
                            validate_local_url, ollama_extract, record_review)


def payload(note='A 未查与计划操作'):
    return {'fields': [dict(field=f, status=s, value=v, evidence=e) for f, s, v, e in DEMO[note]]}


class ExtractionTests(unittest.TestCase):
    def test_demo_marks_not_tested_unknown_and_planned_not_performed(self):
        rows = {r['field']: r for r in demo_extraction('A 未查与计划操作', NOTES['A 未查与计划操作'])}
        self.assertEqual(rows['pathogen']['status'], 'unknown')
        self.assertEqual(rows['procedure_performed']['status'], 'planned')
        self.assertTrue(all(r['review_status'] == 'pending' for r in rows.values()))

    def test_all_synthetic_notes_have_verifiable_spans(self):
        for name, source in NOTES.items():
            for r in demo_extraction(name, source):
                self.assertEqual(source[r['source_start']:r['source_end']], r['evidence'])

    def test_fabricated_quote_and_unsupported_field_are_rejected(self):
        for field, value in [('evidence', '原文根本没有这句话'), ('field', 'diagnosis')]:
            p = payload(); p['fields'][0][field] = value
            with self.assertRaises(ValueError):
                validate_extraction(p, NOTES['A 未查与计划操作'])

    def test_value_not_in_evidence_unknown_value_and_invalid_planned_rejected(self):
        for changes in [dict(value='39.9℃'), dict(status='unknown', value='发热'), dict(status='planned')]:
            p = payload(); p['fields'][0].update(changes)
            with self.assertRaises(ValueError):
                validate_extraction(p, NOTES['A 未查与计划操作'])

    def test_duplicate_fields_and_extra_keys_are_rejected(self):
        p = payload(); p['fields'][1] = copy.deepcopy(p['fields'][0])
        with self.assertRaises(ValueError):
            validate_extraction(p, NOTES['A 未查与计划操作'])
        p = payload(); p['instructions'] = 'override'
        with self.assertRaises(ValueError):
            validate_extraction(p, NOTES['A 未查与计划操作'])

    def test_changed_source_and_missing_reviewer_prevent_review(self):
        source = NOTES['A 未查与计划操作']
        row = demo_extraction('A 未查与计划操作', source)[0]
        with self.assertRaises(ValueError):
            record_review(row, source + '修改', 'accepted', 'reviewer')
        with self.assertRaises(ValueError):
            record_review(row, source, 'accepted', '')
        reviewed = record_review(row, source, 'rejected', 'reviewer', '需复核')
        self.assertEqual(reviewed['review_status'], 'rejected')
        self.assertIn('reviewed_at_utc', reviewed)

    def test_demo_cannot_pretend_to_extract_custom_text(self):
        with self.assertRaises(ValueError):
            demo_extraction('A 未查与计划操作', '自定义病历')

    def test_only_loopback_no_credentials_query_or_redirect_target(self):
        for url in ['https://example.com', 'http://10.0.0.1:11434', 'http://127.0.0.1.evil.test',
                    'http://user:pass@localhost:11434', 'http://localhost:11434/path',
                    'http://localhost:11434?key=x', 'http://localhost:99999']:
            with self.assertRaises(ValueError, msg=url):
                validate_local_url(url)
        self.assertEqual(validate_local_url('http://127.0.0.1:11434/'), 'http://127.0.0.1:11434')

    def test_ollama_adapter_with_mock_server_not_a_model_quality_test(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps({'done': True, 'message': {'content': json.dumps(payload())}}).encode())
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            rows = ollama_extract(NOTES['A 未查与计划操作'], 'mock-only', f'http://127.0.0.1:{server.server_port}')
            self.assertEqual(len(rows), 5)
            self.assertFalse(received[0]['stream'])
            self.assertIn('properties', received[0]['format'])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_http_redirect_is_not_followed(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302); self.send_header('Location', 'http://example.com'); self.end_headers()
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with self.assertRaises(Exception):
                ollama_extract(NOTES['A 未查与计划操作'], 'mock-only', f'http://127.0.0.1:{server.server_port}')
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
