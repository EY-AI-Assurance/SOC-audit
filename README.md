# SOC Audit Form 107-A Automation

FastAPI + React app for parsing SOC 1 reports and filling EY Form 107-A templates.

## Prerequisites

- Conda / Miniconda
- Node.js `22.x` recommended
- npm

## 1. Clone / Open Project

```bash
cd /Users/yixuanma/Desktop/EY/SOC-audit
```

## 2. Backend Setup

Create and activate Python environment:

```bash
conda create -n soc-audit python=3.12
conda activate soc-audit
```

Install backend dependencies:

```bash
pip install -r backend/requirements.txt
```

Create backend environment file:

```bash
touch backend/.env
```

Add your LLM API config to `backend/.env`:

```env
BAILIAN_API_KEY=your_api_key_here
BAILIAN_BASE_URL=https://maas-coding-api.cn-huabei-1.xf-yun.com/v2
BAILIAN_MODEL=astron-code-latest
```

Start backend from project root:

```bash
python run.py
```

Backend runs at:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/health
```

## 3. Frontend Setup

Use Node.js `22.x`. If using `nvm`:

```bash
nvm install 22
nvm use 22
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

Start frontend:

```bash
npm run dev
```

Frontend runs at:

```text
http://localhost:5173
```

## 4. Normal Usage

1. Start backend: `python run.py`
2. Start frontend: `cd frontend && npm run dev`
3. Open `http://localhost:5173`
4. Upload or select a Form 107-A template
5. Upload or select parsed SOC reports
6. Select sheets to fill
7. Run job and download output Excel

## Notes

- Uploaded PDFs, parsed JSON, jobs, and output Excel files are stored under `backend/storage/`.
- `backend/storage/` and `backend/.env` are ignored by git.
- If PDF parsing logic changes, re-upload/re-parse reports.
- If only prompts or extraction logic changes, existing parsed reports can be reused.
