"""
test_diagnostics.py - Comprehensive Unit & Integration Tests

Validates:
1. Chrome process detection and CDP endpoint reachability checks.
2. Semantic DOM parsing via BeautifulSoup.
3. Question container detection and modality classification (HTML, Image, Canvas, SVG).
4. Accessibility audit structure.
5. JSON and HTML diagnostic report generation.
6. Full end-to-end inspection against the demo assessment testbed.
"""

import json
import os
import sys
import unittest

# Ensure root directory is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bs4 import BeautifulSoup

from chrome_connector import check_cdp_endpoint, detect_chrome_processes
from demo_server import DEMO_HTML, start_demo_server
from dom_inspector import DOMInspector
from main import run_diagnostics
from report_generator import ReportGenerator


class TestChromeConnector(unittest.TestCase):
    """Test process detection and CDP endpoint querying."""

    def test_process_detection(self):
        is_running, count, details = detect_chrome_processes()
        self.assertIsInstance(is_running, bool)
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)

    def test_cdp_endpoint_offline(self):
        # Port 59999 should not have a CDP server
        ok, ver, tabs, err = check_cdp_endpoint(host="127.0.0.1", port=59999, timeout=0.5)
        self.assertFalse(ok)
        self.assertIsNone(ver)
        self.assertEqual(tabs, [])
        self.assertIn("Connection refused", err)


class TestDOMAndImageAnalysis(unittest.TestCase):
    """Test semantic DOM extraction and question analysis on sample HTML."""

    def setUp(self):
        self.soup = BeautifulSoup(DEMO_HTML, "html.parser")

    def test_bs4_structure_extraction(self):
        inspector = DOMInspector(page=None)
        structure = inspector.extract_structure_bs4(self.soup)

        self.assertGreater(structure["total_elements"], 10)
        self.assertIn("div", [t["tag"] for t in structure["top_tags"]])

        landmarks = structure["semantic_landmarks"]
        self.assertGreater(landmarks["header"], 0)
        self.assertGreater(landmarks["main"], 0)

    def test_interactive_elements_extraction(self):
        inspector = DOMInspector(page=None)
        interactive = inspector.extract_interactive_elements(page=None, soup=self.soup)

        self.assertGreater(len(interactive["radios"]), 0)
        self.assertGreater(len(interactive["buttons"]), 0)

        # Check question 1 radio
        radio_ids = [r["id"] for r in interactive["radios"]]
        self.assertIn("q1-opt-a", radio_ids)

    def test_question_container_classification(self):
        inspector = DOMInspector(page=None)
        q_elements = inspector.detect_question_containers(page=None, soup=self.soup)

        self.assertGreaterEqual(len(q_elements), 3)

        # Verify modalities detected
        modalities = {q["modality"] for q in q_elements}
        self.assertIn("HTML_TEXT", modalities)
        self.assertIn("IMAGE_BASED", modalities)
        self.assertIn("CANVAS_BASED", modalities)


class TestReportGenerator(unittest.TestCase):
    """Test serialization of report dictionaries into JSON and HTML."""

    def setUp(self):
        self.output_dir = os.path.join(os.path.dirname(__file__), "test_output")
        os.makedirs(self.output_dir, exist_ok=True)
        self.generator = ReportGenerator(output_dir=self.output_dir)
        self.sample_report = {
            "summary": {
                "browser_connection_status": "CONNECTED",
                "total_dom_elements": 150,
                "question_modalities": {"HTML_TEXT": 1, "IMAGE_BASED": 1},
                "accessibility_issues": 1,
            },
            "restrictions": {"url": "http://127.0.0.1:8765", "title": "Test Page"},
            "dom": {"headings": [{"level": "h1", "text": "Demo Test"}]},
            "accessibility": {
                "summary": {"total_issues": 1},
                "issues": [{"type": "NO_ALT", "role": "img", "description": "Missing alt"}],
            },
        }

    def tearDown(self):
        import shutil
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_json_and_html_generation(self):
        json_path, html_path = self.generator.generate(self.sample_report)

        self.assertTrue(os.path.isfile(json_path))
        self.assertTrue(os.path.isfile(html_path))

        with open(json_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            self.assertEqual(loaded["summary"]["browser_connection_status"], "CONNECTED")

        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Demo Test", content)
            self.assertIn("HTML_TEXT", content)


class TestDemoAssessmentEndToEnd(unittest.TestCase):
    """End-to-end integration test against local mock assessment server."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.url = start_demo_server(port=8765)

    def test_demo_run_diagnostics(self):
        out_dir = os.path.join(os.path.dirname(__file__), "e2e_output")
        try:
            report = run_diagnostics(
                port=9222,
                target_url=self.url,
                demo_mode=True,
                output_dir=out_dir,
            )

            self.assertEqual(report["summary"]["browser_connection_status"], "CONNECTED")
            self.assertGreater(report["summary"]["total_dom_elements"], 20)
            self.assertGreaterEqual(len(report["dom"]["detected_questions"]), 3)

            # Confirm artifacts exist
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "dom_report.json")))
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "dom_report.html")))
        finally:
            import shutil
            if os.path.exists(out_dir):
                shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
