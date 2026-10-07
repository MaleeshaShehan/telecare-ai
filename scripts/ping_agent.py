"""Send one envelope to a running specialist, exactly as the Orchestrator would, and
validate the reply. Lets a builder test their agent without the Orchestrator or UI.

Examples
    python scripts/ping_agent.py knowledge_agent --intent package_info --query "cheapest 5GB anytime package"
    python scripts/ping_agent.py knowledge_agent --file agents/knowledge_agent/examples/plan_advice.json
    python scripts/ping_agent.py account_agent --login 0712345678 demo1234
    python scripts/ping_agent.py account_agent --otp 0712345678 482913
    python scripts/ping_agent.py account_agent --intent bill_enquiry --query "why is my bill higher" --token eyJ...
    python scripts/ping_agent.py supervisor_agent --task assess --message "This is ridiculous!"
    python scripts/ping_agent.py supervisor_agent --file agents/supervisor_agent/examples/escalate.json
    python scripts/ping_agent.py supervisor_agent --tickets

Exit code 0 = reply is valid for the contract, 1 = not.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from shared.config import settings  # noqa: E402
from shared.envelope import STATUS_VALUES, Envelope  # noqa: E402
from shared.http import INTERNAL_KEY_HEADER  # noqa: E402
from shared.intents import Intent  # noqa: E402

HEADERS = {INTERNAL_KEY_HEADER: settings.internal_api_key}

# What each agent must include in its payload for each status.
REQUIRED = {
    "knowledge_agent": {"ok": ["answer", "sources"], "not_found": ["reason"], "error": ["reason"]},
    "account_agent": {"ok": ["answer"], "needs_auth": [], "not_found": ["reason"], "error": ["reason"]},
    "supervisor_agent": {"ok": ["sentiment", "score", "escalate", "reason", "priority"],
                         "escalate": ["ticket_id", "answer"], "error": ["reason"]},
}
ALLOWED = {
    "knowledge_agent": {"ok", "not_found", "error"},
    "account_agent": {"ok", "needs_auth", "not_found", "error"},
    "supervisor_agent": {"ok", "escalate", "error"},
}


def ok(msg: str) -> None:
    print(f"  [ok]   {msg}")


def bad(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def post(agent: str, path: str, body: dict) -> tuple[int, dict]:
    url = f"{settings.agent_url(agent)}{path}"
    try:
        r = httpx.post(url, json=body, headers=HEADERS, timeout=60.0)
    except httpx.HTTPError as exc:
        print(f"Cannot reach {url}: {exc}\nIs the agent running?  python -m agents.{agent}")
        sys.exit(1)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"detail": r.text}


def validate_reply(agent: str, req: Envelope, raw: dict) -> bool:
    good = True
    try:
        rep = Envelope.model_validate(raw)
        ok("reply parses as an Envelope")
    except Exception as exc:
        bad(f"reply is not a valid Envelope: {exc}")
        return False
    if rep.sender_agent != agent or rep.receiver_agent != "orchestrator":
        bad(f"sender/receiver wrong: {rep.sender_agent} -> {rep.receiver_agent} (use make_reply)"); good = False
    if rep.conversation_id != req.conversation_id or rep.intent != req.intent:
        bad("conversation_id or intent changed (use make_reply)"); good = False
    status = rep.payload.get("status")
    if status not in STATUS_VALUES:
        bad(f"status {status!r} not in {STATUS_VALUES}"); return False
    if status not in ALLOWED[agent]:
        bad(f"status {status!r} is not allowed from {agent} (allowed: {sorted(ALLOWED[agent])})"); good = False
    else:
        ok(f"status = {status}")
    for key in REQUIRED[agent].get(status, []):
        if key not in rep.payload:
            bad(f"payload missing '{key}' for status {status}"); good = False
    if agent == "knowledge_agent" and status == "ok":
        cites = set(re.findall(r"\[(\d+)\]", rep.payload.get("answer", "")))
        ids = {str(s.get("id")) for s in rep.payload.get("sources", [])}
        if cites and not cites <= ids:
            bad(f"citations {sorted(cites)} not all present in source ids {sorted(ids)}"); good = False
        elif cites:
            ok(f"citations {sorted(cites)} all match sources")
        for s in rep.payload.get("sources", []):
            for k in ("id", "title", "url", "chunk_id"):
                if k not in s:
                    bad(f"source missing '{k}': {s}"); good = False
    if agent == "supervisor_agent" and status == "escalate":
        if not re.fullmatch(r"T-\d{4}", str(rep.payload.get("ticket_id", ""))):
            bad(f"ticket_id {rep.payload.get('ticket_id')!r} should look like T-1001"); good = False
    if agent == "supervisor_agent" and status == "ok":
        if rep.payload.get("priority") not in ("high", "normal", "low"):
            bad("priority must be high | normal | low"); good = False
        if not isinstance(rep.payload.get("escalate"), bool):
            bad("escalate must be a boolean"); good = False
    return good


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("agent", choices=list(ALLOWED))
    p.add_argument("--intent", choices=[i.value for i in Intent])
    p.add_argument("--query", help="payload.query (knowledge / account)")
    p.add_argument("--token", help="auth_token (account)")
    p.add_argument("--task", choices=["assess", "escalate"], help="payload.task (supervisor)")
    p.add_argument("--message", help="payload.message for assess (supervisor)")
    p.add_argument("--failed-count", type=int, default=0)
    p.add_argument("--file", help="JSON file with a 'request' object (see agents/*/examples)")
    p.add_argument("--login", nargs=2, metavar=("MSISDN", "PASSWORD"), help="call /auth/login (account)")
    p.add_argument("--otp", nargs=2, metavar=("MSISDN", "CODE"), help="call /auth/verify-otp (account)")
    p.add_argument("--tickets", action="store_true", help="GET /tickets (supervisor)")
    a = p.parse_args()

    # --- auth helpers ---------------------------------------------------
    if a.login:
        code, data = post(a.agent, "/auth/login", {"msisdn": a.login[0], "password": a.login[1]})
        print(f"HTTP {code}\n{json.dumps(data, indent=2)}")
        if code == 200:
            good = data.get("otp_sent") is True and data.get("channel") in ("simulated", "sms")
            if data.get("channel") == "simulated" and not re.fullmatch(r"\d{6}", str(data.get("debug_otp", ""))):
                good = False
            (ok if good else bad)("login response shape"); return 0 if good else 1
        return 0 if code in (401, 429) else 1
    if a.otp:
        code, data = post(a.agent, "/auth/verify-otp", {"msisdn": a.otp[0], "otp": a.otp[1]})
        print(f"HTTP {code}\n{json.dumps(data, indent=2)}")
        if code == 200:
            good = isinstance(data.get("token"), str) and len(data["token"]) > 10
            (ok if good else bad)("verify-otp response has a token"); return 0 if good else 1
        return 0 if code in (401, 429) else 1
    if a.tickets:
        r = httpx.get(f"{settings.agent_url(a.agent)}/tickets", headers=HEADERS, timeout=10.0)
        print(f"HTTP {r.status_code}\n{json.dumps(r.json(), indent=2)}")
        return 0 if r.status_code == 200 and isinstance(r.json(), list) else 1

    # --- build the envelope -------------------------------------------
    if a.file:
        req = Envelope.model_validate(json.loads(Path(a.file).read_text(encoding="utf-8"))["request"])
    elif a.agent == "supervisor_agent":
        task = a.task or "assess"
        payload = ({"task": "assess", "message": a.message or "", "intent": a.intent or "package_info",
                    "failed_count": a.failed_count} if task == "assess"
                   else {"task": "escalate", "history": [{"role": "user", "text": a.message or ""}],
                         "reason": "manual", "priority": "normal"})
        req = Envelope(conversation_id="ping", sender_agent="orchestrator", receiver_agent=a.agent,
                       intent=Intent(a.intent or ("complaint" if task == "escalate" else "package_info")),
                       payload=payload)
    else:
        if not a.intent or a.query is None:
            p.error("--intent and --query are required (or use --file)")
        req = Envelope(conversation_id="ping", sender_agent="orchestrator", receiver_agent=a.agent,
                       intent=Intent(a.intent), payload={"query": a.query, "entities": {}}, auth_token=a.token)

    print(f"→ POST {settings.agent_url(a.agent)}/handle  intent={req.intent.value}")
    code, data = post(a.agent, "/handle", req.model_dump(mode="json"))
    print(f"← HTTP {code}")
    print(json.dumps(data.get("payload", data), indent=2, ensure_ascii=False))
    if code != 200:
        bad(f"expected HTTP 200, got {code}"); return 1
    return 0 if validate_reply(a.agent, req, data) else 1


if __name__ == "__main__":
    sys.exit(main())
