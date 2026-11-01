"""
chrome_connector.py - Chrome Connection & CDP Management Module

Detects running Chrome instances, establishes connections via Chrome DevTools
Protocol (CDP) over Playwright, and inspects browser targets.
Adheres strictly to authorized diagnostic principles:
- Connects to existing instances without launching a new browser unless requested.
- Provides detailed diagnostic reporting on connection status and restrictions.
"""

import json
import logging
import platform
import subprocess
from typing import Any, Dict, List, Optional, Tuple
import requests
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

logger = logging.getLogger("ChromeDOMInspector.Connector")


class ChromeConnectionError(Exception):
    """Raised when connecting to Chrome or CDP fails."""
    pass


def detect_chrome_processes() -> Tuple[bool, int, List[str]]:
    """
    Detect whether Chrome browser processes are running on the system.
    Returns (is_running, count, details).
    """
    count = 0
    details = []
    os_name = platform.system()

    try:
        if os_name == "Windows":
            output = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
            # First line is header, subsequent lines are chrome.exe processes
            if len(lines) > 1 and "chrome.exe" in lines[1].lower():
                count = len(lines) - 1
                details = [f"Windows chrome.exe instances detected: {count}"]
        else:
            output = subprocess.check_output(
                ["pgrep", "-l", "chrome"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
            count = len(lines)
            details = lines
    except Exception as exc:
        logger.debug(f"Process detection returned: {exc}")

    is_running = count > 0
    logger.info(f"System Chrome process detection: running={is_running}, count={count}")
    return is_running, count, details


def check_cdp_endpoint(
    host: str = "127.0.0.1", port: int = 9222, timeout: float = 2.0
) -> Tuple[bool, Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """
    Check if Chrome DevTools Protocol (CDP) HTTP endpoint is responding.
    Queries /json/version and /json/list.
    Returns (is_available, version_info, tabs_list, error_message).
    """
    base_url = f"http://{host}:{port}"
    version_info = None
    tabs_list = []

    try:
        logger.debug(f"Pinging CDP version endpoint: {base_url}/json/version")
        ver_resp = requests.get(f"{base_url}/json/version", timeout=timeout)
        if ver_resp.status_code == 200:
            version_info = ver_resp.json()
        elif ver_resp.status_code == 403:
            return (
                False,
                None,
                [],
                (
                    f"CDP endpoint returned HTTP 403 Forbidden. "
                    f"Recent Chrome versions require '--remote-allow-origins=*' flag "
                    f"when starting Chrome with '--remote-debugging-port={port}'."
                ),
            )
        else:
            return False, None, [], f"CDP endpoint returned HTTP status {ver_resp.status_code}"

        # Fetch open targets/tabs
        list_resp = requests.get(f"{base_url}/json/list", timeout=timeout)
        if list_resp.status_code == 200:
            tabs_list = list_resp.json()

        logger.info(
            f"Successfully contacted CDP on {base_url}. "
            f"Browser: {version_info.get('Browser', 'Unknown')}, Targets: {len(tabs_list)}"
        )
        return True, version_info, tabs_list, None

    except requests.exceptions.ConnectionError:
        msg = (
            f"Connection refused at {base_url}. Chrome DevTools Protocol is not listening on port {port}. "
            f"Please verify Chrome was launched with '--remote-debugging-port={port}'."
        )
        logger.warning(msg)
        return False, None, [], msg
    except requests.exceptions.Timeout:
        msg = f"Timed out waiting for CDP response from {base_url}."
        logger.warning(msg)
        return False, None, [], msg
    except Exception as exc:
        msg = f"Error querying CDP endpoint at {base_url}: {str(exc)}"
        logger.error(msg)
        return False, None, [], msg


class ChromeConnector:
    """
    Manages connection to an existing Chrome browser instance via CDP.
    Prevents spawning unnecessary browsers and provides target inspection.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host = host
        self.port = port
        self.endpoint_url = f"http://{host}:{port}"
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_launched: bool = False  # Track whether we spawned a temp browser
        self._closed: bool = False

    def get_tab_summary(self) -> List[Dict[str, Any]]:
        """Retrieve a sanitized list of inspectable tabs."""
        ok, _, tabs, _ = check_cdp_endpoint(self.host, self.port)
        if not ok:
            return []

        inspectable = []
        for idx, tab in enumerate(tabs):
            tab_type = tab.get("type", "unknown")
            # Usually 'page', 'iframe', 'service_worker', etc.
            inspectable.append(
                {
                    "index": idx,
                    "id": tab.get("id"),
                    "title": tab.get("title", "Untitled"),
                    "url": tab.get("url", ""),
                    "type": tab_type,
                    "webSocketDebuggerUrl": tab.get("webSocketDebuggerUrl", ""),
                }
            )
        return inspectable

    def connect(
        self,
        tab_selector: Optional[Any] = None,
        launch_fallback: bool = False,
        headless: bool = False,
    ) -> Page:
        """
        Connect to an existing Chrome instance over CDP.

        :param tab_selector: Integer index, URL substring, target ID, or title substring.
        :param launch_fallback: If True, launch a temporary browser ONLY when no running instance can be reached.
        :param headless: Used only if launch_fallback is triggered.
        :return: Playwright Page instance connected to the selected tab.
        """
        logger.info(f"Initiating connection to Chrome at {self.endpoint_url}...")
        is_cdp_up, ver_info, raw_tabs, err_msg = check_cdp_endpoint(self.host, self.port)

        # If CDP is not responding and user did not request launch fallback, diagnose and abort immediately
        if not is_cdp_up and not launch_fallback:
            chrome_running, proc_count, _ = detect_chrome_processes()
            if chrome_running:
                guidance = (
                    f"\n[DIAGNOSTIC NOTICE] Chrome is currently running ({proc_count} processes detected), "
                    f"but remote debugging is not enabled on port {self.port}.\n"
                    f"To inspect your existing Chrome tabs, close Chrome and launch with:\n\n"
                    f'  chrome.exe --remote-debugging-port={self.port} --remote-allow-origins="*" --user-data-dir="%LOCALAPPDATA%\\Google\\Chrome\\DiagnosticProfile"\n\n'
                    f"Alternatively, pass '--launch' to start an isolated inspection session."
                )
                raise ChromeConnectionError(f"{err_msg}\n{guidance}")
            else:
                raise ChromeConnectionError(
                    f"No Chrome instance found listening on port {self.port}.\n{err_msg}\n"
                    f"Pass '--launch' to start a new browser instance for testing."
                )

        # Start Playwright
        self.playwright = sync_playwright().start()

        if is_cdp_up:
            try:
                logger.info(f"Connecting to CDP endpoint via Playwright: {self.endpoint_url}")
                self.browser = self.playwright.chromium.connect_over_cdp(self.endpoint_url)
                
                # Retrieve contexts and pages
                contexts = self.browser.contexts
                if not contexts:
                    logger.warning("No browser contexts found; creating a default context.")
                    self.context = self.browser.new_context()
                else:
                    self.context = contexts[0]

                pages = self.context.pages
                logger.info(f"Connected over CDP. Context pages available: {len(pages)}")

                if not pages:
                    logger.info("No pages currently open in context; creating a new tab.")
                    self.page = self.context.new_page()
                else:
                    self.page = self._select_page(pages, tab_selector)

                self.is_launched = False
                logger.info(f"Target tab selected: '{self.page.title()}' ({self.page.url})")
                return self.page

            except Exception as cdp_err:
                logger.error(f"Failed to attach over CDP: {cdp_err}")
                if not launch_fallback:
                    self.close()
                    raise ChromeConnectionError(
                        f"Failed connecting to existing Chrome CDP at {self.endpoint_url}: {cdp_err}\n"
                        f"Possible cause: Restricted browser mode, firewall, or debugger already attached."
                    ) from cdp_err

        # If CDP is not available
        chrome_running, proc_count, proc_details = detect_chrome_processes()
        if chrome_running and not launch_fallback:
            self.close()
            guidance = (
                f"\n[DIAGNOSTIC NOTICE] Chrome is currently running ({proc_count} processes detected), "
                f"but remote debugging is not enabled on port {self.port}.\n"
                f"To inspect your existing Chrome tabs, close all Chrome instances and launch Chrome with:\n\n"
                f'  chrome.exe --remote-debugging-port={self.port} --remote-allow-origins="*" --user-data-dir="%LOCALAPPDATA%\\Google\\Chrome\\DiagnosticProfile"\n\n'
                f"Alternatively, pass '--launch' to start an isolated inspection session."
            )
            raise ChromeConnectionError(err_msg + "\n" + guidance)

        if not launch_fallback:
            self.close()
            raise ChromeConnectionError(
                f"No Chrome instance found on port {self.port}.\n{err_msg}\n"
                f"Pass '--launch' if you wish to start a new browser instance for testing."
            )

        # Fallback launch explicitly requested
        logger.warning("Launching a temporary Chrome instance (channel='chrome' fallback)...")
        launch_args = [f"--remote-debugging-port={self.port}", "--remote-allow-origins=*"]
        try:
            self.browser = self.playwright.chromium.launch(
                channel="chrome",
                headless=headless,
                args=launch_args,
            )
        except Exception as launch_err:
            logger.warning(f"Could not launch via channel='chrome' ({launch_err}), attempting default chromium launch...")
            self.browser = self.playwright.chromium.launch(
                headless=headless,
                args=launch_args,
            )
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.is_launched = True
        logger.info(f"Temporary browser session created successfully.")
        return self.page

    def _select_page(self, pages: List[Page], selector: Optional[Any]) -> Page:
        """Select a page based on index, URL substring, or title."""
        if selector is None:
            # Default to the last active or first non-blank page
            for p in reversed(pages):
                if p.url and p.url != "about:blank":
                    return p
            return pages[0]

        # Integer index
        if isinstance(selector, int) or (isinstance(selector, str) and selector.isdigit()):
            idx = int(selector)
            if 0 <= idx < len(pages):
                return pages[idx]
            logger.warning(f"Index {idx} out of range (0-{len(pages)-1}), defaulting to first tab.")
            return pages[0]

        # String search (URL or title)
        query = str(selector).lower()
        for p in pages:
            if query in p.url.lower() or query in p.title().lower():
                logger.info(f"Matched tab by query '{selector}': '{p.title()}' ({p.url})")
                return p

        logger.warning(f"No tab matched '{selector}', using first open tab.")
        return pages[0]

    def check_page_restrictions(self) -> Dict[str, Any]:
        """
        Diagnose if the attached page has CDP or DOM inspection restrictions:
        - Security origin restrictions (chrome://, devtools://, etc.)
        - Content Security Policy (CSP) blocking evaluation
        - CDP domain execution capability
        - Window flags indicating restricted or automated environments
        """
        if not self.page:
            return {"status": "error", "error": "No active page connected"}

        diagnostics: Dict[str, Any] = {
            "status": "connected",
            "url": self.page.url,
            "title": self.page.title(),
            "is_restricted_url": False,
            "can_evaluate_js": False,
            "can_query_dom": False,
            "can_access_ax_tree": False,
            "cdp_session_ok": False,
            "detected_restrictions": [],
            "security_origin": "",
        }

        # Check special URL schemas
        url_lower = self.page.url.lower()
        restricted_schemes = ["chrome://", "chrome-extension://", "edge://", "brave://", "about:"]
        for scheme in restricted_schemes:
            if url_lower.startswith(scheme):
                diagnostics["is_restricted_url"] = True
                diagnostics["detected_restrictions"].append(
                    f"Page URL begins with restricted scheme '{scheme}'. Browser blocks script injection on internal pages."
                )

        # Test JavaScript Evaluation
        try:
            eval_res = self.page.evaluate("() => ({ origin: window.location.origin, href: window.location.href, webdriver: navigator.webdriver })")
            diagnostics["can_evaluate_js"] = True
            diagnostics["security_origin"] = eval_res.get("origin", "")
            if eval_res.get("webdriver"):
                diagnostics["detected_restrictions"].append(
                    "navigator.webdriver is set to true (automation signal detected)."
                )
        except Exception as eval_err:
            diagnostics["can_evaluate_js"] = False
            diagnostics["detected_restrictions"].append(f"Runtime evaluation failed: {eval_err}")

        # Test DOM Querying
        try:
            body_count = self.page.evaluate("() => document.querySelectorAll('*').length")
            diagnostics["can_query_dom"] = True
            diagnostics["raw_dom_element_count"] = body_count
        except Exception as dom_err:
            diagnostics["can_query_dom"] = False
            diagnostics["detected_restrictions"].append(f"DOM query access failed: {dom_err}")

        # Test CDP Session Creation
        try:
            cdp_session = self.context.new_cdp_session(self.page)
            # Ping DOM domain
            dom_doc = cdp_session.send("DOM.getDocument", {"depth": 1})
            diagnostics["cdp_session_ok"] = bool(dom_doc and "root" in dom_doc)
            cdp_session.detach()
        except Exception as cdp_err:
            diagnostics["cdp_session_ok"] = False
            diagnostics["detected_restrictions"].append(f"Direct CDP session check failed: {cdp_err}")

        # Test Accessibility tree query via CDP or aria_snapshot
        try:
            cdp = self.context.new_cdp_session(self.page)
            ax_res = cdp.send("Accessibility.getFullAXTree")
            cdp.detach()
            diagnostics["can_access_ax_tree"] = bool(ax_res and "nodes" in ax_res)
        except Exception as ax_err:
            try:
                snapshot = self.page.locator(":root").aria_snapshot()
                diagnostics["can_access_ax_tree"] = snapshot is not None
            except Exception as ax_err2:
                diagnostics["can_access_ax_tree"] = False
                diagnostics["detected_restrictions"].append(f"Accessibility tree query failed: {ax_err2}")

        logger.info(f"Page restriction diagnostics complete: {len(diagnostics['detected_restrictions'])} flags")
        return diagnostics

    def close(self):
        """Clean up connection handles without killing the user's Chrome instance."""
        if self._closed:
            return
        self._closed = True
        try:
            self.page = None
            if self.context and self.is_launched:
                try:
                    self.context.close()
                except Exception:
                    pass
                self.context = None
            if self.browser:
                try:
                    self.browser.close()
                except Exception:
                    pass
                self.browser = None
            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception:
                    pass
                self.playwright = None
            logger.info("Chrome connector closed cleanly.")
        except Exception as exc:
            logger.debug(f"Error during connector cleanup: {exc}")
