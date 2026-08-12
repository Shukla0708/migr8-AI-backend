from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from urllib.parse import unquote

from db.database import engine
from db.models import Base
from routers import auth, projects, validation
from services import s3_service

app = FastAPI(title="MIGR8 AI — Validation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # add your deployed frontend origin too
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(validation.router)


@app.on_event("startup")
def on_startup():
    # For the hackathon: auto-create tables if they don't exist.
    # In practice, run schema.sql directly against Postgres instead.
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok", "storage": s3_service.storage_mode()}


@app.get("/api/local-files/{key:path}")
def serve_local_file(key: str):
    """Hackathon download path when storage_backend is local (no S3)."""
    if s3_service.storage_mode() != "local":
        raise HTTPException(404, "Local file serving is disabled (using S3)")
    decoded = unquote(key)
    try:
        data = s3_service.download_bytes(decoded)
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    filename = decoded.rsplit("/", 1)[-1] or "download.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
