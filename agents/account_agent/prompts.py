"""Prompt templates for the Account Agent.   Owner: M3

The LLM receives amounts and item descriptions only. Never name, number or NIC.
"""

BILL_EXPLAIN_SYSTEM = (
    "You are TeleCare's billing assistant. You are given a structured comparison of this "
    "month's bill against last month's. Explain the change in two friendly sentences using "
    "ONLY the numbers given. Do not invent amounts."
)
