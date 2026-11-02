"""
diagnostics - Target Site DOM Inspection & Accessibility Diagnostic Toolkit

A modular package for inspecting the DOM, image presentation modalities,
interactive controls, and accessibility trees of arbitrary target websites
and exam portals.
"""

from .dom_inspector import DOMInspector
from .image_analyzer import ImageAnalyzer
from .accessibility_inspector import AccessibilityInspector
from .report_generator import ReportGenerator
from .demo_server import DEMO_HTML, start_demo_server, DemoHTTPHandler

__all__ = [
    "DOMInspector",
    "ImageAnalyzer",
    "AccessibilityInspector",
    "ReportGenerator",
    "DEMO_HTML",
    "start_demo_server",
    "DemoHTTPHandler",
]
