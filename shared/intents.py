"""The telecom intent taxonomy and which agent owns each intent.

This is a contract. Adding an intent means telling the group, because the
orchestrator's router, the NLU prompt and the eval set all depend on it.
"""
from enum import Enum


class Intent(str, Enum):
    # Knowledge Agent (public documents, no login)
    PACKAGE_INFO = "package_info"
    TARIFF_QUERY = "tariff_query"
    ROAMING_ADVICE = "roaming_advice"
    COVERAGE_OR_OUTAGE_INFO = "coverage_or_outage_info"
    TROUBLESHOOTING = "troubleshooting"
    PLAN_ADVICE = "plan_advice"
    # Account Agent (one logged-in subscriber)
    BILL_ENQUIRY = "bill_enquiry"
    BILL_BY_MONTH = "bill_by_month"
    QUOTA_CHECK = "quota_check"
    # Supervisor Agent
    COMPLAINT = "complaint"
    # Orchestrator answers itself with a polite refusal
    OUT_OF_SCOPE = "out_of_scope"


# Which specialist handles each intent. The orchestrator routes with this table.
INTENT_OWNER: dict[Intent, str] = {
    Intent.PACKAGE_INFO: "knowledge_agent",
    Intent.TARIFF_QUERY: "knowledge_agent",
    Intent.ROAMING_ADVICE: "knowledge_agent",
    Intent.COVERAGE_OR_OUTAGE_INFO: "knowledge_agent",
    Intent.TROUBLESHOOTING: "knowledge_agent",
    Intent.PLAN_ADVICE: "knowledge_agent",
    Intent.BILL_ENQUIRY: "account_agent",
    Intent.BILL_BY_MONTH: "account_agent",
    Intent.QUOTA_CHECK: "account_agent",
    Intent.COMPLAINT: "supervisor_agent",
    Intent.OUT_OF_SCOPE: "orchestrator",
}

# Intents that need a valid JWT before the orchestrator will route them.
AUTH_REQUIRED: frozenset[Intent] = frozenset(
    {Intent.BILL_ENQUIRY, Intent.BILL_BY_MONTH, Intent.QUOTA_CHECK}
)

# Optional corpus category filter the Knowledge Agent applies per intent.
INTENT_CATEGORY: dict[Intent, str] = {
    Intent.ROAMING_ADVICE: "roaming",
    Intent.PLAN_ADVICE: "package",
    Intent.COVERAGE_OR_OUTAGE_INFO: "coverage",
    Intent.TROUBLESHOOTING: "troubleshooting",
}
