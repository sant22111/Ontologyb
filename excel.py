"""Excel export, same spirit as the tax ontology workbook: one tab per kind of thing."""
import io
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import ontology as ont

BLUE = "00338D"
LIGHT = "EAF0FA"
thin = Side(style="thin", color="D5DCE8")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def _sheet(wb, title, headers, rows, widths):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
        c.fill = PatternFill("solid", fgColor=BLUE)
        c.alignment = Alignment(vertical="center", wrap_text=True)
        c.border = BORDER
    for r in rows:
        ws.append(list(r))
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
            c.border = BORDER
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    ws.row_dimensions[1].height = 24
    return ws


def build_workbook(st) -> bytes:
    s = ont.summary(st)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 90
    ws["A1"] = f"Business map: {st['domain']}"
    ws["A1"].font = Font(bold=True, size=18, color=BLUE)
    ws["A2"] = f"{('Client: ' + st['client'] + ' · ') if st.get('client') else ''}Built in a guided workshop · {st['updated'][:10]} · map strength {s['score']}/100"
    ws["A2"].font = Font(italic=True, color="666666")
    rows = [
        ("Things (classes)", len(st["classes"])), ("Connections (relationships)", len(st["relationships"])),
        ("Details (properties)", len(st["properties"])), ("Rules", len(st["rules"])),
        ("Questions tested", len(st["questions"])),
        ("Answerable questions", sum(1 for q in st["questions"] if q["status"] == "yes")),
        ("Open threads (described later)", len(s["stubs"])),
    ]
    r = 4
    for k, v in rows:
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, v).alignment = Alignment(horizontal="left")
        r += 1
    r += 1
    ws.cell(r, 1, "Strength breakdown").font = Font(bold=True, color=BLUE, size=12)
    r += 1
    for k, v in s["breakdown"].items():
        ws.cell(r, 1, k)
        ws.cell(r, 2, v).alignment = Alignment(horizontal="left")
        r += 1
    r += 1
    if st.get("story"):
        ws.cell(r, 1, "In one minute").font = Font(bold=True, color=BLUE, size=12)
        r += 1
        c = ws.cell(r, 1, st["story"].get("one_minute", ""))
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 90
        r += 2
    ws.cell(r, 1, "How to read this workbook").font = Font(bold=True, color=BLUE, size=12)
    r += 1
    guide = [("Classes", "The things your business deals with, grouped in layers."), ("Relationships", "How things connect, as readable sentences."),
             ("Properties", "Details held about each thing."), ("Rules", "Authority, time, exception and compliance rules."),
             ("Test Questions", "Real questions tried against the map and how each is answered."),
             ("Traceability", "Every element tied back to the words that created it."), ("Change Log", "What changed and when.")]
    for k, v in guide:
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, v)
        r += 1

    classes = list(st["classes"].values())
    _sheet(wb, "Classes", ["Class", "Layer", "Parent", "Description", "Why it matters here", "Example", "Heard in", "Client's words", "Status"],
           [(c["name"], c.get("layer", ""), c.get("parent", ""), c.get("description", ""), c.get("why", ""), c.get("example", ""),
             c.get("source", ""), c.get("source_quote", ""), "Open thread" if c.get("stub") else "Described") for c in classes],
           [22, 16, 16, 44, 44, 34, 20, 40, 14])
    _sheet(wb, "Relationships", ["Relationship", "From", "To", "In plain words", "Why it matters", "Heard in", "Client's words"],
           [(r["name"], r["from"], r["to"], r.get("description", ""), r.get("why", ""), r.get("source", ""), r.get("source_quote", "")) for r in st["relationships"]],
           [22, 20, 20, 48, 44, 20, 40])
    _sheet(wb, "Properties", ["Class", "Property", "Type", "Description", "Heard in"],
           [(p["class"], p["name"], p.get("type", ""), p.get("description", ""), p.get("source", "")) for p in st["properties"]], [22, 24, 12, 52, 20])
    _sheet(wb, "Rules", ["ID", "Category", "Rule", "Applies to", "Heard in", "Client's words"],
           [(r["id"], r["category"], r["text"], ", ".join(r.get("applies_to", [])), r.get("source", ""), r.get("source_quote", "")) for r in st["rules"]],
           [8, 14, 64, 30, 20, 40])
    layers = defaultdict(list)
    for c in classes:
        layers[c.get("layer", "General")].append(c["name"])
    _sheet(wb, "Layers", ["Layer", "Number of classes", "Classes"], [(k, len(v), ", ".join(v)) for k, v in sorted(layers.items())], [22, 16, 90])
    label = {"yes": "Answerable", "partial": "Partly", "no": "Not yet"}
    _sheet(wb, "Test Questions", ["Question", "Result", "Path through the map", "Gaps", "Tested"],
           [(q["question"], label.get(q["status"], q["status"]), "; ".join(x["text"] for x in q.get("steps", [])), "; ".join(g["text"] for g in q.get("gaps", [])), q["ts"][:16].replace("T", " ")) for q in st["questions"]],
           [52, 14, 56, 56, 18])
    trace = []
    for c in classes:
        trace.append(("Class", c["name"], c.get("source", ""), c.get("source_quote", ""), c.get("why", "")))
    for r in st["relationships"]:
        trace.append(("Relationship", f"{r['from']} {r['name']} {r['to']}", r.get("source", ""), r.get("source_quote", ""), r.get("why", "")))
    for r in st["rules"]:
        trace.append(("Rule", r["id"] + " " + r["text"][:60], r.get("source", ""), r.get("source_quote", ""), ""))
    _sheet(wb, "Traceability", ["Type", "Element", "Heard in", "Client's words", "Justification"], trace, [14, 44, 22, 52, 52])
    _sheet(wb, "Change Log", ["When (UTC)", "Action", "Detail"], [(x["ts"][:16].replace("T", " "), x["action"], x["detail"]) for x in st["changelog"]], [20, 16, 90])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def schema_json(st):
    """Same shape idea as the tax schema.json: classes, object properties, data properties, rules."""
    return {
        "domain_name": st["domain"],
        "classes": [{"name": c["name"], "comment": c.get("description", ""), "parents": [c["parent"]] if c.get("parent") else [], "layer": c.get("layer", "")} for c in st["classes"].values()],
        "object_properties": [{"name": r["name"], "domain": [r["from"]], "range": [r["to"]], "comment": r.get("description", "")} for r in st["relationships"]],
        "data_properties": [{"name": p["name"], "domain": p["class"], "type": p.get("type", "text"), "comment": p.get("description", "")} for p in st["properties"]],
        "rules": [{"id": r["id"], "category": r["category"], "text": r["text"], "applies_to": r.get("applies_to", [])} for r in st["rules"]],
    }
