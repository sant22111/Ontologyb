"""Offline stand-in for the AI model. ONLY for testing the app without an API key.
It plays a scripted retail-bank-fraud workshop. Real runs use a real model (see llm.py)."""
import re

SCRIPT = [
    # turn 1
    {
        "reply": "Captured customers, accounts and transactions. Next: who or what raises a warning when something looks wrong?",
        "chips": ["A fraud alert system", "A call from the customer", "Staff spot it"],
        "captured": "3 core things: customers, accounts, transactions",
        "delta": {
            "classes": [
                {"name": "Customer", "layer": "Customer", "description": "A person or business that banks with us.", "why": "Every fraud case ends with a customer who is affected.", "example": "Asha Verma, salaried, 6 years with us", "source_quote": "customers with accounts doing transactions"},
                {"name": "Account", "layer": "Money", "description": "A bank account that holds a customer's money.", "why": "Fraud moves money in and out of accounts.", "example": "Savings account ending 4421", "source_quote": "customers with accounts"},
                {"name": "Transaction", "layer": "Money", "description": "A movement of money between accounts.", "why": "Transactions are the evidence we investigate.", "example": "Rs 48,000 transfer at 2:10am", "source_quote": "accounts doing transactions"},
            ],
            "relationships": [
                {"name": "HOLDS", "from": "Customer", "to": "Account", "description": "A customer holds one or more accounts.", "why": "Links people to money.", "source_quote": "customers with accounts"},
                {"name": "DEBITS", "from": "Transaction", "to": "Account", "description": "A transaction takes money out of an account.", "why": "Shows where money came from.", "source_quote": "accounts doing transactions"},
            ],
            "properties": [
                {"class": "Transaction", "name": "amount", "type": "number", "description": "How much money moved."},
                {"class": "Transaction", "name": "timestamp", "type": "date", "description": "When it happened."},
                {"class": "Customer", "name": "kycStatus", "type": "text", "description": "Whether identity checks are complete."},
                {"class": "Customer", "name": "customerSince", "type": "date", "description": "When they joined."},
            ],
            "rules": [],
        },
    },
    # turn 2
    {
        "reply": "Added alerts, investigators and cases. Which devices or channels do customers use to move money?",
        "chips": ["Mobile app and net banking", "UPI and cards", "Branch counter"],
        "captured": "alerts, investigators and cases",
        "delta": {
            "classes": [
                {"name": "FraudAlert", "layer": "Investigation", "description": "A warning raised when a transaction looks suspicious.", "why": "Starting point of every investigation.", "example": "Alert: 5 transfers in 3 minutes", "source_quote": "the system raises an alert"},
                {"name": "Investigator", "layer": "People", "description": "A staff member who reviews alerts.", "why": "Decides whether an alert is real fraud.", "example": "Rahul, fraud desk", "source_quote": "an investigator looks at it"},
                {"name": "Case", "layer": "Investigation", "description": "A file opened to investigate one or more alerts.", "why": "Holds the evidence and the decision.", "example": "Case 2291: mule account ring", "source_quote": "we open a case"},
            ],
            "relationships": [
                {"name": "RAISES", "from": "Transaction", "to": "FraudAlert", "description": "A transaction can trigger an alert.", "why": "Links evidence to warning.", "source_quote": "the system raises an alert"},
                {"name": "OPENS", "from": "FraudAlert", "to": "Case", "description": "An alert can open a case.", "why": "Escalation path.", "source_quote": "we open a case"},
                {"name": "HANDLES", "from": "Investigator", "to": "Case", "description": "An investigator handles a case.", "why": "Shows ownership.", "source_quote": "an investigator looks at it"},
            ],
            "properties": [
                {"class": "FraudAlert", "name": "riskScore", "type": "number", "description": "How suspicious it looks, 0-100."},
                {"class": "FraudAlert", "name": "status", "type": "text", "description": "Open, closed, escalated."},
                {"class": "Case", "name": "outcome", "type": "text", "description": "Confirmed fraud, false alarm, etc."},
                {"class": "Case", "name": "openedOn", "type": "date", "description": "When opened."},
            ],
            "rules": [],
        },
    },
    # turn 3
    {
        "reply": "Added devices and merchants. Now the rules: who has the final say when an investigator and the system disagree?",
        "chips": ["The investigator decides", "The head of fraud decides", "It depends on the amount"],
        "captured": "devices and merchants",
        "delta": {
            "classes": [
                {"name": "Device", "layer": "Channels", "description": "A phone or computer used to log in.", "why": "Shared devices reveal linked accounts.", "example": "Android phone, fingerprint X", "source_quote": "customers log in from phones"},
                {"name": "Merchant", "layer": "Money", "description": "A shop or business that receives payments.", "why": "Some merchants are fraud hotspots.", "example": "Online electronics store", "source_quote": "payments to merchants"},
            ],
            "relationships": [
                {"name": "USES", "from": "Customer", "to": "Device", "description": "A customer uses a device.", "why": "Links people to devices.", "source_quote": "customers log in from phones"},
                {"name": "PAYS", "from": "Transaction", "to": "Merchant", "description": "A transaction pays a merchant.", "why": "Shows where money went.", "source_quote": "payments to merchants"},
            ],
            "properties": [
                {"class": "Device", "name": "deviceFingerprint", "type": "text", "description": "Unique device identity."},
            ],
            "rules": [],
        },
    },
    # turn 4
    {
        "reply": "Captured three rules. Try the 'Test it' tab now with a real question. What else expires or changes over time?",
        "chips": ["Alert thresholds change yearly", "Cases must close in 30 days", "Nothing else"],
        "captured": "3 rules: authority, time and exception",
        "delta": {
            "classes": [],
            "relationships": [],
            "properties": [],
            "rules": [
                {"text": "The head of fraud has the final say when an investigator and the system disagree.", "category": "authority", "applies_to": ["Investigator", "FraudAlert"], "source_quote": "the head of fraud decides"},
                {"text": "A case must be closed within 30 days of opening.", "category": "time", "applies_to": ["Case"], "source_quote": "cases must close in 30 days"},
                {"text": "Transactions under Rs 500 never raise an alert unless a device is shared.", "category": "exception", "applies_to": ["Transaction", "Device"], "source_quote": "small payments are ignored unless"},
            ],
        },
    },
]


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


DRAFT = {
    "summary": "A typical consumer-goods map: products, the distributors and shops that carry them, and the orders and schemes between. Based on how this kind of business usually works.",
    "delta": {
        "classes": [
            {"name": "Product", "layer": "Products", "description": "Something the company makes and sells.", "why": "Everything starts from what is sold.", "example": "A 200 ml hair oil"},
            {"name": "Sku", "layer": "Products", "description": "One sellable pack size or variant of a product.", "why": "Stock and price are tracked per variant.", "example": "200 ml bottle"},
            {"name": "Distributor", "layer": "Channel", "description": "A business that buys from the company and supplies shops.", "why": "Most sales flow through distributors.", "example": "A city distributor"},
            {"name": "Retailer", "layer": "Channel", "description": "A shop that sells to shoppers.", "why": "Where products reach the shopper.", "example": "A neighbourhood store"},
            {"name": "SalesRep", "layer": "People", "description": "A field person who visits shops and takes orders.", "why": "Drives coverage and orders.", "example": "A territory sales officer"},
            {"name": "Order", "layer": "Sales", "description": "A request to buy products.", "why": "Links who bought what.", "example": "A weekly distributor order"},
            {"name": "TradeScheme", "layer": "Sales", "description": "A discount or incentive offered to the trade.", "why": "Trade spend is a large cost.", "example": "Buy 10 get 1 free"},
            {"name": "Region", "layer": "Places", "description": "A sales area such as a state or territory.", "why": "Targets and reports are by area.", "example": "North zone"},
        ],
        "relationships": [
            {"name": "HAS_VARIANT", "from": "Product", "to": "Sku", "description": "A product comes in one or more variants", "why": ""},
            {"name": "SUPPLIES", "from": "Distributor", "to": "Retailer", "description": "A distributor supplies many shops", "why": ""},
            {"name": "VISITS", "from": "SalesRep", "to": "Retailer", "description": "A rep visits shops on a route", "why": ""},
            {"name": "PLACED_BY", "from": "Order", "to": "Retailer", "description": "An order is placed by a shop", "why": ""},
            {"name": "CONTAINS", "from": "Order", "to": "Sku", "description": "An order contains variants", "why": ""},
            {"name": "FULFILLED_BY", "from": "Order", "to": "Distributor", "description": "A distributor fulfils the order", "why": ""},
            {"name": "APPLIES_TO", "from": "TradeScheme", "to": "Sku", "description": "A scheme applies to some variants", "why": ""},
            {"name": "COVERS", "from": "Distributor", "to": "Region", "description": "A distributor covers an area", "why": ""},
        ],
        "properties": [
            {"class": "Sku", "name": "packSize", "type": "text", "description": "Size of the pack"},
            {"class": "Sku", "name": "price", "type": "number", "description": "List price"},
            {"class": "Order", "name": "orderDate", "type": "date", "description": "When it was placed"},
            {"class": "Order", "name": "value", "type": "number", "description": "Total value"},
        ],
    },
}


def respond(task, ctx):
    classes = ctx.get("classes", [])
    if task == "draft":
        import copy
        return copy.deepcopy(DRAFT)
    if task == "interview" and ctx.get("drafts") and ctx.get("turn", 0) == 0:
        return {"reply": "I prepared a starting draft from public information. It has things like Product, Distributor and Retailer. Do those look right for you?",
                "chips": ["Yes, those are right", "Mostly, but we differ", "Not really"], "captured": "", "delta": {}}
    if task == "interview":
        turn = ctx.get("turn", 0)
        if turn == 0:
            return {
                "reply": "Welcome! Let's map your world together. In a sentence or two: what does your team do day to day, and who or what do you deal with most?",
                "chips": ["We investigate suspicious transactions", "We review contracts and rulings", "I'm not sure where to start"],
                "captured": "",
                "delta": {},
            }
        if turn <= len(SCRIPT):
            return SCRIPT[turn - 1]
        return {"reply": "Anything still missing or wrong on the map? If not, try more questions in the Test it tab.", "chips": ["Looks complete", "Something is missing"], "captured": "", "delta": {}}
    if task == "arena":
        q = ctx.get("question", "")
        nq = _norm(q)
        concepts, hits = [], []
        for c in classes:
            if _norm(c) in nq or (_norm(c).rstrip("s") in nq and len(_norm(c)) > 3):
                hits.append(c)
                concepts.append({"term": c, "kind": "thing", "maps_to": c, "of": None})
        unknown = []
        for w in ("regulator", "branch", "penalty", "complaint", "ombudsman"):
            if w in nq:
                unknown.append(w)
                concepts.append({"term": w.title(), "kind": "thing", "maps_to": None, "of": None})
        rel = [{"from": hits[i], "to": hits[i + 1], "meaning": "linked in the question"} for i in range(len(hits) - 1)]
        return {"concepts": concepts, "relations_needed": rel, "answer_plan": "Follow the connections between the things the question mentions."}
    if task == "fix":
        term = ctx.get("term") or ctx.get("gap_text") or "NewThing"
        name = "".join(w.capitalize() for w in re.sub(r"[^a-zA-Z ]", " ", term).split()) or "NewThing"
        gap = ctx.get("gap", {})
        if gap.get("type") == "missing_connection":
            return {"reply": f"Connected {gap['from']} and {gap['to']}.", "delta": {"relationships": [{"name": "RELATES_TO", "from": gap["from"], "to": gap["to"], "description": f"{gap['from']} relates to {gap['to']}.", "why": "Needed to answer a real question.", "source_quote": ""}]}}
        if gap.get("type") == "missing_detail":
            return {"reply": f"Added the detail {gap['name']}.", "delta": {"properties": [{"class": gap["of"], "name": gap["name"], "type": "text", "description": "Added from a test question."}]}}
        anchor = classes[0] if classes else None
        d = {"classes": [{"name": name, "layer": "Added", "description": f"{name} (added from a test question).", "why": "A real question needed it.", "example": "", "source_quote": ""}]}
        if anchor:
            d["relationships"] = [{"name": "RELATES_TO", "from": name, "to": anchor, "description": f"{name} relates to {anchor}.", "why": "Keeps the map connected.", "source_quote": ""}]
        return {"reply": f"Added {name} and connected it.", "delta": d}
    if task == "challenge":
        return {"reply": "Noted. (mock mode makes no changes)", "delta": {}}
    if task == "story":
        return {
            "headline": f"A map of {ctx.get('domain', 'your business')} that people and AI can both follow.",
            "one_minute": "Customers hold accounts; money moves in transactions; unusual transactions raise alerts; investigators open cases. Rules say who decides and how fast.",
            "sections": [{"title": "The main things", "body": "These are the things your team talks about every day."}, {"title": "How they connect", "body": "Each connection is a sentence your team already says out loud."}],
            "design_choices": [{"choice": "Transactions are kept as their own thing", "why": "Investigators open a transaction to see evidence.", "alternative": "Show them only as links between accounts"}],
            "unlocks": ["Which customers share a device with a flagged account?"],
            "watch_outs": ["Mock mode: this text is a placeholder."],
        }
    if task == "sample":
        ont = ctx.get("ontology", {})
        nodes, edges, by = [], [], {}
        for c in ont.get("classes", []):
            by[c] = []
            for i in range(2):
                nid = f"{c}{i}"
                nodes.append({"id": nid, "class": c, "label": f"{c} {i + 1}"})
                by[c].append(nid)
        for r in ont.get("relationships", []):
            a, b = by.get(r["from"], []), by.get(r["to"], [])
            if a and b:
                edges.append({"from": a[0], "to": b[0], "rel": r["name"]})
                edges.append({"from": a[-1], "to": b[-1], "rel": r["name"]})
        return {"nodes": nodes, "edges": edges}
    if task == "usecases":
        cl = (classes + ["Thing A", "Thing B", "Thing C"])[:4]
        return {"usecases": [
            {"title": f"Trace {cl[0]} to {cl[-1]}", "question": f"Which {cl[-1]} is linked to a given {cl[0]}?",
             "today": "Usually answered by asking several teams and joining files by hand.", "with_map": "Follow the connections from one to the other.",
             "value": "Faster, consistent answers.", "needs": cl[:3]},
            {"title": "Spot what is missing", "question": f"Which {cl[0]} has no {cl[1]} recorded?",
             "today": "Found by manual checks.", "with_map": "The gap shows up as a missing connection.", "value": "Fewer surprises.", "needs": cl[:2]},
            {"title": "Cover a thing the map lacks", "question": "Which deadline is coming up next?",
             "today": "Tracked in separate calendars.", "with_map": "Deadlines hang off the things they apply to.", "value": "No missed dates.", "needs": [cl[0], "Deadline"]},
        ]}
    if task == "suggest":
        return {"questions": [
            "Which customers share a device with an account that raised an alert?",
            "Which investigator handled the most cases last month?",
            "Which regulator penalty applies to a late case?",
            "Which merchants received money from accounts with alerts?",
            "What is the complaint history of a customer?",
        ]}
    return {}
