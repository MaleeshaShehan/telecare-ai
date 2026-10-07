"""Run only the Account Agent:  python -m agents.account_agent"""
import uvicorn

from shared.config import settings

if __name__ == "__main__":
    uvicorn.run("agents.account_agent.main:app", port=settings.account_port, reload=True)
