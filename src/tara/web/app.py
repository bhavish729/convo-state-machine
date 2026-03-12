import logging

from dotenv import load_dotenv

# Ensure LANGCHAIN_* env vars are in os.environ for LangSmith tracing.
# Must happen before any LangChain imports (which occur when routes are loaded).
load_dotenv()

# Configure logging at module level so it runs in the uvicorn worker process
# (not just the reloader parent). This ensures all tara.* logger.info() calls
# actually print to the terminal.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s  %(message)s",
    force=True,  # Override any existing config from uvicorn
)
# Quiet down noisy libraries
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

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
