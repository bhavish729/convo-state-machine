from dotenv import load_dotenv

# Ensure LANGCHAIN_* env vars are in os.environ for LangSmith tracing.
# Must happen before any LangChain imports (which occur when routes are loaded).
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from tara.web.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Tara - Debt Collection Agent", version="0.1.0")
    app.include_router(router)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
