"""
dom_inspector.py - DOM Inspection & Analysis Module

Extracts and analyzes document structure, element attributes, interactive controls
(radios, checkboxes, buttons, labels), text visibility, and structural depth.
Combines live browser DOM evaluation via Playwright with semantic parsing via BeautifulSoup.
"""

import logging
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from playwright.sync_api import Page

logger = logging.getLogger("ChromeDOMInspector.DOM")


class DOMInspector:
    """Performs deep inspection of the live DOM and rendered elements."""

    def __init__(self, page: Optional[Page] = None):
        self.page = page

    def extract_structure_bs4(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Convenience method for semantic BeautifulSoup structure extraction."""
        return self._extract_structure(soup)

    def extract_interactive_elements(
        self, page: Optional[Page] = None, soup: Optional[BeautifulSoup] = None
    ) -> Dict[str, Any]:
        """Extract interactive controls via live page or parsed BeautifulSoup."""
        if soup is not None or self.page is None:
            if soup is None and page is not None:
                soup = BeautifulSoup(page.content(), "html.parser")
            elif soup is None:
                return {"summary": {"total_interactive": 0}, "radios": [], "checkboxes": [], "buttons": []}

            radios = []
            for i, el in enumerate(soup.find_all("input", attrs={"type": "radio"})):
                parent_lbl = el.find_parent("label")
                lbl_text = parent_lbl.get_text(strip=True) if parent_lbl else ""
                radios.append({
                    "index": i,
                    "id": el.get("id"),
                    "name": el.get("name"),
                    "value": el.get("value"),
                    "checked": el.has_attr("checked"),
                    "label": lbl_text,
                    "visible": True,
                })

            checkboxes = []
            for i, el in enumerate(soup.find_all("input", attrs={"type": "checkbox"})):
                parent_lbl = el.find_parent("label")
                lbl_text = parent_lbl.get_text(strip=True) if parent_lbl else ""
                checkboxes.append({
                    "index": i,
                    "id": el.get("id"),
                    "name": el.get("name"),
                    "value": el.get("value"),
                    "checked": el.has_attr("checked"),
                    "label": lbl_text,
                    "visible": True,
                })

            buttons = []
            for i, el in enumerate(soup.find_all(["button", "input"])):
                if el.name == "button" or el.get("type") in ["submit", "button", "reset"]:
                    buttons.append({
                        "index": i,
                        "id": el.get("id"),
                        "text": el.get_text(strip=True) or el.get("value", ""),
                        "visible": True,
                    })

            return {
                "summary": {
                    "total_interactive": len(radios) + len(checkboxes) + len(buttons),
                    "radios_count": len(radios),
                    "checkboxes_count": len(checkboxes),
                    "buttons_count": len(buttons),
                },
                "radios": radios,
                "checkboxes": checkboxes,
                "buttons": buttons,
            }

        return self._extract_interactive_elements()

    def detect_question_containers(
        self, page: Optional[Page] = None, soup: Optional[BeautifulSoup] = None
    ) -> List[Dict[str, Any]]:
        """Classify question presentation modalities from HTML structure."""
        if soup is None:
            target_page = page or self.page
            if target_page:
                soup = BeautifulSoup(target_page.content(), "html.parser")
            else:
                return []

        candidates = soup.find_all(lambda tag: (
            tag.name in ["div", "fieldset", "article", "section"] and (
                any("question" in str(c).lower() or "quiz" in str(c).lower() for c in tag.get("class", [])) or
                "question" in (tag.get("id") or "").lower() or
                (tag.get("id") or "").startswith("q")
            )
        ))

        results = []
        for i, c in enumerate(candidates):
            cid = c.get("id") or f"q-{i}"
            if c.find("canvas"):
                modality = "CANVAS_BASED"
            elif c.find("svg"):
                modality = "SVG_BASED"
            elif c.find("img"):
                modality = "IMAGE_BASED"
            elif c.find_all("input", attrs={"type": "radio"}):
                modality = "HTML_TEXT"
            else:
                modality = "HTML_TEXT"
            results.append({
                "id": cid,
                "element_tag": c.name,
                "modality": modality,
                "stem_text": c.get_text(strip=True)[:100],
            })
        return results

    def inspect(self) -> Dict[str, Any]:
        """
        Execute comprehensive DOM analysis.
        Returns a dictionary containing metrics, interactive controls, text content, and DOM tree.
        """
        logger.info(f"Starting DOM inspection on '{self.page.url}'...")

        # 1. Fetch raw HTML for BeautifulSoup semantic parsing
        html_content = self.page.content()
        soup = BeautifulSoup(html_content, "html.parser")

        # 2. Document metadata
        meta_info = self._extract_metadata(soup)

        # 3. Live evaluated interactive elements (Playwright JS evaluation)
        interactive_data = self._extract_interactive_elements()

        # 4. Visible and hidden text analysis
        text_data = self._extract_text_content()

        # 5. DOM structure, tag counts, depth and semantic summary
        structure_data = self._extract_structure(soup)

        # 6. Simplified DOM skeleton for visualization
        skeleton = self._extract_dom_skeleton()

        report = {
            "metadata": meta_info,
            "structure": structure_data,
            "interactive": interactive_data,
            "text_analysis": text_data,
            "dom_skeleton": skeleton,
        }

        logger.info(
            f"DOM inspection finished: {structure_data['total_elements']} elements, "
            f"{interactive_data['summary']['total_interactive']} interactive elements."
        )
        return report

    def _extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract page metadata, title, encoding, viewport."""
        viewport_meta = soup.find("meta", attrs={"name": "viewport"})
        description_meta = soup.find("meta", attrs={"name": "description"})
        charset_meta = soup.find("meta", attrs={"charset": True})

        return {
            "title": self.page.title(),
            "url": self.page.url,
            "charset": charset_meta["charset"] if charset_meta and charset_meta.has_attr("charset") else "utf-8",
            "viewport": viewport_meta["content"] if viewport_meta and viewport_meta.has_attr("content") else None,
            "description": description_meta["content"] if description_meta and description_meta.has_attr("content") else None,
        }

    def _extract_interactive_elements(self) -> Dict[str, Any]:
        """
        Inspect radio buttons, checkboxes, buttons, labels, and input fields.
        Uses in-browser evaluation to assess live states and bounding client rects.
        """
        js_script = """
        () => {
            const getBox = (el) => {
                const r = el.getBoundingClientRect();
                return {
                    x: Math.round(r.x),
                    y: Math.round(r.y),
                    width: Math.round(r.width),
                    height: Math.round(r.height),
                    visible: r.width > 0 && r.height > 0 && window.getComputedStyle(el).visibility !== 'hidden' && window.getComputedStyle(el).display !== 'none'
                };
            };

            const getAssociatedLabel = (el) => {
                // 1. Check parent label
                let parent = el.closest('label');
                if (parent) {
                    return parent.innerText.trim();
                }
                // 2. Check for attribute
                if (el.id) {
                    const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    if (lbl) return lbl.innerText.trim();
                }
                // 3. Check aria-label or aria-labelledby
                if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
                if (el.getAttribute('aria-labelledby')) {
                    const ref = document.getElementById(el.getAttribute('aria-labelledby'));
                    if (ref) return ref.innerText.trim();
                }
                return null;
            };

            const getParentContext = (el) => {
                const parent = el.parentElement;
                if (!parent) return null;
                return {
                    tag: parent.tagName.toLowerCase(),
                    id: parent.id || null,
                    className: parent.className || null,
                    role: parent.getAttribute('role') || null
                };
            };

            // Collect Radios
            const radios = Array.from(document.querySelectorAll('input[type="radio"]')).map((el, i) => {
                const box = getBox(el);
                return {
                    index: i,
                    id: el.id || null,
                    name: el.name || null,
                    value: el.value || null,
                    checked: el.checked,
                    disabled: el.disabled,
                    required: el.required,
                    label: getAssociatedLabel(el),
                    container: getParentContext(el),
                    bounding_box: box,
                    visible: box.visible
                };
            });

            // Collect Checkboxes
            const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"]')).map((el, i) => {
                const box = getBox(el);
                return {
                    index: i,
                    id: el.id || null,
                    name: el.name || null,
                    value: el.value || null,
                    checked: el.checked,
                    disabled: el.disabled,
                    required: el.required,
                    label: getAssociatedLabel(el),
                    container: getParentContext(el),
                    bounding_box: box,
                    visible: box.visible
                };
            });

            // Collect Buttons
            const buttonSelectors = 'button, input[type="button"], input[type="submit"], input[type="reset"], [role="button"]';
            const buttons = Array.from(document.querySelectorAll(buttonSelectors)).map((el, i) => {
                const box = getBox(el);
                let text = el.innerText || el.value || el.getAttribute('aria-label') || el.title || '';
                return {
                    index: i,
                    tag: el.tagName.toLowerCase(),
                    type: el.type || (el.getAttribute('role') === 'button' ? 'role-button' : 'button'),
                    id: el.id || null,
                    className: el.className || null,
                    text: text.trim().substring(0, 100),
                    disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
                    container: getParentContext(el),
                    bounding_box: box,
                    visible: box.visible
                };
            });

            // Collect Text / Select / Other Form inputs
            const inputSelectors = 'input:not([type="radio"]):not([type="checkbox"]):not([type="button"]):not([type="submit"]):not([type="reset"]):not([type="hidden"]), select, textarea';
            const inputs = Array.from(document.querySelectorAll(inputSelectors)).map((el, i) => {
                const box = getBox(el);
                return {
                    index: i,
                    tag: el.tagName.toLowerCase(),
                    type: el.type || 'text',
                    id: el.id || null,
                    name: el.name || null,
                    placeholder: el.placeholder || null,
                    value: el.value ? el.value.substring(0, 50) : null,
                    disabled: el.disabled,
                    required: el.required || false,
                    label: getAssociatedLabel(el),
                    bounding_box: box,
                    visible: box.visible
                };
            });

            return {
                radios: radios,
                checkboxes: checkboxes,
                buttons: buttons,
                inputs: inputs,
                summary: {
                    radio_count: radios.length,
                    checkbox_count: checkboxes.length,
                    button_count: buttons.length,
                    input_count: inputs.length,
                    total_interactive: radios.length + checkboxes.length + buttons.length + inputs.length
                }
            };
        }
        """
        try:
            return self.page.evaluate(js_script)
        except Exception as exc:
            logger.error(f"Error evaluating interactive elements: {exc}")
            return {
                "radios": [],
                "checkboxes": [],
                "buttons": [],
                "inputs": [],
                "summary": {"radio_count": 0, "checkbox_count": 0, "button_count": 0, "input_count": 0, "total_interactive": 0},
            }

    def _extract_text_content(self) -> Dict[str, Any]:
        """Inspect visible and hidden text content."""
        js_script = """
        () => {
            const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                return style.display !== 'none' && 
                       style.visibility !== 'hidden' && 
                       style.opacity !== '0' &&
                       el.offsetWidth > 0 && 
                       el.offsetHeight > 0;
            };

            const allElements = document.querySelectorAll('h1, h2, h3, h4, h5, h6, p, span, li, a, td, th, div, label');
            let visibleTextSnippets = [];
            let hiddenTextCount = 0;
            let totalWords = 0;

            allElements.forEach(el => {
                // Ignore elements with child elements that already contain text to prevent duplicates
                if (el.children.length === 0) {
                    const text = el.innerText || el.textContent || '';
                    const trimmed = text.trim();
                    if (trimmed.length > 0) {
                        const words = trimmed.split(/\\s+/).length;
                        totalWords += words;
                        if (isVisible(el)) {
                            if (visibleTextSnippets.length < 50 && trimmed.length > 3) {
                                visibleTextSnippets.append ? visibleTextSnippets.append(trimmed) : visibleTextSnippets.push({
                                    tag: el.tagName.toLowerCase(),
                                    text: trimmed.length > 120 ? trimmed.substring(0, 120) + '...' : trimmed
                                });
                            }
                        } else {
                            hiddenTextCount++;
                        }
                    }
                }
            });

            return {
                total_words: totalWords,
                hidden_text_elements: hiddenTextCount,
                sample_visible_snippets: visibleTextSnippets.slice(0, 30)
            };
        }
        """
        try:
            return self.page.evaluate(js_script)
        except Exception as exc:
            logger.error(f"Error extracting text content: {exc}")
            return {"total_words": 0, "hidden_text_elements": 0, "sample_visible_snippets": []}

    def _extract_structure(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Calculate tag counts, max depth, semantic landmarks, and heading hierarchy."""
        all_tags = soup.find_all(True)
        tag_counts: Dict[str, int] = {}
        ids: List[str] = []
        classes: List[str] = []

        max_depth = 0
        for tag in all_tags:
            name = tag.name.lower()
            tag_counts[name] = tag_counts.get(name, 0) + 1

            if tag.get("id"):
                ids.append(tag["id"])
            if tag.get("class"):
                if isinstance(tag["class"], list):
                    classes.extend(tag["class"])
                else:
                    classes.append(tag["class"])

            # Compute depth
            depth = len(list(tag.parents))
            if depth > max_depth:
                max_depth = depth

        # Semantic landmarks
        landmarks = {
            "header": len(soup.find_all("header")),
            "nav": len(soup.find_all("nav")),
            "main": len(soup.find_all("main")),
            "article": len(soup.find_all("article")),
            "section": len(soup.find_all("section")),
            "aside": len(soup.find_all("aside")),
            "footer": len(soup.find_all("footer")),
            "form": len(soup.find_all("form")),
        }

        # Heading hierarchy
        headings = []
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            headings.append({
                "level": h.name.lower(),
                "text": h.get_text(strip=True)[:80]
            })

        # Sort tags by frequency
        sorted_tags = sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)

        return {
            "total_elements": len(all_tags),
            "max_dom_depth": max_depth,
            "unique_ids_count": len(set(ids)),
            "unique_classes_count": len(set(classes)),
            "top_tags": [{"tag": k, "count": v} for k, v in sorted_tags[:15]],
            "all_tag_counts": tag_counts,
            "semantic_landmarks": landmarks,
            "headings": headings[:20],
        }

    def _extract_dom_skeleton(self, max_depth: int = 4) -> Dict[str, Any]:
        """Build a simplified tree representation of the DOM up to max_depth for visual reporting."""
        js_script = f"""
        (maxDepth) => {{
            const buildNode = (el, currentDepth) => {{
                if (!el || currentDepth > maxDepth) return null;
                
                const node = {{
                    tag: el.tagName.toLowerCase(),
                    id: el.id || undefined,
                    class: el.className && typeof el.className === 'string' ? el.className.split(' ').slice(0, 3).join(' ') : undefined,
                    children: []
                }};

                const children = Array.from(el.children);
                for (let child of children) {{
                    const childNode = buildNode(child, currentDepth + 1);
                    if (childNode) {{
                        node.children.push(childNode);
                    }}
                    if (node.children.length >= 10) break; // Limit fan-out for readability
                }}

                return node;
            }};

            return buildNode(document.body, 1);
        }}
        """
        try:
            return self.page.evaluate(js_script, max_depth)
        except Exception as exc:
            logger.debug(f"Skeleton generation skipped or failed: {exc}")
            return {"tag": "body", "children": []}

