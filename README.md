# ParseAnything

Universal document ingestion engine for the DataQuest 3.0 hackathon.

## Pipeline

Upload → Detect & Route → Extract & Assemble → Confidence/Provenance → JSON/Markdown

## Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt   # also needs the tesseract binary for OCR
uvicorn app.main:app --reload
```

Backend: http://localhost:8000

### Windows 10/11 (Python 3.12)

No WSL or Docker needed. Use PowerShell or cmd from the `backend` directory:

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --reload
```

OCR needs the Tesseract binary. Install the Windows build from <https://github.com/UB-Mannheim/tesseract/wiki>
(or `winget install UB-Mannheim.TesseractOCR`). The backend auto-detects `C:\Program Files\Tesseract-OCR\tesseract.exe`
even when it is not on `PATH`; for a custom location set `TESSERACT_CMD` (see `.env.example`).
The default OCR languages are English + Hindi + Tamil (`eng+hin+tam`). Download `hin.traineddata` and `tam.traineddata` into `C:\Program Files\Tesseract-OCR\tessdata`.
If a language pack is missing, the backend logs a warning and falls back to the installed languages. Set `PARSE_OCR_LANGS` to customize the language combination.
Without Tesseract the API still runs, but scanned pages report an OCR-unavailable error and the OCR tests fail.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

## Current status

See `IMPLEMENTATION_STATUS.md` for what works, known limitations and next steps.
API flow: `POST /api/upload` → `POST /api/parse?file_id=…` → `GET /api/status/{id}` → `GET /api/result/{id}` → `GET /api/download/{id}/json|markdown`.
