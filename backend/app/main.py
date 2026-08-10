from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.routers import api_configs, jobs, reports, templates

app = FastAPI(
    title="SOC 107 Analyzer",
    description="Parse SOC 1 reports and auto-fill EY Form 107-A.",
    version="0.2.0",
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router)
app.include_router(jobs.router)
app.include_router(templates.router)
app.include_router(api_configs.router)


@app.on_event("startup")
def migrate_legacy_api_config():
    api_configs.migrate_and_verify_legacy()


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    """Serve the Vite production build and support React client-side routes."""
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    frontend_root = settings.frontend_dir.resolve()
    requested_file = (frontend_root / full_path).resolve()

    if requested_file.is_file() and requested_file.is_relative_to(frontend_root):
        return FileResponse(requested_file)

    index_file = frontend_root / "index.html"
    if not index_file.is_file():
        raise HTTPException(
            status_code=503,
            detail="Frontend has not been built. Run `npm run build` in frontend/.",
        )

    return FileResponse(index_file)
