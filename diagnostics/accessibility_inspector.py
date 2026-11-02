"""
accessibility_inspector.py - Accessibility Tree Inspection & Audit Module

Captures and audits the Chrome browser tab's accessibility tree using Chrome DevTools
Protocol (CDP `Accessibility.getFullAXTree`) and Playwright ARIA snapshots.
Reports roles, accessible names, states, heading hierarchies, and accessibility
issues (e.g. missing labels, unlabelled images, buttons without accessible text).
"""

import logging
from typing import Any, Dict, List, Optional
from playwright.sync_api import Page

logger = logging.getLogger("ChromeDOMInspector.Accessibility")


class AccessibilityInspector:
    """Inspects and audits the accessibility tree of the connected Chrome tab."""

    def __init__(self, page: Page):
        self.page = page

    def inspect(self) -> Dict[str, Any]:
        """
        Capture the full accessibility snapshot and analyze roles, labels, and diagnostics.
        """
        logger.info(f"Extracting accessibility tree for '{self.page.url}'...")

        raw_nodes = []
        aria_snapshot_yaml = ""

        # 1. Capture via CDP Accessibility domain
        try:
            cdp = self.page.context.new_cdp_session(self.page)
            cdp_res = cdp.send("Accessibility.getFullAXTree")
            raw_nodes = cdp_res.get("nodes", [])
            cdp.detach()
            logger.debug(f"Retrieved {len(raw_nodes)} AX nodes from CDP.")
        except Exception as cdp_err:
            logger.warning(f"CDP Accessibility.getFullAXTree failed: {cdp_err}")

        # 2. Capture ARIA snapshot yaml
        try:
            aria_snapshot_yaml = self.page.locator(":root").aria_snapshot()
        except Exception as aria_err:
            logger.debug(f"ARIA snapshot retrieval failed: {aria_err}")

        if not raw_nodes and not aria_snapshot_yaml:
            return {
                "available": False,
                "error": "Accessibility tree could not be retrieved. CDP accessibility domain may be restricted.",
                "summary": {
                    "total_nodes": 0,
                    "total_issues": 0,
                    "error_issues_count": 0,
                    "warning_issues_count": 0,
                    "role_counts": {},
                },
                "issues": [],
                "landmarks": [],
                "controls": [],
                "aria_yaml": "",
            }

        # Traverse and collect metrics from CDP nodes
        role_counts: Dict[str, int] = {}
        issues: List[Dict[str, Any]] = []
        flattened_landmarks: List[Dict[str, Any]] = []
        flattened_controls: List[Dict[str, Any]] = []
        total_nodes = 0

        landmark_roles = {"banner", "complementary", "contentinfo", "form", "main", "navigation", "region", "search", "RootWebArea"}
        control_roles = {"button", "checkbox", "radio", "textbox", "combobox", "link", "slider", "switch", "tab"}

        for node in raw_nodes:
            if node.get("ignored", False):
                continue

            total_nodes += 1
            # Extract role
            role_obj = node.get("role", {})
            role = role_obj.get("value", "unknown") if isinstance(role_obj, dict) else str(role_obj)
            role_lower = role.lower()

            # Extract accessible name
            name_obj = node.get("name", {})
            name = name_obj.get("value", "") if isinstance(name_obj, dict) else str(name_obj or "")
            name_clean = name.strip()

            role_counts[role] = role_counts.get(role, 0) + 1

            # Landmarks
            if role_lower in landmark_roles or role in landmark_roles:
                flattened_landmarks.append({
                    "role": role,
                    "name": name_clean,
                    "nodeId": node.get("nodeId")
                })

            # Form Controls
            if role_lower in control_roles or role in control_roles:
                flattened_controls.append({
                    "role": role,
                    "name": name_clean,
                    "nodeId": node.get("nodeId")
                })

            # Diagnostics & Accessibility Issues
            # 1. Images without name
            if role_lower in ("image", "img", "graphic"):
                if not name_clean:
                    issues.append({
                        "severity": "WARNING",
                        "type": "MISSING_ALT_OR_NAME",
                        "role": role,
                        "description": "Image element lacks an accessible name (missing or empty alt text).",
                        "nodeId": node.get("nodeId"),
                    })

            # 2. Interactive button or link without name
            if role_lower in ("button", "link"):
                if not name_clean:
                    issues.append({
                        "severity": "ERROR",
                        "type": "EMPTY_INTERACTIVE_NAME",
                        "role": role,
                        "description": f"Interactive control '{role}' has no accessible text or label.",
                        "nodeId": node.get("nodeId"),
                    })

            # 3. Form control without label
            if role_lower in ("checkbox", "radio", "textbox", "combobox"):
                if not name_clean:
                    issues.append({
                        "severity": "ERROR",
                        "type": "UNLABELLED_FORM_CONTROL",
                        "role": role,
                        "description": f"Form control '{role}' lacks an accessible label or aria-label.",
                        "nodeId": node.get("nodeId"),
                    })

        sorted_roles = dict(sorted(role_counts.items(), key=lambda item: item[1], reverse=True))

        logger.info(
            f"Accessibility inspection complete: {total_nodes} nodes, {len(issues)} issues detected."
        )

        return {
            "available": True,
            "summary": {
                "total_nodes": total_nodes,
                "total_issues": len(issues),
                "error_issues_count": sum(1 for i in issues if i["severity"] == "ERROR"),
                "warning_issues_count": sum(1 for i in issues if i["severity"] == "WARNING"),
                "role_counts": sorted_roles,
            },
            "issues": issues[:50],
            "landmarks": flattened_landmarks[:30],
            "controls": flattened_controls[:50],
            "aria_yaml": aria_snapshot_yaml,
            "raw_nodes_count": len(raw_nodes),
        }
