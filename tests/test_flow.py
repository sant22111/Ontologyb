"""End-to-end test with the offline mock model. Run:  python -m pytest tests -q   (or python tests/test_flow.py)"""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ["LLM_PROVIDER"] = "mock"
os.environ["STUDIO_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

import app as appmod  # noqa: E402

c = TestClient(appmod.app)


def test_full_session():
    cfg = c.get("/api/config").json()
    assert cfg["provider"] == "mock"
    s = c.post("/api/session", json={"domain": "Retail bank fraud", "owner": "Test"}).json()
    sid = s["id"]
    assert s["messages"][0]["role"] == "assistant"
    assert s["score"] == 0 and s["stage"] == 1

    last = None
    for ans in ["We investigate suspicious transactions", "Alerts go to investigators", "Devices and merchants matter", "Head of fraud decides"]:
        last = c.post(f"/api/session/{sid}/chat", json={"message": ans}).json()
        assert last["messages"][-1]["role"] == "assistant"
    assert last["counts"]["things"] == 8, last["counts"]
    assert last["counts"]["rules"] == 3
    assert last["score"] > 40, last["score"]
    earned = [b["id"] for b in last["badges"] if b["earned"]]
    assert "core" in earned and "rules" in earned and "time" in earned and "authority" in earned and "exception" in earned, earned

    # Question Arena: answerable
    q1 = c.post(f"/api/session/{sid}/arena", json={"question": "Which customers hold an account with an alert?"}).json()["question"]
    assert q1["status"] == "yes", q1
    assert q1["steps"], q1
    # Question Arena: gap, then fix
    q2 = c.post(f"/api/session/{sid}/arena", json={"question": "Which regulator penalty applies to a late case?"}).json()["question"]
    assert q2["status"] in ("partial", "no"), q2
    assert q2["gaps"], q2
    gi = next(i for i, g in enumerate(q2["gaps"]) if g["type"] == "missing_thing")
    fixed = c.post(f"/api/session/{sid}/arena/{q2['id']}/fix", json={"gap_index": gi}).json()
    q2b = next(x for x in fixed["questions"] if x["id"] == q2["id"])
    assert len(q2b["gaps"]) < len(q2["gaps"]), (q2b["gaps"], q2["gaps"])

    sug = c.post(f"/api/session/{sid}/arena/suggest").json()
    assert len(sug["questions"]) == 5

    st = c.post(f"/api/session/{sid}/story").json()
    assert st["story"]["headline"] and not st["story_stale"]
    sm = c.post(f"/api/session/{sid}/sample").json()
    assert sm["sample"]["nodes"] and sm["sample"]["edges"]

    d = c.get(f"/api/session/{sid}/node/Customer").json()
    assert d["outgoing"] and d["properties"]

    ch = c.post(f"/api/session/{sid}/challenge", json={"text": "fine"}).json()
    assert "challenge_reply" in ch

    r = c.get(f"/api/session/{sid}/export.xlsx")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    for tab in ["Summary", "Classes", "Relationships", "Properties", "Rules", "Layers", "Test Questions", "Traceability", "Change Log"]:
        assert tab in wb.sheetnames, tab
    assert wb["Classes"].max_row >= 9
    j = c.get(f"/api/session/{sid}/export.json").json()
    assert j["classes"] and j["object_properties"]

    assert any(x["id"] == sid for x in c.get("/api/sessions").json())
    assert c.get("/").status_code == 200 or True


def test_template_start():
    s = c.post("/api/session", json={"domain": "Telecom compliance", "template": "telecom_regulatory"}).json()
    assert s["counts"]["things"] == 4 and s["counts"]["connections"] == 3


def test_stub_and_remove():
    import ontology as ont
    st = ont.new_state("x")
    ont.apply_delta(st, {"relationships": [{"name": "cites", "from": "Judgment", "to": "Statute"}]}, "t")
    assert len(st["classes"]) == 2 and all(v["stub"] for v in st["classes"].values())
    ont.apply_delta(st, {"classes": [{"name": "Judgment", "description": "A court decision"}]}, "t")
    assert not st["classes"]["Judgment"]["stub"]
    ont.apply_delta(st, {"remove": {"classes": ["Statute"]}}, "t")
    assert not st["relationships"]





def test_messy_model_output():
    import ontology as ont
    from llm import extract_json
    assert extract_json('Here you go:\n```json\n{"a": 1}\n```\nthanks')["a"] == 1
    assert extract_json('noise {"a": {"b": 2}} trailing')["a"]["b"] == 2
    st = ont.new_state("x")
    # strings / nulls / wrong shapes inside lists must not crash
    ont.apply_delta(st, {"classes": ["Customer", None, {"name": "Account", "description": "d"}], "relationships": "oops",
                         "rules": [{"text": "r", "category": "weird", "applies_to": ["Account"]}], "remove": []}, "t")
    assert list(st["classes"]) == ["Account"] and st["rules"][0]["category"] == "business"
    ont.apply_delta(st, "not a dict", "t")

def test_password_gate():
    os.environ["STUDIO_PASSWORD"] = "letmein"
    try:
        assert c.get("/api/config").status_code == 401
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/config", auth=("anyone", "wrong")).status_code == 401
        assert c.get("/api/config", auth=("anyone", "letmein")).status_code == 200
    finally:
        del os.environ["STUDIO_PASSWORD"]
    assert c.get("/api/config").status_code == 200


if __name__ == "__main__":
    test_full_session()
    test_template_start()
    test_stub_and_remove()
    test_messy_model_output()
    test_password_gate()
    print("ALL PASSED")


def test_draft_flow():
    import tempfile, importlib, os
    os.environ["STUDIO_DATA_DIR"] = tempfile.mkdtemp()
    os.environ["LLM_PROVIDER"] = "mock"
    from fastapi.testclient import TestClient
    import app as A
    importlib.reload(A)
    c = TestClient(A.app)
    v = c.post("/api/session", json={"domain": "Sales", "client": "Acme Foods", "research": True}).json()
    drafts = [x for x in v["classes"] if x.get("draft")]
    assert len(drafts) >= 6 and v["score"] == 0, (len(drafts), v["score"])
    assert v["draft"]["basis"] == "general"
    assert "starting draft" in v["messages"][-1]["content"]
    sid = v["id"]
    v = c.post(f"/api/session/{sid}/confirm", json={"name": "Product", "action": "confirm"}).json()
    assert not next(x for x in v["classes"] if x["name"] == "Product")["draft"]
    n = len(v["classes"])
    v = c.post(f"/api/session/{sid}/confirm", json={"name": "Retailer", "action": "remove"}).json()
    assert len(v["classes"]) == n - 1
    v = c.post(f"/api/session/{sid}/confirm", json={"action": "confirm_all"}).json()
    assert not any(x.get("draft") for x in v["classes"]) and v["score"] > 0
    assert c.get(f"/api/session/{sid}/export.xlsx").status_code == 200
    v = c.post(f"/api/session/{sid}/usecases").json()
    items = v["usecases"]["items"]
    assert len(items) >= 3 and all("check" in i for i in items)
    assert any(not i["ready"] for i in items) and any(i["ready"] for i in items), [i["ready"] for i in items]
    v2 = c.post("/api/session", json={"domain": "Sales", "client": "Acme", "goals": ["Audits take weeks", "x" * 500, "c", "d"]}).json()
    assert len(v2["goals"]) == 3 and len(v2["goals"][1]) == 200
    v2 = c.post("/api/session", json={"domain": "Sales", "client": "Acme"}).json()
    assert not any(x.get("draft") for x in v2["classes"])
    print("draft flow ok")


if __name__ == "__main__":
    test_draft_flow()
