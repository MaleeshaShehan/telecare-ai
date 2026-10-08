"""Human agent roster + round-robin assignment.   Owner: M4

The 4 human agents are stored in Supabase (or fall back to an in-memory list
for offline tests). The next agent to receive a ticket is picked in a fair
round-robin order, so work is distributed evenly.
"""
import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

try:
    from supabase import create_client, Client
    SUPABASE_LIB_AVAILABLE = True
except ImportError:
    SUPABASE_LIB_AVAILABLE = False

USE_SUPABASE = (
    SUPABASE_LIB_AVAILABLE
    and bool(SUPABASE_URL)
    and bool(SUPABASE_KEY)
)

supabase: "Client | None" = None
if USE_SUPABASE:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---- In-memory fallback (used for offline tests) ----
_FALLBACK_AGENTS = [
    {"id": 1, "name": "Dulmini Tharushika", "email": "dulminitharushika07@gmail.com", "specialty": "billing"},
    {"id": 2, "name": "Maleesha Shehan",   "email": "maleeshashehan178@gmail.com",   "specialty": "technical"},
    {"id": 3, "name": "Chenuka Ranthila",  "email": "chenukaranthila@gmail.com",       "specialty": "general"},
    # --{"id": 4, "name": "Dinusha Sampath",     "email": "agent.fernando@example.com",     "specialty": "roaming"},
]
_LAST_INDEX = {"i": 0}  # round-robin cursor for the fallback list


def list_active_agents() -> list[dict]:
    """Return all active human agents."""
    if USE_SUPABASE:
        result = (
            supabase.table("human_agents")
            .select("id,name,email,specialty")
            .eq("active", True)
            .order("id")
            .execute()
        )
        return result.data
    return list(_FALLBACK_AGENTS)


def pick_next_agent() -> dict:
    """Round-robin: pick the next human agent fairly.

    Round-robin means we cycle through the list in order:
        T-1001 -> Agent 1
        T-1002 -> Agent 2
        T-1003 -> Agent 3
        T-1004 -> Agent 4
        T-1005 -> Agent 1  (back to the start)
    """
    agents = list_active_agents()
    if not agents:
        # Safety net — never crash, always return something
        return {"name": "on-call agent", "email": "oncall@example.com", "specialty": "general"}

    # Count how many tickets exist already to decide the next agent
    if USE_SUPABASE:
        count_result = supabase.table("tickets").select("id", count="exact").execute()
        n = count_result.count or 0
    else:
        n = _LAST_INDEX["i"]
        _LAST_INDEX["i"] += 1

    return agents[n % len(agents)]