import sys
from pathlib import Path

import uvicorn

PROJECT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        reload=True,
        reload_dirs=[str(BACKEND_DIR)],
        port=8000,
    )
