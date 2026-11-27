from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import BASE_DIR
from app.routers import chapters, library, outline, sessions, structure, usage

app = FastAPI(title="小说生成工作台")

app.include_router(sessions.router)
app.include_router(structure.router)
app.include_router(outline.router)
app.include_router(chapters.router)
app.include_router(usage.router)
app.include_router(library.router)

WEB_DIR = BASE_DIR / "web"


NO_CACHE = {"Cache-Control": "no-store, max-age=0"}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE)


@app.get("/reader")
def reader():
    return FileResponse(WEB_DIR / "reader.html", headers=NO_CACHE)
