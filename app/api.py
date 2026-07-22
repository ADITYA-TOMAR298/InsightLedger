import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import Company, FinancialMetric, ReportDocument, get_db, init_database
from app.schemas import (AskRequest, AskResponse, ChartRequest, ChartResponse, Citation, CompanyOut, ComparisonRequest,
                         ComparisonResponse, DocumentOut, MetricUpsert)
from app.services import CHART_TYPES, answer_question, create_chart, get_or_create_company, ingest_upload, retrieve

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/charts", StaticFiles(directory=str(settings.chart_directory)), name="charts")
frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@app.middleware("http")
async def use_api_prefix_in_production(request, call_next):
    """Map the browser's same-origin `/api/*` URLs to the FastAPI routes.

    Vercel exposes this FastAPI application at the site root. Local development
    still calls the unprefixed routes on localhost:8000.
    """
    path = request.scope["path"]
    if path.startswith("/api/"):
        request.scope["path"] = path[4:]
        request.scope["raw_path"] = request.scope["path"].encode()
    return await call_next(request)


def document_out(record: ReportDocument) -> DocumentOut:
    return DocumentOut(id=record.id, company=record.company.name, filename=record.filename, document_type=record.document_type,
                       reporting_period=record.reporting_period, chunk_count=record.chunk_count, created_at=record.created_at)


@app.get("/health")
def health(): return {"status": "ok"}


@app.get("/companies", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    return db.scalars(select(Company).order_by(Company.name)).all()


@app.get("/documents", response_model=list[DocumentOut])
def list_documents(company: str | None = None, db: Session = Depends(get_db)):
    statement = select(ReportDocument).options(joinedload(ReportDocument.company)).order_by(ReportDocument.created_at.desc())
    if company: statement = statement.join(ReportDocument.company).where(Company.name == company)
    return [document_out(record) for record in db.scalars(statement).all()]


@app.post("/documents/upload", response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile = File(...), company: str = Form(...), document_type: str = Form("annual_report"),
                          reporting_period: str | None = Form(None), db: Session = Depends(get_db)):
    record = await ingest_upload(db, file, company, document_type, reporting_period)
    db.refresh(record, attribute_names=["company"])
    return document_out(record)


@app.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest, db: Session = Depends(get_db)):
    chunks = retrieve(db, payload.question, payload.companies, payload.document_types, payload.reporting_periods, payload.top_k)
    if not chunks: raise HTTPException(404, "No relevant document passages were found.")
    context = "\n\n".join(f"[Source {i + 1}: {chunk.company} | {chunk.filename} | page {chunk.page or 'n/a'}]\n{chunk.content}" for i, chunk in enumerate(chunks))
    if not settings.mistral_api_key:
        raise HTTPException(503, "MISTRAL_API_KEY must be configured to generate answers.")
    answer = answer_question(payload.question, context)
    citations = [Citation(document_id=c.document_id, filename=c.filename, company=c.company,
                          page=c.page, excerpt=c.content[:400]) for c in chunks]
    return AskResponse(answer=answer, citations=citations)


@app.put("/metrics")
def upsert_metric(payload: MetricUpsert, db: Session = Depends(get_db)):
    company = get_or_create_company(db, payload.company)
    metric = db.scalar(select(FinancialMetric).where(FinancialMetric.company_id == company.id, FinancialMetric.period == payload.period, FinancialMetric.metric == payload.metric))
    if metric is None:
        metric = FinancialMetric(company_id=company.id, **payload.model_dump(exclude={"company"}))
        db.add(metric)
    else:
        for field, value in payload.model_dump(exclude={"company"}).items(): setattr(metric, field, value)
    db.commit()
    return {"id": metric.id, "company": company.name, "metric": metric.metric, "period": metric.period}


@app.get("/visualizations/types")
def visualization_types():
    """Options a frontend can show before calling POST /visualizations."""
    return CHART_TYPES


def metric_rows(db: Session, companies: list[str], metrics: list[str] | None, periods: list[str] | None):
    query = select(FinancialMetric).join(FinancialMetric.company).options(joinedload(FinancialMetric.company)).where(Company.name.in_(companies))
    if metrics: query = query.where(FinancialMetric.metric.in_(metrics))
    if periods: query = query.where(FinancialMetric.period.in_(periods))
    return db.scalars(query).all()


@app.post("/visualizations", response_model=ChartResponse)
def visualization(payload: ChartRequest, db: Session = Depends(get_db)):
    rows = metric_rows(db, payload.companies, payload.metrics, payload.periods)
    name, count = create_chart(rows, payload.chart_type, f"{' / '.join(payload.metrics)} — {' vs '.join(payload.companies)}")
    return ChartResponse(chart_url=f"/charts/{name}", title=f"{' / '.join(payload.metrics)}", records_used=count)


@app.post("/compare", response_model=ComparisonResponse)
def compare_companies(payload: ComparisonRequest, db: Session = Depends(get_db)):
    if payload.company_a == payload.company_b: raise HTTPException(422, "Choose two different companies.")
    rows = metric_rows(db, [payload.company_a, payload.company_b], payload.metrics, payload.periods)
    if not rows: raise HTTPException(404, "No comparable metrics were found.")
    records = [{"company": r.company.name, "period": r.period, "metric": r.metric, "value": r.value, "unit": r.unit} for r in rows]
    summary = {}
    for row in records:
        key = f"{row['metric']} ({row['period']})"
        summary.setdefault(key, {})[row["company"]] = row["value"]
        summary[key]["unit"] = row["unit"]
    return ComparisonResponse(companies=[payload.company_a, payload.company_b], records=records, summary=summary)


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    """Serve Vite's production files and fall back to its SPA entry point."""
    asset = frontend_dist / full_path
    if asset.is_file():
        return FileResponse(asset)
    if (frontend_dist / "index.html").is_file():
        return FileResponse(frontend_dist / "index.html")
    raise HTTPException(404, "Frontend build files are unavailable.")
