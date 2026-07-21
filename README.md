# Financial Report Analyzer — backend

FastAPI backend for ingesting annual reports, 10-Ks, 10-Qs, ESG reports, and earnings documents; retrieving their contents with RAG; recording verified financial metrics; plotting period-over-period trends; and comparing two companies.

## Setup

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

Set `MISTRAL_API_KEY` in `.env` for the `/ask` endpoint. The default embedding model (`all-MiniLM-L6-v2`) is public, lightweight, and runs locally on CPU, so it needs no Hugging Face API key or GPU. The first ingestion downloads it if it is not already cached.

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.

## API flow

1. `POST /documents/upload` (multipart): `file`, `company`, `document_type`, and optional `reporting_period`. Text chunks are embedded in Chroma with company/report metadata.
2. `POST /ask`: asks a grounded question with optional company, report-type, and period filters. It returns an answer plus quoted source passages and page numbers.
3. `PUT /metrics`: save a verified metric from a report; these are deliberately explicit rather than guessed from prose.
4. `GET /visualizations/types`: lists the graph choices for the frontend: line, bar, grouped bar, histogram, countplot, boxplot, and heatmap. `POST /visualizations` generates the selected Seaborn/Matplotlib PNG and returns its URL.
5. `POST /compare`: returns aligned metric records and a concise per-period comparison for exactly two companies.

Example visualization request:

```json
{"companies":["Apple","Microsoft"],"metrics":["Revenue","Net income"],"chart_type":"line","periods":["2022","2023","2024"]}
```
