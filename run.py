import sys
import uvicorn

sys.path.insert(0, "backend")

if __name__ == "__main__":
    uvicorn.run("app.main:app", reload=True, port=8000)
