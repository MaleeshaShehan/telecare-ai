"""Run only the Orchestrator (and the UI):  python -m agents.orchestrator"""
import uvicorn

from shared.config import settings

if __name__ == "__main__":
    uvicorn.run("agents.orchestrator.main:app", port=settings.orchestrator_port, reload=True)
