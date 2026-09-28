import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.llm import LLM
from tests.fakes import ScriptedChatModel, classify, submit, text, tool_call


@pytest.fixture
def make_client(db_path, tmp_path):
    def _make(replies=None, llm=None):
        settings = Settings(database_path=db_path, data_dir=tmp_path / "data")
        if llm is None and replies is not None:
            llm = LLM(ScriptedChatModel(replies=list(replies)))
        return TestClient(create_app(settings, llm))

    return _make


def chat(client, message, thread_id=None):
    """Post a chat message and return the parsed SSE events."""
    thread_id = thread_id or uuid.uuid4().hex
    with client.stream("POST", "/api/chat", json={"thread_id": thread_id, "message": message}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_chat_streams_steps_tokens_and_response(make_client):
    replies = [
        classify("generate", "Customers in California"),
        tool_call("get_column_values", table="Customers", column="State", search="cali"),
        submit("SELECT * FROM Customers WHERE State = 'California'"),
        text("Lists customers in California."),
    ]
    with make_client(replies) as client:
        events = chat(client, "customers in california")

    kinds = [e for e, _ in events]
    assert kinds[-1] == "response"
    steps = [d for e, d in events if e == "step"]
    assert [s["node"] for s in steps] == [
        "input_guard", "classify_intent", "retrieve_schema", "generate_sql", "run_data_tools",
        "generate_sql", "validate_sql", "optimize_sql", "explain",
    ]
    assert steps[4]["detail"] == ["Checked values of Customers.State matching 'cali': 1 values"]
    assert "".join(d["text"] for e, d in events if e == "token") == "Lists customers in California."
    response = events[-1][1]
    assert response["type"] == "sql" and "California" in response["sql"]


def test_refusal_over_sse(make_client):
    with make_client([classify("out_of_scope")]) as client:
        events = chat(client, "Who won the FIFA World Cup?")
    assert events[-1][1]["reason"] == "out_of_scope"


def test_llm_failure_becomes_error_event(make_client):
    with make_client([]) as client:  # scripted model with no replies raises
        events = chat(client, "Show all orders")
    assert events[-1][0] == "error"


def test_missing_llm_configuration(db_path, tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = Settings(database_path=db_path, data_dir=tmp_path / "data", llm_model="google_genai:gemini-3.8-flash", llm_fallback_model=None)
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health").json()
        assert health["llm_ready"] is False
        assert health["llm_error"] == "set GOOGLE_API_KEY in .env to use google_genai:gemini-3.8-flash"
        events = chat(client, "Show all orders")
        assert events == [("error", {"message": f"The language model isn't configured: {health['llm_error']}"})]
        assert client.get("/api/schema").status_code == 200  # the rest of the API still works


def test_threads_keep_history_and_responses(make_client):
    thread_id = uuid.uuid4().hex
    replies = [
        classify("generate", "All customers"), submit("SELECT * FROM Customers"), text("All customers."),
        classify("follow_up", "Customers from California"),
        submit("SELECT * FROM Customers WHERE State = 'California'"), text("California customers."),
    ]
    with make_client(replies) as client:
        chat(client, "Show all customers.", thread_id)
        chat(client, "Only those from California.", thread_id)

        threads = client.get("/api/threads").json()
        assert [t["title"] for t in threads] == ["Show all customers."]

        detail = client.get(f"/api/threads/{thread_id}").json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
        assert "State = 'California'" in detail["messages"][3]["response"]["sql"]

        assert client.delete(f"/api/threads/{thread_id}").status_code == 204
        assert client.get(f"/api/threads/{thread_id}").status_code == 404
        assert client.get("/api/threads").json() == []


def test_thread_id_is_validated(make_client):
    with make_client([]) as client:
        r = client.post("/api/chat", json={"thread_id": "../../etc", "message": "hi"})
        assert r.status_code == 422
        assert client.get("/api/threads/..%2Fx").status_code == 404


def test_execute_returns_rows(make_client):
    with make_client([]) as client:
        r = client.post("/api/execute", json={"sql": "SELECT FirstName FROM Customers WHERE State = 'California'"})
    assert r.status_code == 200
    body = r.json()
    assert body["columns"] == ["FirstName"] and body["row_count"] == 4 and not body["truncated"]


def test_execute_rejects_writes(make_client):
    with make_client([]) as client:
        r = client.post("/api/execute", json={"sql": "DROP TABLE Orders"})
        assert r.status_code == 400
        assert "read-only" in r.json()["detail"]["errors"][0]
        assert client.post("/api/execute", json={"sql": "SELECT COUNT(*) FROM Orders"}).json()["rows"] == [[12]]


def test_schema_endpoint(make_client):
    with make_client([]) as client:
        tables = client.get("/api/schema").json()["tables"]
    orders = next(t for t in tables if t["name"] == "Orders")
    assert {"column": "CustomerID", "ref_table": "Customers", "ref_column": "CustomerID"} in orders["foreign_keys"]


def test_llm_error_is_saved_in_the_conversation(make_client):
    thread_id = uuid.uuid4().hex
    with make_client([]) as client:
        events = chat(client, "Show all orders", thread_id)
        assert events[-1][0] == "error"
        messages = client.get(f"/api/threads/{thread_id}").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["response"]["type"] == "error"
    assert messages[1]["content"] == events[-1][1]["message"]


def test_next_turn_works_after_an_error(make_client):
    thread_id = uuid.uuid4().hex
    llm_model = ScriptedChatModel(replies=[])
    with make_client(llm=LLM(llm_model)) as client:
        chat(client, "Show all orders", thread_id)  # fails: no scripted replies
        llm_model.replies.extend([classify("out_of_scope")])
        events = chat(client, "Who won the World Cup?", thread_id)
        assert events[-1][1]["reason"] == "out_of_scope"
        roles = [m["role"] for m in client.get(f"/api/threads/{thread_id}").json()["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_turn_keeps_running_after_client_disconnects(make_client):
    import time

    thread_id = uuid.uuid4().hex
    replies = [classify("generate", "All products"), submit("SELECT * FROM Products"), text("All products.")]
    with make_client(replies) as client:
        with client.stream("POST", "/api/chat", json={"thread_id": thread_id, "message": "all products"}) as r:
            next(r.iter_text())  # read the first event, then drop the connection
        for _ in range(100):
            detail = client.get(f"/api/threads/{thread_id}").json()
            if not detail["running"] and len(detail["messages"]) == 2:
                break
            time.sleep(0.02)
    assert detail["messages"][1]["response"]["type"] == "sql"


def test_resume_and_cancel_when_idle(make_client):
    thread_id = uuid.uuid4().hex
    with make_client([]) as client:
        assert client.get(f"/api/threads/{thread_id}/events").status_code == 204
        assert client.post(f"/api/threads/{thread_id}/cancel").status_code == 404


def test_password_protection(db_path, tmp_path):
    settings = Settings(database_path=db_path, data_dir=tmp_path / "data", app_password="s3cret")
    with TestClient(create_app(settings, LLM(ScriptedChatModel(replies=[])))) as client:
        assert client.get("/api/health").status_code == 200  # open for the host's health check
        denied = client.get("/api/schema")
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"].startswith("Basic")
        assert client.get("/api/schema", auth=("anyone", "wrong")).status_code == 401
        assert client.get("/api/schema", headers={"Authorization": "Basic !!notbase64"}).status_code == 401
        assert client.get("/api/schema", auth=("anyone", "s3cret")).status_code == 200
        r = client.post("/api/execute", json={"sql": "SELECT COUNT(*) FROM Orders"}, auth=("", "s3cret"))
        assert r.status_code == 200


def test_no_password_by_default(make_client):
    with make_client([]) as client:
        assert client.get("/api/schema").status_code == 200
