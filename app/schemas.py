from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CompanyOut(BaseModel):
    id: int
    name: str


class DocumentOut(BaseModel):
    id: str
    company: str
    filename: str
    document_type: str
    reporting_period: str | None
    chunk_count: int
    created_at: datetime


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    companies: list[str] | None = None
    document_types: list[str] | None = None
    reporting_periods: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=15)


class Citation(BaseModel):
    document_id: str
    filename: str
    company: str
    page: int | None = None
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]


class MetricUpsert(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    period: str = Field(min_length=1, max_length=30, examples=["2024"])
    metric: str = Field(min_length=1, max_length=100, examples=["Revenue"])
    value: float
    unit: str = Field(default="USD millions", max_length=30)
    source_document_id: str | None = None


class ChartRequest(BaseModel):
    companies: list[str] = Field(min_length=1, max_length=10)
    metrics: list[str] = Field(min_length=1, max_length=6)
    chart_type: Literal["line", "bar", "grouped_bar", "histogram", "countplot", "boxplot", "heatmap"] = "line"
    periods: list[str] | None = None


class ChartResponse(BaseModel):
    chart_url: str
    title: str
    records_used: int


class ComparisonRequest(BaseModel):
    company_a: str
    company_b: str
    metrics: list[str] | None = None
    periods: list[str] | None = None


class ComparisonResponse(BaseModel):
    companies: list[str]
    records: list[dict]
    summary: dict[str, dict[str, float | str]]
