"""
pipeline_trace.py
=================
Step-by-step pipeline trace for EchoMind Secretary.
Input:  "لیست بیماران دیروز رو نشون بده"
Covers: rule parser → validator → executor (mock DB) → brain Phase-1 router → brain Phase-2 planner
"""

import sys, json, textwrap, logging
from datetime import datetime, timedelta

# Silence internal logger noise so only our own print() calls appear
logging.basicConfig(level=logging.CRITICAL)

sys.path.insert(0, r"c:/AI-Pacs codes/PacsClient V2(5jan)/PacsClientV2")

BAR  = "─" * 62
DBAR = "═" * 62
NL   = "\n"

def section(title):
    print(f"\n{DBAR}\n  {title}\n{DBAR}")

def step(num, label):
    print(f"\n{BAR}\n  STEP {num}: {label}\n{BAR}")

def ok(msg):   print(f"  ✔  {msg}")
def err(msg):  print(f"  ✘  {msg}")
def info(msg): print(f"  ·  {msg}")


USER_TEXT = "لیست بیماران دیروز رو نشون بده"
LANGUAGE  = "fa"

section("AIPacs EchoMind — Full Pipeline Trace")
info(f"Input text : {USER_TEXT}")
info(f"Language   : {LANGUAGE}")
info(f"Date today : {datetime.now().strftime('%Y-%m-%d')}")
info(f"Date yest  : {(datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d')}")


# ══════════════════════════════════════════════════════════════════════════════
# AUTH BOOTSTRAP  (mirrors what the app does on EchoMind login)
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{BAR}\n  AUTH: Bootstrap EchoMind key → GapGPT token\n{BAR}")

from EchoMind.settings_store import get_echomind_api_key
from EchoMind.api_manager import APIKeyManager, Manage

_lic_key = get_echomind_api_key()
_ok, _center_code, _err = APIKeyManager.instance().validate_key(_lic_key)
if not _ok:
    err(f"Key validation failed: {_err}  — trace cannot reach LLM steps.")
else:
    ok(f"License key validated → center={_center_code}")

try:
    _ci = Manage.instance().detect_center(_lic_key)
    ok(f"Center detected: {_ci.center_display}  ({_ci.center_code})")
    info(f"  GapGPT key (masked): {_ci.gapgpt_key[:8]}…{_ci.gapgpt_key[-4:]}")
except Exception as _exc:
    err(f"detect_center failed: {_exc}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Rule Parser
# ══════════════════════════════════════════════════════════════════════════════
step(1, "Rule Parser  (parser_rules.parse_command_rule)")

from EchoMind.secretary.parser_rules import parse_command_rule

rule_plan = parse_command_rule(USER_TEXT)

if rule_plan:
    ok(f"Rule plan produced")
    info(f"  action            = {rule_plan.get('action')}")
    info(f"  entities          = {rule_plan.get('entities')}")
    info(f"  confidence        = {rule_plan.get('confidence')}")
    info(f"  needs_confirmation= {rule_plan.get('needs_confirmation')}")
    info(f"  reason            = {rule_plan.get('reason')}")
else:
    err("Rule parser returned None — will fall through to LLM")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Validator
# ══════════════════════════════════════════════════════════════════════════════
step(2, "Validator  (validator.validate_plan)")

from EchoMind.secretary.validator import validate_plan

plan_to_validate = rule_plan if rule_plan else {
    "action": "list_patients",
    "entities": {"date": "yesterday"},
    "confidence": 0.9,
    "needs_confirmation": False,
    "reason": "fallback test plan",
}

normalized, errors = validate_plan(plan_to_validate)

if not errors:
    ok("Validation passed — no errors")
    info(f"  normalized plan   = {normalized}")
else:
    err(f"Validation errors: {errors}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Date Normalisation inside Executor
# ══════════════════════════════════════════════════════════════════════════════
step(3, "Executor — _normalize_date_filter  (date range resolution)")

from EchoMind.secretary.executor import SecretaryExecutor

date_entity = (normalized or plan_to_validate).get("entities", {}).get("date", "")
info(f"  raw date entity   = {repr(date_entity)}")

d_from, d_to = SecretaryExecutor._normalize_date_filter(date_entity)
ok(f"Date range resolved:")
info(f"  date_from = {d_from}")
info(f"  date_to   = {d_to}")

yesterday_yyyymmdd = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
if d_from == yesterday_yyyymmdd and d_to == yesterday_yyyymmdd:
    ok(f"Correct! Maps to yesterday ({yesterday_yyyymmdd})")
else:
    err(f"Unexpected range: {d_from}..{d_to}  (expected {yesterday_yyyymmdd}..{yesterday_yyyymmdd})")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Executor (mock patient DB)
# ══════════════════════════════════════════════════════════════════════════════
step(4, "Executor — _list_patients  (mock DB rows)")

# Inline mock adapter so we don't need a real Qt widget
class _MockAdapter:
    def is_available(self):          return True
    def get_active_source(self):     return "server"
    def _set_active_source(self, s): pass
    def _set_modalities(self, m):    pass
    def search(self, source=None, criteria=None, timeout_s=45): pass
    def list_rows(self):
        yest = yesterday_yyyymmdd
        today = datetime.now().strftime("%Y%m%d")
        return [
            {"patient_id": "P-001", "patient_name": "Ali Rezaei",     "date": yest,  "modality": "CT"},
            {"patient_id": "P-002", "patient_name": "Sara Ahmadi",    "date": yest,  "modality": "MR"},
            {"patient_id": "P-003", "patient_name": "Hamed Karimi",   "date": today, "modality": "CT"},
            {"patient_id": "P-004", "patient_name": "Maryam Hosseini","date": yest,  "modality": "DX"},
        ]
    def open_patient(self, row, **kw): pass
    def download_studies(self, studies, set_current_tab=False): pass
    def get_selected_row(self): return None

exec_instance = SecretaryExecutor(_MockAdapter())
plan_for_exec = normalized or plan_to_validate
mock_state = {"pending": None, "last_patient": None, "last_list": []}

result = exec_instance._list_patients(plan_for_exec, mock_state)

info(f"  result.ok      = {result['ok']}")
info(f"  result.message = {result['message']}")
if result.get("data"):
    ok(f"Patients returned: {len(result['data'])}")
    for row in result["data"]:
        info(f"    {row.get('patient_id','?'):8s}  {str(row.get('patient_name','?')):22s}  date={row.get('date','?')}  {row.get('modality','?')}")
else:
    err("No data returned")
    info(f"  error_code = {result.get('error_code')}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Brain Phase 1: Module Routing
# ══════════════════════════════════════════════════════════════════════════════
step(5, "Brain Phase 1 — Module Router  (LLM selects module docs)")

from EchoMind.secretary.brain.catalog_loader import (
    load_catalog_text, list_available_module_ids, load_module_docs
)

catalog_text = load_catalog_text()
avail = list_available_module_ids()
info(f"  catalog.yaml      = {len(catalog_text)} chars")
info(f"  available modules = {avail}")

try:
    from EchoMind.secretary.brain.router import route_request, _build_phase1_prompt, _SYSTEM_PROMPT, _MODEL
    info("  Building Phase 1 prompt...")
    _phase1_user_msg = _build_phase1_prompt(USER_TEXT, LANGUAGE, catalog_text)
    info(f"  Prompt length      = {len(_phase1_user_msg)} chars")
    print()
    print("  ── PHASE 1 REQUEST (to LLM) ─────────────────────────────────")
    print(f"  model   : {_MODEL}")
    print(f"  [system]: {_SYSTEM_PROMPT[:120].strip()}…")
    print(f"  [user]  : {_phase1_user_msg[:400].strip()}")
    if len(_phase1_user_msg) > 400:
        print(f"           … ({len(_phase1_user_msg)} total chars)")
    print("  ─────────────────────────────────────────────────────────────")
    print()
    info("  Calling LLM for Phase 1 routing ...")
    decision = route_request(user_text=USER_TEXT, language=LANGUAGE, timeout=20)

    print()
    print("  ── PHASE 1 RESPONSE (from LLM) ──────────────────────────────")
    print(f"  raw response: {decision.raw_response[:600]}")
    print("  ─────────────────────────────────────────────────────────────")
    print()

    if decision.modules:
        ok(f"Phase 1 result:")
        info(f"  modules selected  = {decision.modules}")
        info(f"  reason            = {decision.reason}")
    else:
        err(f"Phase 1 returned no modules. reason={decision.reason}")

except Exception as exc:
    err(f"Phase 1 LLM call failed: {exc}")
    decision = None
    info("  (continuing with manual module selection: ['homepage'])")
    class _FallbackDecision:
        modules = ["homepage"]
        reason  = "manual fallback"
    decision = _FallbackDecision()


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Brain Phase 2: Action Planning
# ══════════════════════════════════════════════════════════════════════════════
step(6, "Brain Phase 2 — Action Planner  (LLM produces JSON plan)")

module_docs = load_module_docs(decision.modules)
info(f"  module docs loaded = {len(module_docs)} chars  (modules: {decision.modules})")

try:
    from EchoMind.secretary.brain.agent import AgentBrain, _SYSTEM_PHASE2, _MODEL as _AGENT_MODEL

    # Build and print the exact messages the LLM will receive
    user_msg = (
        f"Language hint: {LANGUAGE}\n\n"
        "=== MODULE DOCUMENTS (Document 2) ===\n"
        f"{module_docs}\n\n"
        "=== USER REQUEST ===\n"
        f"{USER_TEXT}\n\n"
        "Produce an executable JSON action plan following the output contract above."
    )
    print()
    print("  ── PHASE 2 REQUEST (to LLM) ─────────────────────────────────")
    print(f"  model   : {_AGENT_MODEL}")
    print(f"  [system]: {_SYSTEM_PHASE2[:120].strip()}…")
    print(f"  [user]  : {user_msg[:500].strip()}")
    if len(user_msg) > 500:
        print(f"           … ({len(user_msg)} total chars)")
    print("  ─────────────────────────────────────────────────────────────")
    print()

    brain = AgentBrain(executor=exec_instance, fallback_to_secretary=True)
    info("  Calling LLM for Phase 2 planning ...")
    brain_plan = brain.plan(user_text=USER_TEXT, language=LANGUAGE)

    print()
    print("  ── PHASE 2 RESPONSE (from LLM) ──────────────────────────────")
    print(f"  parsed plan: {json.dumps(brain_plan, ensure_ascii=False, indent=2) if brain_plan else '(none)'}")
    print("  ─────────────────────────────────────────────────────────────")
    print()

    if brain_plan:
        ok("Phase 2 plan produced:")
        info(f"  action            = {brain_plan.get('action')}")
        info(f"  entities          = {brain_plan.get('entities')}")
        info(f"  confidence        = {brain_plan.get('confidence')}")
        info(f"  needs_confirmation= {brain_plan.get('needs_confirmation')}")
        info(f"  reason            = {brain_plan.get('reason')}")
    else:
        err("Phase 2 returned no plan")

except Exception as exc:
    import traceback
    err(f"Phase 2 LLM call failed: {exc}")
    traceback.print_exc()
    brain_plan = None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Brain Dispatch (execute Phase 2 plan)
# ══════════════════════════════════════════════════════════════════════════════
step(7, "Brain Dispatch  (execute brain plan through executor)")

if brain_plan:
    try:
        dispatch_result = brain.dispatch(brain_plan)
        info(f"  result.ok      = {dispatch_result['ok']}")
        info(f"  result.message = {dispatch_result['message']}")
        if dispatch_result.get("data"):
            ok(f"Patients returned via brain dispatch: {len(dispatch_result['data'])}")
            for row in dispatch_result["data"]:
                info(f"    {row.get('patient_id','?')}  {str(row.get('patient_name','?')):20s}  date={row.get('date',row.get('study_date','?'))}")
    except Exception as exc:
        err(f"Dispatch error: {exc}")
else:
    info("  Skipped — no brain plan available (LLM unreachable in this environment)")
    info("  ➜ In production, the legacy rule-based result from STEP 4 is returned instead.")


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
section("PIPELINE SUMMARY")
steps = [
    ("STEP 1 — Rule Parser",       "✔" if rule_plan else "✘"),
    ("STEP 2 — Validator",         "✔" if not errors else "✘"),
    ("STEP 3 — Date Normalise",    "✔" if d_from == yesterday_yyyymmdd else "✘"),
    ("STEP 4 — Executor (mock)",   "✔" if result["ok"] else "✘"),
    ("STEP 5 — Brain Phase 1",     "✔" if decision and decision.modules else "✘"),
    ("STEP 6 — Brain Phase 2",     "✔" if brain_plan else "⚠  (LLM call needed)"),
    ("STEP 7 — Brain Dispatch",    "✔" if brain_plan else "⚠  (follows Step 6)"),
]
for label, status in steps:
    print(f"  {status}  {label}")
print(f"\n{DBAR}")
sys.exit(0)
