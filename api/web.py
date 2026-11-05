"""Interface estática local; dados pessoais continuam nas rotas autenticadas."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
router = APIRouter()


@router.get("/", include_in_schema=False)
@router.get("/app", include_in_schema=False)
def interface_web():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")
