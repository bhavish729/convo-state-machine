import logging
import os

from dotenv import load_dotenv

# Load ALL .env vars into os.environ BEFORE any LangChain imports.
# pydantic-settings only reads TARA_* prefixed vars into the Settings model;
# LANGCHAIN_* env vars (for LangSmith tracing) need to be in os.environ directly.
load_dotenv()

import uvicorn

from tara.config import settings
from tara.web.app import create_app


def main():
    # Configure logging so tara.* loggers output to terminal
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s  %(name)s  %(message)s",
    )
    # Log LangSmith status at startup
    tracing = os.environ.get("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    project = os.environ.get("LANGCHAIN_PROJECT", "default")
    if tracing:
        print(f"[LangSmith] Tracing enabled → project: {project}")
    else:
        print("[LangSmith] Tracing disabled (set LANGCHAIN_TRACING_V2=true in .env)")

    uvicorn.run(
        "tara.web.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
