"""Run only the Supervisor Agent:  python -m agents.supervisor_agent"""
import uvicorn

from shared.config import settings

if __name__ == "__main__":
    uvicorn.run("agents.supervisor_agent.main:app", port=settings.supervisor_port, reload=True)
