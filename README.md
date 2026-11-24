# Business Map Studio (Ontology Studio)

A guided, game-like tool that lets a department or client build an ontology without knowing what one is.
They answer friendly questions, watch a live map grow, test it with their own questions, and download an Excel workbook.
The word "ontology" is only revealed at the end.

## Run it
    cp .env.example .env      # add ONE model key; leave empty for demo mode
    ./run.sh                  # Windows: run.bat
    open http://127.0.0.1:8100

Demo mode (no key) plays a scripted bank-fraud workshop so you can see every screen. Real use needs a model key.

## What the client does
1. **Interview**: plain-language questions, one at a time, with click-to-answer chips. Five levels: Your world, Connect the dots, Rules of the game, Test it, Complete.
2. **Live map**: every answer adds things and connections. Map strength (0-100) and badges track progress.
3. **Test it (Question Arena)**: type real questions. The map shows the path that would answer each, or the gap. "Add to map" fixes a gap.
4. **Explain it**: plain-language story, design choices with justification, what it unlocks, honest limits.
5. **Explore**: click any node for what it is, why it exists, the client's own words that created it, connections, rules, questions it helps answer. "Show example data" fills the map with fictional examples.
6. **Download**: Excel (Summary, Classes, Relationships, Properties, Rules, Layers, Test Questions, Traceability, Change Log) and schema.json.

## Choosing the model (llm.py)
Claude, Azure OpenAI, OpenAI, or KPMG Workbench (copy `workbench_adapter.example.py` to `workbench_adapter.py`).
No client data should go to a public model without approval; use Azure/Workbench for real client sessions.

## How scoring works (no AI involved, so it cannot be gamed by flattery)
Things found 20 · Details 15 · Connected 20 · Rules 15 · Tested with real questions 20 · Traced to client's own words 10.

## Files
- `app.py` API and sessions (JSON files in `data/sessions`)
- `ontology.py` merge, scoring, badges, Question Arena check (deterministic)
- `prompts.py` all prompts (tune here)
- `llm.py` model adapter, `mock_llm.py` offline demo
- `excel.py` workbook and schema.json export
- `static/index.html` the whole front end
- `tests/test_flow.py` end-to-end test (runs on the mock model)

## Known limits
- Prompts were tested only against the mock model. Run one real session and tune `prompts.py`.
- No login. Bind to localhost or put it behind your auth before sharing.
- Gaps are found by checking map structure, not by running the question on real data.
