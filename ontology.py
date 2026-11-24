"""Core engine: the map's data, merging new knowledge in, scoring, badges, and
the deterministic check behind the Question Arena. No AI calls in here."""
import re
import uuid
from collections import deque, defaultdict
from datetime import datetime

STAGE_NAMES = {1: "Your world", 2: "Connect the dots", 3: "Rules of the game", 4: "Test it", 5: "Complete"}

TEMPLATES = {
    "banking_fraud": {
        "label": "Banking fraud and money mules",
        "note": "Starter: Customer, Account, Transaction, FraudAlert, Case were pre-loaded from a banking fraud template. Confirm or adapt them with the client rather than re-asking.",
        "classes": [
            ("Customer", "Customer", "A person or business that banks with us."),
            ("Account", "Money", "A bank account holding a customer's money."),
            ("Transaction", "Money", "A movement of money between accounts."),
            ("FraudAlert", "Investigation", "A warning raised on a suspicious transaction."),
            ("Case", "Investigation", "A file opened to investigate alerts."),
        ],
        "rels": [("HOLDS", "Customer", "Account"), ("DEBITS", "Transaction", "Account"), ("RAISES", "Transaction", "FraudAlert"), ("OPENS", "FraudAlert", "Case")],
    },
    "telecom_regulatory": {
        "label": "Telecom regulatory compliance",
        "note": "Starter: Regulation, LicenceCondition, Operator, Ruling were pre-loaded from a telecom regulatory template. Confirm or adapt them with the client.",
        "classes": [
            ("Regulation", "Law", "A rule issued by a regulator."),
            ("LicenceCondition", "Law", "A condition attached to an operating licence."),
            ("Operator", "Organisations", "A telecom company."),
            ("Ruling", "Law", "A decision by a tribunal or court."),
        ],
        "rels": [("BINDS", "Regulation", "Operator"), ("IMPOSES", "LicenceCondition", "Operator"), ("INTERPRETS", "Ruling", "Regulation")],
    },
    "direct_tax": {
        "label": "Direct tax research",
        "note": "Starter: Section, Rule, Circular, CaseLaw, Issue were pre-loaded from a direct tax template. Confirm or adapt them with the client.",
        "classes": [
            ("Section", "Law", "A provision of the Act."),
            ("Circular", "Law", "Guidance issued by the tax authority."),
            ("CaseLaw", "Judgments", "A court or tribunal judgment."),
            ("Issue", "Research", "A legal question that arises on facts."),
        ],
        "rels": [("CLARIFIES", "Circular", "Section"), ("INTERPRETS", "CaseLaw", "Section"), ("DECIDES", "CaseLaw", "Issue")],
    },
}


def now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def pascal(s):
    s = re.sub(r"[^0-9a-zA-Z ]+", " ", str(s or "")).strip()
    return "".join(w[:1].upper() + w[1:] for w in s.split())


def camel(s):
    parts = re.sub(r"[^0-9a-zA-Z ]+", " ", str(s or "")).split()
    if not parts:
        return ""
    return parts[0][:1].lower() + parts[0][1:] + "".join(w[:1].upper() + w[1:] for w in parts[1:])


def snake_upper(s):
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(s or "")).strip("_")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    return s.upper()


def new_state(domain, template=None, owner="", client="", about=""):
    st = {
        "id": uuid.uuid4().hex[:10],
        "domain": domain.strip() or "My business area",
        "owner": owner.strip(),
        "client": client.strip()[:80],
        "about": about.strip()[:1200],
        "created": now(),
        "updated": now(),
        "template": template if template in TEMPLATES else None,
        "messages": [],
        "classes": {},
        "relationships": [],
        "properties": [],
        "rules": [],
        "questions": [],
        "draft": None,
        "story": None,
        "sample": None,
        "changelog": [],
        "badges_seen": [],
    }
    if st["template"]:
        t = TEMPLATES[st["template"]]
        for name, layer, desc in t["classes"]:
            st["classes"][name] = {
                "name": name, "layer": layer, "parent": "", "description": desc, "why": "From the starter template - confirm with the client.",
                "example": "", "source_quote": "", "source": "Starter template", "stub": False,
            }
        for name, a, b in t["rels"]:
            st["relationships"].append({
                "name": name, "from": a, "to": b, "description": f"{a} {name.lower().replace('_', ' ')} {b}.",
                "why": "From the starter template - confirm with the client.", "source_quote": "", "source": "Starter template",
            })
        log(st, "template", f"Started from template: {t['label']}")
    return st


def log(st, action, detail):
    st["changelog"].append({"ts": now(), "action": action, "detail": detail})
    st["updated"] = now()


def find_class(st, name):
    n = norm(name)
    if not n:
        return None
    for k in st["classes"]:
        if norm(k) == n:
            return k
    return None


def _dicts(x):
    """Models sometimes return strings or nulls inside lists; keep only objects."""
    return [i for i in (x or []) if isinstance(i, dict)] if isinstance(x, list) else []


def _clip(s, n=240):
    return str(s or "").strip()[:n]


def apply_delta(st, delta, source, overwrite=False):
    """Merge what the AI learned into the map. Returns counts and warnings."""
    delta = delta if isinstance(delta, dict) else {}
    added = {"classes": 0, "relationships": 0, "properties": 0, "rules": 0}
    changed = 0
    removed = 0
    warnings = []
    new_class_names = []

    # --- removals
    rem = delta.get("remove") if isinstance(delta.get("remove"), dict) else {}
    for n in rem.get("classes", []) or []:
        k = find_class(st, n if isinstance(n, str) else (n or {}).get("name"))
        if k:
            del st["classes"][k]
            st["relationships"] = [r for r in st["relationships"] if r["from"] != k and r["to"] != k]
            st["properties"] = [p for p in st["properties"] if p["class"] != k]
            for r in st["rules"]:
                r["applies_to"] = [a for a in r.get("applies_to", []) if a != k]
            removed += 1
    for n in rem.get("relationships", []) or []:
        key = snake_upper(n if isinstance(n, str) else n.get("name", ""))
        before = len(st["relationships"])
        st["relationships"] = [r for r in st["relationships"] if r["name"] != key]
        removed += before - len(st["relationships"])
    for n in rem.get("rules", []) or []:
        before = len(st["rules"])
        st["rules"] = [r for r in st["rules"] if r["id"] != n and norm(r["text"]) != norm(n)]
        removed += before - len(st["rules"])

    # --- renames
    for r in _dicts(delta.get("rename")):
        old, new = find_class(st, r.get("from")), pascal(r.get("to"))
        if old and new and not find_class(st, new):
            c = st["classes"].pop(old)
            c["name"] = new
            st["classes"][new] = c
            for rel in st["relationships"]:
                rel["from"] = new if rel["from"] == old else rel["from"]
                rel["to"] = new if rel["to"] == old else rel["to"]
            for p in st["properties"]:
                p["class"] = new if p["class"] == old else p["class"]
            for ru in st["rules"]:
                ru["applies_to"] = [new if a == old else a for a in ru.get("applies_to", [])]
            for c2 in st["classes"].values():
                if c2.get("parent") == old:
                    c2["parent"] = new
            changed += 1

    def ensure_class(name, why_text):
        k = find_class(st, name)
        if k:
            return k
        nm = pascal(name)
        if not nm:
            return None
        st["classes"][nm] = {
            "name": nm, "layer": "Unsorted", "parent": "", "description": "Mentioned but not described yet.", "why": why_text,
            "example": "", "source_quote": "", "source": source, "stub": True,
        }
        added["classes"] += 1
        new_class_names.append(nm)
        warnings.append(f"'{nm}' was mentioned but not described yet")
        return nm

    # --- classes
    for c in _dicts(delta.get("classes")):
        name = pascal(c.get("name"))
        if not name:
            continue
        k = find_class(st, name)
        fields = {
            "layer": _clip(c.get("layer"), 40), "description": _clip(c.get("description")), "why": _clip(c.get("why")),
            "example": _clip(c.get("example")), "source_quote": _clip(c.get("source_quote"), 200),
            "parent": pascal(c.get("parent")) if c.get("parent") else "",
        }
        if k:
            cur = st["classes"][k]
            was_stub = cur.get("stub")
            for f, v in fields.items():
                if v and (overwrite or was_stub or not cur.get(f) or cur.get(f) in ("Unsorted",)):
                    if cur.get(f) != v:
                        cur[f] = v
                        changed += 1
            if was_stub and fields["description"]:
                cur["stub"] = False
                cur["source"] = source
        else:
            st["classes"][name] = {"name": name, **fields, "source": source, "stub": False}
            if not st["classes"][name]["layer"]:
                st["classes"][name]["layer"] = "General"
            added["classes"] += 1
            new_class_names.append(name)

    # --- client confirms drafted items
    cf = delta.get("confirm") if isinstance(delta.get("confirm"), dict) else {}
    for n in cf.get("classes", []) or []:
        k = find_class(st, n if isinstance(n, str) else (n or {}).get("name"))
        if k and st["classes"][k].get("draft"):
            st["classes"][k]["draft"] = False
            st["classes"][k]["source"] = source
            changed += 1

    # --- relationships
    for r in _dicts(delta.get("relationships")):
        name = snake_upper(r.get("name"))
        a = ensure_class(r.get("from"), "Needed to describe a connection.")
        b = ensure_class(r.get("to"), "Needed to describe a connection.")
        if not (name and a and b):
            continue
        ex = next((x for x in st["relationships"] if x["name"] == name and x["from"] == a and x["to"] == b), None)
        fields = {"description": _clip(r.get("description")), "why": _clip(r.get("why")), "source_quote": _clip(r.get("source_quote"), 200)}
        if ex:
            for f, v in fields.items():
                if v and (overwrite or not ex.get(f)):
                    if ex.get(f) != v:
                        ex[f] = v
                        changed += 1
        else:
            st["relationships"].append({"name": name, "from": a, "to": b, **fields, "source": source})
            added["relationships"] += 1

    # --- properties
    for p in _dicts(delta.get("properties")):
        cls = ensure_class(p.get("class"), "Needed to hold a detail.")
        nm = camel(p.get("name"))
        if not (cls and nm):
            continue
        ex = next((x for x in st["properties"] if x["class"] == cls and norm(x["name"]) == norm(nm)), None)
        if ex:
            if overwrite and p.get("description"):
                ex["description"] = _clip(p.get("description"))
                ex["type"] = _clip(p.get("type"), 20) or ex["type"]
                changed += 1
            continue
        st["properties"].append({"class": cls, "name": nm, "type": _clip(p.get("type"), 20) or "text", "description": _clip(p.get("description")), "source": source})
        added["properties"] += 1

    # --- rules
    for r in _dicts(delta.get("rules")):
        text = _clip(r.get("text"), 400)
        if not text or any(norm(x["text"]) == norm(text) for x in st["rules"]):
            continue
        applies = []
        for a in r.get("applies_to", []) or []:
            k = ensure_class(a, "Needed to describe a rule.")
            if k:
                applies.append(k)
        cat = (r.get("category") or "business").lower()
        if cat not in ("authority", "time", "exception", "compliance", "business"):
            cat = "business"
        st["rules"].append({"id": f"R{len(st['rules']) + 1:02d}", "text": text, "category": cat, "applies_to": applies,
                            "source_quote": _clip(r.get("source_quote"), 200), "source": source})
        added["rules"] += 1

    parts = [f"{v} {k}" for k, v in added.items() if v]
    if changed:
        parts.append(f"{changed} reworded")
    if removed:
        parts.append(f"{removed} removed")
    if parts:
        log(st, source, "Added/changed: " + ", ".join(parts))
    return {"added": added, "changed": changed, "removed": removed, "warnings": warnings, "new_classes": new_class_names}


# ---------------------------------------------------------------- scoring
def mark_draft(st):
    """Everything added by the research step is an unconfirmed guess until the client says so."""
    for c in st["classes"].values():
        if c.get("source") == "draft":
            c["draft"] = True
    for r in st["relationships"]:
        if r.get("source") == "draft":
            r["draft"] = True
    for p in st["properties"]:
        if p.get("source") == "draft":
            p["draft"] = True


def confirmed_view(st):
    """Score only what the client has confirmed. A drafted link or detail counts once its things are confirmed."""
    if not any(c.get("draft") for c in st["classes"].values()):
        return st
    cl = {k: v for k, v in st["classes"].items() if not v.get("draft")}
    return {**st, "classes": cl,
            "relationships": [r for r in st["relationships"] if r["from"] in cl and r["to"] in cl],
            "properties": [p for p in st["properties"] if p["class"] in cl]}


def confirm_or_remove(st, name, action):
    k = find_class(st, name)
    if not k and action != "confirm_all":
        return False
    if action == "confirm":
        st["classes"][k]["draft"] = False
        st["classes"][k]["source"] = "Confirmed by the client"
        log(st, "confirm", f"Client confirmed '{k}'")
        return True
    if action == "confirm_all":
        n = 0
        for c in st["classes"].values():
            if c.get("draft"):
                c["draft"] = False
                c["source"] = "Confirmed by the client"
                n += 1
        log(st, "confirm", f"Client confirmed {n} drafted things")
        return True
    apply_delta(st, {"remove": {"classes": [k]}}, "Removed by the client")
    return True


def degree_map(st):
    deg = defaultdict(int)
    for r in st["relationships"]:
        deg[r["from"]] += 1
        deg[r["to"]] += 1
    return deg


def question_credit(st):
    qs = st["questions"]
    if not qs:
        return 0.0, 0
    credit = sum(1.0 if q["status"] == "yes" else 0.5 if q["status"] == "partial" else 0.0 for q in qs)
    return credit / len(qs), len(qs)


def compute_score(st):
    classes = st["classes"]
    n = len(classes)
    deg = degree_map(st)
    connected = (sum(1 for k in classes if deg.get(k, 0) > 0) / n) if n else 0.0
    detailed = 0.0
    if n:
        cnt = defaultdict(int)
        for p in st["properties"]:
            cnt[p["class"]] += 1
        detailed = sum(1 for k in classes if cnt.get(k, 0) >= 2) / n
    traced_items = list(classes.values()) + st["relationships"] + st["rules"]
    traced = (sum(1 for x in traced_items if x.get("source_quote")) / len(traced_items)) if traced_items else 0.0
    ratio, nq = question_credit(st)
    tested = min(nq / 3, 1.0) * 0.5 + ratio * 0.5 if nq else 0.0
    b = {
        "Things found": round(min(n / 10, 1.0) * 20, 1),
        "Details": round(detailed * 15, 1),
        "Connected": round(connected * 20, 1),
        "Rules": round(min(len(st["rules"]) / 4, 1.0) * 15, 1),
        "Tested with real questions": round(tested * 20, 1),
        "Traced to your words": round(traced * 10, 1),
    }
    total = int(round(sum(b.values())))
    return total, b, connected, detailed


BADGE_DEFS = [
    ("core", "Found your core things", "Describe 6 or more things your business deals with"),
    ("connect", "Connected the dots", "6+ connections and almost every thing linked"),
    ("detail", "Detail oriented", "Most things have 2 or more details"),
    ("rules", "Rule keeper", "Capture 3 or more rules"),
    ("time", "Time traveller", "Capture a rule about time (expiry, deadline, versions)"),
    ("authority", "Knows who decides", "Capture a rule about authority or priority"),
    ("exception", "Exception hunter", "Capture an exception to a rule"),
    ("tested", "Question crusher", "Test 3 questions and have most of them answerable"),
]


def compute_badges(st, connected, detailed):
    n = len(st["classes"])
    cats = {r["category"] for r in st["rules"]}
    ratio, nq = question_credit(st)
    cond = {
        "core": n >= 6,
        "connect": len(st["relationships"]) >= 6 and connected >= 0.9,
        "detail": n >= 4 and detailed >= 0.6,
        "rules": len(st["rules"]) >= 3,
        "time": "time" in cats,
        "authority": "authority" in cats,
        "exception": "exception" in cats,
        "tested": nq >= 3 and ratio >= 0.7,
    }
    return [{"id": i, "name": nm, "hint": h, "earned": bool(cond[i])} for i, nm, h in BADGE_DEFS]


def compute_stage(st, connected):
    n = len(st["classes"])
    ratio, nq = question_credit(st)
    stage = 1
    if n >= 6:
        stage = 2
    if stage == 2 and connected >= 0.9 and len(st["relationships"]) >= 5:
        stage = 3
    if stage == 3 and len(st["rules"]) >= 3:
        stage = 4
    if stage == 4 and nq >= 3 and ratio >= 0.6:
        stage = 5
    return stage


def summary(st):
    cs = confirmed_view(st)
    score, breakdown, connected, detailed = compute_score(cs)
    badges = compute_badges(cs, connected, detailed)
    stage = compute_stage(cs, connected)
    stubs = [k for k, v in st["classes"].items() if v.get("stub")]
    orphans = [k for k in st["classes"] if degree_map(st).get(k, 0) == 0]
    return {"score": score, "breakdown": breakdown, "badges": badges, "stage": stage, "stage_name": STAGE_NAMES[stage],
            "stubs": stubs, "orphans": orphans}


def context_block(st, max_chars=6000):
    lines = ["THINGS:"]
    for k, c in st["classes"].items():
        tag = " [not described yet]" if c.get("stub") else ""
        if c.get("draft"):
            tag += " [DRAFT, not confirmed by the client]"
        props = ", ".join(p["name"] for p in st["properties"] if p["class"] == k)
        lines.append(f"- {k} ({c.get('layer', '')}): {c.get('description', '')}{tag}" + (f" | details: {props}" if props else ""))
    lines.append("CONNECTIONS:")
    for r in st["relationships"]:
        lines.append(f"- {r['from']} -{r['name']}-> {r['to']}")
    lines.append("RULES:")
    for r in st["rules"]:
        lines.append(f"- [{r['category']}] {r['text']}")
    out = "\n".join(lines)
    return out[:max_chars] if len(out) > max_chars else out


# ---------------------------------------------------------------- arena
def _adjacency(st):
    adj = defaultdict(list)
    for r in st["relationships"]:
        adj[r["from"]].append((r["to"], r, True))
        adj[r["to"]].append((r["from"], r, False))
    return adj


def shortest_path(st, a, b, max_depth=5):
    if a == b:
        return []
    adj = _adjacency(st)
    seen = {a}
    dq = deque([(a, [])])
    while dq:
        cur, path = dq.popleft()
        if len(path) >= max_depth:
            continue
        for nxt, rel, fwd in adj[cur]:
            if nxt in seen:
                continue
            step = path + [(cur, rel, nxt, fwd)]
            if nxt == b:
                return step
            seen.add(nxt)
            dq.append((nxt, step))
    return None


def evaluate_question(st, q):
    """q has 'concepts' and 'relations_needed' (from the AI). Everything else is deterministic."""
    gaps, nodes, edges, steps = [], set(), set(), []
    resolved = []
    for c in q.get("concepts", []):
        term = c.get("term", "")
        if c.get("kind") == "detail":
            cl = find_class(st, c.get("of") or "")
            if not cl:
                gaps.append({"type": "missing_thing", "term": c.get("of") or term, "text": f"The map has no thing for '{c.get('of') or term}'"})
                continue
            nodes.add(cl)
            resolved.append(cl)
            has = any(p["class"] == cl and (norm(p["name"]) in norm(term) or norm(term) in norm(p["name"])) for p in st["properties"])
            if not has:
                gaps.append({"type": "missing_detail", "of": cl, "name": camel(term), "text": f"'{cl}' has no detail called '{term}'"})
        else:
            cl = find_class(st, c.get("maps_to") or "") or find_class(st, term)
            if not cl:
                gaps.append({"type": "missing_thing", "term": term, "text": f"The map has no thing called '{term}'"})
            else:
                nodes.add(cl)
                resolved.append(cl)
    pairs = []
    for r in q.get("relations_needed", []):
        a, b = find_class(st, r.get("from")), find_class(st, r.get("to"))
        if a and b and a != b:
            pairs.append((a, b))
    if not pairs:
        uniq = list(dict.fromkeys(resolved))
        pairs = [(uniq[i], uniq[i + 1]) for i in range(len(uniq) - 1)]
    for a, b in pairs:
        p = shortest_path(st, a, b)
        if p is None:
            if not any(g.get("type") == "missing_connection" and {g["from"], g["to"]} == {a, b} for g in gaps):
                gaps.append({"type": "missing_connection", "from": a, "to": b, "text": f"Nothing connects '{a}' to '{b}' yet"})
        else:
            for cur, rel, nxt, fwd in p:
                nodes.update([cur, nxt])
                edges.add(f"{rel['name']}|{rel['from']}|{rel['to']}")
                steps.append({"from": cur, "rel": rel["name"], "to": nxt, "forward": fwd,
                              "text": f"{cur} —{rel['name']}→ {nxt}" if fwd else f"{cur} ←{rel['name']}— {nxt}"})
    if not resolved:
        status = "no"
    elif gaps:
        status = "partial"
    else:
        status = "yes"
    # dedupe steps
    seen, uniq_steps = set(), []
    for s in steps:
        k = (s["from"], s["rel"], s["to"])
        if k not in seen:
            seen.add(k)
            uniq_steps.append(s)
    return {"status": status, "gaps": gaps, "nodes": sorted(nodes), "edges": sorted(edges), "steps": uniq_steps}


def add_question(st, question, ai):
    q = {
        "id": uuid.uuid4().hex[:8], "question": question.strip(), "ts": now(),
        "concepts": ai.get("concepts", []) or [], "relations_needed": ai.get("relations_needed", []) or [],
        "answer_plan": ai.get("answer_plan", ""),
    }
    q.update(evaluate_question(st, q))
    st["questions"].append(q)
    log(st, "arena", f"Tested: {q['question'][:80]} → {q['status']}")
    return q


def reevaluate_all(st):
    for q in st["questions"]:
        q.update(evaluate_question(st, q))


# ---------------------------------------------------------------- details
def node_detail(st, name):
    k = find_class(st, name)
    if not k:
        return None
    c = st["classes"][k]
    out = [r for r in st["relationships"] if r["from"] == k]
    inc = [r for r in st["relationships"] if r["to"] == k]
    props = [p for p in st["properties"] if p["class"] == k]
    rules = [r for r in st["rules"] if k in r.get("applies_to", [])]
    qs = [{"id": q["id"], "question": q["question"], "status": q["status"]} for q in st["questions"] if k in q.get("nodes", [])]
    return {"class": c, "outgoing": out, "incoming": inc, "properties": props, "rules": rules, "questions": qs}


def view(st, include_messages=True):
    s = summary(st)
    v = {
        "id": st["id"], "domain": st["domain"], "owner": st.get("owner", ""), "client": st.get("client", ""), "about": st.get("about", ""), "created": st["created"], "updated": st["updated"],
        "template": st["template"], "classes": list(st["classes"].values()), "relationships": st["relationships"],
        "properties": st["properties"], "rules": st["rules"], "questions": st["questions"], "story": st["story"],
        "sample": st["sample"], "draft": st.get("draft"), "changelog": st["changelog"][-60:], **s,
        "counts": {"things": len(st["classes"]), "connections": len(st["relationships"]), "details": len(st["properties"]),
                   "rules": len(st["rules"]), "questions": len(st["questions"])},
    }
    if include_messages:
        v["messages"] = st["messages"]
    return v
