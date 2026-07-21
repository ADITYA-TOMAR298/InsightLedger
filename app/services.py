import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Company, FinancialMetric, ReportDocument

settings = get_settings()
_embeddings = None
_vector_store = None

CHART_TYPES = [
    {"type": "line", "label": "Line chart", "description": "Trends over reporting periods."},
    {"type": "bar", "label": "Bar chart", "description": "Metric values by reporting period."},
    {"type": "grouped_bar", "label": "Grouped bar chart", "description": "Companies and metrics side by side."},
    {"type": "histogram", "label": "Histogram", "description": "Distribution of selected metric values."},
    {"type": "countplot", "label": "Count plot", "description": "Number of metric records by company and metric."},
    {"type": "boxplot", "label": "Box plot", "description": "Spread and outliers across companies and metrics."},
    {"type": "heatmap", "label": "Heatmap", "description": "Metric values across periods in a color matrix."},
]


def embeddings():
    global _embeddings
    if _embeddings is None:
        from langchain_huggingface import HuggingFaceEmbeddings
        _embeddings = HuggingFaceEmbeddings(
            model_name=settings.embedding_model,
            model_kwargs={"device": settings.embedding_device},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings


def vector_store():
    global _vector_store
    if _vector_store is None:
        from langchain_chroma import Chroma
        _vector_store = Chroma(
            collection_name="financial_reports", embedding_function=embeddings(),
            persist_directory=str(settings.chroma_directory),
        )
    return _vector_store


def get_or_create_company(db: Session, name: str) -> Company:
    company = db.scalar(select(Company).where(Company.name == name.strip()))
    if company is None:
        company = Company(name=name.strip())
        db.add(company)
        db.flush()
    return company


def load_document(path: Path):
    from langchain_community.document_loaders import PyPDFLoader, TextLoader
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return PyPDFLoader(str(path)).load()
    if suffix in {".txt", ".md"}:
        return TextLoader(str(path), encoding="utf-8", autodetect_encoding=True).load()
    raise HTTPException(415, "Supported file types are PDF, TXT, and MD.")


async def ingest_upload(db: Session, file: UploadFile, company_name: str, document_type: str, reporting_period: str | None) -> ReportDocument:
    filename = Path(file.filename or "report.pdf").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}:
        raise HTTPException(415, "Supported file types are PDF, TXT, and MD.")
    document_id = str(uuid.uuid4())
    destination = settings.upload_directory / f"{document_id}{suffix}"
    with destination.open("wb") as target:
        shutil.copyfileobj(file.file, target)
    try:
        pages = load_document(destination)
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=180)
        chunks = splitter.split_documents(pages)
        if not chunks:
            raise HTTPException(422, "No readable text was found in this document.")
        for index, chunk in enumerate(chunks):
            chunk.metadata.update({
                "document_id": document_id, "company": company_name.strip(), "filename": filename,
                "document_type": document_type, "reporting_period": reporting_period or "", "chunk_index": index,
                "page": int(chunk.metadata.get("page", 0)) + 1,
            })
        vector_store().add_documents(chunks, ids=[f"{document_id}:{i}" for i in range(len(chunks))])
        company = get_or_create_company(db, company_name)
        record = ReportDocument(id=document_id, company_id=company.id, filename=filename, document_type=document_type,
                                reporting_period=reporting_period, stored_path=str(destination), chunk_count=len(chunks))
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def retrieve(question: str, companies: list[str] | None, document_types: list[str] | None, periods: list[str] | None, top_k: int):
    filters = []
    if companies: filters.append({"company": {"$in": companies}})
    if document_types: filters.append({"document_type": {"$in": document_types}})
    if periods: filters.append({"reporting_period": {"$in": periods}})
    filter_arg = filters[0] if len(filters) == 1 else ({"$and": filters} if filters else None)
    return vector_store().similarity_search(question, k=top_k, filter=filter_arg)


def _legacy_create_chart(rows: list[FinancialMetric], chart_type: str, title: str) -> tuple[str, int]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
        import seaborn as sns
    except ImportError as exc:
        raise HTTPException(503, "Chart dependencies are missing. Run: pip install -r requirements.txt") from exc
    if not rows:
        raise HTTPException(404, "No metrics match the requested companies, metrics, and periods.")
    frame = pd.DataFrame([{"company": row.company.name, "period": row.period, "metric": row.metric, "value": row.value, "unit": row.unit} for row in rows])
    frame["series"] = frame["company"] + " — " + frame["metric"]
    frame["period_sort"] = pd.to_datetime(frame["period"], errors="coerce")
    frame = frame.sort_values(["period_sort", "period"], na_position="last")
    sns.set_theme(style="whitegrid")
    figure, axis = plt.subplots(figsize=(10, 6))
    if chart_type == "line":
        sns.lineplot(data=frame, x="period", y="value", hue="company", style="metric", marker="o", ax=axis)
    else:
        sns.barplot(data=frame, x="period", y="value", hue="series", ax=axis)
    axis.set_title(title)
    axis.set_xlabel("Reporting period")
    axis.set_ylabel(frame["unit"].iloc[0])
    figure.tight_layout()
    chart_name = f"{uuid.uuid4()}.png"
    figure.savefig(settings.chart_directory / chart_name, dpi=160, bbox_inches="tight")
    plt.close(figure)
    return chart_name, len(frame)


def create_chart(rows: list[FinancialMetric], chart_type: str, title: str) -> tuple[str, int]:
    """Create a chart from user-selected, verified financial metrics."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
        import seaborn as sns
    except ImportError as exc:
        raise HTTPException(503, "Chart dependencies are missing. Run: python -m pip install -r requirements.txt") from exc

    if not rows:
        raise HTTPException(404, "No metrics match the requested companies, metrics, and periods.")

    frame = pd.DataFrame([
        {"company": row.company.name, "period": row.period, "metric": row.metric,
         "value": row.value, "unit": row.unit}
        for row in rows
    ])
    frame["series"] = frame["company"] + " - " + frame["metric"]
    frame["period_sort"] = pd.to_datetime(frame["period"], errors="coerce")
    frame = frame.sort_values(["period_sort", "period"], na_position="last")

    sns.set_theme(style="whitegrid")
    figure, axis = plt.subplots(figsize=(10, 6))
    unit = frame["unit"].iloc[0]

    if chart_type == "line":
        sns.lineplot(data=frame, x="period", y="value", hue="company", style="metric", marker="o", ax=axis)
        axis.set(xlabel="Reporting period", ylabel=unit)
    elif chart_type in {"bar", "grouped_bar"}:
        sns.barplot(data=frame, x="period", y="value", hue="series", ax=axis)
        axis.set(xlabel="Reporting period", ylabel=unit)
    elif chart_type == "histogram":
        sns.histplot(data=frame, x="value", hue="company", element="step", bins="auto", ax=axis)
        axis.set(xlabel=unit, ylabel="Number of metric records")
    elif chart_type == "countplot":
        sns.countplot(data=frame, x="company", hue="metric", ax=axis)
        axis.set(xlabel="Company", ylabel="Number of metric records")
    elif chart_type == "boxplot":
        sns.boxplot(data=frame, x="metric", y="value", hue="company", ax=axis)
        axis.set(xlabel="Metric", ylabel=unit)
    elif chart_type == "heatmap":
        heatmap_data = frame.pivot_table(index="series", columns="period", values="value", aggfunc="mean")
        sns.heatmap(heatmap_data, annot=True, fmt=".3g", cmap="Blues", linewidths=0.5, ax=axis,
                    cbar_kws={"label": unit})
        axis.set(xlabel="Reporting period", ylabel="Company - metric")
    else:
        raise HTTPException(422, f"Unsupported chart type: {chart_type}")

    axis.set_title(title)
    figure.tight_layout()
    chart_name = f"{uuid.uuid4()}.png"
    figure.savefig(settings.chart_directory / chart_name, dpi=160, bbox_inches="tight")
    plt.close(figure)
    return chart_name, len(frame)
