"""Run only the Knowledge Agent:  python -m agents.knowledge_agent"""
import uvicorn

from shared.config import settings

if __name__ == "__main__":
    uvicorn.run("agents.knowledge_agent.main:app", port=settings.knowledge_port, reload=True)
