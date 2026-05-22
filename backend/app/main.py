from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import reports
from app.routers import jobs, templates

app = FastAPI(
    title="SOC Audit Automation",
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


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
