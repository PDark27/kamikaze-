"""Webapp do Fiscaliza — servidor FastAPI local.

Expõe `app` para `uvicorn webapp.app:app --reload`.
"""

from .app import app

__all__ = ["app"]
