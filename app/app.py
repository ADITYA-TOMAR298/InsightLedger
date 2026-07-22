"""Vercel-recognized FastAPI entry point.

Vercel detects an ``app`` object in app/app.py and serves the API as a Python
Function. The regular local command remains: ``uvicorn main:app --reload``.
"""
from app.api import app

