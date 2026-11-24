"""Ontology Studio: a guided, game-like way for non-technical clients to build an ontology.
Run:  uvicorn app:app --port 8100   (see README.md)
"""
import base64
import json
import os
import secrets
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware


# --- tiny .env loader (no extra dependency)
def _load_env():
    p = Path(__file__).parent / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

import docs  # noqa: E402
import excel  # noqa: E402
import ontology as ont  # noqa: E402
import prompts as P  # noqa: E402
from llm import LLMError, llm  # noqa: E402

BASE = Path(__file__).parent
DATA = Path(os.getenv("STUDIO_DATA_DIR", BASE / "data")) / "sessions"
DATA.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Ontology Studio")

# Fail closed: a hosted copy with a real model key and no password would let anyone spend your credits.
if os.getenv("PORT") and llm.provider != "mock" and not os.getenv("STUDIO_PASSWORD"):
    raise RuntimeError("Set STUDIO_PASSWORD before deploying with a model key, or anyone with the link can spend your credits.")


class Gate(BaseHTTPMiddleware):
    """Optional shared password (HTTP Basic). Any username works. Set STUDIO_PASSWORD to turn it on."""

    async def dispatch(self, request, call_next):
        pw = os.getenv("STUDIO_PASSWORD")
        if not pw or request.url.path == "/healthz":
            return await call_next(request)
        h = request.headers.get("authorization", "")
        if h.lower().startswith("basic "):
            try:
                _, _, given = base64.b64decode(h[6:]).decode("utf-8").partition(":")
                if secrets.compare_digest(given.encode(), pw.encode()):
                    return await call_next(request)
            except Exception:
                pass
        return PlainTextResponse("Password required", status_code=401,
                                 headers={"WWW-Authenticate": 'Basic realm="Business Map Studio"'})


app.add_middleware(Gate)
_locks = {}
_glock = threading.Lock()


def _lock(sid):
    with _glock:
        return _locks.setdefault(sid, threading.RLock())


def _path(sid):
    if not sid.isalnum():
        raise HTTPException(400, "bad session id")
    return DATA / f"{sid}.json"


def load(sid):
    p = _path(sid)
    if not p.exists():
        raise HTTPException(404, "session not found")
    return json.loads(p.read_text(encoding="utf-8"))


def save(st):
    p = _path(st["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def sig(st):
    return [len(st["classes"]), len(st["relationships"]), len(st["properties"]), len(st["rules"])]


def present(st, include_messages=True):
    v = ont.view(st, include_messages)
    v["story_stale"] = bool(st["story"]) and st["story"].get("sig") != sig(st)
    v["doc_guide_stale"] = bool(st.get("doc_guide")) and st["doc_guide"].get("sig") != sig(st)
    v["usecases_stale"] = bool(st.get("usecases")) and st["usecases"].get("sig") != sig(st)
    v["sample_stale"] = bool(st["sample"]) and st["sample"].get("sig") != sig(st)
    v["llm"] = {"provider": llm.provider, "model": llm.model}
    return v


def ai(task, system, messages, ctx=None, max_tokens=4000):
    try:
        return llm.json(task, system, messages, max_tokens=max_tokens, context=ctx)
    except LLMError as e:
        raise HTTPException(502, str(e))


def llm_history(st, limit=16):
    msgs = [{"role": m["role"], "content": m["content"]} for m in st["messages"]][-limit:]
    if not msgs or msgs[0]["role"] != "user":
        msgs = [{"role": "user", "content": "[Begin the workshop]"}] + msgs
    return msgs


def build_draft(st):
    """Research the client and pre-fill the map with unconfirmed guesses. Never blocks the workshop."""
    tnote = ont.TEMPLATES[st["template"]]["note"] if st["template"] else ""
    user = f"Client: {st['client']}\nArea: {st['domain']}\nTeam notes: {st['about'] or '(none)'}"
    try:
        obj, urls = llm.research(P.draft_system(st["client"], st["about"], st["domain"], tnote, st.get("goals")), user, {})
        delta = obj.get("delta") if isinstance(obj, dict) and isinstance(obj.get("delta"), dict) else {}
        for k in ("rules", "remove", "rename", "confirm"):
            delta.pop(k, None)
        ont.apply_delta(st, delta, "draft")
        ont.mark_draft(st)
        st["draft"] = {"basis": "web" if urls else "general", "sources": urls,
                       "summary": str(obj.get("summary", ""))[:400] if isinstance(obj, dict) else ""}
        ont.trail_add(st, "research", "Starting draft", obj.get("summary", "") if isinstance(obj, dict) else "", obj.get("findings") if isinstance(obj, dict) else [], urls)
        st["headaches"] = [str(h)[:160] for h in (obj.get("headaches") or []) if isinstance(h, str)][:8] if isinstance(obj, dict) else []
        ont.log(st, "draft", "Starting draft prepared (" + (f"{len(urls)} public web pages: " + "; ".join(urls) if urls else "general knowledge only, no web pages read") + ")")
    except Exception as e:  # the workshop still works without the draft
        st["draft"] = {"basis": "none", "sources": [], "error": str(e)[:200]}


def interview_turn(st, user_text):
    turn = sum(1 for m in st["messages"] if m["role"] == "user")
    if user_text is not None:
        st["messages"].append({"role": "user", "content": user_text})
        turn += 1
    s = ont.summary(st)
    drafts = [k for k, c in st["classes"].items() if c.get("draft")]
    tnote = ont.TEMPLATES[st["template"]]["note"] if st["template"] else "No template; start from the client's own words."
    system = P.interview_system(st["domain"], tnote, s["stage"], ont.context_block(st), ", ".join(s["stubs"]), st.get("client", ""), st.get("about", ""), drafts, st.get("goals"), ont.trail_block(st))
    ctx = {"turn": turn, "classes": list(st["classes"].keys()), "drafts": bool(drafts)}
    try:
        res = ai("interview", system, llm_history(st), ctx)
    except HTTPException:
        if user_text is not None:
            st["messages"].pop()
        raise
    result = ont.apply_delta(st, res.get("delta"), f"Answer #{turn}" if turn else "Opening")
    st["messages"].append({"role": "assistant", "content": res.get("reply", "..."), "chips": (res.get("chips") or [])[:4],
                           "captured": res.get("captured", ""), "added": result["added"]})
    return result


class NewSession(BaseModel):
    domain: str
    template: str | None = None
    owner: str = ""
    client: str = ""
    about: str = ""
    research: bool = False
    goals: list[str] = []


class Msg(BaseModel):
    message: str


class Q(BaseModel):
    question: str


class Fix(BaseModel):
    gap_index: int


class Challenge(BaseModel):
    text: str


# --------------------------------------------------------------------- routes
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {"provider": llm.provider, "model": llm.model,
            "templates": [{"id": k, "label": v["label"]} for k, v in ont.TEMPLATES.items()],
            "stages": ont.STAGE_NAMES}


@app.get("/api/sessions")
def sessions():
    out = []
    for p in sorted(DATA.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:30]:
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": st["id"], "domain": st["domain"], "owner": st.get("owner", ""), "updated": st["updated"],
                        "score": ont.summary(st)["score"], "things": len(st["classes"])})
        except Exception:
            continue
    return out


@app.post("/api/session")
def create(body: NewSession):
    if not body.domain.strip():
        raise HTTPException(400, "Tell us what area to map")
    st = ont.new_state(body.domain, body.template, body.owner, body.client, body.about, body.goals)
    with _lock(st["id"]):
        if body.research and st["client"]:
            build_draft(st)
            st["pending_goals"] = True  # the client picks what to fix before the workshop opens
        else:
            interview_turn(st, None)
        save(st)
    return present(st)


class Goals(BaseModel):
    goals: list[str] = []


@app.post("/api/session/{sid}/goals")
def set_goals(sid: str, body: Goals):
    with _lock(sid):
        st = load(sid)
        st["goals"] = [g.strip()[:200] for g in body.goals if g.strip()][:3]
        if st.get("pending_goals"):
            st["pending_goals"] = False
            interview_turn(st, None)
        save(st)
    return present(st)


class More(BaseModel):
    topic: str = ""


def _grow_note(res, label):
    a = res["added"]
    return f"{label}: +{a['classes']} things, +{a['relationships']} connections, +{a['properties']} details, +{a['rules']} rules. Review them and keep or remove each."


@app.post("/api/session/{sid}/suggest-more")
def suggest_more(sid: str, body: More):
    with _lock(sid):
        st = load(sid)
        if not st["classes"]:
            raise HTTPException(400, "Build a few things on the map first")
        topic = body.topic.strip()[:200]
        system = P.enrich_system(ont.context_block(st), st.get("client", ""), st.get("about", ""), st.get("goals"), topic, ont.trail_block(st))
        try:
            obj, urls = llm.research(system, f"Client: {st.get('client') or st['domain']}\nFocus: {topic or 'anything important missing'}", {"classes": list(st["classes"].keys())}, task="enrich")
        except LLMError as e:
            raise HTTPException(502, str(e))
        delta = obj.get("delta") if isinstance(obj, dict) and isinstance(obj.get("delta"), dict) else {}
        for k in ("rules", "remove", "rename", "confirm"):
            delta.pop(k, None)
        res = ont.apply_delta(st, delta, "draft")
        ont.mark_draft(st, "draft")
        ont.trail_add(st, "suggest more", topic or "Open suggestions", obj.get("summary", "") if isinstance(obj, dict) else "", obj.get("findings") if isinstance(obj, dict) else [], urls)
        ont.log(st, "suggest more", (f"Focus: {topic}. " if topic else "") + ("Read " + str(len(urls)) + " public pages: " + "; ".join(urls) if urls else "From general knowledge, no web pages read"))
        save(st)
    v = present(st)
    v["grow"] = {"note": _grow_note(res, "Suggested"), "summary": str(obj.get("summary", ""))[:300] if isinstance(obj, dict) else "", "basis": "web" if urls else "general"}
    return v


@app.post("/api/session/{sid}/document")
async def add_document(sid: str, file: UploadFile = File(...)):
    data = await file.read(docs.MAX_BYTES + 1)
    try:
        text = docs.extract_text(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "Could not read that file. Try saving it as a text or Word file.")
    text = text.strip()
    if len(text) < 60:
        raise HTTPException(400, "No readable text found. A scanned PDF needs to be converted to text first.")
    truncated = len(text) > docs.MAX_CHARS
    text = text[:docs.MAX_CHARS]
    fname = (file.filename or "document")[:80]
    with _lock(sid):
        st = load(sid)
        system = P.doc_system(ont.context_block(st), st.get("client", ""), fname, text, ont.trail_block(st))
        res = ai("doc", system, [{"role": "user", "content": "Extract what the document says."}], {"text": text, "classes": list(st["classes"].keys())}, max_tokens=5000)
        delta = res.get("delta") if isinstance(res.get("delta"), dict) else {}
        for k in ("remove", "rename", "confirm"):
            delta.pop(k, None)
        # keep only quotes that really appear in the document; unverifiable rules are dropped
        sq = docs.squash(text)
        dropped = 0
        for key in ("classes", "relationships", "rules"):
            keep = []
            for it in delta.get(key) or []:
                if not isinstance(it, dict):
                    continue
                ok = docs.quote_in(sq, it.get("source_quote", ""))
                if not ok:
                    it["source_quote"] = ""
                    if key == "rules":
                        dropped += 1
                        continue
                keep.append(it)
            delta[key] = keep
        source = f"Document: {fname}"
        out = ont.apply_delta(st, delta, source)
        ont.mark_draft(st, source)
        ont.trail_add(st, "document", fname, res.get("summary", ""), res.get("findings"))
        ont.log(st, "document", f"Read {fname} ({len(text)} characters{', first part only' if truncated else ''}). Added for review: {out['added']['classes']} things, {out['added']['relationships']} connections, {out['added']['rules']} rules" + (f". Dropped {dropped} rule(s) whose quote was not in the document" if dropped else ""))
        save(st)
    v = present(st)
    v["grow"] = {"note": _grow_note(out, f"From {fname}") + (" Only the first part of the document was read." if truncated else "") + (f" {dropped} rule(s) were dropped because the AI could not back them with a quote from the document." if dropped else ""),
                 "summary": str(res.get("summary", ""))[:300], "basis": "document"}
    return v


class Confirm(BaseModel):
    name: str = ""
    action: str  # confirm | confirm_all | remove
    kind: str = "class"  # class | rule


@app.post("/api/session/{sid}/confirm")
def confirm(sid: str, body: Confirm):
    if body.action not in ("confirm", "confirm_all", "remove"):
        raise HTTPException(400, "unknown action")
    st = load(sid)
    with _lock(sid):
        if not ont.confirm_or_remove(st, body.name, body.action, body.kind):
            raise HTTPException(404, "No such item on the map")
        save(st)
    return present(st)


@app.get("/api/session/{sid}")
def get_session(sid: str):
    return present(load(sid))


@app.delete("/api/session/{sid}")
def delete_session(sid: str):
    p = _path(sid)
    if p.exists():
        p.unlink()
    return {"ok": True}


@app.post("/api/session/{sid}/chat")
def chat(sid: str, body: Msg):
    text = body.message.strip()
    if not text:
        raise HTTPException(400, "empty message")
    with _lock(sid):
        st = load(sid)
        before = {b["id"] for b in ont.summary(st)["badges"] if b["earned"]}
        stage_before = ont.summary(st)["stage"]
        result = interview_turn(st, text[:4000])
        after = ont.summary(st)
        new_badges = [b["name"] for b in after["badges"] if b["earned"] and b["id"] not in before]
        save(st)
    v = present(st)
    v["turn"] = {"added": result["added"], "warnings": result["warnings"], "new_badges": new_badges, "level_up": after["stage"] > stage_before}
    return v


@app.post("/api/session/{sid}/arena")
def arena(sid: str, body: Q):
    with _lock(sid):
        st = load(sid)
        if not st["classes"]:
            raise HTTPException(400, "Build a few things on the map first")
        ctx = {"question": body.question, "classes": list(st["classes"].keys())}
        res = ai("arena", P.arena_system(ont.context_block(st)), [{"role": "user", "content": body.question}], ctx)
        q = ont.add_question(st, body.question, res)
        save(st)
    v = present(st)
    v["question"] = q
    return v


@app.post("/api/session/{sid}/arena/suggest")
def arena_suggest(sid: str):
    st = load(sid)
    res = ai("suggest", P.suggest_system(ont.context_block(st)), [{"role": "user", "content": "Suggest questions."}], {})
    return {"questions": (res.get("questions") or [])[:5]}


@app.post("/api/session/{sid}/arena/{qid}/fix")
def arena_fix(sid: str, qid: str, body: Fix):
    with _lock(sid):
        st = load(sid)
        q = next((x for x in st["questions"] if x["id"] == qid), None)
        if not q or not (0 <= body.gap_index < len(q["gaps"])):
            raise HTTPException(404, "gap not found")
        gap = q["gaps"][body.gap_index]
        if gap["type"] == "missing_thing":
            rule = f"Question: {q['question']}\nGap: {gap['text']}. Add a thing named exactly '{ont.pascal(gap['term'])}' and connect it to the most relevant existing thing(s)."
        elif gap["type"] == "missing_connection":
            rule = f"Question: {q['question']}\nGap: {gap['text']}. Add the most sensible connection (or short chain via an existing thing) between {gap['from']} and {gap['to']}."
        else:
            rule = f"Question: {q['question']}\nGap: {gap['text']}. Add the detail '{gap['name']}' to {gap['of']}."
        ctx = {"gap": gap, "term": gap.get("term", ""), "classes": list(st["classes"].keys())}
        res = ai("fix", P.fix_system(ont.context_block(st), rule), [{"role": "user", "content": "Fix this gap."}], ctx)
        result = ont.apply_delta(st, res.get("delta"), "Question Arena")
        if gap["type"] == "missing_thing":
            want = ont.pascal(gap["term"])
            for c in q["concepts"]:
                if ont.norm(c.get("term")) == ont.norm(gap["term"]) or (c.get("kind") == "detail" and ont.norm(c.get("of")) == ont.norm(gap["term"])):
                    target = ont.find_class(st, want) or (result["new_classes"][0] if result["new_classes"] else None)
                    if target:
                        c["maps_to"] = target
                        if c.get("kind") == "detail":
                            c["of"] = target
        ont.reevaluate_all(st)
        save(st)
    v = present(st)
    v["fix_reply"] = res.get("reply", "")
    return v


@app.post("/api/session/{sid}/doc-guide")
def doc_guide(sid: str):
    with _lock(sid):
        st = load(sid)
        have = [t["label"] for t in st.get("trail", []) if t["step"] == "document"]
        res = ai("docguide", P.docguide_system(ont.context_block(st), st.get("client", ""), st.get("about", ""), st.get("goals"), ont.trail_block(st), have),
                 [{"role": "user", "content": "What should the client upload?"}], {}, max_tokens=2500)
        items = []
        for d in (res.get("documents") or [])[:6]:
            if isinstance(d, dict) and d.get("title"):
                items.append({k: str(d.get(k, ""))[:300] for k in ("title", "why", "look_for", "format", "avoid")})
        if not items:
            raise HTTPException(502, "The AI did not return suggestions. Try again.")
        st["doc_guide"] = {"intro": str(res.get("intro", ""))[:300], "items": items, "excel_tip": str(res.get("excel_tip", ""))[:300], "sig": sig(st)}
        save(st)
    return present(st)


@app.post("/api/session/{sid}/usecases")
def usecases(sid: str):
    with _lock(sid):
        st = load(sid)
        if len(st["classes"]) < 3:
            raise HTTPException(400, "Add a few more things before asking for use cases")
        ctx = {"classes": list(st["classes"].keys())}
        res = ai("usecases", P.usecases_system(ont.context_block(st), st.get("goals"), st.get("client", ""), ont.trail_block(st)),
                 [{"role": "user", "content": "Write the use cases."}], ctx, max_tokens=3000)
        items = []
        for u in (res.get("usecases") or [])[:5]:
            if not isinstance(u, dict) or not u.get("question"):
                continue
            items.append({
                "title": str(u.get("title", ""))[:120], "question": str(u["question"])[:300],
                "today": str(u.get("today", ""))[:300], "with_map": str(u.get("with_map", ""))[:300], "value": str(u.get("value", ""))[:300],
                "needs": [str(n)[:60] for n in (u.get("needs") or []) if isinstance(n, str)][:6],
            })
        if not items:
            raise HTTPException(502, "The AI did not return any use cases. Try again.")
        st["usecases"] = {"items": items, "sig": sig(st)}
        ont.log(st, "use cases", f"Wrote {len(items)} use cases")
        save(st)
    return present(st)


@app.post("/api/session/{sid}/story")
def story(sid: str):
    with _lock(sid):
        st = load(sid)
        if len(st["classes"]) < 3:
            raise HTTPException(400, "Add a few more things before asking for the story")
        res = ai("story", P.story_system(ont.context_block(st), ont.trail_block(st), st.get("goals")), [{"role": "user", "content": "Explain the map."}], {"domain": st["domain"], "classes": list(st["classes"].keys())}, max_tokens=3500)
        res["sig"] = sig(st)
        st["story"] = res
        ont.log(st, "story", "Generated plain-language explanation")
        save(st)
    return present(st)


@app.post("/api/session/{sid}/sample")
def sample(sid: str):
    with _lock(sid):
        st = load(sid)
        if len(st["relationships"]) < 1:
            raise HTTPException(400, "Add some connections first")
        ctx = {"ontology": {"classes": list(st["classes"].keys()), "relationships": st["relationships"]}}
        res = ai("sample", P.sample_system(ont.context_block(st)), [{"role": "user", "content": "Create example data."}], ctx, max_tokens=3500)
        rels = {(r["name"], r["from"], r["to"]) for r in st["relationships"]}
        nodes, ids = [], {}
        for n in (res.get("nodes") or [])[:60]:
            cl = ont.find_class(st, n.get("class"))
            nid = str(n.get("id", ""))
            if cl and nid and nid not in ids:
                ids[nid] = cl
                nodes.append({"id": nid, "class": cl, "label": str(n.get("label", nid))[:40]})
        edges = []
        for e in res.get("edges") or []:
            a, b, r = str(e.get("from")), str(e.get("to")), ont.snake_upper(e.get("rel"))
            if a in ids and b in ids and (r, ids[a], ids[b]) in rels:
                edges.append({"from": a, "to": b, "rel": r})
        st["sample"] = {"nodes": nodes, "edges": edges, "sig": sig(st)}
        ont.log(st, "sample", f"Generated example data: {len(nodes)} items, {len(edges)} links")
        save(st)
    return present(st)


@app.get("/api/session/{sid}/node/{name}")
def node(sid: str, name: str):
    st = load(sid)
    d = ont.node_detail(st, name)
    if not d:
        raise HTTPException(404, "not found")
    return d


@app.post("/api/session/{sid}/challenge")
def challenge(sid: str, body: Challenge):
    with _lock(sid):
        st = load(sid)
        res = ai("challenge", P.challenge_system(ont.context_block(st)), [{"role": "user", "content": body.text[:3000]}], {"classes": list(st["classes"].keys())})
        result = ont.apply_delta(st, res.get("delta"), "Client challenge", overwrite=True)
        ont.reevaluate_all(st)
        save(st)
    v = present(st)
    v["challenge_reply"] = res.get("reply", "")
    v["turn"] = {"added": result["added"], "changed": result["changed"], "removed": result["removed"]}
    return v


@app.get("/api/session/{sid}/export.xlsx")
def export_xlsx(sid: str):
    st = json.loads(json.dumps(load(sid)))
    dr = {k for k, c in st["classes"].items() if c.get("draft")}
    tag = "[Unconfirmed draft from public information] "
    for k in dr:
        st["classes"][k]["description"] = tag + (st["classes"][k].get("description") or "")
    for r in st["relationships"]:
        if r["from"] in dr or r["to"] in dr:
            r["description"] = tag + (r.get("description") or "")
    for p in st["properties"]:
        if p["class"] in dr:
            p["description"] = tag + (p.get("description") or "")
    for r in st["rules"]:
        if r.get("draft"):
            r["text"] = tag + r["text"]
    data = excel.build_workbook(st)
    name = "".join(ch if ch.isalnum() else "_" for ch in st["domain"])[:40] or "ontology"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}_ontology.xlsx"'})


@app.get("/api/session/{sid}/export.json")
def export_json(sid: str):
    st = load(sid)
    name = "".join(ch if ch.isalnum() else "_" for ch in st["domain"])[:40] or "ontology"
    return Response(json.dumps(excel.schema_json(st), indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}_schema.json"'})


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
