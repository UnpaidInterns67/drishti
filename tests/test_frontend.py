import unittest
from pathlib import Path


FRONTEND = Path(__file__).parents[1] / "web"


class FrontendAssetTests(unittest.TestCase):
    def test_entrypoint_references_local_assets(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")

        self.assertIn('href="/assets/styles.css"', html)
        self.assertIn('src="/assets/app.js"', html)
        self.assertIn('id="document-input"', html)
        self.assertIn('id="camera"', html)
        self.assertIn('id="decision-panel"', html)
        self.assertIn('id="record-search"', html)
        self.assertIn('id="status-filter"', html)
        self.assertIn('id="audit-list"', html)
        self.assertIn('id="login-form"', html)
        self.assertIn('id="active-checkpoint"', html)
        self.assertIn('id="logout-button"', html)
        self.assertIn('id="history-section"', html)
        self.assertIn('id="identity-graph"', html)
        self.assertIn('id="graph-detail"', html)
        self.assertIn('id="capture-quality"', html)
        self.assertIn('id="inspection-panel"', html)
        self.assertIn('id="decision-path"', html)
        self.assertIn("Travel / identity document", html)
        self.assertIn("authorized officer retains the final decision", html)
        self.assertIn('id="disposition-panel"', html)
        self.assertIn('data-disposition="REFERRED"', html)
        self.assertNotIn('id="offline-kyc-input"', html)
        self.assertNotIn('id="offline-kyc-share-code"', html)

    def test_synthetic_demo_controls_and_routes(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")
        for control in ("demo-panel", "demo-scenarios", "demo-result-notice", "demo-recapture", "demo-exit"):
            self.assertIn(f'id="{control}"', html)
        self.assertIn("No real faces", html)
        self.assertIn("/demo/scenarios", javascript)
        self.assertIn("/demo/runs/${state.sessionId}/recapture", javascript)
        self.assertIn('"demo/runs" : "screenings"', javascript)
        self.assertIn("Open temporary synthetic audit", javascript)

    def test_client_uses_the_screening_workflow(self):
        javascript = (FRONTEND / "app.js").read_text(encoding="utf-8")

        self.assertIn('/screenings/${state.sessionId}/face/start', javascript)
        self.assertIn('/screenings/${state.sessionId}/face/frame', javascript)
        self.assertIn('/screenings/${state.sessionId}/finalize', javascript)
        self.assertIn('method: "DELETE"', javascript)
        self.assertIn("function renderHistory()", javascript)
        self.assertIn("async function loadAudit(sessionId)", javascript)
        self.assertIn('headers.set("X-CSRF-Token", state.csrfToken)', javascript)
        self.assertIn("async function changeCheckpoint()", javascript)
        self.assertIn("async function restoreSession()", javascript)
        self.assertIn('officer.role !== "ADMIN"', javascript)
        self.assertNotIn("X-Admin-Key", javascript)
        self.assertNotIn("/screenings/aadhaar-offline-kyc", javascript)
        self.assertIn("UIDAI DIGITAL SIGNATURE VALID", javascript)
        self.assertIn("function renderIdentityGraph(graph)", javascript)
        self.assertIn("new ResizeObserver(draw)", javascript)
        self.assertIn("function renderCaptureQuality(face)", javascript)
        self.assertIn("function renderSecondaryInspection(inspection)", javascript)
        self.assertIn("DOCUMENT CAPTURE QUALITY PASSED", javascript)
        self.assertIn("Authenticity assurance", javascript)
        self.assertIn("async function recordDisposition(decision)", javascript)
        self.assertIn("Front photo vs signed QR", javascript)
        self.assertIn("differs from signed QR portrait", javascript)


if __name__ == "__main__":
    unittest.main()
