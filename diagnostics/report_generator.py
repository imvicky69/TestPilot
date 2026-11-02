"""
report_generator.py - Diagnostic Report Generator Module

Generates the core project deliverables:
1. `dom_report.json`: Comprehensive structured diagnostic data.
2. `dom_report.html`: Responsive, interactive standalone HTML dashboard with
   visual indicators, question modality breakdown, image cards, and a11y audits.
3. Summary logs and status reporting.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("ChromeDOMInspector.Reporter")


class ReportGenerator:
    """Compiles inspection data and produces JSON and HTML diagnostic artifacts."""

    def __init__(self, data: Optional[Dict[str, Any]] = None, output_dir: str = "."):
        self.data = data or {}
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate(self, data: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        """Generate both reports and return (json_path, html_path) tuple."""
        if data is not None:
            self.data = data
        json_path = self.generate_json()
        html_path = self.generate_html()
        return json_path, html_path

    def generate_all(self) -> Dict[str, str]:
        """Generate both dom_report.json and dom_report.html."""
        json_path = self.generate_json()
        html_path = self.generate_html()
        logger.info(f"Generated diagnostic reports: JSON='{json_path}', HTML='{html_path}'")
        return {"json": json_path, "html": html_path}

    def generate_json(self, filename: str = "dom_report.json") -> str:
        """Serialize data to formatted JSON."""
        target_path = os.path.join(self.output_dir, filename)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved JSON report to {target_path}")
        return os.path.abspath(target_path)

    def generate_html(self, filename: str = "dom_report.html") -> str:
        """Render a modern, standalone interactive HTML dashboard."""
        target_path = os.path.join(self.output_dir, filename)
        html_content = self._build_html_template()
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"Saved HTML report to {target_path}")
        return os.path.abspath(target_path)

    def _build_html_template(self) -> str:
        """Construct the complete standalone HTML string with inline CSS and JS."""
        summary = self.data.get("summary", {})
        metadata = self.data.get("dom", {}).get("metadata", {})
        restrictions = self.data.get("restrictions", {})
        dom_struct = self.data.get("dom", {}).get("structure", {})
        interactive = self.data.get("dom", {}).get("interactive", {})
        image_data = self.data.get("images", {})
        a11y_data = self.data.get("accessibility", {})
        question_data = image_data.get("question_diagnostics", {})

        page_title = metadata.get('title') or restrictions.get('title') or 'Page'
        page_url = metadata.get('url') or restrictions.get('url') or '#'

        # Headings list
        headings = self.data.get("dom", {}).get("headings", []) or dom_struct.get("headings", [])
        headings_rows = "".join([f"<li><code>{h.get('level', 'h')}</code>: {h.get('text', '')}</li>" for h in headings])
        if not headings_rows:
            headings_rows = "<li class='text-muted'>No headings recorded</li>"

        # Modalities badges
        modalities = question_data.get("modalities_summary") or summary.get("question_modalities", {})
        modality_chips = "".join([
            f'<span class="badge badge-{k.lower()}">{k}: {v}</span> '
            for k, v in modalities.items() if v > 0
        ]) or '<span class="badge badge-muted">No questions detected</span>'

        # Generate Questions Table Rows
        questions_rows = ""
        for q in question_data.get("questions", []):
            modality = q.get("modality", "UNKNOWN")
            badge_class = f"badge-{modality.lower()}"
            prompt = q.get("prompt_snippet", "N/A")
            note = q.get("diagnostic_note", "")
            has_choices = "Yes" if q.get("has_interactive_choices") else "No"
            questions_rows += f"""
            <tr>
                <td><strong>#{q.get('index')}</strong></td>
                <td><span class="badge {badge_class}">{modality}</span></td>
                <td class="text-truncate" title="{prompt}">{prompt}</td>
                <td>{has_choices}</td>
                <td><small>{note}</small></td>
                <td><code>{q.get('tag')}{'#' + q.get('id') if q.get('id') else ''}</code></td>
            </tr>
            """
        if not questions_rows:
            questions_rows = "<tr><td colspan='6' class='text-center text-muted'>No question containers detected on this page.</td></tr>"

        # Generate Images Table Rows
        images_rows = ""
        for img in image_data.get("images", [])[:50]:
            broken_badge = '<span class="badge badge-error">Broken</span>' if img.get("is_broken") else '<span class="badge badge-success">OK</span>'
            vis_badge = '<span class="badge badge-info">Visible</span>' if img.get("is_visible") else '<span class="badge badge-muted">Hidden</span>'
            src = img.get("src", "")
            src_display = src[:45] + "..." if len(src) > 45 else src
            alt_display = img.get("alt") if img.get("alt") is not None else '<em class="text-muted">None</em>'
            container_desc = img.get("container", {}).get("descriptor", "N/A") if img.get("container") else "N/A"
            
            images_rows += f"""
            <tr>
                <td>#{img.get('index')}</td>
                <td>{vis_badge} {broken_badge}</td>
                <td title="{src}"><a href="{src}" target="_blank" class="code-link">{src_display}</a></td>
                <td>{alt_display}</td>
                <td>{img.get('rendered_width')} x {img.get('rendered_height')} px</td>
                <td>{img.get('natural_width')} x {img.get('natural_height')} px</td>
                <td><code>{img.get('loading')}</code></td>
                <td><code>{container_desc}</code></td>
            </tr>
            """
        if not images_rows:
            images_rows = "<tr><td colspan='8' class='text-center text-muted'>No <code>&lt;img&gt;</code> elements found.</td></tr>"

        # Interactive Controls Rows
        interactive_rows = ""
        for r in interactive.get("radios", []):
            checked_str = "Checked" if r.get("checked") else "Unchecked"
            interactive_rows += f"""
            <tr>
                <td><span class="badge badge-radio">Radio</span></td>
                <td><code>{r.get('name') or '-'}</code></td>
                <td>{r.get('value') or '-'}</td>
                <td>{r.get('label') or '<em class="text-muted">No label</em>'}</td>
                <td>{checked_str}</td>
                <td>{'Disabled' if r.get('disabled') else 'Active'}</td>
            </tr>
            """
        for c in interactive.get("checkboxes", []):
            checked_str = "Checked" if c.get("checked") else "Unchecked"
            interactive_rows += f"""
            <tr>
                <td><span class="badge badge-checkbox">Checkbox</span></td>
                <td><code>{c.get('name') or '-'}</code></td>
                <td>{c.get('value') or '-'}</td>
                <td>{c.get('label') or '<em class="text-muted">No label</em>'}</td>
                <td>{checked_str}</td>
                <td>{'Disabled' if c.get('disabled') else 'Active'}</td>
            </tr>
            """
        for b in interactive.get("buttons", []):
            interactive_rows += f"""
            <tr>
                <td><span class="badge badge-button">Button</span></td>
                <td><code>{b.get('type') or '-'}</code></td>
                <td>-</td>
                <td><strong>{b.get('text') or '<em class="text-muted">No text</em>'}</strong></td>
                <td>-</td>
                <td>{'Disabled' if b.get('disabled') else 'Active'}</td>
            </tr>
            """
        if not interactive_rows:
            interactive_rows = "<tr><td colspan='6' class='text-center text-muted'>No interactive controls found.</td></tr>"

        # Accessibility Issues Rows
        a11y_issues_rows = ""
        for issue in a11y_data.get("issues", []):
            severity = issue.get("severity", "WARNING")
            sev_badge = f'<span class="badge badge-{severity.lower()}">{severity}</span>'
            a11y_issues_rows += f"""
            <tr>
                <td>{sev_badge}</td>
                <td><code>{issue.get('role')}</code></td>
                <td><strong>{issue.get('type')}</strong></td>
                <td>{issue.get('description')}</td>
            </tr>
            """
        if not a11y_issues_rows:
            a11y_issues_rows = "<tr><td colspan='4' class='text-center text-success'>🎉 No high-priority accessibility issues detected!</td></tr>"

        # Top Tags Rows
        top_tags_rows = ""
        for t in dom_struct.get("top_tags", [])[:10]:
            top_tags_rows += f"""
            <div class="tag-bar-item">
                <span class="tag-name"><code>&lt;{t['tag']}&gt;</code></span>
                <span class="tag-count">{t['count']}</span>
            </div>
            """

        # Restrictions alerts
        restrictions_alert = ""
        restr_list = restrictions.get("detected_restrictions", [])
        if restr_list:
            restr_items = "".join([f"<li>{r}</li>" for r in restr_list])
            restrictions_alert = f"""
            <div class="alert alert-warning">
                <strong>⚠️ Browser / Security Restrictions Noticed:</strong>
                <ul>{restr_items}</ul>
            </div>
            """
        else:
            restrictions_alert = """
            <div class="alert alert-success">
                <strong>✅ CDP & DOM Access Clear:</strong> All standard DevTools protocol evaluation domains are functioning normally without website restrictions.
            </div>
            """

        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DOM Inspection & Diagnostic Report - {page_title}</title>
    <style>
        :root {{
            --bg-color: #0f172a;
            --surface-color: #1e293b;
            --surface-hover: #334155;
            --border-color: #334155;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --primary: #38bdf8;
            --primary-dark: #0284c7;
            --accent: #818cf8;
            --success: #34d399;
            --warning: #fbbf24;
            --error: #f87171;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-primary);
            font-family: var(--font-family);
            line-height: 1.5;
            padding: 24px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        header {{
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }}

        .header-title h1 {{
            font-size: 1.6rem;
            color: var(--primary);
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .header-title p {{
            color: var(--text-secondary);
            font-size: 0.95rem;
        }}

        .header-meta {{
            text-align: right;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }}

        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}

        .kpi-card {{
            background-color: var(--surface-color);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 20px;
            position: relative;
            overflow: hidden;
            transition: transform 0.15s ease;
        }}

        .kpi-card:hover {{
            transform: translateY(-2px);
            border-color: var(--primary);
        }}

        .kpi-title {{
            font-size: 0.82rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            margin-bottom: 8px;
        }}

        .kpi-value {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--text-primary);
        }}

        .kpi-subtext {{
            font-size: 0.8rem;
            color: var(--text-secondary);
            margin-top: 4px;
        }}

        .nav-tabs {{
            display: flex;
            gap: 8px;
            border-bottom: 2px solid var(--border-color);
            margin-bottom: 20px;
            overflow-x: auto;
        }}

        .tab-btn {{
            background: none;
            border: none;
            color: var(--text-secondary);
            padding: 10px 18px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            border-bottom: 3px solid transparent;
            margin-bottom: -2px;
            transition: all 0.2s ease;
        }}

        .tab-btn.active {{
            color: var(--primary);
            border-bottom-color: var(--primary);
        }}

        .tab-btn:hover:not(.active) {{
            color: var(--text-primary);
        }}

        .tab-content {{
            display: none;
        }}

        .tab-content.active {{
            display: block;
        }}

        .card {{
            background-color: var(--surface-color);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }}

        .card-header {{
            font-size: 1.15rem;
            font-weight: 600;
            margin-bottom: 16px;
            color: var(--primary);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
            text-align: left;
        }}

        th, td {{
            padding: 12px 14px;
            border-bottom: 1px solid var(--border-color);
        }}

        th {{
            background-color: rgba(15, 23, 42, 0.6);
            color: var(--text-secondary);
            font-weight: 600;
        }}

        tr:hover td {{
            background-color: rgba(255, 255, 255, 0.02);
        }}

        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .badge-html_text {{ background-color: #0369a1; color: #e0f2fe; }}
        .badge-image_based {{ background-color: #7c2d12; color: #ffedd5; }}
        .badge-canvas_based {{ background-color: #581c87; color: #f3e8ff; }}
        .badge-svg_based {{ background-color: #14532d; color: #dcfce7; }}
        .badge-hybrid {{ background-color: #831843; color: #fce7f3; }}
        .badge-success {{ background-color: rgba(52, 211, 153, 0.15); color: #34d399; }}
        .badge-warning {{ background-color: rgba(251, 191, 36, 0.15); color: #fbbf24; }}
        .badge-error {{ background-color: rgba(248, 113, 113, 0.15); color: #f87171; }}
        .badge-info {{ background-color: rgba(56, 189, 248, 0.15); color: #38bdf8; }}
        .badge-muted {{ background-color: #334155; color: #94a3b8; }}
        .badge-radio {{ background-color: #1e3a8a; color: #93c5fd; }}
        .badge-checkbox {{ background-color: #134e4a; color: #99f6e4; }}
        .badge-button {{ background-color: #431407; color: #fdba74; }}

        .alert {{
            padding: 14px 18px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 0.9rem;
        }}

        .alert-success {{
            background-color: rgba(52, 211, 153, 0.1);
            border: 1px solid rgba(52, 211, 153, 0.3);
            color: #a7f3d0;
        }}

        .alert-warning {{
            background-color: rgba(251, 191, 36, 0.1);
            border: 1px solid rgba(251, 191, 36, 0.3);
            color: #fde68a;
        }}

        .alert ul {{
            margin-top: 8px;
            padding-left: 20px;
        }}

        code {{
            background-color: #0f172a;
            padding: 2px 6px;
            border-radius: 4px;
            color: #38bdf8;
            font-family: Consolas, Monaco, monospace;
            font-size: 0.85em;
        }}

        .code-link {{
            color: var(--primary);
            text-decoration: none;
        }}

        .code-link:hover {{
            text-decoration: underline;
        }}

        .text-truncate {{
            max-width: 320px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .text-center {{ text-align: center; }}
        .text-muted {{ color: var(--text-secondary); }}

        .tag-bars {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 12px;
        }}

        .tag-bar-item {{
            background: #0f172a;
            border: 1px solid var(--border-color);
            padding: 6px 12px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
        }}

        .tag-count {{
            background: var(--surface-hover);
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: bold;
            color: var(--primary);
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-title">
                <h1>🔍 Chrome DOM Inspection & Diagnostic Report</h1>
                <p>Inspected Target: <strong>{page_title}</strong> (<a href="{page_url}" target="_blank" class="code-link">{page_url}</a>)</p>
            </div>
            <div class="header-meta">
                <p>Status: <span class="badge badge-success">{summary.get('connection_status', 'CONNECTED')}</span></p>
                <p>Timestamp: {timestamp_str}</p>
                <p>CDP Version: {self.data.get('browser', {}).get('Browser', 'Chrome')}</p>
            </div>
        </header>

        {restrictions_alert}

        <!-- Top KPI Grid -->
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-title">Total DOM Elements</div>
                <div class="kpi-value">{summary.get('total_dom_elements', 0)}</div>
                <div class="kpi-subtext">Max Tree Depth: {dom_struct.get('max_dom_depth', 0)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Rendered Images</div>
                <div class="kpi-value">{summary.get('image_count', 0)}</div>
                <div class="kpi-subtext">Lazy-loaded: {image_data.get('summary', {}).get('lazy_loaded_images_count', 0)} | Broken: {image_data.get('summary', {}).get('broken_images_count', 0)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Canvas Elements</div>
                <div class="kpi-value">{summary.get('canvas_count', 0)}</div>
                <div class="kpi-subtext">SVGs: {image_data.get('summary', {}).get('total_svgs', 0)} | CSS BG: {image_data.get('summary', {}).get('total_css_background_images', 0)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Interactive Elements</div>
                <div class="kpi-value">{summary.get('interactive_element_count', 0)}</div>
                <div class="kpi-subtext">Radios: {interactive.get('summary', {}).get('radio_count', 0)} | Checks: {interactive.get('summary', {}).get('checkbox_count', 0)} | Buttons: {interactive.get('summary', {}).get('button_count', 0)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Detected Questions</div>
                <div class="kpi-value">{summary.get('detected_question_containers', 0)}</div>
                <div class="kpi-subtext">{modality_chips}</div>
            </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="nav-tabs">
            <button class="tab-btn active" onclick="switchTab('tab-questions')">📝 Question Diagnostics</button>
            <button class="tab-btn" onclick="switchTab('tab-images')">🖼️ Images & Visuals ({summary.get('image_count', 0)})</button>
            <button class="tab-btn" onclick="switchTab('tab-interactive')">🔘 Interactive Controls ({summary.get('interactive_element_count', 0)})</button>
            <button class="tab-btn" onclick="switchTab('tab-a11y')">♿ Accessibility ({a11y_data.get('summary', {}).get('total_issues', 0)} Issues)</button>
            <button class="tab-btn" onclick="switchTab('tab-dom')">🌳 DOM Structure & Tags</button>
        </div>

        <!-- Tab 1: Questions Diagnostics -->
        <div id="tab-questions" class="tab-content active">
            <div class="card">
                <div class="card-header">
                    <span>Detected Question Containers & Modality Analysis</span>
                    <div>{modality_chips}</div>
                </div>
                <p class="text-muted" style="margin-bottom: 16px;">
                    Identifies whether exam or quiz questions appear as standard HTML text, rendered images (e.g. anti-copying screenshots), Canvas elements, or SVG vectors.
                </p>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Modality</th>
                                <th>Question Stem / Prompt</th>
                                <th>Choices Present</th>
                                <th>Diagnostic Findings</th>
                                <th>DOM Container</th>
                            </tr>
                        </thead>
                        <tbody>
                            {questions_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Tab 2: Images -->
        <div id="tab-images" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>Rendered Image Analysis</span>
                    <span>Total: {len(image_data.get('images', []))}</span>
                </div>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Status</th>
                                <th>Source URL</th>
                                <th>Alt Text</th>
                                <th>Rendered Dimensions</th>
                                <th>Natural Dimensions</th>
                                <th>Loading</th>
                                <th>Container</th>
                            </tr>
                        </thead>
                        <tbody>
                            {images_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Tab 3: Interactive Controls -->
        <div id="tab-interactive" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>Form Controls: Radios, Checkboxes, Buttons, and Inputs</span>
                </div>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Control Type</th>
                                <th>Name / Tag</th>
                                <th>Value</th>
                                <th>Associated Label / Text</th>
                                <th>State</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {interactive_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Tab 4: Accessibility -->
        <div id="tab-a11y" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>Accessibility Tree Audit & Violations</span>
                    <span class="badge badge-warning">{a11y_data.get('summary', {}).get('total_issues', 0)} issues detected</span>
                </div>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Severity</th>
                                <th>Role</th>
                                <th>Issue Type</th>
                                <th>Description</th>
                            </tr>
                        </thead>
                        <tbody>
                            {a11y_issues_rows}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Tab 5: DOM Structure -->
        <div id="tab-dom" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>Document Headings Hierarchy</span>
                </div>
                <div style="padding: 16px;">
                    <ul style="padding-left: 20px; line-height: 1.8;">
                        {headings_rows}
                    </ul>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <span>Dominant HTML Element Tags</span>
                </div>
                <div class="tag-bars">
                    {top_tags_rows}
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <span>Semantic Landmarks</span>
                </div>
                <div class="tag-bars">
                    {"".join([f'<div class="tag-bar-item"><span class="tag-name"><code>&lt;{k}&gt;</code></span><span class="tag-count">{v}</span></div>' for k, v in dom_struct.get('semantic_landmarks', {}).items()])}
                </div>
            </div>
        </div>

    </div>

    <script>
        function switchTab(tabId) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');
        }}
    </script>
</body>
</html>
"""
        return html_template

