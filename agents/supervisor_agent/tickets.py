"""Ticket store in data/db/tickets.db.   Owner: M4

    create_ticket(conversation_id, summary: dict, priority) -> str   # "T-1001", "T-1002", ...
    list_open_tickets() -> list[dict]                                 # for ui/pages/console.py

Parameterised SQL only.
"""
