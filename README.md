# TestPilot

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](tests/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%20%7C%20Cross--Platform-lightgrey.svg)]()

**TestPilot** is a high-performance Python automation system for Chrome DOM inspection, visual accessibility auditing, and automated competitive exam testing via Google Chrome DevTools Protocol (CDP) and Google Gemini Vision AI.

---

## 🌟 Key Capabilities

### 1. Modern Light Theme Live Dashboard (`dashboard.py`)
- **TestPilot UI**: Modern Apple/Linear design system featuring clean typography, light neutral palettes, subtle borders, and smooth transitions.
- **Auto Tab Discovery**: Automatically enumerates open CDP targets, detects test sessions (`pw.live/practice-v2`), and binds with 1 click.
- **Vision Inference & Reasoning Engine**: Submits high-resolution stem images to Gemini Vision (`gemini-flash-lite-latest` default for ~1.8s sub-second latency) requesting strict structured JSON (`answer: A|B|C|D`, `confidence: HIGH|MEDIUM|LOW`, step-by-step reasoning).
- **Anti-Trap Competitive Exam Reasoning**: Specialized prompts tailored for multi-statement questions, checking exact rocket/missile nomenclature, enactment vs amendment dates, beneficiary vs co-investor distinctions, extreme qualifiers, and statement counting traps.
- **Fail-Safe DOM Execution**: Native Playwright CDP locator clicking with smooth viewport centering and verified DOM state confirmation before submitting answers.

### 2. Live On-Screen HUD Overlay & Question Palette Tracking
- **TestPilot In-Browser HUD**: Injects a live HUD overlay directly onto the active exam tab displaying solving state, current question number, model latency, and countdown pacing.
- **DOM Question Palette Tracking**: Real-time inspection of test navigation chips, tracking:
  - Total Questions
  - Questions Answered (Green)
  - Questions Not Answered (Red)
  - Questions Left to Attempt
  - Questions Not Visited (Grey)

### 3. Comprehensive Diagnostic & Security Suite (`main.py`)
- **DOM Hierarchy Analysis**: Element counts, unique IDs, classes, tag frequencies, and maximum DOM nesting depth.
- **Question Presentation Modalities**: Identifies if questions are rendered via `HTML_TEXT`, `IMAGE_BASED`, `CANVAS_BASED`, `SVG_BASED`, or `HYBRID`.
- **Accessibility Tree Audit**: CDP `Accessibility.getFullAXTree` audits flagging unlabelled controls, missing alt text, and broken landmarks.
- **Deliverables**: Produces `dom_report.json` and interactive standalone `dom_report.html`.

---

## 📁 Repository Structure

```
sandBox/
├── .github/
│   └── workflows/
│       └── build_release.yml      # Automated GitHub Actions workflow for Windows TestPilot.exe releases
├── packaging/
│   ├── pyinstaller.spec           # PyInstaller build specification (TestPilot.exe)
│   └── build_windows_exe.bat      # 1-click script to compile Windows executable
├── scripts/
│   ├── launch_chrome_debug.bat    # 1-click script to start Chrome on port 9222
│   ├── run_dashboard.bat          # 1-click script to launch TestPilot Dashboard (port 8000)
│   ├── run_gui.bat                # 1-click script to launch TestPilot desktop GUI
│   └── run_diagnostics.bat        # 1-click script to run CDP diagnostics
├── tests/
│   ├── __init__.py
│   ├── test_diagnostics.py        # End-to-end integration and DOM unit tests (100% PASS)
│   └── test_solver.py             # Solver option mapping & schema tests
├── accessibility_inspector.py     # CDP accessibility tree inspection
├── chrome_connector.py            # Chrome process detector & CDP connector
├── dashboard.py                   # FastAPI + Uvicorn real-time live solver dashboard
├── demo_server.py                 # Mock assessment server for offline testing
├── dom_inspector.py               # DOM structure, interactive elements & metrics
├── gui.py                         # PySide6 desktop GUI interface
├── image_analyzer.py              # Visual structure & question modality detection
├── main.py                        # CLI entrypoint and diagnostic orchestrator
├── report_generator.py            # JSON and HTML report renderer
├── test_automation.py             # Headless question solver CLI worker
├── pyproject.toml                 # PEP 621 packaging metadata & CLI commands (testpilot)
├── requirements.txt               # Production dependencies
├── requirements-dev.txt           # Development, test, and packaging dependencies
├── .gitignore                     # Git ignore rules (protects API keys, dumps, logs)
├── .gitattributes                 # Line-ending normalizations (CRLF for .bat, LF for code)
├── LICENSE                        # MIT License
└── README.md                      # Documentation
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
playwright install chromium
```

### 2. Configure Gemini API Key
Create a `.gemini_key.txt` file in the project root containing your Gemini API key (this file is ignored by git), or set the environment variable:
```cmd
set GEMINI_API_KEY=your_api_key_here
```

### 3. Launch Chrome with Remote Debugging
Double-click `scripts\launch_chrome_debug.bat`, or run from terminal:
```cmd
scripts\launch_chrome_debug.bat
```
Navigate to your exam session on the opened Chrome window.

### 4. Start TestPilot Dashboard
Double-click `scripts\run_dashboard.bat`, or run:
```bash
python dashboard.py --port 8000
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser:
- Select the active exam tab from the dropdown.
- Choose your model (`gemini-flash-lite-latest` recommended for sub-2s inference).
- Click **Solve 1 Step** to inspect the first question or **Start Auto** to run unattended testing.

---

## 🧪 Running the Test Suite

Run all unit and integration tests:
```bash
python -m unittest discover tests
```
Or with `pytest`:
```bash
pytest tests/
```

All 11 tests validate process detection, offline DOM parsing, modality classification, JSON/HTML report generation, and full end-to-end headless diagnostics.

---

## 📦 Windows Release & Packaging

### Local Compilation
To compile a standalone Windows `.exe` locally:
```cmd
packaging\build_windows_exe.bat
```
The output executable will be placed in `dist\TestPilot.exe`.

### Automated GitHub Releases
The repository includes a GitHub Actions release pipeline (`.github/workflows/build_release.yml`).
To publish a new Windows release:
```bash
git tag v1.0.0
git push origin v1.0.0
```
GitHub Actions will automatically run the test suite, compile the executable on `windows-latest`, package it into `TestPilot-Windows-x64.zip`, and publish the release on GitHub.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
