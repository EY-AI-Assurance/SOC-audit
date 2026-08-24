from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
