"""
image_analyzer.py - Image & Visual Structure Diagnostics Module

Performs in-depth analysis of rendered images, canvas elements, SVGs, CSS backgrounds,
image container hierarchies, and detects whether questions or assessment items
appear as images, canvas elements, SVGs, or standard HTML text.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from playwright.sync_api import Page

logger = logging.getLogger("ChromeDOMInspector.ImageAnalyzer")


class ImageAnalyzer:
    """Analyzes images, visual rendering containers, and question presentation modalities."""

    def __init__(self, page: Page):
        self.page = page

    def analyze(self) -> Dict[str, Any]:
        """Run full image diagnostics and question modality detection."""
        logger.info(f"Starting image and visual structure analysis on '{self.page.url}'...")

        # 1. Collect standard <img> elements
        img_elements = self._extract_img_tags()

        # 2. Collect <canvas> elements
        canvas_elements = self._extract_canvas_tags()

        # 3. Collect <svg> elements
        svg_elements = self._extract_svg_tags()

        # 4. Collect elements with CSS background-image
        bg_elements = self._extract_bg_images()

        # 5. Question Container & Modality Diagnostics
        question_diagnostics = self._detect_question_containers()

        # 6. Aggregate visual metrics
        summary = {
            "total_images": len(img_elements),
            "total_canvases": len(canvas_elements),
            "total_svgs": len(svg_elements),
            "total_css_background_images": len(bg_elements),
            "broken_images_count": sum(1 for img in img_elements if img.get("is_broken")),
            "lazy_loaded_images_count": sum(1 for img in img_elements if img.get("loading") == "lazy"),
            "hidden_images_count": sum(1 for img in img_elements if not img.get("is_visible")),
            "detected_question_containers_count": question_diagnostics["total_questions"],
            "question_modalities": question_diagnostics["modalities_summary"],
        }

        logger.info(
            f"Image diagnostics completed: {len(img_elements)} images, {len(canvas_elements)} canvases, "
            f"{len(svg_elements)} SVGs, {question_diagnostics['total_questions']} question containers detected."
        )

        return {
            "summary": summary,
            "images": img_elements,
            "canvases": canvas_elements,
            "svgs": svg_elements,
            "css_background_images": bg_elements,
            "question_diagnostics": question_diagnostics,
        }

    def _extract_img_tags(self) -> List[Dict[str, Any]]:
        """Inspect all <img> tags, dimensions, loading attrs, visibility, and parent chain."""
        js_script = """
        () => {
            const getParentChain = (el, maxLevels = 4) => {
                let chain = [];
                let curr = el.parentElement;
                let level = 0;
                while (curr && level < maxLevels && curr.tagName.toLowerCase() !== 'body') {
                    const idStr = curr.id ? `#${curr.id}` : '';
                    const classStr = curr.className && typeof curr.className === 'string' ? `.${curr.className.trim().split(/\\s+/).slice(0, 2).join('.')}` : '';
                    const style = window.getComputedStyle(curr);
                    chain.push({
                        tag: curr.tagName.toLowerCase(),
                        id: curr.id || null,
                        className: curr.className || null,
                        display: style.display,
                        role: curr.getAttribute('role') || null,
                        descriptor: `${curr.tagName.toLowerCase()}${idStr}${classStr}`
                    });
                    curr = curr.parentElement;
                    level++;
                }
                return chain;
            };

            const images = Array.from(document.querySelectorAll('img')).map((img, index) => {
                const rect = img.getBoundingClientRect();
                const style = window.getComputedStyle(img);
                const isVisible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                const inViewport = rect.top < window.innerHeight && rect.bottom >= 0 && rect.left < window.innerWidth && rect.right >= 0;
                
                const src = img.src || img.getAttribute('src') || '';
                let imageType = 'external';
                if (src.startsWith('data:')) imageType = 'data_uri';
                else if (src.startsWith('blob:')) imageType = 'blob';
                else if (src.endsWith('.svg') || src.includes('.svg?')) imageType = 'svg';
                else if (src.endsWith('.png')) imageType = 'png';
                else if (src.endsWith('.webp')) imageType = 'webp';
                else if (src.endsWith('.jpg') || src.endsWith('.jpeg')) imageType = 'jpeg';

                const isBroken = img.complete && img.naturalWidth === 0 && img.naturalHeight === 0 && src !== '';

                return {
                    index: index,
                    src: src.length > 300 ? src.substring(0, 300) + '...[truncated]' : src,
                    alt: img.alt !== undefined ? img.alt : null,
                    loading: img.getAttribute('loading') || 'eager',
                    decoding: img.decoding || 'auto',
                    natural_width: img.naturalWidth,
                    natural_height: img.naturalHeight,
                    rendered_width: Math.round(rect.width),
                    rendered_height: Math.round(rect.height),
                    aspect_ratio: rect.height > 0 ? +(rect.width / rect.height).toFixed(2) : null,
                    is_visible: isVisible,
                    in_viewport: inViewport,
                    is_broken: isBroken,
                    image_type: imageType,
                    bounding_box: {
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    },
                    container: getParentChain(img)[0] || null,
                    parent_chain: getParentChain(img)
                };
            });

            return images;
        }
        """
        try:
            return self.page.evaluate(js_script)
        except Exception as exc:
            logger.error(f"Error extracting image tags: {exc}")
            return []

    def _extract_canvas_tags(self) -> List[Dict[str, Any]]:
        """Inspect all <canvas> tags, pixel dimensions, client size, and container."""
        js_script = """
        () => {
            const canvases = Array.from(document.querySelectorAll('canvas')).map((cv, index) => {
                const rect = cv.getBoundingClientRect();
                const style = window.getComputedStyle(cv);
                const isVisible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                
                return {
                    index: index,
                    id: cv.id || null,
                    className: cv.className || null,
                    width_attr: cv.width,
                    height_attr: cv.height,
                    rendered_width: Math.round(rect.width),
                    rendered_height: Math.round(rect.height),
                    is_visible: isVisible,
                    bounding_box: {
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    },
                    container: cv.parentElement ? {
                        tag: cv.parentElement.tagName.toLowerCase(),
                        id: cv.parentElement.id || null,
                        className: cv.parentElement.className || null
                    } : null
                };
            });
            return canvases;
        }
        """
        try:
            return self.page.evaluate(js_script)
        except Exception as exc:
            logger.error(f"Error extracting canvas elements: {exc}")
            return []

    def _extract_svg_tags(self) -> List[Dict[str, Any]]:
        """Inspect all inline <svg> elements and check for embedded text, paths, or images."""
        js_script = """
        () => {
            const svgs = Array.from(document.querySelectorAll('svg')).map((svg, index) => {
                const rect = svg.getBoundingClientRect();
                const textNodes = Array.from(svg.querySelectorAll('text')).map(t => t.textContent.trim()).filter(Boolean);
                const hasImages = svg.querySelectorAll('image').length > 0;
                const pathCount = svg.querySelectorAll('path').length;

                return {
                    index: index,
                    id: svg.id || null,
                    className: svg.getAttribute('class') || null,
                    viewBox: svg.getAttribute('viewBox') || null,
                    rendered_width: Math.round(rect.width),
                    rendered_height: Math.round(rect.height),
                    path_count: pathCount,
                    has_embedded_images: hasImages,
                    embedded_text_count: textNodes.length,
                    sample_text: textNodes.slice(0, 3).join(', '),
                    container: svg.parentElement ? {
                        tag: svg.parentElement.tagName.toLowerCase(),
                        id: svg.parentElement.id || null,
                        className: svg.parentElement.className || null
                    } : null
                };
            });
            return svgs;
        }
        """
        try:
            return self.page.evaluate(js_script)
        except Exception as exc:
            logger.error(f"Error extracting SVGs: {exc}")
            return []

    def _extract_bg_images(self) -> List[Dict[str, Any]]:
        """Find elements with CSS background-image configured."""
        js_script = """
        () => {
            const bgImages = [];
            const all = document.querySelectorAll('*');
            for (let i = 0; i < all.length && bgImages.length < 50; i++) {
                const el = all[i];
                // Skip script/style/link/meta/img
                const tag = el.tagName.toLowerCase();
                if (['script', 'style', 'link', 'meta', 'img', 'svg'].includes(tag)) continue;

                const bg = window.getComputedStyle(el).backgroundImage;
                if (bg && bg !== 'none' && bg.startsWith('url(')) {
                    const rect = el.getBoundingClientRect();
                    const cleanUrl = bg.replace(/^url\\(['"]?/, '').replace(/['"]?\\)$/, '');
                    bgImages.push({
                        tag: tag,
                        id: el.id || null,
                        className: el.className || null,
                        background_url: cleanUrl.length > 200 ? cleanUrl.substring(0, 200) + '...' : cleanUrl,
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        is_visible: rect.width > 0 && rect.height > 0
                    });
                }
            }
            return bgImages;
        }
        """
        try:
            return self.page.evaluate(js_script)
        except Exception as exc:
            logger.error(f"Error extracting CSS background images: {exc}")
            return []

    def _detect_question_containers(self) -> Dict[str, Any]:
        """
        Detect question items in quizzes/exams and identify their presentation modality:
        - HTML_TEXT: Standard HTML paragraphs/spans/headings.
        - IMAGE_BASED: Question stem/body rendered as an image element.
        - CANVAS_BASED: Question stem rendered inside a <canvas>.
        - SVG_BASED: Question stem rendered inside an <svg>.
        - HYBRID: Mixed stem and options (e.g. image stem with HTML choices).
        """
        js_script = """
        () => {
            // Helper to test if text looks like a question or prompt
            const questionRegex = /(question|q\\.?\\s*\\d+|problem|item|prompt|exercise)/i;
            const numberStartRegex = /^\\s*(\\d+|[ivxlcdm]+)[\\.\\)]/i;

            const detectedQuestions = [];

            // 1. Look for explicit question container patterns
            const candidates = document.querySelectorAll(
                '[class*="question"], [id*="question"], [class*="quiz"], [class*="problem"], ' +
                '[class*="test-item"], [class*="mcq"], [role*="listitem"], fieldset, .card, article'
            );

            const processedElements = new Set();

            candidates.forEach((el, index) => {
                // Ignore tiny or massive containers
                const rect = el.getBoundingClientRect();
                if (rect.width < 50 || rect.height < 30) return;
                if (processedElements.has(el)) return;

                // Check text or headings inside
                const text = el.innerText ? el.innerText.trim() : '';
                const hasQuestionKeyword = questionRegex.test(el.className) || 
                                           questionRegex.test(el.id) || 
                                           questionRegex.test(text.substring(0, 100));

                const hasChoices = el.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"]').length > 0;

                // If candidate has question keyword or choices
                if (hasQuestionKeyword || hasChoices) {
                    processedElements.add(el);

                    // Analyze stem elements
                    const imgs = Array.from(el.querySelectorAll('img')).filter(img => {
                        const r = img.getBoundingClientRect();
                        return r.width > 40 && r.height > 20; // Filter out icons
                    });
                    const canvases = el.querySelectorAll('canvas');
                    const svgs = el.querySelectorAll('svg');
                    const textLength = text.length;

                    // Determine modality
                    let modality = 'UNKNOWN';
                    let confidence = 'MEDIUM';
                    let details = [];

                    if (canvases.length > 0 && textLength < 40) {
                        modality = 'CANVAS_BASED';
                        confidence = 'HIGH';
                        details.push(`Stem rendered via ${canvases.length} <canvas> element(s) with minimal HTML text (${textLength} chars)`);
                    } else if (imgs.length > 0 && textLength < 60) {
                        modality = 'IMAGE_BASED';
                        confidence = 'HIGH';
                        details.push(`Stem rendered via <img> tag (src: ${imgs[0].src.substring(0, 80)}...) with minimal HTML text`);
                    } else if (svgs.length > 0 && textLength < 40) {
                        modality = 'SVG_BASED';
                        confidence = 'HIGH';
                        details.push(`Stem rendered via ${svgs.length} <svg> element(s)`);
                    } else if (imgs.length > 0 && textLength >= 60) {
                        modality = 'HYBRID';
                        confidence = 'HIGH';
                        details.push(`Stem contains both HTML text (${textLength} chars) and supporting <img> element(s)`);
                    } else if (canvases.length > 0 && textLength >= 40) {
                        modality = 'HYBRID';
                        confidence = 'HIGH';
                        details.push(`Contains both HTML text and interactive/rendering <canvas>`);
                    } else if (textLength > 15) {
                        modality = 'HTML_TEXT';
                        confidence = 'HIGH';
                        details.push(`Standard HTML text rendering (${textLength} chars)`);
                    }

                    // Extract question title / stem snippet
                    let promptSnippet = text.substring(0, 150).replace(/\\n+/g, ' ');
                    if (!promptSnippet && imgs.length > 0) {
                        promptSnippet = `[Image Stem: ${imgs[0].alt || imgs[0].src.split('/').pop()}]`;
                    } else if (!promptSnippet && canvases.length > 0) {
                        promptSnippet = `[Canvas Stem ID: ${canvases[0].id || 'untitled'}]`;
                    }

                    detectedQuestions.push({
                        index: detectedQuestions.length + 1,
                        tag: el.tagName.toLowerCase(),
                        id: el.id || null,
                        className: el.className || null,
                        modality: modality,
                        confidence: confidence,
                        prompt_snippet: promptSnippet,
                        has_interactive_choices: hasChoices,
                        choice_radios_count: el.querySelectorAll('input[type="radio"]').length,
                        choice_checkboxes_count: el.querySelectorAll('input[type="checkbox"]').length,
                        image_stems_count: imgs.length,
                        canvas_count: canvases.length,
                        svg_count: svgs.length,
                        diagnostic_note: details.join('; '),
                        bounding_box: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        }
                    });
                }
            });

            return detectedQuestions;
        }
        """
        try:
            questions: List[Dict[str, Any]] = self.page.evaluate(js_script)
        except Exception as exc:
            logger.error(f"Error detecting question containers: {exc}")
            questions = []

        # Tally modality counts
        modalities_summary = {
            "HTML_TEXT": sum(1 for q in questions if q.get("modality") == "HTML_TEXT"),
            "IMAGE_BASED": sum(1 for q in questions if q.get("modality") == "IMAGE_BASED"),
            "CANVAS_BASED": sum(1 for q in questions if q.get("modality") == "CANVAS_BASED"),
            "SVG_BASED": sum(1 for q in questions if q.get("modality") == "SVG_BASED"),
            "HYBRID": sum(1 for q in questions if q.get("modality") == "HYBRID"),
            "UNKNOWN": sum(1 for q in questions if q.get("modality") == "UNKNOWN"),
        }

        return {
            "total_questions": len(questions),
            "modalities_summary": modalities_summary,
            "questions": questions,
        }

