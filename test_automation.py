"""
test_automation.py - Automated Testing & Question Solver via Chrome CDP and Gemini Multimodal API

Features:
- Connects to active Chrome instance via CDP (port 9222).
- Targets pw.live test session or inspectable tab.
- Extracts question image directly from DOM (div#test-question-description img) or element screenshot.
- Makes direct POST request to Gemini API (models/gemini-2.5-flash or gemini-1.5-flash) with structured JSON schema.
- Selects the predicted option (A/B/C/D via input#question-option-[0-3]).
- Clicks 'Save & Next' (button#save-next-btn:visible).
- Logs complete telemetry (timing, latency, reasoning, options) to automation_run.jsonl and console.
"""

import argparse
import base64
import datetime
import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional, Tuple
import requests

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Try importing ChromeConnector from local sandbox
try:
    from chrome_connector import ChromeConnector, check_cdp_endpoint
except ImportError:
    ChromeConnector = None

console = Console(highlight=False)

# Option ID mapping based on DOM report
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


class QuestionSolverAutomation:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-flash-lite-latest",
        host: str = "127.0.0.1",
        port: int = 9222,
        tab_keyword: str = "practice-v2",
        log_file: str = "automation_run.jsonl",
        dry_run: bool = False,
        pacing_delay: float = 1.5,
    ):
        self.api_key = api_key
        self.model = model
        self.host = host
        self.port = port
        self.tab_keyword = tab_keyword
        self.log_file = log_file
        self.dry_run = dry_run
        self.pacing_delay = pacing_delay
        self.connector: Optional[ChromeConnector] = None
        self.page = None

    def connect_browser(self):
        """Attach to Chrome instance over CDP."""
        console.print(f"[bold cyan]Connecting to Chrome CDP at {self.host}:{self.port}...[/bold cyan]")
        if ChromeConnector is None:
            raise RuntimeError("chrome_connector.py not found in working directory.")

        self.connector = ChromeConnector(host=self.host, port=self.port)
        self.page = self.connector.connect(tab_selector=self.tab_keyword)
        console.print(f"[bold green]Connected successfully![/bold green] Tab: '{self.page.title()}' ({self.page.url})")

    def capture_question_image(self) -> Tuple[bytes, str]:
        """
        Extract question image either via HTTP download of src attribute
        or via high-resolution DOM element screenshot fallback.
        """
        # Wait for question container to appear
        self.page.wait_for_selector("#test-question-description", timeout=10000)
        
        img_element = self.page.locator("#test-question-description img")
        img_count = img_element.count()
        img_src = ""

        if img_count > 0:
            img_src = img_element.first.get_attribute("src") or ""

        # Try downloading direct image src if available
        if img_src and img_src.startswith("http"):
            try:
                resp = requests.get(img_src, timeout=10)
                if resp.status_code == 200 and len(resp.content) > 500:
                    return resp.content, img_src
            except Exception as e:
                console.print(f"[yellow]Direct download failed ({e}); using element screenshot fallback...[/yellow]")

        # Fallback: Capture high-res screenshot of the question element directly
        question_locator = self.page.locator("#test-question-description")
        img_bytes = question_locator.screenshot(type="png")
        return img_bytes, img_src or "DOM_SCREENSHOT"

    def query_gemini_vision(self, image_bytes: bytes) -> Tuple[Dict[str, Any], float]:
        """
        Submit raw image to Gemini REST API requesting strict JSON output.
        Returns (parsed_json, latency_seconds).
        """
        clean_model = self.model.strip()
        model_path = clean_model if clean_model.startswith("models/") else f"models/{clean_model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent?key={self.api_key}"
        base64_img = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
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
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64_img,
                            }
                        },
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
                            "description": "The correct option key: A, B, C, or D",
                        },
                        "confidence": {
                            "type": "STRING",
                            "enum": ["HIGH", "MEDIUM", "LOW"],
                            "description": "Confidence level in this answer",
                        },
                        "reasoning": {
                            "type": "STRING",
                            "description": "Brief explanation / mathematical derivation for the answer",
                        },
                    },
                    "required": ["answer"],
                },
                "temperature": 0.1,
            },
        }

        models_to_try = [self.model]
        for fb in ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.8-flash", "gemini-3.5-flash"]:
            if fb not in models_to_try:
                models_to_try.append(fb)

        last_err = ""
        for attempt_m in models_to_try:
            clean_m = attempt_m.strip()
            m_path = clean_m if clean_m.startswith("models/") else f"models/{clean_m}"
            post_url = f"https://generativelanguage.googleapis.com/v1beta/{m_path}:generateContent?key={self.api_key}"
            start_time = time.time()
            try:
                resp = requests.post(post_url, json=payload, headers={"Content-Type": "application/json"}, timeout=8)
                latency = time.time() - start_time
                if resp.status_code == 200:
                    res_json = resp.json()
                    candidates = res_json.get("candidates", [])
                    if candidates:
                        text_content = candidates[0]["content"]["parts"][0]["text"]
                        parsed_data = json.loads(text_content)
                        if attempt_m != self.model:
                            self.model = attempt_m
                            console.print(f"[bold cyan]⚡ Switched and pinned active model to: {self.model}[/bold cyan]")
                        return parsed_data, latency
                    last_err = "No candidates in response"
                else:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:150]}"
            except requests.exceptions.Timeout:
                latency = time.time() - start_time
                last_err = f"Model {attempt_m} read timed out ({latency:.1f}s)"
            except Exception as ex:
                last_err = str(ex)

        raise RuntimeError(f"All Gemini models failed. Last error: {last_err}")

    def apply_answer_and_advance(self, answer_letter: str) -> str:
        """
        Ticks the option in DOM and clicks Save & Next.
        """
        option_id = OPTION_MAP.get(answer_letter.upper())
        if not option_id:
            raise ValueError(f"Unrecognized answer choice: {answer_letter}")

        if self.dry_run:
            return f"[DRY-RUN] Skipped clicking #{option_id} and 'Save & Next'"

        # 1. Scroll option card cleanly into center of viewport
        self.page.evaluate(f"""() => {{
            const inp = document.getElementById('{option_id}');
            if (!inp) return;
            const row = inp.closest('div.cursor-pointer') || inp.parentElement;
            if (row) {{
                row.scrollIntoView({{ behavior: 'instant', block: 'center' }});
            }}
        }}""")
        time.sleep(0.15)

        # 2. Trigger Playwright native locator click on the label / radio wrapper
        label_loc = self.page.locator(f"label:has(#{option_id})")
        if label_loc.count() > 0:
            label_loc.first.scroll_into_view_if_needed()
            label_loc.first.click(timeout=2500)
        else:
            row_loc = self.page.locator(f"div.cursor-pointer:has(#{option_id})")
            if row_loc.count() > 0:
                row_loc.first.scroll_into_view_if_needed()
                row_loc.first.click(timeout=2500)
            else:
                inp_loc = self.page.locator(f"#{option_id}")
                inp_loc.scroll_into_view_if_needed()
                inp_loc.click(force=True, timeout=2000)

        # 3. Comprehensive React state trigger & DOM verification
        self.page.evaluate(f"""() => {{
            const inp = document.getElementById('{option_id}');
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
            checked = self.page.evaluate(f"""() => {{
                const inp = document.getElementById('{option_id}');
                return inp ? (inp.checked || inp.getAttribute('aria-checked') === 'true') : false;
            }}""")
            if checked:
                break

        if not checked:
            raise RuntimeError(f"Could not verify selection of option {answer_letter} (#{option_id}). Aborted before Save & Next to prevent skipping.")

        time.sleep(0.4)

        # 2. Click visible Save & Next button using Playwright native locator (ensures real user gesture)
        save_btn = self.page.locator("button#save-next-btn:visible, button:has-text('Save & Next'):visible").first
        save_btn.scroll_into_view_if_needed()
        save_btn.click(timeout=3000)

        return f"Ticked #{option_id} (Option {answer_letter}) [VERIFIED] and clicked 'Save & Next'"

    def log_record(self, record: Dict[str, Any]):
        """Persist structured record to JSONL log."""
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def run(self, max_questions: int = 10):
        """Execute the automation loop over questions."""
        self.connect_browser()
        console.print(Panel.fit(
            f"[bold]Starting Automated Testing Loop[/bold]\n"
            f"Model: [cyan]{self.model}[/cyan] | Max Questions: [yellow]{max_questions}[/yellow] | Dry Run: [magenta]{self.dry_run}[/magenta]\n"
            f"Log File: [green]{self.log_file}[/green]"
        ))

        previous_img_src = None
        solved_count = 0

        for q_idx in range(1, max_questions + 1):
            iter_start = datetime.datetime.now(datetime.timezone.utc).isoformat()
            console.print(f"\n[bold blue]--- Question #{q_idx} ---[/bold blue]")

            try:
                # 1. Capture question
                img_bytes, img_src = self.capture_question_image()
                console.print(f"Captured stem: [dim]{img_src[:70]}...[/dim] ({len(img_bytes)} bytes)")

                # Prevent duplicate processing of the same question
                if img_src == previous_img_src and img_src != "DOM_SCREENSHOT":
                    console.print("[yellow]Warning: Image src identical to previous question. Waiting for DOM update...[/yellow]")
                    time.sleep(1.0)
                    img_bytes, img_src = self.capture_question_image()

                previous_img_src = img_src

                # 2. Call Gemini
                console.print(f"Sending raw image to [cyan]{self.model}[/cyan]...")
                gemini_resp, latency = self.query_gemini_vision(img_bytes)
                answer = gemini_resp.get("answer", "").upper()
                confidence = gemini_resp.get("confidence", "UNKNOWN")
                reasoning = gemini_resp.get("reasoning", "")

                console.print(f"[bold green]Answer:[/bold green] [bold yellow]{answer}[/bold yellow] | "
                              f"[bold green]Confidence:[/bold green] {confidence} | "
                              f"[bold green]Latency:[/bold green] {latency:.2f}s")
                console.print(f"[dim]Reasoning: {reasoning}[/dim]")

                # 3. Apply DOM interaction
                action_result = self.apply_answer_and_advance(answer)
                console.print(f"[green]Action:[/green] {action_result}")

                # 4. Log telemetry
                log_data = {
                    "timestamp": iter_start,
                    "question_index": q_idx,
                    "image_url": img_src,
                    "model": self.model,
                    "gemini_latency_seconds": round(latency, 3),
                    "gemini_response": gemini_resp,
                    "predicted_answer": answer,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "action_taken": action_result,
                    "status": "SUCCESS",
                }
                self.log_record(log_data)
                solved_count += 1

                # 5. Pacing delay
                time.sleep(self.pacing_delay)

            except Exception as e:
                console.print(f"[bold red]Error on Question #{q_idx}:[/bold red] {e}")
                err_data = {
                    "timestamp": iter_start,
                    "question_index": q_idx,
                    "status": "ERROR",
                    "error_message": str(e),
                }
                self.log_record(err_data)
                time.sleep(2.0)

        console.print(f"\n[bold green]Completed run! Total processed: {solved_count}/{max_questions}[/bold green]")
        if self.connector:
            self.connector.close()


def main():
    parser = argparse.ArgumentParser(description="Automated Question Solver via Chrome CDP and Gemini API")
    parser.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY", ""), help="Gemini API Key")
    parser.add_argument("--model", default="gemini-flash-latest", help="Gemini Model (e.g. gemini-flash-latest, gemini-3.8-flash)")
    parser.add_argument("--host", default="127.0.0.1", help="Chrome CDP Host")
    parser.add_argument("--port", type=int, default=9222, help="Chrome CDP Port")
    parser.add_argument("--tab", default="practice-v2", help="Tab title/URL keyword")
    parser.add_argument("--max-questions", type=int, default=10, help="Number of questions to solve")
    parser.add_argument("--dry-run", action="store_true", help="Log answers without clicking DOM options")
    parser.add_argument("--delay", type=float, default=1.5, help="Pacing delay in seconds between questions")
    parser.add_argument("--log-file", default="automation_run.jsonl", help="Output JSONL log path")

    args = parser.parse_args()

    if not args.api_key:
        console.print("[bold red]Error:[/bold red] Gemini API key not provided. Set GEMINI_API_KEY or pass --api-key.")
        sys.exit(1)

    automation = QuestionSolverAutomation(
        api_key=args.api_key,
        model=args.model,
        host=args.host,
        port=args.port,
        tab_keyword=args.tab,
        log_file=args.log_file,
        dry_run=args.dry_run,
        pacing_delay=args.delay,
    )
    automation.run(max_questions=args.max_questions)


if __name__ == "__main__":
    main()

