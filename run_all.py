"""Start the four agents in one command.   Owner: M1

    python run_all.py

Each agent runs as its own uvicorn process. We wait for every /health to
answer, then print the UI address. The web UI (ui/web) is static files
served by the Orchestrator itself, so there is no fifth process.
"""
import subprocess
import sys
import time
import webbrowser

import httpx

from shared.config import settings

AGENTS = [
    ("orchestrator", "agents.orchestrator.main:app", settings.orchestrator_port),
    ("knowledge_agent", "agents.knowledge_agent.main:app", settings.knowledge_port),
    ("account_agent", "agents.account_agent.main:app", settings.account_port),
    ("supervisor_agent", "agents.supervisor_agent.main:app", settings.supervisor_port),
]


def wait_for_health(name: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                print(f"  [ok] {name} on :{port}")
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    print(f"  [FAIL] {name} did not answer /health on :{port}")
    return False


def main() -> None:
    procs: list[subprocess.Popen] = []
    try:
        print("Starting agents...")
        for name, target, port in AGENTS:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "uvicorn", target, "--port", str(port), "--log-level", "warning"]
            ))
        if not all(wait_for_health(name, port) for name, _, port in AGENTS):
            raise SystemExit("One or more agents failed to start.")

        url = f"http://127.0.0.1:{settings.orchestrator_port}/"
        print(f"\nTeleCare AI is running at {url}\nCtrl+C to stop.")
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("Stopping...")
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
