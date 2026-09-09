"""Authenticated synthetic walkthrough integration and isolation checks."""
from dataclasses import replace
from unittest.mock import patch
import unittest
from fastapi.testclient import TestClient
from backend.main import app, database
from backend.auth import auth_service
from backend.config import settings
from backend import demo


class DemoTests(unittest.TestCase):
    def setUp(self):
        auth_service.create_officer_for_test('demo-test', 'synthetic-test-password-123', role='OFFICER')
        self.client = TestClient(app, base_url='https://testserver')
        self.client.__enter__()
        login = self.client.post('/api/v1/auth/login', json={'username':'demo-test','password':'synthetic-test-password-123'})
        self.client.headers['X-CSRF-Token'] = login.json()['csrf_token']
        self.config = patch('backend.demo.settings', replace(settings, demo_enabled=True))
        self.config.start()

    def tearDown(self):
        self.config.stop()
        self.client.__exit__(None,None,None)
        demo._runs.clear()

    def test_walkthroughs_and_recapture_are_isolated(self):
        before = database.list_screenings(200)
        expected = {'clean-clearance':'APPROVE','document-inconsistency':'RETRY','poor-capture':'RETRY','identity-conflict':'REJECT'}
        for scenario, decision in expected.items():
            response = self.client.post('/api/v1/demo/scenarios/' + scenario)
            self.assertEqual(response.status_code, 200, response.text)
            snapshot = response.json()
            self.assertTrue(snapshot['synthetic'])
            self.assertEqual(snapshot['final']['decision'], decision)
            run = snapshot['session_id']
            self.assertIsNone(database.get_screening(run))
            if scenario == 'document-inconsistency':
                mismatch = next(item for item in snapshot['final']['evidence'] if item['code'] == 'OCR_MRZ_MISMATCH')
                self.assertIn('DEMO0002', mismatch['message'])
                self.assertIn('DEMO0001', mismatch['message'])
            if scenario == 'identity-conflict':
                self.assertEqual(snapshot['final']['continuity']['status'], 'IDENTITY_CONFLICT')
                self.assertEqual(snapshot['final']['secondary_inspection']['primary_action']['actor'], 'SUPERVISOR')
                self.assertTrue(snapshot['final']['continuity']['graph']['nodes'])
                denied = self.client.post(f'/api/v1/demo/runs/{run}/disposition', json={'decision':'CLEARED','reason_code':'SUPERVISOR_DIRECTION'})
                self.assertEqual(denied.status_code, 403)
            if scenario == 'poor-capture':
                self.assertIn('IMAGE_RECAPTURE_REQUIRED', snapshot['final']['reasons'])
                self.assertNotIn('POSSIBLE_TAMPERING', snapshot['final']['reasons'])
                recapture = self.client.post(f'/api/v1/demo/runs/{run}/recapture').json()
                self.assertEqual(recapture['final']['decision'], 'APPROVE')
                self.assertTrue(recapture['demo']['recaptured'])
            result = self.client.post(f'/api/v1/demo/runs/{run}/disposition', json={'decision':'REFERRED' if decision != 'APPROVE' else 'CLEARED','reason_code':'DOCUMENT_EXAMINATION'})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.json()['final']['officer_disposition']['synthetic'])
            self.assertEqual(self.client.get(f'/api/v1/demo/runs/{run}/audit').json()['events'][-1]['event_type'], 'SYNTHETIC_DISPOSITION_RECORDED')
        self.assertEqual(before, database.list_screenings(200))

    def test_disabled_production_csrf_and_ownership(self):
        with patch('backend.demo.settings', replace(settings, demo_enabled=False)):
            self.assertEqual(self.client.post('/api/v1/demo/scenarios/clean-clearance').status_code,404)
        with patch('backend.demo.settings', replace(settings, demo_enabled=True, environment='production')):
            self.assertFalse(self.client.get('/api/v1/demo/scenarios').json()['enabled'])
            self.assertEqual(self.client.post('/api/v1/demo/scenarios/clean-clearance').status_code,404)
        run = self.client.post('/api/v1/demo/scenarios/clean-clearance').json()['session_id']
        self.assertEqual(self.client.post(f'/api/v1/demo/runs/{run}/recapture').status_code,409)
        self.assertEqual(self.client.post(f'/api/v1/screenings/{run}/finalize', json={}).status_code,404)
        demo._runs[run]['owner'] = -1
        self.assertEqual(self.client.get(f'/api/v1/demo/runs/{run}/audit').status_code,404)
        self.assertEqual(self.client.post('/api/v1/demo/scenarios/unknown').status_code,404)
        self.client.headers.pop('X-CSRF-Token')
        self.assertEqual(self.client.post('/api/v1/demo/scenarios/clean-clearance').status_code,403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/v1/demo/scenarios').status_code,401)
