from enum import StrEnum


class ToolName(StrEnum):
    SEARCH_KNOWLEDGE = "search_knowledge"
    LOOKUP_ORDER = "lookup_order"
    CREATE_SUPPORT_REQUEST = "create_support_request"
    REQUEST_HUMAN_HANDOFF = "request_human_handoff"
    ASK_CLARIFICATION = "ask_clarification"
    DECLINE_UNSUPPORTED = "decline_unsupported"
