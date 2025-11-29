# LLM Analysis Quiz Solver
Automated multi-step data analysis and quiz-solving backend using Flask, Playwright, and Gemini 2.0 Flash.

This project implements an HTTP API endpoint that receives a quiz URL, scrapes the page (including JavaScript-rendered content), downloads files, processes them, extracts relevant information, uses Gemini LLM reasoning to compute the correct answer, and submits the solution back to the quiz server.

---

## Features

### API Endpoint `/quiz`
The endpoint accepts a JSON payload:

```json
{
  "email": "student email",
  "secret": "student secret",
  "url": "quiz-url"
}
```

The system:
- Validates JSON
- Validates the secret string
- Renders the quiz page using a headless browser
- Extracts HTML, text, and downloadable files
- Sends everything to Gemini for analysis
- Submits the answer back to the given submit URL

---

## LLM-Powered Quiz Solving

The backend uses **Google Gemini 2.0 Flash** to:
- Interpret quiz instructions
- Parse HTML + JavaScript-rendered content
- Read text extracted from PDFs, CSVs, JSON, XLSX, etc.
- Perform calculations and analysis
- Produce a structured JSON-only answer
- Identify the correct submission endpoint
- Build the correct answer payload

The model is configured with:

```text
response_mime_type = "application/json"
```

This ensures 100% JSON-safe output.

---

## JavaScript Rendering with Playwright

Many quiz pages are rendered dynamically using JavaScript.  
The backend:
- Launches a Chromium headless browser  
- Loads the quiz page  
- Waits for all JS execution  
- Extracts visible text  
- Extracts full HTML content  
- Scans for downloadable files (PDF/CSV/XLSX/JSON)  

Playwright ensures accurate DOM rendering.

---

## Supported File Extraction

The backend automatically extracts:

- PDF text (via pdfplumber)
- CSV (UTF-8 decoding)
- JSON
- XLS/XLSX (downloaded)
- ZIP
- HTML tables via visible text

Extracted content is passed directly into Gemini for reasoning.

---

## Multi-step Quiz Handling

Some quizzes return a new URL:

```json
{
  "correct": true,
  "url": "https://example.com/next-quiz"
}
```

The backend will:
1. Detect the new URL  
2. Load the next quiz page  
3. Continue solving  
4. Stop only when:
   - There is no next URL, or
   - 3 minutes have passed

---

## Secret Validation

Rules followed exactly as required by the instructors:
- Wrong secret → **HTTP 403**
- Invalid JSON → **HTTP 400**
- Valid → **HTTP 200**

---

## Environment Variables

Create a `.env` file (not committed to GitHub):

```
GEMINI_API_KEY=your_gemini_key
QUIZ_SECRET=your_fixed_secret
```

Both must match your Google Form submission.

---

## Running Locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Install Playwright:

```bash
playwright install
```
Run the Flask Application:
If you're running the project locally, make sure to:

✅ Uncomment the following line in app.py:
**app.run(port=5000, debug=True)**
❌ Comment out the production deployment line:
**#serve(app, host="0.0.0.0", port=8000)**

Run server:

```bash
python main.py
```

Server runs at:

```
http://localhost:5000/quiz
```

---

## Deployment

Deploy using:

- Render (recommended)
- Railway
- Fly.io
- Ngrok (tunnel)

Submit the **public endpoint URL** in the Google Form.

---

## Repository Structure

```
.
├── main.py
├── README.md
├── test.py
├── requirements.txt
├── LICENSE
├── .gitignore
└── .env  (ignored)
```

---

## License

This project uses the MIT License as required.

---

## Author

Vishnu Siva  
LLM Analysis Quiz Solver

