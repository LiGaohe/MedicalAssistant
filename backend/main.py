from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from .config import settings
from .database import init_db
from .api import upload_router, asr_router, task_router, llm_router

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

app.include_router(upload_router)
app.include_router(asr_router)
app.include_router(task_router)
app.include_router(llm_router)

frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


@app.on_event("startup")
async def startup_event():
    init_db()


@app.get("/")
async def root():
    index_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "中文门诊病历生成系统", "version": settings.APP_VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
