# tests/gui/echomind_driven/

In-process GUI tests driven by `modules/EchoMind/secretary/`. The Secretary
already has adapters that operate on the live `home_widget` instance
(`adapters/home_widget_adapter.py`). Test files here are NOT runnable as
standalone scripts — they expose a `run(secretary_executor)` entry point
that gets called *from inside the AI-PACS process* once the main window is
fully up.

## How to wire one in

Add a `--secretary-test` flag in `main.py` that, after startup completes,
imports and runs `tests.gui.echomind_driven.<module>.run(executor)`. The
executor is the same one EchoMind uses for natural-language commands, so
each test step looks like:

```python
from modules.EchoMind.secretary.contracts import SecretaryActionPlan

plan: SecretaryActionPlan = {
    "action": "list_patients",
    "entities": {"modality": "MR", "date": "yesterday"},
}
result = executor.dispatch(plan, state={})
assert result["ok"], result["message"]
```

This route avoids ALL UI clicks — it talks directly to the widget Python
objects — so it's race-free and 10–100× faster than pywinauto. The
trade-off is it can only exercise paths the Secretary catalog already
covers (`download.md`, `homepage.md`, `eagle_ai.md`, etc.).

## Suggested files (not yet created)

| File | Tests |
|---|---|
| `test_secretary_list_mri_yesterday.py` | The Scenario-1 list-then-open path via Secretary actions. |
| `test_secretary_bulk_download.py` | Multi-patient enqueue via the Secretary `download` action. |
| `test_secretary_eagle_eye_open.py` | Secretary opens Eagle Eye on an MG study (no drag-drop). |

Add `test_secretary_<scenario>.py` files following the pattern above —
one `run(executor)` per file, no pytest decorators (tests/code/system/
covers the structural side; this is for live-process verification).
