"""
demo_server.py - Local Assessment & Diagnostic Test Server

Serves a rich synthetic test page with:
- HTML text questions
- Image-based questions (stem rendered as image)
- Canvas-based questions (stem drawn on canvas)
- SVG-based questions (vector diagram + prompt)
- Hybrid questions
- Radios, checkboxes, buttons with labels
- Various image states (lazy, visible, hidden, broken)
- Accessibility test cases
Used for automated testing, verification, and offline demos.
"""

import http.server
import socketserver
import threading
from typing import Tuple

DEMO_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sample Online Assessment & Diagnostics Testbed</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f4f6f8;
            margin: 0;
            padding: 24px;
            color: #333;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            background: #fff;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        header {
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 16px;
            margin-bottom: 24px;
        }
        .quiz-card {
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 24px;
            background: #fafafa;
        }
        .question-stem {
            font-size: 1.1rem;
            font-weight: bold;
            margin-bottom: 12px;
        }
        .options-list {
            list-style: none;
            padding: 0;
            margin: 0;
        }
        .options-list li {
            margin: 8px 0;
        }
        .badge {
            background: #0284c7;
            color: white;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
        }
        .canvas-container {
            background: #e2e8f0;
            border: 1px dashed #64748b;
            padding: 10px;
            display: inline-block;
            margin-bottom: 10px;
        }
        .css-bg-box {
            width: 200px;
            height: 80px;
            background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="80"><rect width="200" height="80" fill="%2338bdf8"/><text x="20" y="45" fill="white" font-family="sans-serif" font-size="14">CSS Background Banner</text></svg>');
            background-size: cover;
            border-radius: 4px;
            margin: 10px 0;
        }
        .hidden-element {
            display: none;
        }
        button {
            background-color: #2563eb;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 1rem;
        }
        button:hover {
            background-color: #1d4ed8;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Computer Science & Logic Diagnostic Exam</h1>
            <p>Diagnostic page for DOM element, image modality, and accessibility inspection.</p>
            <div class="css-bg-box" role="img" aria-label="Decorative Exam Banner"></div>
        </header>

        <main>
            <!-- Question 1: Pure HTML Text -->
            <div class="quiz-card question-item" id="q1">
                <span class="badge">Question 1 (HTML Text)</span>
                <p class="question-stem">What is the average time complexity of searching an element in a balanced binary search tree containing N elements?</p>
                <ul class="options-list">
                    <li><label><input type="radio" id="q1-opt-a" name="q1_opt" value="A"> A) O(1)</label></li>
                    <li><label><input type="radio" id="q1-opt-b" name="q1_opt" value="B"> B) O(log N)</label></li>
                    <li><label><input type="radio" id="q1-opt-c" name="q1_opt" value="C"> C) O(N)</label></li>
                    <li><label><input type="radio" id="q1-opt-d" name="q1_opt" value="D"> D) O(N log N)</label></li>
                </ul>
            </div>

            <!-- Question 2: Image-based Question Stem (e.g. anti-scraping / formula image) -->
            <div class="quiz-card question-item" id="q2">
                <span class="badge">Question 2 (Image-Based Stem)</span>
                <div class="image-stem-wrapper" style="margin: 12px 0;">
                    <img src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='450' height='70'><rect width='450' height='70' fill='%231e293b' rx='6'/><text x='15' y='42' fill='%23f8fafc' font-family='sans-serif' font-size='16'>Solve for x: \\int_{0}^{x} (3t^2 + 2) dt = 14</text></svg>"
                         alt="Mathematical formula question rendered as image"
                         width="450"
                         height="70"
                         loading="eager">
                </div>
                <ul class="options-list">
                    <li><label><input type="radio" name="q2_opt" value="A"> A) x = 2</label></li>
                    <li><label><input type="radio" name="q2_opt" value="B"> B) x = 3</label></li>
                    <li><label><input type="radio" name="q2_opt" value="C"> C) x = 4</label></li>
                </ul>
            </div>

            <!-- Question 3: Canvas-based Question Stem (interactive graphics) -->
            <div class="quiz-card question-item" id="q3">
                <span class="badge">Question 3 (Canvas-Based Stem)</span>
                <div class="canvas-container">
                    <canvas id="geometryCanvas" width="400" height="120" style="display:block;"></canvas>
                </div>
                <ul class="options-list">
                    <li><label><input type="radio" name="q3_opt" value="A"> A) Acute Angle</label></li>
                    <li><label><input type="radio" name="q3_opt" value="B"> B) Right Angle</label></li>
                    <li><label><input type="radio" name="q3_opt" value="C"> C) Obtuse Angle</label></li>
                </ul>
            </div>

            <!-- Question 4: SVG-based Vector Question -->
            <div class="quiz-card question-item" id="q4">
                <span class="badge">Question 4 (SVG Vector Stem)</span>
                <div class="svg-stem-container" style="margin: 12px 0;">
                    <svg width="350" height="90" viewBox="0 0 350 90" xmlns="http://www.w3.org/2000/svg">
                        <rect width="350" height="90" fill="#f1f5f9" stroke="#94a3b8" rx="8" />
                        <circle cx="50" cy="45" r="25" fill="#3b82f6" />
                        <text x="90" y="40" font-family="sans-serif" font-size="14" fill="#1e293b">Identify the component</text>
                        <text x="90" y="60" font-family="sans-serif" font-size="12" fill="#64748b">Network Topology Node</text>
                    </svg>
                </div>
                <ul class="options-list">
                    <li><label><input type="radio" name="q4_opt" value="A"> A) Star Hub</label></li>
                    <li><label><input type="radio" name="q4_opt" value="B"> B) Ring Repeater</label></li>
                </ul>
            </div>

            <!-- Question 5: Hybrid Question (Text prompt + supporting image + checkboxes) -->
            <div class="quiz-card question-item" id="q5">
                <span class="badge">Question 5 (Hybrid Question)</span>
                <p class="question-stem">Which of the following database isolation levels prevent dirty reads? Refer to the diagram below:</p>
                <div style="margin: 10px 0;">
                    <img src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='280' height='50'><rect width='280' height='50' fill='%23e0f2fe' rx='4'/><text x='15' y='30' fill='%230369a1' font-family='sans-serif' font-size='13'>ACID Transaction Matrix</text></svg>"
                         alt="Transaction isolation diagram"
                         width="280"
                         height="50"
                         loading="lazy">
                </div>
                <ul class="options-list">
                    <li><label><input type="checkbox" name="q5_opt" value="RC"> Read Committed</label></li>
                    <li><label><input type="checkbox" name="q5_opt" value="RR"> Repeatable Read</label></li>
                    <li><label><input type="checkbox" name="q5_opt" value="SER"> Serializable</label></li>
                    <li><label><input type="checkbox" name="q5_opt" value="RU"> Read Uncommitted</label></li>
                </ul>
            </div>

            <!-- Accessibility / Edge cases testing area -->
            <section id="edge-cases" style="margin-top: 30px; border-top: 1px solid #e2e8f0; padding-top: 20px;">
                <h3>Form Controls & Accessibility Edge Cases</h3>
                <div>
                    <!-- Missing alt image -->
                    <img src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='60' height='60'><rect width='60' height='60' fill='%23cbd5e1'/></svg>"
                         width="60" height="60">
                    
                    <!-- Broken image -->
                    <img src="http://127.0.0.1:9999/non_existent_image.png" alt="Broken test image" width="100" height="50">
                    
                    <!-- Hidden element -->
                    <div class="hidden-element">Hidden secret text not visible to candidate</div>
                </div>

                <div style="margin-top: 15px;">
                    <button type="submit" id="btnSubmit">Submit Assessment</button>
                    <button type="button" id="btnSave">Save Progress</button>
                    <!-- Unlabelled button -->
                    <button type="button" id="btnEmpty" style="width: 30px; height: 30px; padding: 0;"></button>
                </div>
            </section>
        </main>
    </div>

    <script>
        // Draw onto the canvas element
        const canvas = document.getElementById('geometryCanvas');
        if (canvas && canvas.getContext) {
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.strokeStyle = '#0284c7';
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(30, 90);
            ctx.lineTo(150, 90);
            ctx.lineTo(150, 20);
            ctx.closePath();
            ctx.stroke();
            ctx.fillStyle = '#0f172a';
            ctx.font = '14px Arial';
            ctx.fillText('Find angle θ between the hypotenuse and base.', 170, 60);
        }
    </script>
</body>
</html>
"""


class DemoHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Simple HTTP handler serving the demo page."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        body = DEMO_HTML.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress noisy HTTP request logging
        pass


def start_demo_server(port: int = 8765) -> Tuple[socketserver.TCPServer, str]:
    """Start local background HTTP server serving demo page."""
    server = socketserver.TCPServer(("127.0.0.1", port), DemoHTTPHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{port}"
    return server, url

