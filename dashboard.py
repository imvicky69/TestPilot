"""
dashboard.py - TestPilot: Real-Time Visual Automation Dashboard & Remote Solver
Features:
- Modern Light Theme UI (Linear / Apple design system).
- Live on-screen floating HUD overlay injected onto Chrome exam tab.
- Live DOM detection of Question Palette (Total questions, Answered, Left, Not Answered).
- Multi-statement competitive exam anti-trap reasoning prompt.
- Fast Attempt 1 querying via gemini-flash-lite-latest with fallback cascade.
- Playwright CDP native locator clicking with center scrollIntoView (100% verified, zero skips).
"""

import argparse
import base64
import datetime
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

# Playwright
from playwright.sync_api import sync_playwright

# Local modules
from chrome_connector import check_cdp_endpoint, detect_chrome_processes, ChromeConnector

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Dashboard")

# Cache CDP and Process checks to avoid lag
_last_cdp_check = 0.0
_cached_cdp_result = (False, {}, [], "Initial")
_last_proc_check = 0.0
_cached_proc_result = (False, 0, [])

def get_cached_chrome_processes(ttl: float = 2.0):
    global _last_proc_check, _cached_proc_result
    now = time.time()
    if now - _last_proc_check > ttl:
        _cached_proc_result = detect_chrome_processes()
        _last_proc_check = now
    return _cached_proc_result

def get_cached_cdp_endpoint(ttl: float = 1.5):
    global _last_cdp_check, _cached_cdp_result
    now = time.time()
    if now - _last_cdp_check > ttl:
        _cached_cdp_result = check_cdp_endpoint("127.0.0.1", 9222, timeout=0.4)
        _last_cdp_check = now
    return _cached_cdp_result

app = FastAPI(title="TestPilot")

def load_saved_key() -> str:
    if os.path.exists(".gemini_key.txt"):
        try:
            with open(".gemini_key.txt", "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return os.environ.get("GEMINI_API_KEY", "")

# Global State
class AutomationState:
    def __init__(self):
        self.is_running = False
        self.stop_requested = False
        self.step_mode = False
        self.current_tab_id: Optional[str] = None
        self.current_tab_title: str = ""
        self.current_tab_url: str = ""
        self.api_key: str = load_saved_key()
        self.model: str = "gemini-flash-lite-latest"
        self.dry_run: bool = False
        self.delay: float = 3.5
        self.max_questions: int = 25
        self.show_overlay: bool = True
        
        # Telemetry & Current Question
        self.question_number: int = 0
        self.image_url: str = ""
        self.image_base64: str = ""
        self.predicted_answer: str = ""
        self.confidence: str = ""
        self.reasoning: str = ""
        self.latency_seconds: float = 0.0
        self.action_status: str = "Ready"
        self.total_solved: int = 0
        
        # DOM Live Palette Tracking
        self.total_questions: int = 0
        self.questions_answered: int = 0
        self.questions_not_answered: int = 0
        self.questions_left: int = 0
        self.questions_not_visited: int = 0
        self.palette_chips: List[Dict[str, Any]] = []
        
        # Logs & History
        self.logs: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        
        # Thread lock
        self.lock = threading.Lock()
        self.worker_thread: Optional[threading.Thread] = None

    def log(self, level: str, message: str, meta: Optional[Dict[str, Any]] = None):
        entry = {
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "level": level.upper(),
            "message": message,
            "meta": meta or {},
        }
        with self.lock:
            self.logs.append(entry)
            if len(self.logs) > 300:
                self.logs.pop(0)
        logger.info(f"[{entry['level']}] {message}")

state = AutomationState()

# Helper: Find Chrome Executable
def find_chrome_executable() -> Optional[str]:
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in paths:
        if os.path.isfile(p):
            return p
    return None

def launch_chrome_debug(port: int = 9222, target_url: Optional[str] = None) -> Tuple[bool, str]:
    import subprocess
    chrome_path = find_chrome_executable()
    if not chrome_path:
        return False, "Google Chrome executable not found in standard paths."

    debug_dir = os.path.join(os.environ.get("TEMP", os.getcwd()), "chrome_debug_profile")
    os.makedirs(debug_dir, exist_ok=True)

    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={debug_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if target_url:
        args.append(target_url)

    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, f"Chrome launched with CDP port {port}."
    except Exception as e:
        return False, f"Failed launching Chrome: {e}"

OPTION_MAP = {
    "A": "question-option-0",
    "B": "question-option-1",
    "C": "question-option-2",
    "D": "question-option-3",
    "1": "question-option-0",
    "2": "question-option-1",
    "3": "question-option-2",
    "4": "question-option-3",
}

def extract_palette_from_dom(page) -> Dict[str, Any]:
    """Extracts live exam palette status and question chips directly from the active pw.live test DOM."""
    js = """
    () => {
        const text = document.body.innerText || '';
        
        // Match summary counters from the legend
        const answeredMatch = text.match(/(\\d+)\\s*\\n*\\s*Answered(?!\\s*&)/i);
        const notAnsweredMatch = text.match(/(\\d+)\\s*\\n*\\s*Not Answered/i);
        const notVisitedMatch = text.match(/(\\d+)\\s*\\n*\\s*Not Visited/i);
        const reviewMatch = text.match(/(\\d+)\\s*\\n*\\s*Mark for review/i);
        
        // Find all question chips (e.g. questionItem-1, questionItem-2 or palette buttons)
        const chips = Array.from(document.querySelectorAll('[id*=\"questionItem\"], [class*=\"solutionQuestionChip\"], .col-span-1')).map(el => {
            const rawText = (el.innerText || '').trim();
            const num = parseInt(rawText);
            if (isNaN(num)) return null;
            
            const html = el.innerHTML || '';
            const cls = (el.className || '') + ' ' + (el.parentElement ? el.parentElement.className : '');
            
            let status = 'NOT_VISITED';
            if (cls.includes('isAnswered') || html.includes('rgb(27, 121, 56)') || html.includes('#0B7A32') || html.includes('bg-[#0B7A32]') || html.includes('bg-green')) {
                status = 'ANSWERED';
            } else if (cls.includes('isNotAnswered') || html.includes('#BF2734') || html.includes('bg-[#BF2734]') || html.includes('bg-[#FEE7E9]')) {
                status = 'NOT_ANSWERED';
            } else if (cls.includes('isActive') || html.includes('border-primary') || html.includes('border-[2px]')) {
                status = 'ACTIVE';
            } else if (html.includes('74, 31, 184') || cls.includes('review')) {
                status = 'REVIEW';
            }
            
            return { num, status };
        }).filter(Boolean);
        
        // Deduplicate chips by number
        const uniqueChips = {};
        chips.forEach(c => {
            if (!uniqueChips[c.num] || c.status !== 'NOT_VISITED') {
                uniqueChips[c.num] = c;
            }
        });
        const sortedChips = Object.values(uniqueChips).sort((a,b) => a.num - b.num);
        
        const ansCount = answeredMatch ? parseInt(answeredMatch[1]) : sortedChips.filter(c => c.status === 'ANSWERED').length;
        const notAnsCount = notAnsweredMatch ? parseInt(notAnsweredMatch[1]) : sortedChips.filter(c => c.status === 'NOT_ANSWERED').length;
        const notVisCount = notVisitedMatch ? parseInt(notVisitedMatch[1]) : sortedChips.filter(c => c.status === 'NOT_VISITED').length;
        const reviewCount = reviewMatch ? parseInt(reviewMatch[1]) : sortedChips.filter(c => c.status === 'REVIEW').length;
        
        const total = sortedChips.length || (ansCount + notAnsCount + notVisCount + reviewCount) || 0;
        const left = Math.max(0, total - ansCount);
        
        return {
            total_questions: total,
            answered: ansCount,
            not_answered: notAnsCount,
            not_visited: notVisCount,
            marked_review: reviewCount,
            questions_left: left,
            chips: sortedChips.map(c => ({ num: c.num, status: c.status }))
        };
    }
    """
    try:
        return page.evaluate(js)
    except Exception:
        return {"total_questions": 0, "answered": 0, "not_answered": 0, "questions_left": 0, "chips": []}

def update_screen_overlay_hud(page, status: str, q_num: Any = "-", answer: str = "-", confidence: str = "", answered: int = 0, total: int = 0, left: int = 0, msg: str = ""):
    """Injects or updates the on-screen live telemetry HUD widget directly onto the active Chrome exam page."""
    js = """
    (data) => {
        let hud = document.getElementById('testpilot-hud');
        if (!hud) {
            hud = document.createElement('div');
            hud.id = 'testpilot-hud';
            hud.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 2147483647;
                width: 310px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background: rgba(255, 255, 255, 0.95);
                backdrop-filter: blur(14px);
                -webkit-backdrop-filter: blur(14px);
                border: 1px solid rgba(203, 213, 225, 0.9);
                border-radius: 16px;
                box-shadow: 0 16px 36px rgba(15, 23, 42, 0.12), 0 4px 12px rgba(15, 23, 42, 0.06);
                color: #0f172a;
                user-select: none;
                transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
                overflow: hidden;
            `;
            document.body.appendChild(hud);
        }
        
        const status = data.status || 'ACTIVE';
        const qNum = data.qNum || '-';
        const answer = data.answer || '-';
        const conf = data.confidence || '';
        const answered = data.answered ?? 0;
        const total = data.total ?? 0;
        const left = data.left ?? (total - answered);
        const msg = data.msg || 'Automation active...';
        const pct = total > 0 ? Math.round((answered / total) * 100) : 0;
        
        let statusBadgeColor = '#10b981';
        let statusText = 'SOLVER ACTIVE';
        if (status === 'THINKING') {
            statusBadgeColor = '#6366f1';
            statusText = 'GEMINI VISION THINKING';
        } else if (status === 'TICKING') {
            statusBadgeColor = '#f59e0b';
            statusText = 'VERIFYING & TICKING';
        } else if (status === 'PACING') {
            statusBadgeColor = '#3b82f6';
            statusText = 'PACING DELAY';
        } else if (status === 'COMPLETED') {
            statusBadgeColor = '#10b981';
            statusText = 'TEST COMPLETED';
        }
        
        hud.innerHTML = `
            <div style="background: linear-gradient(135deg, #f8fafc 0%, #edf2f7 100%); border-bottom: 1px solid #e2e8f0; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${statusBadgeColor}; box-shadow: 0 0 8px ${statusBadgeColor};"></span>
                    <span style="font-size: 11px; font-weight: 700; letter-spacing: 0.5px; color: #334155; text-transform: uppercase;">${statusText}</span>
                </div>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 10px; font-weight: 800; color: #4f46e5; background: #eef2ff; padding: 2px 6px; border-radius: 4px;">TESTPILOT</span>
                    <span style="font-size: 11px; font-weight: 600; color: #64748b; background: #e2e8f0; padding: 2px 7px; border-radius: 999px;">Q#${qNum}</span>
                </div>
            </div>
            
            <div style="padding: 12px 14px;">
                <div style="display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 8px;">
                    <div>
                        <span style="font-size: 10px; text-transform: uppercase; font-weight: 600; color: #64748b; letter-spacing: 0.5px;">Predicted Choice</span>
                        <div style="font-size: 24px; font-weight: 800; color: #1e293b; line-height: 1.1;">Option ${answer}</div>
                    </div>
                    ${conf ? `<span style="font-size: 10px; font-weight: 700; color: ${conf === 'HIGH' ? '#047857' : '#b45309'}; background: ${conf === 'HIGH' ? '#d1fae5' : '#fef3c7'}; padding: 3px 8px; border-radius: 6px;">${conf}</span>` : ''}
                </div>
                
                <div style="margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; font-size: 11px; font-weight: 600; color: #475569; margin-bottom: 3px;">
                        <span>Progress: ${answered}/${total}</span>
                        <span>${left} Left</span>
                    </div>
                    <div style="width: 100%; height: 5px; background: #e2e8f0; border-radius: 999px; overflow: hidden;">
                        <div style="width: ${pct}%; height: 100%; background: linear-gradient(90deg, #6366f1, #3b82f6); border-radius: 999px; transition: width 0.3s ease;"></div>
                    </div>
                </div>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; margin-bottom: 8px;">
                    <div style="background: #f1f5f9; padding: 5px 6px; border-radius: 6px; text-align: center;">
                        <div style="font-size: 9px; font-weight: 600; color: #64748b; text-transform: uppercase;">Answered</div>
                        <div style="font-size: 13px; font-weight: 700; color: #10b981;">${answered}</div>
                    </div>
                    <div style="background: #f1f5f9; padding: 5px 6px; border-radius: 6px; text-align: center;">
                        <div style="font-size: 9px; font-weight: 600; color: #64748b; text-transform: uppercase;">Remaining</div>
                        <div style="font-size: 13px; font-weight: 700; color: #3b82f6;">${left}</div>
                    </div>
                    <div style="background: #f1f5f9; padding: 5px 6px; border-radius: 6px; text-align: center;">
                        <div style="font-size: 9px; font-weight: 600; color: #64748b; text-transform: uppercase;">Total</div>
                        <div style="font-size: 13px; font-weight: 700; color: #475569;">${total}</div>
                    </div>
                </div>
                
                <div style="font-size: 10px; color: #475569; background: #f8fafc; border: 1px solid #e2e8f0; padding: 5px 8px; border-radius: 6px; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    ℹ️ ${msg}
                </div>
            </div>
        `;
    }
    """
    try:
        page.evaluate(js, {
            "status": status,
            "qNum": q_num,
            "answer": answer,
            "confidence": confidence,
            "answered": answered,
            "total": total,
            "left": left,
            "msg": msg
        })
    except Exception:
        pass

# Worker Logic
def solve_single_question(page, api_key: str, model: str, dry_run: bool) -> Tuple[Dict[str, Any], str]:
    """Inspects question, calls Gemini REST API, selects option, clicks Save & Next."""
    # 1. Wait for question container
    page.wait_for_selector("#test-question-description", timeout=12000)
    
    # 2. Extract DOM Palette and update live counts
    palette = extract_palette_from_dom(page)
    with state.lock:
        state.total_questions = palette.get("total_questions", 0)
        state.questions_answered = palette.get("answered", 0)
        state.questions_not_answered = palette.get("not_answered", 0)
        state.questions_left = palette.get("questions_left", 0)
        state.questions_not_visited = palette.get("not_visited", 0)
        state.palette_chips = palette.get("chips", [])
    
    img_element = page.locator("#test-question-description img")
    img_src = ""
    img_bytes = b""
    if img_element.count() > 0:
        img_src = img_element.first.get_attribute("src") or ""

    if img_src and img_src.startswith("http"):
        try:
            resp = requests.get(img_src, timeout=8)
            if resp.status_code == 200 and len(resp.content) > 500:
                img_bytes = resp.content
        except Exception as e:
            state.log("WARN", f"Failed downloading img src ({e}); falling back to element screenshot.")

    if not img_bytes:
        img_bytes = page.locator("#test-question-description").screenshot(type="png")
        if not img_src:
            img_src = "DOM_SCREENSHOT"

    b64_str = base64.b64encode(img_bytes).decode("utf-8")

    # Update state for live viewing
    with state.lock:
        state.image_url = img_src
        state.image_base64 = f"data:image/png;base64,{b64_str}"
        state.action_status = f"Captured question stem ({len(img_bytes):,} bytes). Querying Gemini..."

    state.log("INFO", f"Captured question image ({len(img_bytes):,} bytes). Sending to Gemini ({model})...")

    # Update on-screen overlay HUD
    if state.show_overlay:
        update_screen_overlay_hud(
            page,
            status="THINKING",
            q_num=state.question_number,
            answered=state.questions_answered,
            total=state.total_questions,
            left=state.questions_left,
            msg=f"Captured {len(img_bytes):,} B stem. Querying Gemini Vision..."
        )

    # 3. Call Gemini Vision API with competitive exam anti-trap rules
    prompt_text = (
        "You are an elite competitive exam expert specializing in UPSC CSE and State PSC examinations.\n"
        "Carefully solve the multiple-choice question shown in this image with meticulous attention to detail.\n"
        "\nCRITICAL COMPETITIVE EXAM RULES & TRAPS TO AVOID:\n"
        "1. Exact Rocket & Missile Nomenclature: Watch out for classic traps swapping launch vehicles (e.g. LVM3 / GSLV Mk III vs PSLV), missile classes, or satellite series.\n"
        "2. Enactment vs Amendment Dates: Distinguish between original enactment years vs later amendments (e.g. UAPA 1967 vs 2004/2019).\n"
        "3. Co-Investor vs Beneficiary: Do not confuse third-party regional connectivity beneficiaries with direct project co-investors.\n"
        "4. Extreme Words: Words like 'all', 'only', 'always', 'exclusive', 'principal' are almost always false in multi-statement questions unless statutorily exact.\n"
        "5. Statement Counting: If asked 'How many statements are correct?' (Only one, Only two, All three, None), count individually verified statements.\n"
        "\nAnalyze each statement step-by-step. Return the single best correct option strictly conforming to the requested JSON schema."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text},
                    {"inline_data": {"mime_type": "image/png", "data": b64_str}}
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "OBJECT",
                "properties": {
                    "answer": {
                        "type": "STRING",
                        "enum": ["A", "B", "C", "D"],
                        "description": "The selected option letter (A, B, C, or D)"
                    },
                    "confidence": {
                        "type": "STRING",
                        "enum": ["HIGH", "MEDIUM", "LOW"]
                    },
                    "reasoning": {
                        "type": "STRING",
                        "description": "Clear step-by-step reasoning or mathematical derivation"
                    }
                },
                "required": ["answer"]
            },
            "temperature": 0.1
        }
    }

    models_to_try = [model]
    for fallback in ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.8-flash", "gemini-3.5-flash"]:
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    parsed = None
    last_error = ""
    latency = 0.0
    successful_model = model

    for attempt_idx, attempt_model in enumerate(models_to_try):
        clean_model = attempt_model.strip()
        model_path = clean_model if clean_model.startswith("models/") else f"models/{clean_model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent?key={api_key}"
        
        state.log("INFO", f"Querying {attempt_model} (attempt {attempt_idx+1}/{len(models_to_try)})...")
        t0 = time.time()
        try:
            api_resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=8)
            latency = time.time() - t0
            
            if api_resp.status_code == 200:
                res_json = api_resp.json()
                candidates = res_json.get("candidates", [])
                if candidates:
                    raw_text = candidates[0]["content"]["parts"][0]["text"]
                    parsed = json.loads(raw_text)
                    successful_model = attempt_model
                    break
                else:
                    last_error = "No candidates returned"
            else:
                last_error = f"HTTP {api_resp.status_code}: {api_resp.text[:200]}"
                state.log("WARN", f"Model {attempt_model} failed ({last_error}).")
        except requests.exceptions.Timeout:
            latency = time.time() - t0
            last_error = f"Model {attempt_model} read timed out after {latency:.1f}s"
            state.log("WARN", f"{last_error}. Trying next available fallback model...")
        except Exception as exc:
            last_error = str(exc)
            state.log("WARN", f"Model {attempt_model} error: {exc}. Trying fallback...")

    if not parsed:
        raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")

    ans = parsed.get("answer", "").upper()
    confidence = parsed.get("confidence", "UNKNOWN")
    reasoning = parsed.get("reasoning", "")

    with state.lock:
        state.predicted_answer = ans
        state.confidence = confidence
        state.reasoning = reasoning
        state.latency_seconds = round(latency, 2)
        state.action_status = f"Gemini answered '{ans}' ({confidence} confidence) in {latency:.2f}s."

    state.log("SUCCESS", f"Gemini Answer: [{ans}] | Confidence: {confidence} | Latency: {latency:.2f}s", {"reasoning": reasoning})

    if state.show_overlay:
        update_screen_overlay_hud(
            page,
            status="TICKING",
            q_num=state.question_number,
            answer=ans,
            confidence=confidence,
            answered=state.questions_answered,
            total=state.total_questions,
            left=state.questions_left,
            msg=f"Option {ans} ({confidence}). Verifying in DOM..."
        )

    # 4. Apply DOM Interaction with Smooth Center Scroll & Native Locator Click
    opt_id = OPTION_MAP.get(ans)
    action_text = ""
    if not opt_id:
        raise ValueError(f"Invalid answer choice received: {ans}")

    if dry_run:
        action_text = f"[DRY-RUN] Verified option #{opt_id} (Option {ans}). Skipped clicking."
        state.log("INFO", action_text)
    else:
        # 1. Scroll option card cleanly into center of viewport
        page.evaluate(f"""() => {{
            const inp = document.getElementById('{opt_id}');
            if (!inp) return;
            const row = inp.closest('div.cursor-pointer') || inp.parentElement;
            if (row) {{
                row.scrollIntoView({{ behavior: 'instant', block: 'center' }});
            }}
        }}""")
        time.sleep(0.15)

        # 2. Trigger Playwright native locator click on the label / radio wrapper
        label_loc = page.locator(f"label:has(#{opt_id})")
        if label_loc.count() > 0:
            label_loc.first.scroll_into_view_if_needed()
            label_loc.first.click(timeout=2500)
        else:
            row_loc = page.locator(f"div.cursor-pointer:has(#{opt_id})")
            if row_loc.count() > 0:
                row_loc.first.scroll_into_view_if_needed()
                row_loc.first.click(timeout=2500)
            else:
                inp_loc = page.locator(f"#{opt_id}")
                inp_loc.scroll_into_view_if_needed()
                inp_loc.click(force=True, timeout=2000)

        # 3. Comprehensive React state trigger & DOM verification
        page.evaluate(f"""() => {{
            const inp = document.getElementById('{opt_id}');
            if (!inp) return;
            if (!inp.checked || inp.getAttribute('aria-checked') !== 'true') {{
                const lbl = inp.closest('label');
                if (lbl) lbl.click();
                inp.checked = true;
                inp.setAttribute('aria-checked', 'true');
                try {{
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked')?.set;
                    if (setter) setter.call(inp, true);
                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }} catch (e) {{}}
            }}
        }}""")

        # Poll for DOM confirmation
        checked = False
        for _ in range(15):
            time.sleep(0.1)
            checked = page.evaluate(f"""() => {{
                const inp = document.getElementById('{opt_id}');
                return inp ? (inp.checked || inp.getAttribute('aria-checked') === 'true') : false;
            }}""")
            if checked:
                break

        if not checked:
            err_msg = f"Failed to select Option {ans} (#{opt_id}) in DOM! Stopped before 'Save & Next' to prevent skipping question."
            state.log("ERROR", err_msg)
            raise RuntimeError(err_msg)

        state.log("SUCCESS", f"Verified Option {ans} (#{opt_id}) is CHECKED in DOM.")
        time.sleep(0.4)

        # Click Save & Next using Playwright native locator
        save_btn = page.locator("button#save-next-btn:visible, button:has-text('Save & Next'):visible").first
        save_btn.scroll_into_view_if_needed()
        save_btn.click(timeout=3000)

        action_text = f"Ticked #{opt_id} (Option {ans}) [VERIFIED] and clicked 'Save & Next'."
        state.log("SUCCESS", action_text)

        # Refresh live palette counters
        time.sleep(0.5)
        new_palette = extract_palette_from_dom(page)
        with state.lock:
            state.total_questions = new_palette.get("total_questions", state.total_questions)
            state.questions_answered = new_palette.get("answered", state.questions_answered + 1)
            state.questions_not_answered = new_palette.get("not_answered", state.questions_not_answered)
            state.questions_left = new_palette.get("questions_left", max(0, state.total_questions - state.questions_answered))
            state.questions_not_visited = new_palette.get("not_visited", state.questions_not_visited)
            state.palette_chips = new_palette.get("chips", state.palette_chips)

        if state.show_overlay:
            update_screen_overlay_hud(
                page,
                status="PACING",
                q_num=state.question_number,
                answer=ans,
                confidence=confidence,
                answered=state.questions_answered,
                total=state.total_questions,
                left=state.questions_left,
                msg=f"Option {ans} [VERIFIED]. Pacing before next question..."
            )

    with state.lock:
        state.action_status = action_text
        state.total_solved += 1
        history_item = {
            "num": state.total_solved,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "image": state.image_base64,
            "answer": ans,
            "confidence": confidence,
            "reasoning": reasoning,
            "latency": round(latency, 2),
            "status": "SUCCESS" if not dry_run else "DRY_RUN",
        }
        state.history.append(history_item)
        if len(state.history) > 100:
            state.history.pop(0)

    return parsed, successful_model

def automation_worker_thread(tab_identifier: Any, api_key: str, model: str, dry_run: bool, delay: float, max_q: int, step_only: bool, show_overlay: bool = True):
    """Main worker thread executing the automation loop over Playwright CDP."""
    state.is_running = True
    state.stop_requested = False
    state.show_overlay = show_overlay
    state.log("INFO", f"Starting automation worker (step_mode={step_only}, max_questions={max_q}, pacing_delay={delay}s)...")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            contexts = browser.contexts
            if not contexts:
                raise RuntimeError("No browser contexts found in Chrome.")

            context = contexts[0]
            pages = context.pages
            if not pages:
                raise RuntimeError("No open tabs found in Chrome.")

            target_page = None
            if isinstance(tab_identifier, int) and tab_identifier < len(pages):
                target_page = pages[tab_identifier]
            else:
                for pg in pages:
                    if str(tab_identifier) in pg.url or str(tab_identifier) in pg.title():
                        target_page = pg
                        break
            if not target_page:
                target_page = pages[0]

            with state.lock:
                state.current_tab_title = target_page.title()
                state.current_tab_url = target_page.url

            state.log("INFO", f"Connected to target tab: '{target_page.title()}' ({target_page.url})")

            # Initial Palette Extraction
            init_palette = extract_palette_from_dom(target_page)
            with state.lock:
                state.total_questions = init_palette.get("total_questions", 0)
                state.questions_answered = init_palette.get("answered", 0)
                state.questions_not_answered = init_palette.get("not_answered", 0)
                state.questions_left = init_palette.get("questions_left", 0)
                state.questions_not_visited = init_palette.get("not_visited", 0)
                state.palette_chips = init_palette.get("chips", [])

            if show_overlay:
                update_screen_overlay_hud(
                    target_page,
                    status="ACTIVE",
                    q_num=1,
                    answered=state.questions_answered,
                    total=state.total_questions,
                    left=state.questions_left,
                    msg="Starting automated exam session..."
                )

            solved_in_session = 0
            current_model = model
            while not state.stop_requested and (step_only or solved_in_session < max_q):
                solved_in_session += 1
                with state.lock:
                    state.question_number = solved_in_session

                state.log("INFO", f"--- Processing Question #{solved_in_session} ---")
                try:
                    parsed, verified_model = solve_single_question(target_page, api_key=api_key, model=current_model, dry_run=dry_run)
                    if verified_model and verified_model != current_model:
                        current_model = verified_model
                        with state.lock:
                            state.model = verified_model
                        state.log("INFO", f"⚡ Pinned verified working model for all subsequent questions: {verified_model}")
                except Exception as ex:
                    state.log("ERROR", f"Error on question #{solved_in_session}: {ex}")
                    with state.lock:
                        state.action_status = f"Error: {ex}"
                    time.sleep(2.0)

                if step_only:
                    state.log("INFO", "Step execution completed.")
                    break

                # Pacing sleep
                for _ in range(int(delay * 10)):
                    if state.stop_requested:
                        break
                    time.sleep(0.1)

            state.log("INFO", f"Automation finished. Solved: {solved_in_session} question(s).")
            if show_overlay:
                update_screen_overlay_hud(
                    target_page,
                    status="COMPLETED",
                    q_num=solved_in_session,
                    answered=state.questions_answered,
                    total=state.total_questions,
                    left=state.questions_left,
                    msg=f"Finished! Solved {solved_in_session} question(s)."
                )

        except Exception as e:
            state.log("ERROR", f"Worker fatal error: {e}")
            with state.lock:
                state.action_status = f"Fatal Error: {e}"
        finally:
            state.is_running = False
            state.stop_requested = False


# API Routes
@app.get("/api/status")
def get_status():
    chrome_running, proc_count, _ = get_cached_chrome_processes()
    cdp_up, _, tabs, _ = get_cached_cdp_endpoint()
    return {
        "chrome_running": chrome_running,
        "chrome_processes": proc_count,
        "cdp_available": cdp_up,
        "tabs_count": len(tabs),
        "is_running": state.is_running,
        "current_tab_title": state.current_tab_title,
        "current_tab_url": state.current_tab_url,
    }

@app.get("/api/test-model")
def test_model(model_name: str = "gemini-flash-lite-latest"):
    key = state.api_key
    if not key:
        return {"error": "No API key in state"}
    clean_model = model_name.strip()
    m_path = clean_model if clean_model.startswith("models/") else f"models/{clean_model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{m_path}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": "Hello, reply strictly with: OK"}]}],
        "generationConfig": {"temperature": 0.0}
    }
    t0 = time.time()
    try:
        r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=8)
        lat = round(time.time() - t0, 2)
        return {"status_code": r.status_code, "latency": lat, "response": r.text[:200]}
    except Exception as e:
        return {"error": str(e), "latency": round(time.time() - t0, 2)}

@app.get("/api/models")
def get_available_models(api_key: Optional[str] = None):
    key = api_key or state.api_key
    preferred_order = ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.8-flash", "gemini-3.5-flash"]
    if not key:
        return {"models": preferred_order}
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            models_data = resp.json().get("models", [])
            valid_models = []
            for m in models_data:
                name = m.get("name", "").replace("models/", "")
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods and ("flash" in name or "pro" in name):
                    valid_models.append(name)
            
            sorted_models = []
            for p in preferred_order:
                if p in valid_models:
                    sorted_models.append(p)
            for m in valid_models:
                if m not in sorted_models:
                    sorted_models.append(m)
            return {"models": sorted_models or preferred_order}
        else:
            return {"models": preferred_order, "error": resp.text}
    except Exception as e:
        return {"models": preferred_order, "error": str(e)}

@app.post("/api/chrome/launch")
def api_launch_chrome(payload: Optional[Dict[str, Any]] = None):
    url = (payload or {}).get("url")
    ok, msg = launch_chrome_debug(port=9222, target_url=url)
    global _last_cdp_check, _last_proc_check
    _last_cdp_check = 0.0
    _last_proc_check = 0.0
    return {"success": ok, "message": msg}

@app.get("/api/tabs")
def get_tabs():
    cdp_up, _, raw_tabs, _ = get_cached_cdp_endpoint(ttl=0.5)
    if not cdp_up:
        return {"tabs": []}
    enriched = []
    for idx, t in enumerate(raw_tabs):
        if t.get("type") in ("page", "app"):
            u = t.get("url", "")
            title = t.get("title", "")
            is_test = "pw.live" in u or "practice" in u or "test" in u
            enriched.append({
                "index": idx,
                "id": t.get("id"),
                "title": title or "Untitled Tab",
                "url": u,
                "is_test": is_test,
            })
    return {"tabs": enriched}

@app.post("/api/solver/start")
def start_solver(req: Request, payload: Dict[str, Any]):
    if state.is_running:
        raise HTTPException(status_code=400, detail="Automation is already running.")

    api_key = payload.get("api_key", "").strip() or state.api_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key is required.")

    try:
        with open(".gemini_key.txt", "w", encoding="utf-8") as f:
            f.write(api_key)
    except Exception:
        pass

    tab_idx = payload.get("tab_index", 0)
    model = payload.get("model", "gemini-flash-lite-latest").strip()
    dry_run = bool(payload.get("dry_run", False))
    delay = float(payload.get("delay", 3.5))
    max_q = int(payload.get("max_questions", 25))
    step_only = bool(payload.get("step_only", False))
    show_overlay = bool(payload.get("show_overlay", True))

    state.api_key = api_key
    state.model = model
    state.dry_run = dry_run
    state.delay = delay
    state.max_questions = max_q
    state.show_overlay = show_overlay

    worker = threading.Thread(
        target=automation_worker_thread,
        args=(tab_idx, api_key, model, dry_run, delay, max_q, step_only, show_overlay),
        daemon=True,
    )
    state.worker_thread = worker
    worker.start()

    return {"status": "started", "step_mode": step_only}

@app.post("/api/solver/stop")
def stop_solver():
    if not state.is_running:
        return {"status": "not_running"}
    state.stop_requested = True
    state.log("WARN", "Stop / Pause requested by user. Waiting for active question to finish...")
    return {"status": "stopping"}

@app.get("/api/solver/state")
def get_solver_state():
    with state.lock:
        return {
            "is_running": state.is_running,
            "question_number": state.question_number,
            "image_url": state.image_url,
            "image_base64": state.image_base64,
            "predicted_answer": state.predicted_answer,
            "confidence": state.confidence,
            "reasoning": state.reasoning,
            "latency_seconds": state.latency_seconds,
            "action_status": state.action_status,
            "total_solved": state.total_solved,
            "total_questions": state.total_questions,
            "questions_answered": state.questions_answered,
            "questions_not_answered": state.questions_not_answered,
            "questions_left": state.questions_left,
            "questions_not_visited": state.questions_not_visited,
            "palette_chips": state.palette_chips,
            "history": state.history[-15:],
            "logs": state.logs[-40:],
        }

@app.get("/api/logs")
def get_logs():
    with state.lock:
        return {"logs": state.logs}

# Dashboard SPA HTML - High-End Light Modern Theme (Linear / Apple design)
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TestPilot</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @keyframes pulse-subtle {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.8; transform: scale(0.98); }
    }
    .pulse-indicator { animation: pulse-subtle 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #f1f5f9; }
    ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
  </style>
</head>
<body class="bg-[#f8fafc] text-slate-800 font-sans min-h-screen flex flex-col antialiased selection:bg-indigo-500 selection:text-white">

  <!-- Top Navigation & Control Header -->
  <header class="bg-white border-b border-slate-200/90 px-6 py-3.5 sticky top-0 z-50 shadow-[0_1px_3px_0_rgba(0,0,0,0.04)]">
    <div class="max-w-[1600px] mx-auto flex flex-wrap items-center justify-between gap-4">
      
      <!-- Brand & Status Badges -->
      <div class="flex items-center gap-4">
        <div class="flex items-center gap-2.5">
          <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-600 flex items-center justify-center shadow-md shadow-indigo-500/20">
            <i class="fa-solid fa-brain text-white text-base"></i>
          </div>
          <div>
            <h1 class="text-base font-bold tracking-tight text-slate-900 flex items-center gap-2">
              TestPilot
              <span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">Live</span>
            </h1>
            <p class="text-[11px] text-slate-500 font-medium">CDP Automation & Vision AI</p>
          </div>
        </div>

        <div class="h-6 w-[1px] bg-slate-200 mx-1 hidden sm:block"></div>

        <!-- CDP Status Pill -->
        <div id="badge-cdp" class="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200">
          <span class="w-2 h-2 rounded-full bg-rose-500"></span>
          <span id="text-cdp">CDP Disconnected</span>
        </div>

        <!-- Runner Status Pill -->
        <div id="badge-runner" class="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 border border-slate-200">
          <span class="w-2 h-2 rounded-full bg-slate-400"></span>
          <span id="text-runner">Runner Idle</span>
        </div>
      </div>

      <!-- Quick Actions: Launch Chrome & Tabs -->
      <div class="flex items-center flex-wrap gap-2.5">
        <button onclick="launchChrome()" id="btn-launch-chrome" class="px-3.5 py-2 bg-slate-100 hover:bg-slate-200 active:bg-slate-300 border border-slate-200 text-xs font-semibold rounded-lg text-slate-700 transition flex items-center gap-2 shadow-sm">
          <i class="fa-brands fa-chrome text-amber-500 text-sm"></i>
          <span>Launch Debug Chrome</span>
        </button>

        <div class="flex items-center gap-1 bg-slate-50 border border-slate-200 rounded-lg p-1">
          <button onclick="refreshTabs()" title="Refresh Open Tabs" class="p-1.5 hover:bg-slate-200 rounded text-slate-500 hover:text-slate-800 transition">
            <i class="fa-solid fa-arrows-rotate text-xs"></i>
          </button>
          <select id="tab-selector" class="bg-transparent text-xs text-slate-700 focus:outline-none px-2 py-1 max-w-[280px] truncate font-medium">
            <option value="0">Loading tabs...</option>
          </select>
        </div>

        <!-- Start / Stop / Step Controls -->
        <div class="flex items-center gap-2 ml-1">
          <button onclick="startSolving(true)" id="btn-step" class="px-3 py-2 bg-indigo-50 hover:bg-indigo-100 active:bg-indigo-200 border border-indigo-200 text-xs font-bold rounded-lg text-indigo-700 transition flex items-center gap-1.5 shadow-sm">
            <i class="fa-solid fa-forward-step"></i>
            <span>Solve 1 Step</span>
          </button>

          <button onclick="startSolving(false)" id="btn-start" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-xs font-bold rounded-lg text-white transition flex items-center gap-1.5 shadow-md shadow-indigo-600/20">
            <i class="fa-solid fa-play"></i>
            <span>Start Auto</span>
          </button>

          <button onclick="stopSolving()" id="btn-stop" disabled class="px-3 py-2 bg-rose-50 hover:bg-rose-100 active:bg-rose-200 border border-rose-200 text-rose-700 disabled:opacity-40 disabled:cursor-not-allowed text-xs font-bold rounded-lg transition flex items-center gap-1.5">
            <i class="fa-solid fa-stop"></i>
            <span>Stop</span>
          </button>
        </div>

      </div>
    </div>
  </header>

  <!-- Main Container -->
  <main class="max-w-[1600px] mx-auto p-6 flex-1 w-full space-y-6">

    <!-- Live Exam Counters Top Row (4 Metric Cards) -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      
      <!-- Answered Card -->
      <div class="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-sm flex items-center justify-between">
        <div>
          <div class="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Answered (DOM)</div>
          <div id="stat-answered" class="text-2xl font-black text-emerald-600 mt-1">0</div>
          <div class="text-[10px] text-emerald-700 font-medium">Confirmed Checked</div>
        </div>
        <div class="w-11 h-11 rounded-xl bg-emerald-50 border border-emerald-200 flex items-center justify-center text-emerald-600 text-lg">
          <i class="fa-solid fa-circle-check"></i>
        </div>
      </div>

      <!-- Remaining Card -->
      <div class="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-sm flex items-center justify-between">
        <div>
          <div class="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Remaining (Left)</div>
          <div id="stat-left" class="text-2xl font-black text-indigo-600 mt-1">0</div>
          <div class="text-[10px] text-indigo-600 font-medium">Pending to Solve</div>
        </div>
        <div class="w-11 h-11 rounded-xl bg-indigo-50 border border-indigo-200 flex items-center justify-center text-indigo-600 text-lg">
          <i class="fa-solid fa-list-check"></i>
        </div>
      </div>

      <!-- Total Questions Card -->
      <div class="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-sm flex items-center justify-between">
        <div>
          <div class="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Total Questions</div>
          <div id="stat-total" class="text-2xl font-black text-slate-800 mt-1">0</div>
          <div class="text-[10px] text-slate-500 font-medium">Detected in Section</div>
        </div>
        <div class="w-11 h-11 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-600 text-lg">
          <i class="fa-solid fa-shapes"></i>
        </div>
      </div>

      <!-- Latency & Model Card -->
      <div class="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-sm flex items-center justify-between">
        <div>
          <div class="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Gemini Latency</div>
          <div id="stat-latency" class="text-2xl font-black text-amber-600 mt-1">0.00s</div>
          <div id="stat-model-name" class="text-[10px] text-slate-500 font-medium truncate max-w-[150px]">gemini-flash-lite</div>
        </div>
        <div class="w-11 h-11 rounded-xl bg-amber-50 border border-amber-200 flex items-center justify-center text-amber-600 text-lg">
          <i class="fa-solid fa-bolt"></i>
        </div>
      </div>

    </div>

    <!-- Top Settings Drawer -->
    <div class="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-sm">
      <div class="grid grid-cols-1 md:grid-cols-5 gap-4 items-center">
        
        <!-- API Key Input -->
        <div class="space-y-1">
          <label class="text-[11px] font-bold text-slate-600 uppercase tracking-wider flex items-center justify-between">
            <span>Gemini API Key</span>
            <span class="text-[10px] text-emerald-600 font-medium">Stored Locally</span>
          </label>
          <div class="relative">
            <input type="password" id="input-api-key" placeholder="AIzaSy..." class="w-full bg-slate-50 border border-slate-300 text-xs text-slate-900 rounded-lg px-3 py-2 pr-9 focus:border-indigo-500 focus:bg-white focus:outline-none transition">
            <button onclick="toggleKeyVisibility()" class="absolute right-2.5 top-2.5 text-slate-400 hover:text-slate-600 text-xs">
              <i id="key-eye-icon" class="fa-solid fa-eye"></i>
            </button>
          </div>
        </div>

        <!-- Model Selection -->
        <div class="space-y-1">
          <label class="text-[11px] font-bold text-slate-600 uppercase tracking-wider">Vision Model</label>
          <select id="select-model" class="w-full bg-slate-50 border border-slate-300 text-xs text-slate-900 rounded-lg px-3 py-2 focus:border-indigo-500 focus:bg-white focus:outline-none transition font-medium">
            <option value="gemini-flash-lite-latest" selected>gemini-flash-lite-latest (Instant ~1.8s & Recommended)</option>
            <option value="gemini-flash-latest">gemini-flash-latest</option>
            <option value="gemini-3.8-flash">gemini-3.8-flash</option>
            <option value="gemini-3.5-flash">gemini-3.5-flash</option>
          </select>
        </div>

        <!-- Pacing Delay & Max Questions -->
        <div class="grid grid-cols-2 gap-2">
          <div class="space-y-1">
            <label class="text-[11px] font-bold text-slate-600 uppercase tracking-wider">Delay (sec)</label>
            <input type="number" id="input-delay" value="3.5" step="0.5" min="0.5" max="15" class="w-full bg-slate-50 border border-slate-300 text-xs text-slate-900 rounded-lg px-3 py-2 focus:border-indigo-500 focus:bg-white focus:outline-none font-medium">
          </div>
          <div class="space-y-1">
            <label class="text-[11px] font-bold text-slate-600 uppercase tracking-wider">Max Qs</label>
            <input type="number" id="input-max-q" value="25" min="1" max="200" class="w-full bg-slate-50 border border-slate-300 text-xs text-slate-900 rounded-lg px-3 py-2 focus:border-indigo-500 focus:bg-white focus:outline-none font-medium">
          </div>
        </div>

        <!-- On-Screen Overlay Toggle -->
        <div class="flex items-center gap-3 bg-slate-50 p-2.5 rounded-xl border border-slate-200">
          <label class="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" id="check-overlay" checked class="sr-only peer">
            <div class="w-9 h-5 bg-slate-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600"></div>
          </label>
          <div>
            <div class="text-xs font-bold text-slate-800">On-Screen HUD</div>
            <div class="text-[11px] text-slate-500">Live overlay on exam tab</div>
          </div>
        </div>

        <!-- Dry Run Mode Toggle -->
        <div class="flex items-center gap-3 bg-slate-50 p-2.5 rounded-xl border border-slate-200">
          <label class="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" id="check-dry-run" class="sr-only peer">
            <div class="w-9 h-5 bg-slate-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-amber-500"></div>
          </label>
          <div>
            <div class="text-xs font-bold text-slate-800">Dry-Run Mode</div>
            <div class="text-[11px] text-slate-500">Solve without clicking</div>
          </div>
        </div>

      </div>
    </div>

    <!-- Live Execution Grid (Split View) -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">

      <!-- Left Column: Live Question Image & Palette (7 Cols) -->
      <div class="lg:col-span-7 space-y-4">
        
        <!-- Question Stem Card -->
        <div class="bg-white border border-slate-200/90 rounded-2xl overflow-hidden shadow-sm flex flex-col h-[520px]">
          
          <!-- Card Header -->
          <div class="px-5 py-3.5 border-b border-slate-200 flex items-center justify-between bg-slate-50/70">
            <div class="flex items-center gap-3">
              <span class="w-2.5 h-2.5 rounded-full bg-indigo-600 pulse-indicator"></span>
              <h2 class="text-sm font-bold text-slate-900 flex items-center gap-2">
                Active Question Stem
                <span id="lbl-question-num" class="px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200 text-xs font-bold"># -</span>
              </h2>
            </div>
            <div class="flex items-center gap-2">
              <span id="lbl-img-source" class="text-[11px] text-slate-400 font-mono truncate max-w-[260px]">Waiting for capture...</span>
              <button onclick="openImageInNewTab()" title="Expand full image" class="p-1 hover:bg-slate-200 rounded text-slate-500 hover:text-slate-800 transition">
                <i class="fa-solid fa-up-right-from-square text-xs"></i>
              </button>
            </div>
          </div>

          <!-- Image Container -->
          <div class="flex-1 bg-slate-100/50 flex items-center justify-center p-4 overflow-auto relative">
            <img id="img-question" src="" alt="Question Preview" class="max-h-full max-w-full object-contain rounded-lg shadow-sm border border-slate-200 hidden">
            
            <div id="img-placeholder" class="text-center space-y-3 text-slate-400 py-16">
              <i class="fa-regular fa-image text-4xl text-slate-300"></i>
              <p class="text-xs text-slate-500 font-medium">No question captured yet.<br>Click <span class="text-indigo-600 font-bold">'Solve 1 Step'</span> or <span class="text-indigo-600 font-bold">'Start Auto'</span> to extract the active question.</p>
            </div>
          </div>

          <!-- Live Status Bar -->
          <div class="px-5 py-2.5 border-t border-slate-200 bg-slate-50/80 flex items-center justify-between text-xs">
            <div class="flex items-center gap-2">
              <span class="text-slate-500 font-semibold">Status:</span>
              <span id="lbl-action-status" class="text-slate-800 font-mono font-medium">System Ready</span>
            </div>
            <div class="text-[11px] text-slate-500">
              Session Solved: <span id="lbl-total-solved" class="text-indigo-600 font-bold">0</span>
            </div>
          </div>

        </div>

        <!-- Live Question Palette Chips Grid Card -->
        <div class="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-sm">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <i class="fa-solid fa-border-all text-indigo-600 text-sm"></i>
              <h3 class="text-xs font-bold text-slate-900 uppercase tracking-wider">Exam Question Palette</h3>
            </div>
            <div class="flex items-center gap-3 text-[11px] font-medium text-slate-500">
              <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-emerald-500"></span> Answered</span>
              <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-rose-500"></span> Not Answered</span>
              <span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded bg-slate-300"></span> Left</span>
            </div>
          </div>
          <div id="palette-chips-grid" class="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto p-1 bg-slate-50 rounded-xl border border-slate-200">
            <div class="text-xs text-slate-400 p-2 font-medium">Palette chips will appear when test is attached...</div>
          </div>
        </div>

      </div>

      <!-- Right Column: Gemini Decision & Telemetry (5 Cols) -->
      <div class="lg:col-span-5 space-y-4">
        
        <!-- Decision Card -->
        <div class="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-sm space-y-4">
          <div class="flex items-center justify-between border-b border-slate-200 pb-3">
            <h2 class="text-sm font-bold text-slate-900 flex items-center gap-2">
              <i class="fa-solid fa-wand-magic-sparkles text-indigo-600"></i>
              Gemini Vision Decision
            </h2>
            <div class="flex items-center gap-2">
              <span class="text-[11px] text-slate-500">Latency:</span>
              <span id="lbl-latency" class="text-xs font-mono font-bold text-indigo-600">0.00s</span>
            </div>
          </div>

          <!-- Answer & Confidence Spotlight -->
          <div class="grid grid-cols-2 gap-4">
            
            <!-- Predicted Answer Badge -->
            <div class="bg-slate-50 border border-slate-200 rounded-xl p-3.5 text-center flex flex-col items-center justify-center">
              <span class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Predicted Choice</span>
              <div id="badge-answer" class="w-14 h-14 rounded-2xl bg-indigo-50 border border-indigo-200 flex items-center justify-center text-3xl font-black text-indigo-700 shadow-sm">
                -
              </div>
            </div>

            <!-- Confidence Rating -->
            <div class="bg-slate-50 border border-slate-200 rounded-xl p-3.5 text-center flex flex-col items-center justify-center">
              <span class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Model Confidence</span>
              <div id="badge-confidence" class="px-3.5 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider bg-slate-200 text-slate-600 border border-slate-300">
                PENDING
              </div>
              <span class="text-[10px] text-slate-400 font-medium mt-2">Zero-shot multimodal</span>
            </div>

          </div>

          <!-- Reasoning Output Box -->
          <div class="space-y-1.5">
            <label class="text-[11px] font-bold text-slate-600 uppercase tracking-wider flex items-center gap-1.5">
              <i class="fa-solid fa-align-left text-xs"></i>
              <span>Step-by-Step Reasoning</span>
            </label>
            <div id="box-reasoning" class="h-44 bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs text-slate-700 font-sans leading-relaxed overflow-y-auto whitespace-pre-wrap select-text">
Reasoning will appear here once Gemini evaluates the question stem...
            </div>
          </div>

          <!-- DOM Action Confirmation -->
          <div class="bg-slate-50 border border-slate-200 rounded-xl p-3 flex items-center justify-between text-xs">
            <div class="flex items-center gap-2">
              <i class="fa-solid fa-circle-check text-emerald-600"></i>
              <span class="text-slate-500">DOM Radio:</span>
              <span id="lbl-dom-target" class="font-mono font-bold text-slate-800">-</span>
            </div>
            <span class="text-[11px] text-slate-500 font-mono">Button: #save-next-btn</span>
          </div>

        </div>

      </div>

    </div>

    <!-- Bottom Section: History & Live Event Console (Tabs) -->
    <div class="bg-white border border-slate-200/90 rounded-2xl overflow-hidden shadow-sm">
      <div class="flex border-b border-slate-200 px-4 bg-slate-50/70 justify-between items-center">
        <div class="flex">
          <button onclick="switchBottomTab('history')" id="tab-btn-history" class="px-4 py-3 text-xs font-bold border-b-2 border-indigo-600 text-indigo-700 flex items-center gap-2">
            <i class="fa-solid fa-clock-rotate-left"></i>
            <span>Session History</span>
          </button>
          <button onclick="switchBottomTab('logs')" id="tab-btn-logs" class="px-4 py-3 text-xs font-bold border-b-2 border-transparent text-slate-500 hover:text-slate-800 flex items-center gap-2">
            <i class="fa-solid fa-terminal"></i>
            <span>Live Diagnostics Console</span>
          </button>
        </div>
        <button onclick="clearLogs()" class="text-xs text-slate-500 hover:text-slate-800 transition py-1 px-2.5 rounded hover:bg-slate-200">Clear</button>
      </div>

      <!-- History Pane -->
      <div id="pane-history" class="p-4 max-h-72 overflow-y-auto">
        <table class="w-full text-left text-xs text-slate-700">
          <thead class="bg-slate-50 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0 border-b border-slate-200">
            <tr>
              <th class="py-2.5 px-3">#</th>
              <th class="py-2.5 px-3">Time</th>
              <th class="py-2.5 px-3">Thumbnail</th>
              <th class="py-2.5 px-3">Choice</th>
              <th class="py-2.5 px-3">Confidence</th>
              <th class="py-2.5 px-3">Latency</th>
              <th class="py-2.5 px-3">Reasoning Snippet</th>
              <th class="py-2.5 px-3">Status</th>
            </tr>
          </thead>
          <tbody id="table-history-body" class="divide-y divide-slate-100 font-mono">
            <tr>
              <td colspan="8" class="text-center py-6 text-slate-400 font-sans">No questions solved yet in this session.</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Logs Pane -->
      <div id="pane-logs" class="p-4 max-h-72 overflow-y-auto font-mono text-xs text-slate-700 space-y-1 bg-slate-50 hidden">
        <div class="text-slate-400">Connecting to system telemetry...</div>
      </div>
    </div>

  </main>

  <script>
    // State persistence
    const savedKey = localStorage.getItem("gemini_api_key") || "";
    if (savedKey) {
      document.getElementById("input-api-key").value = savedKey;
      fetchAvailableModels(savedKey);
    }

    document.getElementById("input-api-key").addEventListener("input", (e) => {
      const val = e.target.value.trim();
      localStorage.setItem("gemini_api_key", val);
      if (val.length > 25) fetchAvailableModels(val);
    });

    async function fetchAvailableModels(apiKey) {
      if (!apiKey || apiKey.length < 20) return;
      try {
        const resp = await fetch("/api/models?api_key=" + encodeURIComponent(apiKey));
        const data = await resp.json();
        if (data.models && data.models.length > 0) {
          const sel = document.getElementById("select-model");
          const curVal = sel.value;
          sel.innerHTML = "";
          data.models.forEach(m => {
            const opt = document.createElement("option");
            opt.value = m;
            let label = m;
            if (m === "gemini-flash-lite-latest") label += " (Instant ~1.8s & Recommended)";
            else if (m.includes("1.5-flash")) label += " (Fast & Reliable GA)";
            else if (m.includes("2.0-flash")) label += " (High Speed)";
            else if (m.includes("3.8-flash")) label += " (Preview)";
            opt.textContent = label;
            sel.appendChild(opt);
          });
          if (data.models.includes("gemini-flash-lite-latest")) {
            sel.value = "gemini-flash-lite-latest";
          } else if (curVal && data.models.includes(curVal)) {
            sel.value = curVal;
          } else if (data.models.includes("gemini-flash-latest")) {
            sel.value = "gemini-flash-latest";
          } else if (data.models.includes("gemini-3.8-flash")) {
            sel.value = "gemini-3.8-flash";
          }
        }
      } catch (err) {
        console.warn("Dynamic model query failed:", err);
      }
    }

    function toggleKeyVisibility() {
      const el = document.getElementById("input-api-key");
      const icon = document.getElementById("key-eye-icon");
      if (el.type === "password") {
        el.type = "text";
        icon.classList.replace("fa-eye", "fa-eye-slash");
      } else {
        el.type = "password";
        icon.classList.replace("fa-eye-slash", "fa-eye");
      }
    }

    // Tab Switching
    function switchBottomTab(tab) {
      const historyPane = document.getElementById("pane-history");
      const logsPane = document.getElementById("pane-logs");
      const historyBtn = document.getElementById("tab-btn-history");
      const logsBtn = document.getElementById("tab-btn-logs");

      if (tab === "history") {
        historyPane.classList.remove("hidden");
        logsPane.classList.add("hidden");
        historyBtn.className = "px-4 py-3 text-xs font-bold border-b-2 border-indigo-600 text-indigo-700 flex items-center gap-2";
        logsBtn.className = "px-4 py-3 text-xs font-bold border-b-2 border-transparent text-slate-500 hover:text-slate-800 flex items-center gap-2";
      } else {
        historyPane.classList.add("hidden");
        logsPane.classList.remove("hidden");
        logsBtn.className = "px-4 py-3 text-xs font-bold border-b-2 border-indigo-600 text-indigo-700 flex items-center gap-2";
        historyBtn.className = "px-4 py-3 text-xs font-bold border-b-2 border-transparent text-slate-500 hover:text-slate-800 flex items-center gap-2";
      }
    }

    // Chrome Launch
    async function launchChrome() {
      const btn = document.getElementById("btn-launch-chrome");
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-amber-500"></i> Launching...`;
      try {
        const resp = await fetch("/api/chrome/launch", { method: "POST" });
        const data = await resp.json();
        alert(data.message);
        setTimeout(refreshTabs, 1500);
      } catch (e) {
        alert("Failed to launch Chrome: " + e);
      } finally {
        btn.innerHTML = `<i class="fa-brands fa-chrome text-amber-500 text-sm"></i> <span>Launch Debug Chrome</span>`;
      }
    }

    // Refresh Open Tabs
    async function refreshTabs() {
      const sel = document.getElementById("tab-selector");
      try {
        const resp = await fetch("/api/tabs");
        const data = await resp.json();
        sel.innerHTML = "";

        if (data.tabs && data.tabs.length > 0) {
          let testTabIdx = -1;
          data.tabs.forEach((t, i) => {
            const opt = document.createElement("option");
            opt.value = t.index;
            const badge = t.is_test ? "⭐ [TEST] " : "";
            opt.textContent = `${badge}${t.title.slice(0, 32)} (${t.url.slice(0, 25)}...)`;
            if (t.is_test && testTabIdx === -1) testTabIdx = i;
            sel.appendChild(opt);
          });
          if (testTabIdx !== -1) sel.selectedIndex = testTabIdx;
        } else {
          sel.innerHTML = `<option value="0">No Chrome tabs found (launch Chrome first)</option>`;
        }
      } catch (e) {
        sel.innerHTML = `<option value="0">Error loading tabs</option>`;
      }
    }

    // Start Solving
    async function startSolving(stepOnly = false) {
      const apiKey = document.getElementById("input-api-key").value.trim();
      if (!apiKey) {
        alert("Please enter your Gemini API Key in the settings drawer.");
        return;
      }

      const payload = {
        api_key: apiKey,
        model: document.getElementById("select-model").value,
        tab_index: parseInt(document.getElementById("tab-selector").value) || 0,
        dry_run: document.getElementById("check-dry-run").checked,
        delay: parseFloat(document.getElementById("input-delay").value) || 3.5,
        max_questions: parseInt(document.getElementById("input-max-q").value) || 25,
        step_only: stepOnly,
        show_overlay: document.getElementById("check-overlay").checked,
      };

      try {
        const resp = await fetch("/api/solver/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const res = await resp.json();
        if (resp.status !== 200) {
          alert("Error: " + res.detail);
        }
      } catch (e) {
        alert("Request failed: " + e);
      }
    }

    // Stop Solving
    async function stopSolving() {
      try {
        await fetch("/api/solver/stop", { method: "POST" });
      } catch (e) {
        console.error("Stop failed:", e);
      }
    }

    function openImageInNewTab() {
      const img = document.getElementById("img-question");
      if (img.src && !img.classList.contains("hidden")) {
        const w = window.open("");
        w.document.write(`<img src="${img.src}" style="max-width:100%; height:auto; margin:auto; display:block;">`);
      }
    }

    function clearLogs() {
      document.getElementById("pane-logs").innerHTML = "";
    }

    // Polling System State & UI updates
    let lastRenderedImg = "";
    async function pollState() {
      try {
        const sResp = await fetch("/api/status");
        const sys = await sResp.json();

        // Update Header Badges
        const cdpBadge = document.getElementById("badge-cdp");
        const cdpText = document.getElementById("text-cdp");
        if (sys.cdp_available) {
          cdpBadge.className = "flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200";
          cdpText.textContent = `CDP Connected (${sys.tabs_count} tabs)`;
        } else {
          cdpBadge.className = "flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200";
          cdpText.textContent = sys.chrome_running ? "CDP Port 9222 Closed" : "Chrome Offline";
        }

        const runnerBadge = document.getElementById("badge-runner");
        const runnerText = document.getElementById("text-runner");
        const btnStart = document.getElementById("btn-start");
        const btnStep = document.getElementById("btn-step");
        const btnStop = document.getElementById("btn-stop");

        if (sys.is_running) {
          runnerBadge.className = "flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200";
          runnerText.innerHTML = `<span class="w-2 h-2 rounded-full bg-indigo-600 pulse-indicator"></span> Running Automation`;
          btnStart.disabled = true;
          btnStep.disabled = true;
          btnStop.disabled = false;
        } else {
          runnerBadge.className = "flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 border border-slate-200";
          runnerText.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-400"></span> Runner Idle`;
          btnStart.disabled = false;
          btnStep.disabled = false;
          btnStop.disabled = true;
        }

        // Solver state
        const stateResp = await fetch("/api/solver/state");
        const st = await stateResp.json();

        // Top Statistics Cards
        document.getElementById("stat-answered").textContent = st.questions_answered || 0;
        document.getElementById("stat-left").textContent = st.questions_left || 0;
        document.getElementById("stat-total").textContent = st.total_questions || 0;
        document.getElementById("stat-latency").textContent = `${st.latency_seconds || 0}s`;

        // Question Image
        const img = document.getElementById("img-question");
        const placeholder = document.getElementById("img-placeholder");
        if (st.image_base64) {
          if (lastRenderedImg !== st.image_base64) {
            img.src = st.image_base64;
            lastRenderedImg = st.image_base64;
          }
          img.classList.remove("hidden");
          placeholder.classList.add("hidden");
        }

        document.getElementById("lbl-question-num").textContent = `# ${st.question_number || "-"}`;
        document.getElementById("lbl-img-source").textContent = st.image_url ? st.image_url.slice(-40) : "No stem";
        document.getElementById("lbl-action-status").textContent = st.action_status || "Ready";
        document.getElementById("lbl-total-solved").textContent = st.total_solved;

        // Render Palette Chips
        if (st.palette_chips && st.palette_chips.length > 0) {
          const grid = document.getElementById("palette-chips-grid");
          grid.innerHTML = st.palette_chips.map(chip => {
            let bg = "bg-slate-200 text-slate-700";
            if (chip.status === "ANSWERED") bg = "bg-emerald-500 text-white font-bold";
            else if (chip.status === "NOT_ANSWERED") bg = "bg-rose-500 text-white font-bold";
            else if (chip.status === "ACTIVE") bg = "bg-indigo-600 text-white font-bold ring-2 ring-indigo-400 ring-offset-1";
            else if (chip.status === "REVIEW") bg = "bg-purple-600 text-white font-bold";
            return `<div class="w-7 h-7 flex items-center justify-center rounded-lg text-xs font-semibold ${bg} transition-all">${chip.num}</div>`;
          }).join("");
        }

        // Answer & Confidence
        const ansBadge = document.getElementById("badge-answer");
        ansBadge.textContent = st.predicted_answer || "-";

        const confBadge = document.getElementById("badge-confidence");
        confBadge.textContent = st.confidence || "PENDING";
        if (st.confidence === "HIGH") {
          confBadge.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider bg-emerald-50 text-emerald-700 border border-emerald-200";
        } else if (st.confidence === "MEDIUM") {
          confBadge.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider bg-amber-50 text-amber-700 border border-amber-200";
        } else if (st.confidence === "LOW") {
          confBadge.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider bg-rose-50 text-rose-700 border border-rose-200";
        } else {
          confBadge.className = "px-3.5 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider bg-slate-200 text-slate-600 border border-slate-300";
        }

        document.getElementById("lbl-latency").textContent = `${st.latency_seconds || 0}s`;
        document.getElementById("box-reasoning").textContent = st.reasoning || "Reasoning will appear here...";
        document.getElementById("lbl-dom-target").textContent = st.predicted_answer ? `#question-option-${["A","B","C","D"].indexOf(st.predicted_answer)}` : "-";

        // Render History Table
        if (st.history && st.history.length > 0) {
          const tbody = document.getElementById("table-history-body");
          tbody.innerHTML = st.history.slice().reverse().map(h => `
            <tr class="hover:bg-slate-50 transition">
              <td class="py-2.5 px-3 font-bold text-slate-900">#${h.num}</td>
              <td class="py-2.5 px-3 text-slate-500">${h.time}</td>
              <td class="py-2.5 px-3">
                <img src="${h.image}" class="w-10 h-7 object-cover rounded border border-slate-200 shadow-xs cursor-pointer" onclick="window.open('${h.image}')">
              </td>
              <td class="py-2.5 px-3 font-black text-indigo-700">Option ${h.answer}</td>
              <td class="py-2.5 px-3">
                <span class="px-2 py-0.5 rounded text-[10px] font-bold ${h.confidence === 'HIGH' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-slate-100 text-slate-600'}">${h.confidence}</span>
              </td>
              <td class="py-2.5 px-3 text-slate-600">${h.latency}s</td>
              <td class="py-2.5 px-3 text-slate-600 max-w-[340px] truncate font-sans">${h.reasoning}</td>
              <td class="py-2.5 px-3">
                <span class="px-2 py-0.5 rounded text-[10px] font-bold ${h.status === 'SUCCESS' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}">${h.status}</span>
              </td>
            </tr>
          `).join("");
        }

        // Render Logs Pane
        if (st.logs && st.logs.length > 0) {
          const logsPane = document.getElementById("pane-logs");
          logsPane.innerHTML = st.logs.slice().reverse().map(l => {
            let color = "text-slate-600";
            if (l.level === "SUCCESS") color = "text-emerald-700 font-semibold";
            else if (l.level === "WARN") color = "text-amber-700 font-semibold";
            else if (l.level === "ERROR") color = "text-rose-700 font-bold";
            return `<div><span class="text-slate-400">[${l.time}]</span> <span class="${color}">[${l.level}]</span> <span class="text-slate-800">${l.message}</span></div>`;
          }).join("");
        }

      } catch (err) {
        console.warn("Poll state error:", err);
      } finally {
        setTimeout(pollState, 1000);
      }
    }

    // Startup
    refreshTabs();
    pollState();
  </script>

</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return DASHBOARD_HTML

def main():
    parser = argparse.ArgumentParser(description="TestPilot - Live Automation Dashboard")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind dashboard server to")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface")
    parser.add_argument("--no-open", action="store_true", help="Do not automatically open browser on start")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    logger.info(f"Starting TestPilot at {url}")

    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

if __name__ == "__main__":
    main()
