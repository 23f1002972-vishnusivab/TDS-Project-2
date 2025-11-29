import os
import json
import base64
import logging
import tempfile
from urllib.parse import urljoin, urlparse
from flask import Flask, request, jsonify
import requests
import pdfplumber
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import google.generativeai as genai
from waitress import serve

load_dotenv()
logging.basicConfig(level=logging.INFO)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logging.warning(
        "GEMINI_API_KEY not found in environment. Set GEMINI_API_KEY before running."
    )

genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel(
    "gemini-2.0-flash",
    generation_config={
        "response_mime_type": "application/json",
        "max_output_tokens": 2000,
    },
)

app = Flask(__name__)

QUIZ_SECRET = os.environ.get("QUIZ_SECRET")


def download_file(url, session=None, max_bytes=5_000_000):
    s = session or requests
    resp = s.get(url, stream=True, timeout=45)
    resp.raise_for_status()
    length = int(resp.headers.get("content-length", 0) or 0)
    if length and length > max_bytes:
        raise ValueError("Remote file too large")
    data = resp.content
    if len(data) > max_bytes:
        raise ValueError("Downloaded file exceeds limit")
    return data, resp.headers.get("content-type", "")


def extract_text_from_pdf_bytes(pdf_bytes):
    texts = []
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tf:
        tf.write(pdf_bytes)
        tf.flush()
        try:
            with pdfplumber.open(tf.name) as pdf:
                for page in pdf.pages:
                    texts.append(page.extract_text() or "")
        except Exception as e:
            logging.exception("PDF parse failed: %s", e)
            return None
    return "\n\n".join(texts)


def _extract_text_from_gemini_response(resp):
    """
    Robustly extract textual output from different shapes of genai responses.
    Prefer resp.text if present, then known attributes.
    """
    if hasattr(resp, "text") and resp.text:
        return resp.text
    try:
        out = getattr(resp, "output", None)
        if out:
            if isinstance(out, list) and len(out) > 0:
                for item in out:
                    if isinstance(item, dict):
                        content = item.get("content")
                        if isinstance(content, list) and len(content) > 0:
                            first = content[0]
                            if isinstance(first, dict) and "text" in first:
                                return first["text"]
                        if "text" in item:
                            return item["text"]
            elif isinstance(out, dict):
                content = out.get("content")
                if isinstance(content, list) and len(content) > 0:
                    if isinstance(content[0], dict) and "text" in content[0]:
                        return content[0]["text"]
    except Exception:
        pass
    try:
        gens = getattr(resp, "generations", None)
        if gens:
            if isinstance(gens, list) and len(gens) > 0:
                g0 = gens[0]
                if isinstance(g0, dict) and "text" in g0:
                    return g0["text"]
                if hasattr(g0, "text"):
                    return g0.text
    except Exception:
        pass
    try:
        return str(resp)
    except Exception:
        return ""


def call_gemini_for_solution(page_html, page_text, collected_files):
    prompt = """
You are an assistant that reads a rendered HTML page (provided as 'HTML' and 'TEXT') and returns a strictly valid JSON object with the following fields:
- answer: A succinct answer value (number/string/boolean or small JSON) if known.
- submit_url: The exact URL to POST the answer to, or null if none.
- payload: A JSON object to send in the POST body (or null). Must include "email" and "secret" if submission required.
- attachment_base64: Optional base64-encoded file string if the answer must be uploaded as a file.
Rules:
1) Output exactly one valid JSON object and nothing else.
2) If you cannot determine an answer, set answer to null and include a 'reason' field.
3) If a downloaded file is provided, process it and compute the requested answer.
"""
    html_snippet = page_html[:14000]
    text_snippet = page_text[:12000]

    files_info = []
    for f in collected_files:
        info = {"filename": f.get("filename")}
        if f.get("is_text"):
            info["text_preview"] = (f.get("text") or "")[:5000]
        else:
            b64 = base64.b64encode(f.get("bytes") or b"").decode("utf-8")
            info["base64"] = b64[:10000]
        files_info.append(info)

    user_input = {"HTML": html_snippet, "TEXT": text_snippet, "FILES": files_info}
    full_prompt = json.dumps(user_input) + "\n\n" + prompt

    try:
        response = model.generate_content(
            full_prompt, generation_config={"max_output_tokens": 1500}
        )
        text_out = _extract_text_from_gemini_response(response)
        start = text_out.find("{")
        end = text_out.rfind("}")
        json_text = (
            text_out[start : end + 1]
            if start != -1 and end != -1 and end > start
            else text_out
        )
        solution = json.loads(json_text)
        return solution
    except Exception as e:
        logging.exception("Gemini call failed: %s", e)
        return {
            "answer": None,
            "submit_url": None,
            "payload": None,
            "reason": "model_error",
            "model_exception": str(e),
        }


def render_page_and_collect(url, timeout_ms=30000):
    collected_files = []
    html = ""
    visible_text = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except PWTimeout:
            try:
                page.goto(url, wait_until="load", timeout=timeout_ms)
            except Exception as e:
                logging.warning("Playwright navigation warning: %s", e)
        html = page.content()
        visible_text = page.inner_text("body") if page.query_selector("body") else ""
        anchors = page.query_selector_all("a")
        for a in anchors:
            try:
                href = a.get_attribute("href")
                if not href:
                    continue
                full = urljoin(url, href)
                parsed = urlparse(full)
                path = parsed.path.lower()
                if any(
                    path.endswith(ext)
                    for ext in [".pdf", ".csv", ".xlsx", ".xls", ".json", ".zip"]
                ):
                    try:
                        data, content_type = download_file(full)
                        filename = os.path.basename(path) or "downloaded"
                        file_entry = {"filename": filename, "bytes": data}
                        if (
                            content_type.startswith("text/")
                            or filename.endswith(".csv")
                            or filename.endswith(".json")
                        ):
                            try:
                                file_entry["text"] = data.decode(
                                    "utf-8", errors="ignore"
                                )
                                file_entry["is_text"] = True
                            except Exception:
                                file_entry["is_text"] = False
                        elif filename.endswith(".pdf"):
                            file_entry["text"] = extract_text_from_pdf_bytes(data) or ""
                            file_entry["is_text"] = True
                        else:
                            file_entry["is_text"] = False
                        collected_files.append(file_entry)
                        break
                    except Exception as e:
                        logging.warning("Failed to download candidate %s : %s", full, e)
                        continue
            except Exception as e:
                logging.warning("Error processing anchor: %s", e)
                continue
        context.close()
        browser.close()
    return {"html": html, "text": visible_text, "collected_files": collected_files}


@app.route("/quiz", methods=["POST"])
def quiz_endpoint():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid_json"}), 400
    if not data:
        return jsonify({"error": "invalid_json"}), 400
    email = data.get("email")
    secret = data.get("secret")
    url = data.get("url")
    if secret != QUIZ_SECRET:
        return jsonify({"error": "invalid_secret"}), 403
    if not url or not email:
        return jsonify({"error": "missing_fields"}), 400
    try:
        page_data = render_page_and_collect(url)
        html = page_data["html"]
        text = page_data["text"]
        files = page_data["collected_files"]
        solution = call_gemini_for_solution(html, text, files)
        if not isinstance(solution, dict):
            return jsonify({"error": "model_failed"}), 500
        payload = solution.get("payload")
        submit_url = solution.get("submit_url")
        if payload is None and solution.get("answer") is not None and submit_url:
            payload = {"email": email, "secret": secret, "answer": solution["answer"]}
        if isinstance(payload, dict):
            payload["email"] = email
            payload["secret"] = secret
        else:
            return (
                jsonify({"error": "no_payload_from_model", "model_output": solution}),
                500,
            )
        if not submit_url:
            return jsonify({"result": "no_submit_url", "solution": solution}), 200
        headers = {"Content-Type": "application/json"}
        attach_b64 = solution.get("attachment_base64")
        if attach_b64:
            payload["attachment_base64"] = attach_b64
        resp = requests.post(submit_url, json=payload, headers=headers, timeout=90)
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"status_code": resp.status_code, "text": resp.text}
        return (
            jsonify(
                {
                    "submit_response": resp_json,
                    "submit_status": resp.status_code,
                    "submit_url": submit_url,
                    "model_solution": solution,
                }
            ),
            200,
        )
    except Exception as e:
        logging.exception("Error solving quiz: %s", e)
        return jsonify({"error": "server_error", "detail": str(e)}), 500


if __name__ == "__main__":
    #app.run(port=5000, debug=True)
    serve(app, host="0.0.0.0", port=8000)

