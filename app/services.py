"""Small, serverless-friendly report processing services.

This module intentionally uses no local embedding model, vector database, or
plotting library. Those packages make a Vercel Python Function several GB.
"""
from __future__ import annotations

import html
import json
import math
import re
import shutil
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import Company, DocumentChunk, FinancialMetric, ReportDocument

settings = get_settings()

CHART_TYPES = [
    {"type": "line", "label": "Line chart", "description": "Trends over reporting periods."},
    {"type": "bar", "label": "Bar chart", "description": "Metric values by reporting period."},
    {"type": "grouped_bar", "label": "Grouped bar chart", "description": "Companies and metrics side by side."},
    {"type": "histogram", "label": "Histogram", "description": "Distribution of selected metric values."},
    {"type": "piechart", "label": "Pie chart", "description": "Proportion of selected metric values."},
    {"type": "countplot", "label": "Count plot", "description": "Number of metric records by company and metric."},
    {"type": "boxplot", "label": "Box plot", "description": "Spread and outliers across companies and metrics."},
    {"type": "heatmap", "label": "Heatmap", "description": "Metric values across periods in a color matrix."},
]


@dataclass
class RetrievedChunk:
    document_id: str
    filename: str
    company: str
    page: int | None
    content: str


def get_or_create_company(db: Session, name: str) -> Company:
    company = db.scalar(select(Company).where(Company.name == name.strip()))
    if company is None:
        company = Company(name=name.strip())
        db.add(company)
        db.flush()
    return company


def _read_pages(path: Path) -> list[tuple[int | None, str]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return [(index + 1, page.extract_text() or "") for index, page in enumerate(PdfReader(str(path)).pages)]
    if suffix in {".txt", ".md"}:
        return [(None, path.read_text(encoding="utf-8", errors="replace"))]
    raise HTTPException(415, "Supported file types are PDF, TXT, and MD.")


def _split_text(text: str, size: int = 1200, overlap: int = 180) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [text[start:start + size] for start in range(0, len(text), size - overlap)]


import concurrent.futures

def get_gemini_embedding(text: str) -> list[float]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={settings.gemini_api_key}"
    payload = json.dumps({"model": "models/gemini-embedding-2", "content": {"parts": [{"text": text}]}}).encode()
    request = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)["embedding"]["values"]
    except Exception as exc:
        raise HTTPException(502, "Failed to fetch embedding from Gemini.") from exc


def get_gemini_embeddings_batch(texts: list[str]) -> list[list[float]]:
    if not texts: return []
    # Gemini v1beta doesn't cleanly support batchEmbedContents for text-embedding-004
    # We use ThreadPoolExecutor to fetch them concurrently using the standard endpoint
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        return list(executor.map(get_gemini_embedding, texts))


def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))
    if norm_a == 0 or norm_b == 0: return 0.0
    return dot_product / (norm_a * norm_b)


async def ingest_upload(db: Session, file: UploadFile, company_name: str, document_type: str, reporting_period: str | None) -> ReportDocument:
    if not settings.gemini_api_key:
        raise HTTPException(500, "GEMINI_API_KEY is not configured.")
    filename = Path(file.filename or "report.pdf").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}:
        raise HTTPException(415, "Supported file types are PDF, TXT, and MD.")
    document_id = str(uuid.uuid4())
    destination = settings.upload_directory / f"{document_id}{suffix}"
    with destination.open("wb") as target:
        shutil.copyfileobj(file.file, target)
    try:
        chunks = [(page, part) for page, text in _read_pages(destination) for part in _split_text(text)]
        if not chunks:
            raise HTTPException(422, "No readable text was found in this document.")
            
        # Fetch embeddings concurrently
        batch_texts = [text for _, text in chunks]
        embeddings = get_gemini_embeddings_batch(batch_texts)
            
        company = get_or_create_company(db, company_name)
        record = ReportDocument(id=document_id, company_id=company.id, filename=filename, document_type=document_type,
                                reporting_period=reporting_period, stored_path=str(destination), chunk_count=len(chunks))
        db.add(record)
        db.add_all(DocumentChunk(document_id=document_id, page=page, chunk_index=index, content=content, embedding=json.dumps(emb))
                   for index, ((page, content), emb) in enumerate(zip(chunks, embeddings)))
        db.commit()
        db.refresh(record)
        return record
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise


def retrieve(db: Session, question: str, companies: list[str] | None, document_types: list[str] | None,
             periods: list[str] | None, top_k: int) -> list[RetrievedChunk]:
    if not settings.gemini_api_key:
        raise HTTPException(500, "GEMINI_API_KEY is not configured.")
        
    query = select(DocumentChunk).join(DocumentChunk.document).join(ReportDocument.company).options(
        joinedload(DocumentChunk.document).joinedload(ReportDocument.company))
    if companies:
        query = query.where(Company.name.in_(companies))
    if document_types:
        query = query.where(ReportDocument.document_type.in_(document_types))
    if periods:
        query = query.where(ReportDocument.reporting_period.in_(periods))
        
    question_embedding = get_gemini_embedding(question)
    
    matches = []
    for chunk in db.scalars(query).all():
        if chunk.embedding:
            chunk_embedding = json.loads(chunk.embedding)
            score = _cosine_similarity(question_embedding, chunk_embedding)
            matches.append((score, chunk))
            
    matches.sort(key=lambda item: item[0], reverse=True)
    return [RetrievedChunk(document_id=chunk.document_id, filename=chunk.document.filename,
                           company=chunk.document.company.name, page=chunk.page, content=chunk.content)
            for _, chunk in matches[:top_k]]


def answer_question(question: str, context: str) -> str:
    """Call Gemini's chat API without the heavyweight LangChain package."""
    if not settings.gemini_api_key:
        raise HTTPException(500, "GEMINI_API_KEY is not configured.")
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={settings.gemini_api_key}"
    payload = json.dumps({
        "systemInstruction": {
            "parts": [{"text": "Answer only from the supplied financial-report context. State when evidence is insufficient and cite source numbers such as [Source 1]."}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": f"Question: {question}\n\nContext:\n{context}"}]}
        ]
    }).encode()
    
    request = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=55) as response:
            body = json.load(response)
        if "candidates" in body and body["candidates"]:
            return str(body["candidates"][0]["content"]["parts"][0]["text"])
        return "The model did not return an answer."
    except Exception as exc:
        raise HTTPException(502, "The Gemini service could not generate an answer.") from exc


def create_chart(rows: list[FinancialMetric], chart_type: str, title: str) -> tuple[str, int]:
    """Render a compact SVG chart without matplotlib, pandas, or seaborn."""
    if not rows:
        raise HTTPException(404, "No metrics match the requested companies, metrics, and periods.")
    if chart_type not in {item["type"] for item in CHART_TYPES}:
        raise HTTPException(422, f"Unsupported chart type: {chart_type}")
    values = [abs(row.value) for row in rows]
    maximum = max(values) or 1
    width, height, left, top = 900, max(220, 90 + len(rows) * 42), 230, 55
    bars = []
    palette = ["#34d399", "#a78bfa", "#22d3ee", "#fbbf24"]
    for index, row in enumerate(rows):
        y = top + index * 42
        bar_width = int((abs(row.value) / maximum) * (width - left - 70))
        label = html.escape(f"{row.company.name} | {row.metric} | {row.period}")
        bars.append(f'<text x="15" y="{y + 18}" fill="#27272a" font-size="13">{label}</text><rect x="{left}" y="{y}" width="{bar_width}" height="26" rx="4" fill="{palette[index % len(palette)]}"/><text x="{left + bar_width + 8}" y="{y + 18}" fill="#27272a" font-size="13">{row.value:g} {html.escape(row.unit)}</text>')
    safe_title = html.escape(title)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><text x="15" y="30" fill="#18181b" font-family="Arial" font-size="20" font-weight="bold">{safe_title} ({html.escape(chart_type)})</text>{"".join(bars)}</svg>'
    chart_name = f"{uuid.uuid4()}.svg"
    (settings.chart_directory / chart_name).write_text(svg, encoding="utf-8")
    return chart_name, len(rows)
