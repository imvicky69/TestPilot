"""
gui.py - PySide6 Desktop GUI for Chrome DOM Inspection & Diagnostics

Provides a visual desktop application for detecting Chrome instances, selecting tabs,
running DOM & image diagnostics, and reviewing results interactively.
"""

import os
import sys
import webbrowser
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chrome_connector import check_cdp_endpoint, detect_chrome_processes
from main import run_diagnostics


class DiagnosticWorker(QThread):
    """Background worker to perform DOM and CDP diagnostics without freezing the UI."""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, host: str, port: int, tab_selector: Any, launch_fallback: bool, navigate_url: Optional[str] = None):
        super().__init__()
        self.host = host
        self.port = port
        self.tab_selector = tab_selector
        self.launch_fallback = launch_fallback
        self.navigate_url = navigate_url

    def run(self):
        try:
            res = run_diagnostics(
                host=self.host,
                port=self.port,
                tab_selector=self.tab_selector,
                launch_fallback=self.launch_fallback,
                navigate_url=self.navigate_url,
                output_dir=".",
                headless=False,
            )
            self.finished.emit(res)
        except Exception as exc:
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    """Main Desktop Window for the Chrome DOM Inspection Tool."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TestPilot - Diagnostic Suite & Solver")
        self.resize(1200, 800)
        self.last_results: Optional[Dict[str, Any]] = None
        self.worker: Optional[DiagnosticWorker] = None

        self._setup_style()
        self._init_ui()
        self.refresh_tabs()

    def _setup_style(self):
        """Apply modern dark-theme stylesheet."""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
                color: #38bdf8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #0284c7;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0369a1;
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748b;
            }
            QPushButton#btnDemo {
                background-color: #4f46e5;
            }
            QPushButton#btnDemo:hover {
                background-color: #4338ca;
            }
            QLineEdit, QComboBox {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 10px;
                color: #f8fafc;
            }
            QTableWidget {
                background-color: #1e293b;
                border: 1px solid #334155;
                gridline-color: #334155;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #0f172a;
                color: #94a3b8;
                font-weight: bold;
                border: 1px solid #334155;
                padding: 6px;
            }
            QTabWidget::pane {
                border: 1px solid #334155;
                border-radius: 8px;
                background-color: #1e293b;
            }
            QTabBar::tab {
                background-color: #0f172a;
                color: #94a3b8;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #1e293b;
                color: #38bdf8;
                font-weight: bold;
            }
            QTextEdit {
                background-color: #090d16;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #38bdf8;
                font-family: Consolas, monospace;
            }
        """)

    def _init_ui(self):
        """Construct UI layout and components."""
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Connection Header Box
        conn_box = QGroupBox("Chrome Connection & Target Tab")
        conn_layout = QHBoxLayout(conn_box)

        conn_layout.addWidget(QLabel("Host:"))
        self.host_input = QLineEdit("127.0.0.1")
        self.host_input.setFixedWidth(100)
        conn_layout.addWidget(self.host_input)

        conn_layout.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit("9222")
        self.port_input.setFixedWidth(70)
        conn_layout.addWidget(self.port_input)

        self.btn_launch_chrome = QPushButton("🌐 Launch Chrome (CDP)")
        self.btn_launch_chrome.clicked.connect(self._on_launch_chrome_clicked)
        conn_layout.addWidget(self.btn_launch_chrome)

        self.btn_refresh = QPushButton("🔄 Refresh Tabs")
        self.btn_refresh.clicked.connect(self.refresh_tabs)
        conn_layout.addWidget(self.btn_refresh)

        conn_layout.addWidget(QLabel("Target Tab:"))
        self.tab_combo = QComboBox()
        self.tab_combo.setMinimumWidth(320)
        conn_layout.addWidget(self.tab_combo, 1)

        self.btn_inspect = QPushButton("🚀 Run DOM Diagnostics")
        self.btn_inspect.clicked.connect(self.run_inspection)
        conn_layout.addWidget(self.btn_inspect)

        self.btn_live_dash = QPushButton("⚡ Live Solver Web Dashboard")
        self.btn_live_dash.setStyleSheet("background-color: #059669; color: white;")
        self.btn_live_dash.clicked.connect(self._on_open_live_dashboard)
        conn_layout.addWidget(self.btn_live_dash)

        self.btn_demo = QPushButton("🧪 Run Demo Test")
        self.btn_demo.setObjectName("btnDemo")
        self.btn_demo.clicked.connect(self.run_demo_mode)
        conn_layout.addWidget(self.btn_demo)

        main_layout.addWidget(conn_box)

        # 2. Status & Metric Cards
        metric_layout = QHBoxLayout()

        self.card_status = self._create_card("Connection Status", "DISCONNECTED", "#94a3b8")
        self.card_dom = self._create_card("Total DOM Elements", "0", "#38bdf8")
        self.card_images = self._create_card("Rendered Images", "0", "#fbbf24")
        self.card_canvases = self._create_card("Canvases & SVGs", "0", "#a855f7")
        self.card_interactive = self._create_card("Interactive Elements", "0", "#34d399")
        self.card_questions = self._create_card("Detected Questions", "0", "#f87171")

        for card in [self.card_status, self.card_dom, self.card_images, self.card_canvases, self.card_interactive, self.card_questions]:
            metric_layout.addWidget(card)

        main_layout.addLayout(metric_layout)

        # 3. Tabbed Diagnostic Detail Views
        self.tabs = QTabWidget()

        # Tab 1: Questions
        self.tab_questions = QWidget()
        q_layout = QVBoxLayout(self.tab_questions)
        self.table_questions = QTableWidget(0, 5)
        self.table_questions.setHorizontalHeaderLabels(["#", "Modality", "Prompt / Stem Snippet", "Choices", "Diagnostic Note"])
        self.table_questions.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        q_layout.addWidget(self.table_questions)
        self.tabs.addTab(self.tab_questions, "📝 Question Diagnostics")

        # Tab 2: Images
        self.tab_images = QWidget()
        img_layout = QVBoxLayout(self.tab_images)
        self.table_images = QTableWidget(0, 6)
        self.table_images.setHorizontalHeaderLabels(["#", "Status", "Rendered Size", "Natural Size", "Alt Text", "Source URL"])
        self.table_images.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        img_layout.addWidget(self.table_images)
        self.tabs.addTab(self.tab_images, "🖼️ Rendered Images")

        # Tab 3: Interactive Elements
        self.tab_interactive = QWidget()
        int_layout = QVBoxLayout(self.tab_interactive)
        self.table_interactive = QTableWidget(0, 5)
        self.table_interactive.setHorizontalHeaderLabels(["Type", "Name / ID", "Value", "Associated Label / Text", "State"])
        self.table_interactive.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        int_layout.addWidget(self.table_interactive)
        self.tabs.addTab(self.tab_interactive, "🔘 Interactive Controls")

        # Tab 4: Accessibility
        self.tab_a11y = QWidget()
        a11y_layout = QVBoxLayout(self.tab_a11y)
        self.table_a11y = QTableWidget(0, 4)
        self.table_a11y.setHorizontalHeaderLabels(["Severity", "Role", "Issue Type", "Description"])
        self.table_a11y.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        a11y_layout.addWidget(self.table_a11y)
        self.tabs.addTab(self.tab_a11y, "♿ Accessibility Audit")

        # Tab 5: Logs
        self.tab_logs = QWidget()
        log_layout = QVBoxLayout(self.tab_logs)
        self.log_viewer = QTextEdit()
        self.log_viewer.setReadOnly(True)
        log_layout.addWidget(self.log_viewer)
        self.tabs.addTab(self.tab_logs, "📝 Diagnostics Log")

        main_layout.addWidget(self.tabs, 1)

        # 4. Bottom Action Bar
        bottom_layout = QHBoxLayout()
        self.lbl_report_status = QLabel("Ready. Select a tab or click 'Run Demo Test' to start.")
        bottom_layout.addWidget(self.lbl_report_status, 1)

        self.btn_open_html = QPushButton("🌐 View HTML Dashboard")
        self.btn_open_html.setEnabled(False)
        self.btn_open_html.clicked.connect(self.open_html_report)
        bottom_layout.addWidget(self.btn_open_html)

        self.btn_open_json = QPushButton("📄 View JSON Report")
        self.btn_open_json.setEnabled(False)
        self.btn_open_json.clicked.connect(self.open_json_report)
        bottom_layout.addWidget(self.btn_open_json)

        main_layout.addLayout(bottom_layout)
        self.setCentralWidget(main_widget)

    def _create_card(self, title: str, initial_val: str, color: str) -> QFrame:
        """Create a styled metric card."""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        lbl_title = QLabel(title.upper())
        lbl_title.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold;")
        lbl_val = QLabel(initial_val)
        lbl_val.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_val)
        frame.val_label = lbl_val  # attach reference
        return frame

    def refresh_tabs(self):
        """Query CDP endpoint and update tab dropdown."""
        host = self.host_input.text().strip()
        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            port = 9222

        ok, ver, tabs, err = check_cdp_endpoint(host, port)
        self.tab_combo.clear()

        if ok and tabs:
            self.card_status.val_label.setText("CONNECTED")
            self.card_status.val_label.setStyleSheet("color: #34d399; font-size: 20px; font-weight: bold;")
            for idx, tab in enumerate(tabs):
                title = tab.get("title") or "Untitled"
                url = tab.get("url") or ""
                self.tab_combo.addItem(f"{idx}: {title} ({url[:40]}...)", userData=idx)
            self.lbl_report_status.setText(f"Connected to Chrome ({len(tabs)} tabs found).")
        else:
            self.card_status.val_label.setText("DISCONNECTED")
            self.card_status.val_label.setStyleSheet("color: #f87171; font-size: 20px; font-weight: bold;")
            is_run, count, _ = detect_chrome_processes()
            if is_run:
                self.lbl_report_status.setText(f"Chrome running ({count} procs) but CDP port {port} closed. Start Chrome with --remote-debugging-port={port}")
            else:
                self.lbl_report_status.setText(f"Chrome not detected on {host}:{port}. Click 'Run Demo Test' or launch Chrome.")

    def _on_launch_chrome_clicked(self):
        """Launch Chrome with remote debugging on port 9222."""
        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            port = 9222
        from main import launch_debug_chrome
        launch_debug_chrome(port)
        self.lbl_report_status.setText(f"Launching Chrome on port {port}... waiting for tabs.")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, self.refresh_tabs)

    def _on_open_live_dashboard(self):
        """Start or open the Live Question Solver Web Dashboard."""
        import subprocess
        import webbrowser
        # Launch dashboard.py in background if not already running
        subprocess.Popen([sys.executable, "dashboard.py", "--port", "8000"])
        self.lbl_report_status.setText("Live Web Dashboard opened on http://127.0.0.1:8000")

    def run_inspection(self):
        """Run diagnostics on the selected tab."""
        host = self.host_input.text().strip()
        port = int(self.port_input.text().strip())
        idx = self.tab_combo.currentData()

        self._start_diagnostic_worker(host, port, idx, launch_fallback=False)

    def run_demo_mode(self):
        """Run self-contained demo test."""
        from demo_server import start_demo_server
        self.lbl_report_status.setText("Starting local demo assessment server...")
        server, demo_url = start_demo_server(port=8765)
        self._start_diagnostic_worker("127.0.0.1", 9222, 0, launch_fallback=True, navigate_url=demo_url)

    def _start_diagnostic_worker(self, host: str, port: int, tab_idx: Any, launch_fallback: bool, navigate_url: Optional[str] = None):
        self.btn_inspect.setEnabled(False)
        self.btn_demo.setEnabled(False)
        self.lbl_report_status.setText("Running DOM, Image, and Accessibility diagnostics...")

        self.worker = DiagnosticWorker(host, port, tab_idx, launch_fallback, navigate_url)
        self.worker.finished.connect(self._on_diagnostics_finished)
        self.worker.error.connect(self._on_diagnostics_error)
        self.worker.start()

    @Slot(dict)
    def _on_diagnostics_finished(self, result: Dict[str, Any]):
        self.btn_inspect.setEnabled(True)
        self.btn_demo.setEnabled(True)
        self.last_results = result
        self.btn_open_html.setEnabled(True)
        self.btn_open_json.setEnabled(True)

        data = result.get("data", {})
        summary = data.get("summary", {})
        dom_struct = data.get("dom", {}).get("structure", {})
        images = data.get("images", {})
        interactive = data.get("dom", {}).get("interactive", {})
        a11y = data.get("accessibility", {})

        # Update metric cards
        self.card_dom.val_label.setText(str(summary.get("total_dom_elements", 0)))
        self.card_images.val_label.setText(str(summary.get("image_count", 0)))
        self.card_canvases.val_label.setText(str(summary.get("canvas_count", 0)))
        self.card_interactive.val_label.setText(str(summary.get("interactive_element_count", 0)))
        self.card_questions.val_label.setText(str(summary.get("detected_question_containers", 0)))

        # Update Questions Table
        questions = images.get("question_diagnostics", {}).get("questions", [])
        self.table_questions.setRowCount(len(questions))
        for row, q in enumerate(questions):
            self.table_questions.setItem(row, 0, QTableWidgetItem(f"#{q.get('index')}"))
            self.table_questions.setItem(row, 1, QTableWidgetItem(q.get("modality", "")))
            self.table_questions.setItem(row, 2, QTableWidgetItem(q.get("prompt_snippet", "")))
            self.table_questions.setItem(row, 3, QTableWidgetItem("Yes" if q.get("has_interactive_choices") else "No"))
            self.table_questions.setItem(row, 4, QTableWidgetItem(q.get("diagnostic_note", "")))

        # Update Images Table
        img_list = images.get("images", [])
        self.table_images.setRowCount(len(img_list))
        for row, img in enumerate(img_list):
            vis = "Visible" if img.get("is_visible") else "Hidden"
            if img.get("is_broken"):
                vis += " (Broken)"
            self.table_images.setItem(row, 0, QTableWidgetItem(f"#{img.get('index')}"))
            self.table_images.setItem(row, 1, QTableWidgetItem(vis))
            self.table_images.setItem(row, 2, QTableWidgetItem(f"{img.get('rendered_width')}x{img.get('rendered_height')}"))
            self.table_images.setItem(row, 3, QTableWidgetItem(f"{img.get('natural_width')}x{img.get('natural_height')}"))
            self.table_images.setItem(row, 4, QTableWidgetItem(img.get("alt") or ""))
            self.table_images.setItem(row, 5, QTableWidgetItem(img.get("src", "")))

        # Update Interactive Table
        controls = []
        for r in interactive.get("radios", []):
            controls.append(("Radio", r.get("name") or "", r.get("value") or "", r.get("label") or "", "Checked" if r.get("checked") else "Unchecked"))
        for c in interactive.get("checkboxes", []):
            controls.append(("Checkbox", c.get("name") or "", c.get("value") or "", c.get("label") or "", "Checked" if c.get("checked") else "Unchecked"))
        for b in interactive.get("buttons", []):
            controls.append(("Button", b.get("tag"), "-", b.get("text") or "", "Disabled" if b.get("disabled") else "Active"))

        self.table_interactive.setRowCount(len(controls))
        for row, ctrl in enumerate(controls):
            for col in range(5):
                self.table_interactive.setItem(row, col, QTableWidgetItem(ctrl[col]))

        # Update A11y Table
        issues = a11y.get("issues", [])
        self.table_a11y.setRowCount(len(issues))
        for row, iss in enumerate(issues):
            self.table_a11y.setItem(row, 0, QTableWidgetItem(iss.get("severity", "")))
            self.table_a11y.setItem(row, 1, QTableWidgetItem(iss.get("role", "")))
            self.table_a11y.setItem(row, 2, QTableWidgetItem(iss.get("type", "")))
            self.table_a11y.setItem(row, 3, QTableWidgetItem(iss.get("description", "")))

        # Read diagnostics.log
        if os.path.exists("diagnostics.log"):
            with open("diagnostics.log", "r", encoding="utf-8") as f:
                self.log_viewer.setPlainText(f.read())

        self.lbl_report_status.setText("Diagnostics completed successfully! Reports generated.")
        QMessageBox.information(self, "Diagnostics Complete", "DOM inspection & diagnostics finished successfully!")

    @Slot(str)
    def _on_diagnostics_error(self, err_msg: str):
        self.btn_inspect.setEnabled(True)
        self.btn_demo.setEnabled(True)
        self.lbl_report_status.setText("Diagnostics failed.")
        QMessageBox.critical(self, "Diagnostics Error", err_msg)

    def open_html_report(self):
        """Open generated dom_report.html in default system browser."""
        if self.last_results:
            path = self.last_results.get("paths", {}).get("html")
            if path and os.path.exists(path):
                webbrowser.open(f"file://{os.path.abspath(path)}")

    def open_json_report(self):
        """Open generated dom_report.json."""
        if self.last_results:
            path = self.last_results.get("paths", {}).get("json")
            if path and os.path.exists(path):
                webbrowser.open(f"file://{os.path.abspath(path)}")


def launch_gui():
    """Start desktop PySide6 application."""
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_gui()

