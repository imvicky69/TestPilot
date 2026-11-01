"""
main.py - Chrome DOM Inspection & Diagnostic Utility (CLI & Orchestrator)

Coordinates Chrome CDP connection, DOM inspection, image diagnostics,
accessibility audits, and report generation.

Usage:
    python main.py --demo                  # Run automated self-contained demo
    python main.py --port 9222             # Connect to existing Chrome instance
    python main.py --list-tabs             # List all open tabs in Chrome
    python main.py --tab "exam"            # Select tab containing "exam"
    python main.py --gui                   # Launch desktop GUI interface
"""

import argparse
import logging
import os
import sys
import webbrowser
from typing import Any, Dict, Optional

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from accessibility_inspector import AccessibilityInspector
from chrome_connector import ChromeConnectionError, ChromeConnector, check_cdp_endpoint, detect_chrome_processes
from dom_inspector import DOMInspector
from image_analyzer import ImageAnalyzer
from report_generator import ReportGenerator

console = Console(highlight=False, legacy_windows=False)


def setup_logging(output_dir: str = ".") -> logging.Logger:
    """Configure logging to stream to both console and diagnostics.log."""
    os.makedirs(output_dir, exist_ok=True)
    log_file = os.path.join(output_dir, "diagnostics.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Clean existing handlers
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    # File Handler
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # Console Handler (INFO level)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    logger = logging.getLogger("ChromeDOMInspector")
    logger.info(f"Diagnostics logging initialized. Log file: {os.path.abspath(log_file)}")
    return logger


def list_tabs_cli(host: str, port: int):
    """List all open inspectable tabs in the remote Chrome instance."""
    ok, ver, tabs, err = check_cdp_endpoint(host, port)
    if not ok:
        console.print(f"[bold red]Cannot connect to Chrome on {host}:{port}[/bold red]")
        console.print(f"[yellow]{err}[/yellow]")
        return

    table = Table(title=f"Open Chrome Tabs on {host}:{port}", show_header=True, header_style="bold cyan")
    table.add_column("Index", style="dim", width=6)
    table.add_column("Title", style="bold white", max_width=40)
    table.add_column("Type", style="green", width=12)
    table.add_column("URL", style="blue")

    for idx, tab in enumerate(tabs):
        table.add_row(
            str(idx),
            tab.get("title", "Untitled")[:40],
            tab.get("type", "unknown"),
            tab.get("url", "")[:70],
        )

    console.print(table)


def run_diagnostics(
    host: str = "127.0.0.1",
    port: int = 9222,
    tab_selector: Optional[Any] = None,
    launch_fallback: bool = False,
    navigate_url: Optional[str] = None,
    output_dir: str = ".",
    headless: bool = False,
    target_url: Optional[str] = None,
    demo_mode: bool = False,
) -> Dict[str, Any]:
    """
    Execute full diagnostic workflow against a Chrome browser tab:
    1. Connect via CDP
    2. Check restrictions & capabilities
    3. Run DOM inspection
    4. Run Image & Question analysis
    5. Run Accessibility inspection
    6. Generate reports
    """
    if target_url and not navigate_url:
        navigate_url = target_url
    if demo_mode:
        launch_fallback = True
        headless = True

    logger = logging.getLogger("ChromeDOMInspector.Core")
    connector = ChromeConnector(host=host, port=port)

    try:
        page = connector.connect(tab_selector=tab_selector, launch_fallback=launch_fallback, headless=headless)

        if navigate_url:
            logger.info(f"Navigating to specified URL: {navigate_url}")
            page.goto(navigate_url, wait_until="load", timeout=30000)

        # 1. Restricted Browser & Security Diagnostics
        restrictions = connector.check_page_restrictions()

        # 2. DOM Structure & Interactive Controls
        dom_inspector = DOMInspector(page)
        dom_report = dom_inspector.inspect()

        # 3. Image & Question Diagnostics
        image_analyzer = ImageAnalyzer(page)
        image_report = image_analyzer.analyze()

        # Attach detected questions to dom_report for easy querying
        dom_report["detected_questions"] = image_report.get("question_diagnostics", {}).get("questions", [])

        # 4. Accessibility Tree
        a11y_inspector = AccessibilityInspector(page)
        a11y_report = a11y_inspector.inspect()

        # 5. Browser version info
        _, version_info, _, _ = check_cdp_endpoint(host, port)

        # 6. Aggregate Master Report
        master_summary = {
            "browser_connection_status": "CONNECTED",
            "total_dom_elements": dom_report["structure"]["total_elements"],
            "image_count": image_report["summary"]["total_images"],
            "canvas_count": image_report["summary"]["total_canvases"],
            "interactive_element_count": dom_report["interactive"]["summary"]["total_interactive"],
            "detected_question_containers": image_report["summary"]["detected_question_containers_count"],
            "question_modalities": image_report["summary"]["question_modalities"],
            "accessibility_issues": a11y_report["summary"]["total_issues"],
        }

        full_data = {
            "summary": master_summary,
            "browser": version_info or {"Browser": "Chrome"},
            "restrictions": restrictions,
            "dom": dom_report,
            "images": image_report,
            "accessibility": a11y_report,
        }

        # 7. Generate Reports
        reporter = ReportGenerator(full_data, output_dir=output_dir)
        paths = reporter.generate_all()

        combined_result = dict(full_data)
        combined_result["data"] = full_data
        combined_result["paths"] = paths

        return combined_result

    finally:
        connector.close()


def print_summary_panel(data: Dict[str, Any], paths: Dict[str, str]):
    """Print an executive summary table and deliverables status in console."""
    summary = data.get("summary", {})
    modalities = summary.get("question_modalities", {})

    table = Table(title="🔍 Chrome DOM Diagnostic Summary", show_header=True, header_style="bold green")
    table.add_column("Diagnostic Metric", style="bold white")
    table.add_column("Result / Count", style="bold yellow")
    table.add_column("Details", style="dim")

    table.add_row(
        "Browser Connection",
        summary.get("browser_connection_status", "UNKNOWN"),
        "CDP active and responsive",
    )
    table.add_row(
        "Total DOM Elements",
        str(summary.get("total_dom_elements", 0)),
        f"Max depth: {data.get('dom', {}).get('structure', {}).get('max_dom_depth', 0)}",
    )
    table.add_row(
        "Rendered Images",
        str(summary.get("image_count", 0)),
        f"Broken: {data.get('images', {}).get('summary', {}).get('broken_images_count', 0)}, Lazy: {data.get('images', {}).get('summary', {}).get('lazy_loaded_images_count', 0)}",
    )
    table.add_row(
        "Canvas Elements",
        str(summary.get("canvas_count", 0)),
        f"SVGs: {data.get('images', {}).get('summary', {}).get('total_svgs', 0)}",
    )
    table.add_row(
        "Interactive Elements",
        str(summary.get("interactive_element_count", 0)),
        f"Radios: {data.get('dom', {}).get('interactive', {}).get('summary', {}).get('radio_count', 0)}, Buttons: {data.get('dom', {}).get('interactive', {}).get('summary', {}).get('button_count', 0)}",
    )
    table.add_row(
        "Detected Questions",
        str(summary.get("detected_question_containers", 0)),
        f"Modalities: {', '.join([f'{k}: {v}' for k, v in modalities.items() if v > 0]) or 'None'}",
    )
    table.add_row(
        "Accessibility Issues",
        str(summary.get("accessibility_issues", 0)),
        f"Errors: {data.get('accessibility', {}).get('summary', {}).get('error_issues_count', 0)}, Warnings: {data.get('accessibility', {}).get('summary', {}).get('warning_issues_count', 0)}",
    )

    console.print(table)

    console.print(
        Panel.fit(
            f"[bold green]Diagnostic Deliverables Successfully Generated![/bold green]\n\n"
            f"📄 JSON Report:        [cyan]{paths.get('json')}[/cyan]\n"
            f"🌐 HTML Dashboard:     [cyan]{paths.get('html')}[/cyan]\n"
            f"📝 Diagnostics Log:    [cyan]{os.path.abspath('diagnostics.log')}[/cyan]\n\n"
            f"[dim]To view the report, open the HTML file in your web browser.[/dim]",
            title="✅ Execution Complete",
            border_style="green",
        )
    )


def launch_debug_chrome(port: int = 9222):
    """Convenience helper to launch Chrome with remote debugging enabled."""
    import subprocess
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    chrome_path = None
    for c in candidates:
        if os.path.exists(c):
            chrome_path = c
            break

    if not chrome_path:
        console.print("[bold red]Could not automatically locate chrome.exe on standard paths.[/bold red]")
        return

    profile_dir = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\DiagnosticProfile")
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        chrome_path,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
    ]
    console.print(f"[bold cyan]Launching Chrome with remote debugging on port {port}...[/bold cyan]")
    subprocess.Popen(cmd)
    console.print(f"[bold green]Chrome launched successfully![/bold green] You can now navigate to your tab and run: [yellow]python main.py[/yellow]")


def run_demo(output_dir: str = "."):
    """Run an automated demo test against the built-in assessment server."""
    from demo_server import start_demo_server

    console.print("[bold cyan]Starting built-in assessment demo server...[/bold cyan]")
    server, demo_url = start_demo_server(port=8765)
    console.print(f"[green]Demo server listening at {demo_url}[/green]")

    try:
        console.print("[bold cyan]Launching automated diagnostic session...[/bold cyan]")
        result = run_diagnostics(
            host="127.0.0.1",
            port=9222,
            launch_fallback=True,
            navigate_url=demo_url,
            output_dir=output_dir,
            headless=True,
        )
        print_summary_panel(result["data"], result["paths"])
        return result
    finally:
        server.shutdown()


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="TestPilot - Chrome DOM Inspection & Diagnostic Utility"
    )
    parser.add_argument("--port", type=int, default=9222, help="Chrome CDP port (default: 9222)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Chrome CDP host (default: 127.0.0.1)")
    parser.add_argument("--tab", type=str, default=None, help="Tab selector (index, URL substring, or title)")
    parser.add_argument("--url", type=str, default=None, help="Optional URL to navigate to")
    parser.add_argument("--output-dir", type=str, default=".", help="Directory to save generated reports")
    parser.add_argument("--list-tabs", action="store_true", help="List open Chrome tabs and exit")
    parser.add_argument("--launch", action="store_true", help="Launch a temporary browser if no instance is running")
    parser.add_argument("--demo", action="store_true", help="Run automated self-contained demo test")
    parser.add_argument("--start-chrome", action="store_true", help="Launch Chrome with remote debugging on port 9222")
    parser.add_argument("--dashboard", action="store_true", help="Launch the Live Question Solver Web Dashboard")
    parser.add_argument("--gui", action="store_true", help="Launch the PySide6 Desktop GUI")
    parser.add_argument("--open-report", action="store_true", help="Automatically open HTML report in default browser")

    args = parser.parse_args()
    setup_logging(args.output_dir)

    # 1. Launch Dashboard if requested
    if args.dashboard:
        try:
            from dashboard import main as run_dashboard
            run_dashboard()
            return
        except Exception as e:
            console.print(f"[bold red]Failed to start Live Dashboard: {e}[/bold red]")
            sys.exit(1)

    # 1a. Launch GUI if requested
    if args.gui:
        try:
            from gui import launch_gui
            launch_gui()
            return
        except ImportError as e:
            console.print(f"[bold red]Failed to load PySide6 GUI: {e}[/bold red]")
            sys.exit(1)

    # 1b. Start Chrome with remote debugging
    if args.start_chrome:
        launch_debug_chrome(args.port)
        return

    # 2. List tabs if requested
    if args.list_tabs:
        list_tabs_cli(args.host, args.port)
        return

    # 3. Demo mode
    if args.demo:
        res = run_demo(output_dir=args.output_dir)
        if args.open_report and res:
            webbrowser.open(f"file://{os.path.abspath(res['paths']['html'])}")
        return

    # 4. Standard Inspection
    try:
        console.print(f"[bold cyan]Connecting to Chrome on {args.host}:{args.port}...[/bold cyan]")
        res = run_diagnostics(
            host=args.host,
            port=args.port,
            tab_selector=args.tab,
            launch_fallback=args.launch,
            navigate_url=args.url,
            output_dir=args.output_dir,
        )
        print_summary_panel(res["data"], res["paths"])

        if args.open_report:
            webbrowser.open(f"file://{os.path.abspath(res['paths']['html'])}")

    except ChromeConnectionError as conn_err:
        console.print(f"\n[bold red]Chrome Connection Failure:[/bold red]\n{conn_err}\n")
        sys.exit(1)
    except Exception as exc:
        logging.getLogger("ChromeDOMInspector").exception(f"Unexpected diagnostic error: {exc}")
        console.print(f"\n[bold red]Diagnostic Error:[/bold red] {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
