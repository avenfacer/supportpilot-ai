from app.ai.errors import ProviderResponseError, ProviderTimeoutError
from app.repositories.memory import InMemoryKnowledgeRepository
from tests.conftest import ClientFactory, ScriptedLLM

FAQ = "How long does standard shipping take?"


def _all_chunk_ids(repo: InMemoryKnowledgeRepository) -> set[str]:
    return {c.id for chunks in repo.chunks.values() for c in chunks}


def test_faq_is_answered_with_valid_citations(
    make_client: ClientFactory, knowledge_repo: InMemoryKnowledgeRepository
) -> None:
    response = make_client().post("/api/v1/chat", json={"message": FAQ, "conversation_id": "c-1"})
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "answered"
    assert "3-5 business days" in body["answer"]
    assert body["conversation_id"] == "c-1"
    assert body["citations"], "answered FAQ must cite sources"
    assert {c["source_id"] for c in body["citations"]} <= _all_chunk_ids(knowledge_repo)
    assert all(c["document_id"] == "shipping" for c in body["citations"])
    assert body["ticket_id"] is None and body["needs_human"] is False


def test_unsupported_question_abstains_without_guessing(make_client: ClientFactory) -> None:
    body = make_client().post("/api/v1/chat", json={"message": "Do you sell laptops?"}).json()
    assert body["status"] == "unsupported"
    assert body["citations"] == []
    assert body["needs_human"] is True
    assert body["handoff_reason"] == "insufficient_evidence"


def test_citation_not_in_retrieval_is_dropped(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(
        tool="search_knowledge",
        arguments={"query": FAQ},
        answer={
            "answer": "Standard shipping takes 3-5 business days.",
            "citation_ids": ["shipping:002", "made_up:999"],
            "sufficient_evidence": True,
        },
    )
    body = make_client(llm=llm).post("/api/v1/chat", json={"message": FAQ}).json()
    assert body["status"] == "answered"
    assert [c["source_id"] for c in body["citations"]] == ["shipping:002"]


def test_answer_with_only_fabricated_citations_is_rejected(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(
        tool="search_knowledge",
        arguments={"query": FAQ},
        answer={
            "answer": "It takes 3 days.",
            "citation_ids": ["fake:1"],
            "sufficient_evidence": True,
        },
    )
    body = make_client(llm=llm).post("/api/v1/chat", json={"message": FAQ}).json()
    assert body["status"] == "unsupported"
    assert body["citations"] == []


def test_answer_with_numbers_not_in_sources_is_rejected(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(
        tool="search_knowledge",
        arguments={"query": FAQ},
        answer={
            "answer": "Standard shipping takes 2 business days and costs $1.99.",
            "citation_ids": ["shipping:002"],
            "sufficient_evidence": True,
        },
    )
    body = make_client(llm=llm).post("/api/v1/chat", json={"message": FAQ}).json()
    assert body["status"] == "unsupported"


def test_model_reporting_insufficient_evidence_abstains(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(
        tool="search_knowledge",
        arguments={"query": FAQ},
        answer={"answer": "", "citation_ids": [], "sufficient_evidence": False},
    )
    body = make_client(llm=llm).post("/api/v1/chat", json={"message": FAQ}).json()
    assert body["status"] == "unsupported"


def test_conflicting_evidence_escalates(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(
        tool="search_knowledge",
        arguments={"query": FAQ},
        answer={
            "answer": "",
            "citation_ids": ["shipping:002"],
            "sufficient_evidence": True,
            "conflicting_evidence": True,
        },
    )
    body = make_client(llm=llm).post("/api/v1/chat", json={"message": FAQ}).json()
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "conflicting_policy"
    assert body["needs_human"] is True


def test_retrieved_text_is_wrapped_as_untrusted_reference(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(
        tool="search_knowledge",
        arguments={"query": FAQ},
        answer={"answer": "", "citation_ids": [], "sufficient_evidence": False},
    )
    make_client(llm=llm).post("/api/v1/chat", json={"message": FAQ})
    prompt = llm.answer_prompts[0]
    assert '<untrusted_reference id="shipping:' in prompt
    assert "<customer_question>" in prompt


def test_malformed_model_output_returns_safe_503(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(tool="search_knowledge", arguments={"query": FAQ}, answer="not json {")
    response = make_client(llm=llm).post("/api/v1/chat", json={"message": FAQ})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "ai_temporarily_unavailable"
    assert "json" not in error["message"].lower()


def test_provider_timeout_returns_safe_503(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(plan_error=ProviderTimeoutError("plan timed out after 20s"))
    response = make_client(llm=llm).post("/api/v1/chat", json={"message": FAQ})
    assert response.status_code == 503
    assert "timed out" not in response.text


def test_provider_response_error_during_answer_is_safe(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(
        tool="search_knowledge",
        arguments={"query": FAQ},
        answer_error=ProviderResponseError("no content"),
    )
    response = make_client(llm=llm).post("/api/v1/chat", json={"message": FAQ})
    assert response.status_code == 503


def test_customer_id_in_body_is_rejected(make_client: ClientFactory) -> None:
    response = make_client().post(
        "/api/v1/chat", json={"message": "Where is ORD-2001?", "customer_id": "CUST-002"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_blank_message_is_rejected_without_echoing_input(make_client: ClientFactory) -> None:
    response = make_client().post("/api/v1/chat", json={"message": "   "})
    assert response.status_code == 422
    assert "input" not in response.json()
