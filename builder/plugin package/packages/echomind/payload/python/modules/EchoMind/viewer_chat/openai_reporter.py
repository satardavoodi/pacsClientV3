import base64
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import requests

from .api_manager import APIKeyManager, Manage
from modules.EchoMind.llm_client import chat_completion
from modules.EchoMind.settings_store import get_llm_backend, get_openai_settings, get_prompt_settings, get_proxy_settings


# ── OPT-33 (2026-07-13): EchoMind AI calls MUST have a timeout ───────────────
# Every `requests.post` in this module used to be issued with NO `timeout=`, i.e.
# requests waits FOREVER. That is not a crash (each call runs on an `ApiWorker`
# QThread wrapped in try/except, so the app survives and shows "check your
# internet"), but on a HALF-OPEN connection — a link that dies mid-request, which
# is exactly what the 2026-07-13 laptop network did (see OPT-28) — the worker
# thread NEVER returns:
#   * the "typing…" bubble spins forever,
#   * the Send button stays locked (`lock_btn`),
#   * the QThread leaks, and every retry leaks another one.
# That is the "EchoMind hangs when the internet drops" symptom. A clean refusal
# is far better than an infinite wait: with a timeout the worker raises, the
# except path fires, and the user gets the existing "Connection error — check
# your internet connection" bubble and can retry.
#
# (connect, read): a connect must fail fast; a long LLM completion legitimately
# needs a generous READ budget, so the read timeout is deliberately large. Both
# are tunable; `AIPACS_ECHOMIND_HTTP_TIMEOUT=0` restores the legacy no-timeout
# behaviour (emergencies only — it can hang the AI panel indefinitely).
_DEFAULT_CONNECT_TIMEOUT_S = 10.0
_DEFAULT_READ_TIMEOUT_S = 180.0


def _request_timeout():
    """(connect, read) timeout for every outbound AI call. None = legacy hang."""
    raw = (os.getenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", "") or "").strip()
    if raw == "0":
        return None  # kill switch: byte-identical legacy (wait forever)
    connect = _DEFAULT_CONNECT_TIMEOUT_S
    read = _DEFAULT_READ_TIMEOUT_S
    if raw:
        try:
            read = float(raw)
        except ValueError:
            read = _DEFAULT_READ_TIMEOUT_S
    return (connect, read)


def _get_requests_proxies() -> "dict[str, str]":
    """Return a requests-compatible proxies dict.

    - 'direct': returns {} so requests explicitly bypasses ALL proxy sources
      (system registry, HTTP_PROXY/HTTPS_PROXY env vars, Windows WinInet).
      Passing proxies=None would still let requests pick up system proxies.
    - 'socks5': returns the configured SOCKS5 proxy.
    """
    try:
        cfg = get_proxy_settings()
        if cfg.get("connection_type") != "socks5":
            return {}  # explicit bypass — no system/env proxy
        port = int(cfg.get("proxy_port") or 2080)
        proxy_url = f"socks5://127.0.0.1:{port}"
        return {"http": proxy_url, "https": proxy_url}
    except Exception:
        return {}  # fail-safe: no proxy


# ------------------------------------------------------
#  Safety helpers (never crash UI if analytics fails)
# ------------------------------------------------------
def _to_str(x) -> str:
    if x is None:
        return ""
    try:
        return str(x)
    except Exception:
        return ""

def _log_usage_safe(m, center, model, prompt_tokens, completion_tokens, user_msg) -> None:
    """
    Log token usage robustly across possible Manage.update_usage signatures.
    Prevents crashes like: 'NoneType' object has no attribute 'strip'
    """
    try:
        c = (_to_str(center).strip() or "Unknown")
        mdl = (_to_str(model).strip() or "Unknown")
        pt = int(prompt_tokens or 0)
        ct = int(completion_tokens or 0)
        um = _to_str(user_msg)
        try:
            m.update_usage(c, mdl, pt, ct, um)  # preferred (includes message)
        except TypeError:
            # backward-compatible signatures
            m.update_usage(c, mdl, pt, ct)
    except Exception:
        # Never let analytics crash the caller
        return


# ----------------------------------------------------------
#  ENSURE STRUCTURE EXISTS
# ----------------------------------------------------------
def ensure_usage_nodes(usage, center, model):
    """Ensure JSON structure exists for center + model."""
    if center not in usage["centers"]:
        usage["centers"][center] = {"models": {}}

    if model not in usage["centers"][center]["models"]:
        usage["centers"][center]["models"][model] = {
            "count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "last_used": None,
            "history": []
        }


def _is_openai_backend() -> bool:
    return get_llm_backend() == "openai"


def _feature_prompt(name: str) -> str:
    if not _is_openai_backend():
        return ""
    try:
        return str(get_prompt_settings().get(name) or "").strip()
    except Exception:
        return ""


def _compose_prompt(base_prompt: str, feature_name: str) -> str:
    extra = _feature_prompt(feature_name)
    if not extra:
        return base_prompt
    return f"{extra}\n\n{base_prompt}"


def _openai_result(
    *,
    system_prompt: str,
    user_content: Any,
    user_msg: str,
    model: str,
    api_key_override: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    cfg = get_openai_settings()
    result = chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        model=(_to_str(model).strip() or str(cfg.get("text_model") or "gpt-4o-mini")),
        temperature=float(cfg.get("temperature", 0.2) if temperature is None else temperature),
        max_tokens=int(max_tokens or cfg.get("max_output_tokens") or 4096),
        timeout=int(cfg.get("timeout_seconds") or 60),
        api_key_override=api_key_override,
        reasoning_effort=str(cfg.get("reasoning_effort") or "").strip() or None,
    )
    return {
        "content": result.get("content", ""),
        "usage": result.get("usage", {}),
    }



_MRI_REQUIRED_KEYS: list = [
    "Report Title",
    "Pathological Findings",
    "Normal Findings",
    "Impression",
    "Recommendations",
]

_CT_REQUIRED_KEYS: list = [
    "Report Title",
    "Pathological Findings",
    "Normal Findings",
    "Impression",
    "Recommendations",
]

_MAMMOGRAPHY_REQUIRED_KEYS: list = [
    "Report Title",
    "Breast Composition",
    "Pathological Findings",
    "Normal Findings",
    "Axillary Evaluation",
    "BI-RADS Category",
]

_ULTRASOUND_REQUIRED_KEYS: list = [
    "Report Title",
    "Pathological Findings",
    "Normal Findings",
]

_OB_ULTRASOUND_REQUIRED_KEYS: list = [
    "Report Title",
    "Gestational Age & Dating",
    "Fetal Presentation",
    "Biometry",
    "Placenta & Umbilical Cord",
    "Amniotic Fluid",
    "Normal Findings",
]

_VALIDATED_MODALITIES: frozenset = frozenset({
    "mri", "ct", "mammography",
    "sonography", "ultrasound",
    "obstetric ultrasound", "ob ultrasound",
    "pregnancy ultrasound", "fetal ultrasound",
})


def _clean_model_json_text(raw):
    """Strip markdown fences and <|end|> end-tokens from model JSON output."""
    if not isinstance(raw, str):
        return raw
    import re as _re
    text = raw.strip()
    # Strip <|end|> FIRST so closing ``` fence is still at the end
    text = _re.sub(r"\s*<\|end\|>\s*$", "", text)
    text = text.strip()
    # Strip opening ```json or ``` fence
    text = _re.sub(r"^```(?:json)?\s*", "", text, flags=_re.IGNORECASE)
    # Strip closing ``` fence
    text = _re.sub(r"\s*```$", "", text)
    return text.strip()
def _validate_report_json(raw, modality: str):
    """
    Validate and repair JSON output for a given modality.
    Modalities not in _VALIDATED_MODALITIES: passthrough unchanged.
    Handled modalities: strip fences → parse → validate required keys →
    coerce empty optionals to null → return canonical JSON string.
    Raises ValueError on parse failure or missing required keys.
    """
    _mod = modality.lower()
    if not isinstance(raw, str) or _mod not in _VALIDATED_MODALITIES:
        return raw
    import json as _json
    text = _clean_model_json_text(raw)
    try:
        data = _json.loads(text)
    except (_json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"non-parseable JSON returned by model: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a JSON object (dict) but got {type(data).__name__}"
        )
    # Determine required/optional keys per modality
    if _mod == "mammography":
        _required = _MAMMOGRAPHY_REQUIRED_KEYS
        _optional: list = []
    elif _mod in ("obstetric ultrasound", "ob ultrasound",
                  "pregnancy ultrasound", "fetal ultrasound"):
        _required = _OB_ULTRASOUND_REQUIRED_KEYS
        _optional = ["Anatomy Survey", "Doppler", "Impression", "Recommendations"]
    else:  # mri, ct, sonography, ultrasound
        _required = ["Report Title", "Pathological Findings", "Normal Findings"]
        _optional = ["Impression", "Recommendations"]
    # Coerce empty / N/A optional fields to null (keep key present)
    for key in _optional:
        val = data.get(key)
        if isinstance(val, str) and val.strip().lower() in ("", "n/a", "none", "-"):
            data[key] = None
    # Ensure ALL optional keys are present (insert as null if missing)
    for key in _optional:
        if key not in data:
            data[key] = None
    # Validate required keys — raise on missing
    for k in _required:
        if not data.get(k):
            raise ValueError(f"Required key missing or empty: {k!r}")
    return _json.dumps(data, ensure_ascii=False, indent=2)

def reporter(
    user_msg: str,
    modality: Optional[str] = "",
    normal_template: Optional[str] = "",
    CENTER_Key: Optional[str] = None,
    model: str = "gpt-4.1-mini"):
    user_msg = _to_str(user_msg)
    modality = _to_str(modality)
    normal_template = _to_str(normal_template)
    m = Manage.instance()
    center, api_key = m.get_center_and_gapgpt_key()
    if normal_template:
        ##print("NORMAL TEMPLATE IS PRESENTED")
        template_logic = ("""
            TEMPLATE LOGIC (User Provided Normal Template Override):
            • A full normal_template has been provided by the user.
            • You MUST ignore any internal rules or default logic related to RSNA-style generation of normal findings.
            • DO NOT generate or reconstruct any normal findings yourself.
            • DO NOT include any anatomical regions not present in the provided template.
            • Use ONLY the provided normal_template for the "Normal Findings" section.
            • Maintain the exact formatting and tone unless a region is affected by the provided pathological findings.
            • If a pathological finding affects a specific region, remove or adjust ONLY that region from the normal_template accordingly.
            • SEX-SPECIFIC ANATOMY: Do NOT infer or assume the patient's sex. Even if the provided template lists
              sex-specific organs (prostate, uterus, ovaries, seminal vesicles, cervix, testes), OMIT any such organ
              the physician did NOT explicitly mention — do NOT auto-complete a normal/"unremarkable" statement for it,
              and NEVER output both male and female organs in the same report.
            • Output must follow the standard JSON schema: { "Report Title", "Pathological Findings", "Normal Findings" } with <|end|> at the end."""
                        )
    else:
        template_logic = (
            "TEMPLATE LOGIC (No Normal Template Provided):\n"
            "• No 'normal_template' was provided.\n"
            "• Therefore, construct the 'Report Title' using RSNA-style rules.\n"
            "• Construct 'Normal Findings' automatically using META-driven RSNA structure.\n"
            "• Exclude any organ mentioned in Pathological Findings.\n"
            "• SEX-SPECIFIC ANATOMY: Do NOT infer or assume the patient's sex. Include a sex-specific organ "
            "(prostate, uterus, ovaries, seminal vesicles, cervix, testes) ONLY IF the physician explicitly "
            "mentioned it; otherwise OMIT it entirely and do NOT emit a normal/'unremarkable' statement for it. "
            "NEVER output both male and female organs in the same report.\n\n"
        )




    if modality:
        base_modality_logic = f"MODALITY LOGIC:\n• The imaging modality is '{modality}'.\n• Customize the 'Report Title' to include the modality (e.g., '{modality} of [Body Part]').\n• Tailor 'Normal Findings' structure and terminology to the modality, using appropriate standards and avoiding repetition.\n"
        modality_lower = modality.lower()
        if modality_lower == "ct":
                    specific_instructions = ("""

                        MODALITY LOGIC (CT):
                        • The imaging modality is CT (Computed Tomography).
                        • Construct 'Normal Findings' using RSNA structured CT reporting standards when no user-provided normal_template is available.
                        • Only mention contrast phases (e.g., non-contrast, arterial, portal venous, delayed) if explicitly referenced in the input.
                        • Use structured, grouped, RSNA-style anatomical organisation — concise, non-redundant.
                        • Exclude any anatomical region already described in Pathological Findings from the Normal Findings.

                        * Recognise Persian / Finglish CT terminology and map to correct radiologic English:
                        – "برونشکتازی / bronshiektazi" → Bronchiectasis
                        – "گراند گلس / grand glass" → Ground-glass opacity (GGO)
                        – "آمفیزم / amfizem" → Emphysema
                        – "کونکا بولوزا / concha boloza" → Concha bullosa
                        – "دیورتیکولایتیس / diverticolitis" → Diverticulitis
                        – "استرندینگ چربی" → Fat stranding
                        – "هایپردنس / هایپودنس" → Hyperdense / Hypodense
                        – "لنفادنوپاتی / lemfnodopaty" → Lymphadenopathy
                        – "پنوموتوراکس / pnomotoraks" → Pneumothorax
                        – "پلورال افیوژن / ploralafijon" → Pleural effusion
                        – "هیدرونفروز / hidronefros" → Hydronephrosis
                        – "نفرولیتیازیس / sange kolyeh" → Nephrolithiasis
                        – "آپاندیسیت / apandisit" → Appendicitis
                        – "پنوموپریتونئوم" → Pneumoperitoneum
                        – "تنوسینوویت" → Tenosynovitis
                        – "اکیپشوس" → Osteophytosis

                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        CT — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS (READ FIRST)
                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        This rule applies to EVERY CT body region (head, chest, abdomen/pelvis, spine, MSK, angiography, etc.).
                        CRITICAL DISTINCTION between GENERATING new content and PRESERVING dictated content:
                        - FORBIDDEN: You must NOT independently generate, invent, infer, or expand a NEW impression,
                          conclusion, differential diagnosis, suggestion, follow-up advice, clinical correlation,
                          laboratory correlation, pathologic correlation, biopsy recommendation, further-imaging
                          recommendation, or management recommendation that the physician did NOT dictate.
                        - MANDATORY: ANY impression, conclusion, suggestion, recommendation, follow-up, or
                          clinical/laboratory/pathologic correlation the physician EXPLICITLY dictated is SOURCE
                          CONTENT and MUST be preserved (meaning and intent intact) in the final report — e.g.
                          "the above findings are suggestive of ...", "clinical correlation is recommended",
                          "correlation with laboratory findings is recommended", "further evaluation is recommended",
                          "biopsy is recommended".
                        - The "do not invent" rule NEVER authorizes deleting, omitting, suppressing, weakening,
                          softening, or replacing physician-dictated content. When unsure, KEEP it (meaning intact).

                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        CRITICAL: IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK (HARD RULE)
                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        You MUST treat "Impression" and "Recommendations" as REQUIRED FIELDS **IFF** they exist in the input transcript.

                        DEFINITION OF "EXISTS IN INPUT":
                        - Impression EXISTS if the input includes ANY explicit diagnostic conclusion/جمع‌بندی تشخیصی such as:
                        "impression", "جمع‌بندی", "نتیجه", "در مجموع", "مطرح‌کننده", "suggestive of", "compatible with", "favored diagnosis", "به نفع", "به احتمال زیاد", etc.
                        - Recommendations EXISTS if the input includes ANY explicit advice/اقدام پیشنهادی such as:
                        "recommend", "توصیه", "follow-up", "biopsy", "correlation", "clinical correlation", "laboratory correlation", "pathologic correlation", "further evaluation", "further imaging", "repeat imaging", "نمونه‌برداری", "بررسی بیشتر", etc.

                        HARD CONSTRAINTS:
                        1) If Impression EXISTS in input → output JSON MUST include "Impression" as a NON-EMPTY string.
                        2) If Recommendations EXISTS in input → output JSON MUST include "Recommendations" as a NON-EMPTY string.
                        3) If either exists but you omit it or leave it empty → output is INVALID; regenerate.
                        4) DO NOT invent Impression/Recommendations if not stated in input.
                        5) DO NOT set them to null, "N/A", "-", or empty string if they exist in input.

                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        PATHOLOGICAL FINDINGS RULES (CT-SPECIFIC)
                        ═══════════════════════════════════════════════════════════════
                        When reporting pathological findings, describe the IMAGING MANIFESTATION,
                        not just the diagnosis label. Structure each finding as:
                          "[Anatomical location] demonstrates [CT imaging appearance], consistent with / suggestive of [diagnosis]."

                        CORRECT:   "A 2.4 cm hypodense lesion in hepatic segment VI with peripheral rim
                                    enhancement on portal-venous phase, consistent with a hepatic abscess."
                        INCORRECT: "Hepatic abscess."

                        CORRECT:   "Focal area of hyperdensity measuring 18 mL in the right basal ganglia
                                    with surrounding hypodense oedema and 4 mm rightward midline shift,
                                    consistent with hypertensive intraparenchymal haemorrhage."
                        INCORRECT: "Intracerebral bleeding."

                        CT-SPECIFIC MEASUREMENT AND CLASSIFICATION RULES:
                          • Brain haemorrhage: specify type (EDH/SDH/SAH/IPH), location, volume (ABC/2 method or mL), density (HU), mass effect, midline shift in mm.
                          • Stroke: ASPECTS score for MCA territory; specify territory (MCA/ACA/PCA), density change (loss of grey-white), sulcal effacement.
                          • Pulmonary nodule: size (longest dimension, mm), lobe, segment, density (solid/part-solid/GGO/calcified), morphology (smooth/irregular/spiculated), Fleischner Society category.
                          • Pleural effusion: laterality, estimated volume (small <300 mL / moderate / large), loculation, associated atelectasis.
                          • Liver lesion: segment (I-VIII), size (3 planes, cm), density/attenuation pattern (arterial enhancement/wash-out/peripheral rim), satellite lesions.
                          • Bile duct: calibre in mm; if dilated state level of obstruction.
                          • Pancreatitis: Revised Atlanta severity, Balthazar grade, necrosis percentage, duct calibre.
                          • Appendix: diameter in mm, wall thickness, periappendiceal fat stranding, abscess, perforation (free air or extraluminal faecal material).
                          • Bowel obstruction: specify dilated segment (small/large bowel), transition point, degree (partial/complete), closed-loop signs.
                          • Kidney stone: size in mm, location (caliceal/pelvis/proximal/mid/distal ureter/UVJ), HU density, obstructive hydronephrosis grade (mild/moderate/severe).
                          • Spinal fracture: AO/Magerl classification, vertebral height loss (%), burst vs compression, canal compromise (%), retropulsion.
                          • Disc herniation: level, direction (central/paracentral/foraminal/far-lateral), size (mm), nerve root or thecal sac compression.
                          • Pulmonary embolism: vessel level (main/lobar/segmental/subsegmental), RV:LV ratio, RV strain signs.
                          • Aortic aneurysm: maximal diameter (mm) at sinus / ascending / arch / descending; mural thrombus; intramural haematoma; dissection flap (Stanford A/B).
                          • Lymph node: short-axis diameter (mm), location, necrosis, calcification; reference to size threshold.
                        ═══════════════════════════════════════════════════════════════

                        * RSNA-compliant normal findings per CT body region:

                        – BRAIN CT (NON-CONTRAST):
                            • No acute territorial infarction; grey-white matter differentiation is preserved bilaterally.
                            • No intracranial haemorrhage (parenchymal, subdural, epidural, or subarachnoid).
                            • No abnormal intraparenchymal hyperdensity or hypodensity.
                            • Ventricular system is normal in size and configuration; no hydrocephalus.
                            • No midline shift or significant mass effect.
                            • Basal cisterns are patent and symmetric; no effacement.
                            • No extra-axial fluid collection.
                            • Cerebral sulci and gyri are appropriate for patient age; no asymmetric sulcal effacement.
                            • The cerebellum and brainstem show no focal hypodense or hyperdense lesion.
                            • Posterior fossa structures are unremarkable; fourth ventricle is in normal position.
                            • Osseous calvarium: no fracture, lytic, or sclerotic lesion.
                            • Visualised paranasal sinuses and mastoid air cells are clear.
                            • The orbits are normal in appearance; globes are symmetric.

                        – BRAIN CT WITH CONTRAST:
                            • No abnormal parenchymal, leptomeningeal, or dural enhancement.
                            • No ring-enhancing or nodular-enhancing lesion.
                            • Major intracranial vessels demonstrate normal enhancement without filling defect or cutoff.
                            • No abnormal enhancement in the posterior fossa or brainstem.
                            • Choroid plexuses enhance symmetrically; no abnormal ependymal enhancement.

                        – CHEST CT AND HRCT:
                            • Lung parenchyma: clear lung fields bilaterally; no focal consolidation, mass, or suspicious nodule.
                            • No ground-glass opacity, interstitial thickening, or honeycombing.
                            • Airways: trachea and central bronchi are patent and normally calibred; no bronchiectasis or bronchial wall thickening.
                            • Pleura: no pleural effusion, pleural thickening, or pneumothorax bilaterally.
                            • Mediastinum: no mediastinal widening or mass; no pathologic lymphadenopathy (no node greater than 1 cm short axis).
                            • Heart: normal in size; no pericardial effusion or thickening.
                            • Thoracic aorta and pulmonary vasculature are normal in calibre and course.
                            • Oesophagus: not dilated; no wall thickening.
                            • Chest wall and osseous structures: no rib fracture, no lytic or sclerotic bony lesion.
                            • Thyroid gland (visualised): symmetric; no nodule detected on this limited view.
                            • Visualised upper abdominal organs are unremarkable.

                        – NECK CT:
                            • Larynx: normal configuration and symmetry; no mucosal irregularity or subglottic narrowing.
                            • Epiglottis and supraglottic structures: unremarkable.
                            • Hypopharynx and oropharynx: no asymmetric soft tissue thickening.
                            • Thyroid gland: normal in size, morphology, and attenuation; no nodule or calcification.
                            • Parathyroid glands: not enlarged.
                            • Salivary glands: parotid and submandibular glands are symmetric and normal in attenuation.
                            • No pathologic cervical lymphadenopathy (no node greater than 1 cm short axis); no necrotic node.
                            • Carotid arteries and internal jugular veins: patent bilaterally; no vascular abnormality.
                            • Prevertebral soft tissues: not thickened.
                            • Cervical spine (limited view): normal alignment; no fracture or subluxation.

                        – PARANASAL SINUS CT:
                            • Frontal sinuses: clear bilaterally; no mucosal thickening, polyp, or air-fluid level.
                            • Maxillary sinuses: clear bilaterally; no mucosal thickening, polyp, or opacification.
                            • Ethmoid air cells: clear bilaterally; no opacification or cell wall erosion.
                            • Sphenoid sinus: clear; no opacification or lateral recess involvement.
                            • Nasal cavity: patent bilaterally; nasal septum midline without perforation; inferior and middle turbinates are of normal size.
                            • Ostiomeatal complexes: patent bilaterally; no obstructing polyp or mucosal disease.
                            • No concha bullosa; no paradoxical middle turbinate.
                            • Orbits (limited view): no periorbital extension of sinus disease; optic nerves unremarkable.
                            • Dentition (limited view): no periapical lucency or dental abscess on this limited view.

                        – ABDOMEN CT:
                            • Liver: normal in size, morphology, and attenuation; no focal hepatic lesion; smooth hepatic contour.
                            • Gallbladder: normal wall thickness and luminal content; no cholelithiasis or polyp.
                            • Bile ducts: common bile duct not dilated (less than 6 mm); no intrahepatic biliary ductal dilatation.
                            • Spleen: normal in size and attenuation; no focal splenic lesion.
                            • Pancreas: normal in size, contour, and attenuation; pancreatic duct not dilated (less than 3 mm); no peripancreatic fat stranding.
                            • Adrenal glands: normal size and morphology bilaterally; no adrenal mass.
                            • Kidneys: normal in size, cortical thickness, and enhancement bilaterally; no nephrolithiasis or hydronephrosis; no perinephric fat stranding.
                            • Bowel: no small or large bowel obstruction; no bowel wall thickening or pneumatosis; appendix visualised and normal (less than 6 mm).
                            • No pneumoperitoneum or intraperitoneal free fluid.
                            • Abdominal aorta: normal calibre (less than 3 cm); no aneurysmal dilatation or mural thrombus.
                            • No enlarged abdominal or retroperitoneal lymph nodes (no node greater than 1 cm short axis).
                            • Abdominal wall: no hernia or abnormal soft tissue mass.

                        – PELVIS CT:
                            ── SEX-SPECIFIC ANATOMY RULE (STRICT — applies to prostate, uterus, ovaries, seminal vesicles, cervix, vagina, testes) ──
                            • DO NOT infer or assume the patient's sex. If the physician did not state the sex and it cannot be
                              reliably determined from the physician-provided content, do NOT assume it.
                            • Include a sex-specific organ ONLY IF the physician EXPLICITLY mentioned that organ (or provided a
                              finding that clearly requires it). If the physician gave no information about a sex-specific organ,
                              OMIT that organ entirely — do NOT emit a normal/"unremarkable" statement for it.
                            • NEVER include BOTH male and female organs in the same report. A report must never list, e.g., the
                              prostate AND the uterus/ovaries together just because this template mentions both.
                            • Urinary bladder: normal wall thickness; no intraluminal filling defect, calculus, or mural mass.
                            • Distal ureters: not dilated; no ureteric calculus at the ureterovesical junction.
                            • Uterus — INCLUDE ONLY IF the physician explicitly mentioned it: normal in size and attenuation; no intraluminal mass or myometrial lesion. (Otherwise OMIT entirely.)
                            • Ovaries — INCLUDE ONLY IF the physician explicitly mentioned them: normal in size; no ovarian mass or complex cyst. (Otherwise OMIT entirely.)
                            • Prostate — INCLUDE ONLY IF the physician explicitly mentioned it: normal in size; no hypodense lesion. (Otherwise OMIT entirely.)
                            • Seminal vesicles — INCLUDE ONLY IF the physician explicitly mentioned them: symmetric and unremarkable. (Otherwise OMIT entirely.)
                            • Rectum and sigmoid colon: normal wall thickness; no pericolonic fat stranding.
                            • No pelvic lymphadenopathy; no free pelvic fluid.
                            • Pelvic floor musculature: symmetric and unremarkable.
                            • Osseous structures of the pelvis: no lytic, sclerotic, or erosive changes; sacroiliac joints symmetric; femoral heads spherical with preserved joint space.

                        – ABDOMINOPELVIC CT:
                            • Full survey of abdominal and pelvic organs as described above with no focal abnormality identified.
                            • No pneumoperitoneum or free intraperitoneal fluid.
                            • Abdominal aorta and iliac vessels: normal in calibre; no aneurysm.
                            • No significant abdominal or pelvic lymphadenopathy.

                        – CERVICAL SPINE CT:
                            • Vertebral alignment: normal cervical lordosis maintained; no anterolisthesis or retrolisthesis at any level.
                            • Vertebral bodies: normal height, cortical margins, and bone density at C1 through C7.
                            • Intervertebral disc spaces: maintained at all cervical levels; no disc calcification.
                            • Spinal canal: adequate AP diameter at all levels; no significant central stenosis.
                            • Neural foramina: patent bilaterally at all cervical levels.
                            • Facet joints: normal articular surfaces; no hypertrophic change or erosion.
                            • Atlantoaxial joint: normal alignment; odontoid process intact and normally positioned; C1-C2 interval preserved.
                            • Prevertebral soft tissues: not thickened.
                            • Posterior elements (pedicles, laminae, spinous processes): intact at all levels.
                            • No fracture, dislocation, lytic, or sclerotic bony lesion.

                        – THORACIC SPINE CT:
                            • Vertebral alignment: normal thoracic kyphosis; no spondylolisthesis at any level.
                            • Vertebral bodies: normal height, cortical integrity, and bone density from T1 to T12; no compression deformity.
                            • Intervertebral disc spaces: maintained throughout.
                            • Spinal canal: patent at all thoracic levels; no significant stenosis.
                            • Posterior elements: pedicles, laminae, transverse processes, and spinous processes intact.
                            • Costovertebral articulations: normal bilaterally; no rib head erosion or subluxation.
                            • Paravertebral soft tissues: no paravertebral mass or abscess.
                            • No lytic, sclerotic, or destructive bony lesion throughout the thoracic spine.

                        – LUMBAR SPINE CT:
                            • Vertebral alignment: normal lumbar lordosis; no spondylolisthesis at L1 through S1.
                            • Vertebral bodies: normal height and bone density at all lumbar levels; no compression or wedge deformity.
                            • Intervertebral disc spaces: maintained at all levels; no significant disc height loss or calcification.
                            • Spinal canal: adequate AP diameter and cross-sectional area at all lumbar levels.
                            • Thecal sac: not compressed at any level.
                            • Neural foramina: patent bilaterally at all lumbar levels; no significant foraminal narrowing.
                            • Facet joints: normal articular surfaces bilaterally; no significant joint space narrowing or vacuum phenomenon.
                            • Sacroiliac joints: symmetric and unremarkable; no erosion or sclerosis.
                            • Paraspinal musculature: normal bulk and attenuation bilaterally.
                            • No fracture, lytic, or sclerotic lesion at L1 through S1 or the sacrum.

                        – MSK CT SHOULDER:
                            • Glenohumeral joint: normal articular surfaces; preserved joint space; no effusion.
                            • Humeral head: normal sphericity and cortical integrity; no Hill-Sachs defect.
                            • Glenoid: normal morphology; no Bankart osseous lesion or glenoid rim fracture.
                            • Acromioclavicular joint: normal; no superior migration of the humeral head.
                            • Acromion: no os acromiale; subacromial space not critically narrowed.
                            • Clavicle and scapula: intact; no fracture or lytic lesion.
                            • Soft tissues (visualised): no abnormal calcification or soft tissue mass.

                        – MSK CT HIP:
                            • Femoral head: normal sphericity; no subchondral collapse, cyst, or osteonecrosis.
                            • Acetabulum: normal morphology; no fracture, labral ossification, or protrusio.
                            • Hip joint space: preserved bilaterally; no joint effusion.
                            • No cam or pincer deformity.
                            • Femoral neck: normal neck-shaft angle; no stress fracture or cortical defect.
                            • Pelvis and proximal femora: no lytic, sclerotic, or permeative bony lesion.
                            • Soft tissues: no iliopsoas or trochanteric bursitis; no calcific tendinopathy.

                        – MSK CT KNEE:
                            • Tibial plateau: no fracture, depression, or cortical disruption.
                            • Femoral condyles: intact articular surfaces; no osteochondral defect.
                            • Patellofemoral joint: normal alignment; no tilt or subluxation; no patellar fracture.
                            • Joint space: preserved in all three compartments.
                            • No intra-articular loose body.
                            • Proximal fibula: intact.
                            • Soft tissues: no soft tissue calcification.

                        – MSK CT ANKLE AND FOOT:
                            • Tibiotalar joint: normal alignment and joint space; no fracture.
                            • Talus: intact; no osteochondral lesion of the talar dome; no avascular necrosis.
                            • Calcaneus: normal morphology; no fracture.
                            • Subtalar, talonavicular, and calcaneocuboid joints: normal alignment; no coalition.
                            • Metatarsals and phalanges: intact; no stress fracture or lytic lesion.
                            • No tarsal coalition.
                            • Soft tissues: no abnormal calcification.

                        – MSK CT WRIST AND HAND:
                            • Distal radius and ulna: intact articular surfaces; normal ulnar variance; no fracture.
                            • Carpal bones: normal alignment and osseous integrity; no scaphoid fracture; no carpal coalition.
                            • Intercarpal joints: normally aligned; no dissociation.
                            • Metacarpals and phalanges: intact; no cortical disruption or periosteal reaction.
                            • Soft tissues: no calcification; no erosive joint disease.

                        – CORONARY CTA:
                            • Coronary artery origin and course: all three vessels arise normally from the aortic root; no anomalous origin.
                            • Left main coronary artery (LMCA): patent throughout; no significant stenosis or calcified plaque.
                            • Left anterior descending artery (LAD): patent; no significant stenosis; no obstructive calcification.
                            • Left circumflex artery (LCx): patent; no significant stenosis.
                            • Right coronary artery (RCA): patent; right-dominant circulation; no significant stenosis.
                            • Cardiac chambers: no chamber dilatation; left ventricular wall thickness within normal limits.
                            • Myocardium: no perfusion defect or focal myocardial thinning.
                            • Pericardium: no pericardial effusion or constrictive thickening.
                            • Aortic root and ascending aorta: normal in calibre; no dilatation.
                            • Pulmonary vasculature: no pulmonary embolism or filling defect.
                            • Incidental extracardiac findings: none significant.

                        – CT ANGIOGRAPHY AORTA:
                            • Aortic root and ascending aorta: normal calibre; no aneurysm, intramural haematoma, or penetrating ulcer.
                            • Aortic arch: normal origin of branch vessels; no arch aneurysm.
                            • Descending thoracic aorta: normal calibre and smooth wall; no dissection flap.
                            • Abdominal aorta: normal calibre (less than 3 cm); no aneurysmal dilatation or mural thrombus.
                            • Major visceral branches (celiac, SMA, renal arteries): patent and normally arising with no stenosis.
                            • Iliac arteries: normal in calibre and course bilaterally; no aneurysm.
                            • No arteriovenous fistula or vascular anomaly.

                        – CT UROGRAPHY AND CT KUB:
                            • Kidneys: normal in size, cortical thickness, and corticomedullary differentiation bilaterally; normal parenchymal enhancement.
                            • Collecting systems: no caliceal dilatation or hydronephrosis bilaterally.
                            • No nephrolithiasis; no cortical scar or nephrocalcinosis.
                            • Ureters: course normally throughout their length; no ureteral calculus, stricture, or dilatation.
                            • Urinary bladder: normal wall thickness and morphology; no intraluminal filling defect, calculus, or mural lesion.
                            • No perinephric fat stranding or retroperitoneal mass.
                            • Adrenal glands: normal size and morphology bilaterally.


                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        OUTPUT FORMAT (STRICT)
                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        Return only a valid JSON object — no other text before or after.
                        Do not include markdown, headers, or explanations.
                        Do not include code fences (no ``` or ```json wrappers).

                        Schema (required | optional):
                        {
                          "Report Title": string,                // REQUIRED
                          "Pathological Findings": string,       // REQUIRED
                          "Normal Findings": string,             // REQUIRED
                          "Impression": string | null,           // OPTIONAL — include only if stated in input
                          "Recommendations": string | null       // OPTIONAL — include only if stated in input
                        }

                        Report Title format examples:
                          "CT Scan of the Brain Without Contrast"
                          "Contrast-Enhanced CT of the Chest"
                          "HRCT of the Chest"
                          "CT of the Cervical Spine Without Contrast"
                          "Triphasic CT of the Abdomen and Pelvis"
                          "CT KUB (Kidneys, Ureters, and Bladder)"
                          "Coronary CT Angiography"
                          "CT Angiography of the Thoracic and Abdominal Aorta"

                        Rules:
                          • Start immediately with { — NO preceding text.
                          • End with } — NO following text, no <|end|>.
                          • All JSON strings must be properly escaped.
                          • No trailing commas. No extra keys.
                          • Pathological Findings: use numbered list format when multiple findings exist.
                          • Normal Findings: use anatomically grouped bullet format.
                          • If Impression/Recommendations are absent from input → omit those keys entirely.

                        """
                    )
        elif modality_lower == "mri":
                        specific_instructions = ("""

                        * The imaging modality is MRI.
                        * Construct the 'Normal Findings' using RSNA reporting standards for MRI when no user-provided normal_template is available.

                        * Only mention specific MRI sequences (e.g., DWI, Spectroscopy, SWI) if explicitly referenced in the input.

                        * Use structured RSNA-style descriptors tailored to body region:
                            – Always generate grouped, concise, non-redundant normal findings.
                            – Exclude any body part explicitly described in pathological findings.
                            – Do not create normal findings for irrelevant regions.

                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        MRI — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS (READ FIRST)
                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        This rule applies to EVERY MRI body region (brain, spine, MSK, breast, abdomen/pelvis, etc.).
                        CRITICAL DISTINCTION between GENERATING new content and PRESERVING dictated content:
                        - FORBIDDEN: You must NOT independently generate, invent, infer, or expand a NEW impression,
                          conclusion, differential diagnosis, suggestion, follow-up advice, clinical correlation,
                          laboratory correlation, pathologic correlation, biopsy recommendation, further-imaging
                          recommendation, or management recommendation that the physician did NOT dictate.
                        - MANDATORY: ANY impression, conclusion, suggestion, recommendation, follow-up, or
                          clinical/laboratory/pathologic correlation the physician EXPLICITLY dictated is SOURCE
                          CONTENT and MUST be preserved (meaning and intent intact) in the final report — e.g.
                          "the above findings are suggestive of ...", "clinical correlation is recommended",
                          "correlation with laboratory findings is recommended", "further evaluation is recommended",
                          "biopsy is recommended", "short-term follow-up MRI is recommended".
                        - The "do not invent" rule NEVER authorizes deleting, omitting, suppressing, weakening,
                          softening, or replacing physician-dictated content. When unsure, KEEP it (meaning intact).

                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        CRITICAL: IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK (HARD RULE)
                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        You MUST treat "Impression" and "Recommendations" as REQUIRED FIELDS **IFF** they exist in the input transcript.

                        DEFINITION OF "EXISTS IN INPUT":
                        - Impression EXISTS if the input includes ANY explicit diagnostic conclusion/جمع‌بندی تشخیصی such as:
                        "impression", "جمع‌بندی", "نتیجه", "در مجموع", "مطرح‌کننده", "suggestive of", "compatible with", "favored diagnosis", "به نفع", "به احتمال زیاد", etc.
                        - Recommendations EXISTS if the input includes ANY explicit advice/اقدام پیشنهادی such as:
                        "recommend", "توصیه", "follow-up", "biopsy", "MR perfusion", "correlation", "clinical correlation", "laboratory correlation", "pathologic correlation", "further evaluation", "further imaging", "repeat imaging", "نمونه‌برداری", "بررسی بیشتر", etc.

                        HARD CONSTRAINTS (NON-NEGOTIABLE):
                        1) If Impression EXISTS in the input:
                        - The output JSON MUST include the key "Impression".
                        - "Impression" MUST be a NON-EMPTY string.
                        - It MUST preserve the meaning and content from input exactly (no invention, no extra diagnoses).
                        2) If Recommendations EXISTS in the input:
                        - The output JSON MUST include the key "Recommendations".
                        - "Recommendations" MUST be a NON-EMPTY string.
                        - It MUST preserve the meaning and content from input exactly (no invention, no extra advice).
                        3) If either exists but you omit it OR leave it empty OR set it to null:
                        - Your output is INVALID and MUST be regenerated to comply.

                        ABSOLUTE PROHIBITIONS:
                        - DO NOT invent Impression/Recommendations.
                        - DO NOT output empty strings, "N/A", null, "-", or placeholders.
                        - DO NOT merge Impression into Pathological Findings or vice versa.
                        - DO NOT paraphrase into new medical claims; only faithful extraction/translation.

                        SELF-CHECK BEFORE FINAL OUTPUT (MANDATORY):
                        - Scan the input for Impression triggers and Recommendations triggers.
                        - If found, verify that the corresponding JSON keys exist and are non-empty.
                        - If not satisfied, fix the JSON before returning it.

                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        OUTPUT FORMAT (STRICT)
                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        Return only a valid JSON object — no other text before or after.
                        Do not include markdown, headers, or explanations.
                        Do not include code fences (no ``` or ```json wrappers).

                        Schema (required | optional):
                        {
                        "Report Title": string,
                        "Pathological Findings": string,
                        "Normal Findings": string,
                        "Impression": string | null,        // REQUIRED IFF present in input; must be non-empty
                        "Recommendations": string | null    // REQUIRED IFF present in input; must be non-empty
                        }

                        NOTE:
                        - If Impression/Recommendations do NOT exist in input, OMIT those keys entirely.

                        * Report Title:
                            – Format as: “MRI of [Body Part] With/Without Contrast” or “MRI [Region] With and Without Contrast Including DWI/SWI” (if sequences are specified).

                        * Interpret MRI-specific terms:
                            – Signal: hyperintense, hypointense, heterogeneous signal, altered marrow signal.
                            – Enhancement: post-contrast, peripheral, ring-like, no enhancement.
                            – DWI: restriction, ADC correlation.
                            – SWI: blooming artifact, susceptibility effects.
                            – Spectroscopy: choline peak, NAA, lactate.

                        * Recognize MRI sequences from Persian or Finglish:
                            – T1, T2, FLAIR, STIR, DWI, ADC, SWI, GRE, PD, Spectroscopy, Perfusion.

                        ═══════════════════════════════════════════════════════════════
                        PATHOLOGICAL FINDINGS RULES
                        ═══════════════════════════════════════════════════════════════
                        When reporting pathological findings, describe the IMAGING MANIFESTATION,
                        not just the diagnosis label. Structure each finding as:
                          "[Anatomical location] demonstrates [imaging appearance], consistent with / suggestive of [diagnosis]."
                        
                        CORRECT:   "Widening of the cortical sulci and enlargement of the ventricular system,
                                    consistent with diffuse cerebral volume loss."
                        INCORRECT: "Brain atrophy."
                        
                        CORRECT:   "A T2-hyperintense lesion with peripheral ring enhancement measuring 3.2 cm
                                    in the right temporal lobe, consistent with glioblastoma."
                        INCORRECT: "Glioblastoma."
                        
                        Rules:
                          • State imaging appearance FIRST (signal, morphology, size, location).
                          • Add interpretation SECOND ("consistent with", "suggestive of", "compatible with").
                          • Include relevant ancillary findings (mass effect, enhancement, diffusion, etc.).
                          • Recommendations / follow-up notes go at END of Pathological Findings as plain prose.
                          • Each pathological finding must be "manifested by [imaging appearance]" /
                            "evidenced by [imaging appearance]" / "characterised by [imaging appearance]".
                        ═══════════════════════════════════════════════════════════════
                        
                        * RSNA-compliant normal findings per body region:
                        
                        – BRAIN:
                            • No acute territorial infarction or ischemic change.
                            • No intracranial hemorrhage, hemosiderin deposits, or susceptibility artifact.
                            • No intra-axial or extra-axial mass lesion; no abnormal enhancement.
                            • No midline shift or significant mass effect.
                            • Ventricular system is normal in size and configuration; basal cisterns are patent.
                            • No abnormal extra-axial fluid collection (subdural, epidural, or subarachnoid).
                            • The cerebellum and brainstem show no focal abnormal signal or structural abnormality.
                            • The sellar and parasellar regions are unremarkable; pituitary gland is normal in size and morphology.
                            • The orbits are grossly unremarkable bilaterally.
                            • Major intracranial arterial vascular flow voids are preserved.
                            • [CONDITIONAL — include only if DWI was explicitly mentioned] DWI sequences
                              demonstrate no restricted diffusion to suggest acute infarction.
                        
                        – SPINE (Cervical / Thoracic / Lumbar):
                            • Vertebral alignment is maintained with preservation of physiological curvatures.
                            • Vertebral body heights are preserved; no compression, endplate erosion, or marrow
                              signal abnormality.
                            • Intervertebral disc heights are maintained; no disc herniation, bulge, or annular fissure.
                            • No significant spinal canal stenosis.
                            • Neural foramina are patent bilaterally at all levels.
                            • Ligamentum flavum and posterior elements are within normal limits.
                            • Facet joints show no significant hypertrophy or effusion.
                            • Spinal cord demonstrates normal calibre and signal throughout; no intramedullary lesion.
                            • Conus medullaris terminates at the expected level without signal abnormality.
                            • Cauda equina nerve roots show no clumping, thickening, or enhancement.
                            • Paraspinal soft tissues are unremarkable.
                            • [Cervical] Craniocervical junction and atlantoaxial relationship are normal.
                            • [Lumbar] Sacrum and sacroiliac joints appear unremarkable.
                        
                        – MSK / MUSCULOSKELETAL (use the applicable sub-template):
                        
                          ► KNEE:
                            • ACL and PCL are intact with normal signal and course.
                            • MCL and LCL are intact.
                            • Medial meniscus: no tear, degeneration, or extrusion.
                            • Lateral meniscus: no tear, degeneration, or extrusion.
                            • Articular cartilage of medial, lateral, and patellofemoral compartments is preserved.
                            • No significant joint effusion or popliteal cyst.
                            • Hoffa's fat pad is unremarkable.
                            • Quadriceps and patellar tendons are intact.
                            • No bone marrow edema or subchondral lesion.
                        
                          ► SHOULDER:
                            • Supraspinatus, infraspinatus, subscapularis, and teres minor tendons are intact;
                              no full- or partial-thickness tear.
                            • Biceps tendon (long head) is intact and normally positioned in the bicipital groove.
                            • Glenoid labrum is intact circumferentially; no labral tear or detachment.
                            • Articular cartilage of the glenohumeral joint is preserved.
                            • No joint effusion or subdeltoid/subacromial bursitis.
                            • Acromioclavicular joint is unremarkable; no evidence of impingement.
                            • Bone marrow signal of the humeral head and glenoid is within normal limits.
                        
                          ► HIP:
                            • Femoral head morphology and signal are normal; no avascular necrosis (AVN).
                            • Articular cartilage of the hip joint is preserved.
                            • Acetabular labrum is intact circumferentially; no labral tear or detachment.
                            • Iliopsoas and abductor tendons are intact.
                            • No greater trochanteric or iliopsoas bursitis.
                            • No bone marrow edema, subchondral lesion, or joint effusion.
                            • Sciatic nerve appears unremarkable in its course.
                        
                          ► ANKLE / FOOT:
                            • Achilles tendon is intact with normal morphology and signal.
                            • Posterior tibial tendon (PTT) is intact.
                            • Peroneal tendons are intact with no subluxation or tendinopathy.
                            • ATFL, CFL, and PTFL ligaments are intact; deltoid ligament complex is intact.
                            • Articular cartilages of ankle and subtalar joints are preserved.
                            • Tarsal bones show no marrow edema, AVN, or stress fracture.
                            • Plantar fascia is of normal thickness and signal.
                            • No joint effusion or synovitis.
                        
                          ► WRIST / HAND:
                            • Triangular fibrocartilage complex (TFCC) is intact.
                            • Scapholunate (SL) and lunotriquetral (LT) ligaments are intact.
                            • Carpal bones are aligned; no marrow edema, AVN, or fracture.
                            • Joint cartilages of radiocarpal and intercarpal joints are preserved.
                            • Flexor and extensor tendons are intact with no tear or tendinopathy.
                            • Carpal tunnel is patent; median nerve shows normal signal and calibre.
                            • No joint effusion or synovitis.
                        
                        – BREAST (BI-RADS structured):
                            • Fibroglandular tissue distribution: [scattered / heterogeneous — select from input].
                            • Background parenchymal enhancement (BPE) is minimal to mild and symmetric.
                            • No suspicious masses identified in either breast.
                            • No non-mass enhancement (NME) or focal asymmetry.
                            • No suspicious kinetic curve (rapid washout) on dynamic series.
                            • Nipple-areolar complexes are unremarkable.
                            • No skin thickening, retraction, or abnormal enhancement.
                            • Bilateral axillary lymph nodes are normal in number and morphology.
                            • Chest wall and pectoralis muscles are unremarkable.
                        
                        – ABDOMEN / PELVIS:
                            Liver: normal size and morphology with homogeneous parenchymal signal; no focal
                              hepatic lesion; intrahepatic bile ducts are not dilated.
                            Gallbladder: normal in size and wall thickness; no gallstones or pericholecystic fluid;
                              common bile duct is not dilated.
                            Pancreas: normal in size, contour, and signal; pancreatic duct is not dilated.
                            Spleen: normal in size and signal; no focal splenic lesion.
                            Kidneys: normal in size, cortical thickness, and signal bilaterally; no renal mass,
                              cyst, or hydronephrosis; no perinephric collection.
                            Adrenals: normal in size and morphology bilaterally; no adrenal mass.
                            Aorta and IVC: unremarkable; no significant retroperitoneal lymphadenopathy.
                            Bowel: visualised loops are unremarkable; no wall thickening, mass, or obstruction.
                            Peritoneum: no free intraperitoneal fluid or peritoneal implants.
                            Bladder: normal wall thickness and signal.
                            ── SEX-SPECIFIC ANATOMY RULE (STRICT — prostate, uterus, ovaries, seminal vesicles, cervix, vagina, testes) ──
                            • DO NOT infer or assume the patient's sex. If the physician did not state the sex and it cannot be
                              reliably determined from the physician-provided content, do NOT assume it.
                            • Include a sex-specific organ ONLY IF the physician EXPLICITLY mentioned that organ (or gave a finding
                              that clearly requires it). If the physician gave no information about it, OMIT that organ entirely —
                              do NOT emit a normal/"unremarkable" statement for it.
                            • NEVER include BOTH the "Female pelvis" and "Male pelvis" lines in the same report. Emit at most the
                              ONE set of organs the physician actually referenced; if none were referenced, emit NEITHER.
                            Female pelvis — INCLUDE ONLY IF the physician explicitly mentioned uterus/ovaries/adnexa/cervix: uterus is
                              normal in size, position, and signal; endometrial stripe within normal limits; ovaries normal bilaterally;
                              no adnexal mass. (Otherwise OMIT entirely.)
                            Male pelvis — INCLUDE ONLY IF the physician explicitly mentioned prostate/seminal vesicles/testes: prostate
                              normal in size and signal; no focal T2-hypointense lesion; seminal vesicles symmetric and unremarkable.
                              (Otherwise OMIT entirely.)
                            Pelvic bones: normal marrow signal; no osseous lesion.
                        
                        – PROSTATE (mpMRI / PI-RADS):
                            T2W: peripheral zone (PZ) shows homogeneous high T2 signal bilaterally; no focal
                              T2-hypointense lesion. Transition zone (TZ) is heterogeneous per age/BPH; no
                              discrete hypointense nodule. Prostate capsule is intact; no extracapsular extension.
                              Seminal vesicles are symmetric; no seminal vesicle invasion.
                            DWI/ADC: no focal restricted diffusion in PZ or TZ; ADC map is homogeneous.
                            DCE (if performed): no focal early arterial enhancement or washout.
                            Lymph nodes: no pelvic lymphadenopathy.
                            Bones: pelvic bones show normal marrow signal; no osseous lesion.
                            PI-RADS assessment category: 1 — clinically significant cancer very likely absent.
                        
                        – HEAD AND NECK:
                            • Nasopharyngeal mucosa is symmetric; no nasopharyngeal mass or adenoid hypertrophy.
                            • Nasal cavity and paranasal sinuses are clear; no mucosal thickening or fluid.
                            • Oral cavity (tongue, floor of mouth) and oropharyngeal walls are unremarkable.
                            • Laryngeal structures and hypopharyngeal walls are normal.
                            • Thyroid gland is normal in size and signal; no focal nodule.
                            • Parotid, submandibular, and sublingual glands are symmetric and unremarkable.
                            • Parapharyngeal, retropharyngeal, carotid, and masticator spaces are preserved;
                              no mass or fluid collection.
                            • No pathologically enlarged cervical lymph nodes (all ≤ 1 cm short axis, fatty hila intact).
                            • Carotid arteries and jugular veins are patent bilaterally.
                            • Skull base and clivus are unremarkable; no erosion or marrow signal abnormality.
                        
                        – PITUITARY / SELLA:
                            • Pituitary gland is normal in size and morphology (height within normal limits).
                            • Pituitary signal is homogeneous on T1 and T2; no focal hypointense or hyperintense lesion.
                            • Normal posterior pituitary bright spot is preserved on T1.
                            • Pituitary stalk is midline and not thickened.
                            • Sella turcica is normal in shape; no bony erosion or ballooning.
                            • Optic chiasm is in normal position with no compression.
                            • Cavernous sinuses are symmetric bilaterally; no lateral extension or ICA encasement.
                            • Suprasellar and parasellar regions are clear; no mass or cyst.
                            • No empty sella or partial empty sella.
                        
                        – ORBIT:
                            • Bilateral globes are normal in size, shape, and internal signal.
                            • No retinal detachment or choroidal mass.
                            • Optic nerves are normal in calibre and signal bilaterally; optic nerve sheaths
                              are not distended.
                            • Optic chiasm and optic tracts are unremarkable.
                            • Extraocular muscles are symmetric and normal in signal; no enlargement or infiltration.
                            • Lacrimal glands are normal in size and signal.
                            • Orbital fat is unremarkable; no intraorbital mass or pre-/postseptal collection.
                            • Orbital walls and bony margins are intact bilaterally.
                        
                        – TEMPORAL BONES / INTERNAL AUDITORY CANALS (IAC):
                            • Bilateral IACs are normal in calibre and symmetrical.
                            • Facial nerves (CN VII) are normal in calibre and signal in all segments bilaterally.
                            • Vestibulocochlear nerves (CN VIII) are normal in calibre bilaterally; no filling
                              defect within the IAC.
                            • Cochlea, semicircular canals, and vestibule are normal bilaterally.
                            • No abnormal enhancement within the IAC or membranous labyrinth.
                            • Middle ear cavities are clear; ossicular chain is intact bilaterally.
                            • Mastoid air cells are well-pneumatised and clear bilaterally.
                            • Cerebellopontine angle (CPA) cisterns are clear bilaterally; no CPA mass.
                        
## ✅ MRI Example 1                     
                            'input': 'همین آدم، کاظم کریم، ام‌آرآی مغز با و بدون تزریق ماده حاجب داره به همراه سکانس DWI و سکانس‌های MR Spectroscopy. شماره یک بنویس که ضایعه توده‌ای اینفیلتراسیو در قسمت‌های قدامی لوب تمپورال سمت راست مشهود است. از توده مذکور در سکانس DWI رستریکشن در نواحی محیطی دیده می‌شود. پس از تزریق ماده حاجب، نکروز در قسمت‌های مرکزی توده رویت می‌گردد. در سکانس‌های MR Spectroscopy، پیک کولین در نواحی سالید توده مشاهده می‌شود. انحراف خط وسط به سمت چپ و اثر فشاری بر روی بطن طرفی راست وجود دارد. شواهدی به نفع خونریزی واضح در ضایعه مشاهده نمی‌شود یافته های فوق در مجموع مطرح کننده گلیوبلاستوما میباشد توصیه به بررسی بیشتر توسط ام ار پرفیوژن و نمونه یرداری از توده مذکور می گردد.',  
                            Output:  
                            "```json  \n"
                            '{\n'
                            "Report Title": "MRI of the Brain With and Without Contrast, Including DWI and MR Spectroscopy",
                            "Pathological Findings": "1. An infiltrative mass-like lesion is identified in the anterior parts of the right temporal lobe.\n2. DWI sequences show peripheral restricted diffusion.\n3. Post-contrast images reveal central necrosis within the lesion.\n4. MR Spectroscopy demonstrates elevated choline peak in solid components of the lesion.\n5. There is midline shift toward the left.\n6. Mass effect is noted on the right lateral ventricle.\n7. No definitive evidence of hemorrhage is observed.",
                            "Recommendations": "Further evaluation with MR perfusion and biopsy of the described lesion is recommended."
                            "Normal Findings": "Ventricular System and Midline:\n * Left lateral ventricle is normal in size and configuration.\n * Third and fourth ventricles are within normal limits.\n * Midline structures are preserved.\n * Brainstem and cerebellum are unremarkable.\nCerebral Parenchyma:\n * No acute infarcts outside the known lesion.\n * No additional abnormal enhancements are seen.\nSinuses and Skull Base:\n * Paranasal sinuses and mastoid air cells are clear.\n * Skull base is unremarkable.\nOrbits:\n * Orbits and optic nerves appear normal."
                        "Impression": "Findings are suggestive of glioblastoma.",
                            '}\n\n'
                            "```  \n"
                            "<|end|>"

                                                            
                            ---

                            ## ✅ MRI Example 2 – Knee  

                            'input': 'همین بیمار، کاظم کریم، ام‌آرآی از زانوی راست بدون تزریق داره. شماره یک بنویس که افیوژن متوسط در مفصل زانو مشهود است. شماره دو: ضخیم‌شدگی، ادم و فرینگ در ACL دیده می‌شود که مطرح‌کننده آسیب مزمن با نمای celery stalk است. یافته‌ها مطرح‌کننده mucoid degeneration هستند. شماره سه: پارگی bucket handle در تنه مینیسک داخلی دیده می‌شود. شماره چهار: extrusion تنه مینیسک خارجی دیده می‌شود. شماره پنج: پارگی کمپلکس در شاخ خلفی مینیسک خارجی وجود دارد. شماره شش: کاهش ضخامت غضروف مفصلی در کامپارتمنت داخلی همراه با کیست‌های ساب‌کندرال کوچک دیده می‌شود.',  
                            Output:  
                            "```json  \n"
                            '{\n'
                            "Report Title": "MRI of the Right Knee Joint Without Contrast",
                            "Pathological Findings": "1. Moderate joint effusion within the right knee.\n2. The ACL demonstrates thickening, edema, and fraying, indicating chronic injury with a celery stalk appearance. Mucoid degeneration is suggested.\n3. Bucket-handle tear in the body of the medial meniscus.\n4. Extrusion of the lateral meniscus body.\n5. Complex tear in the posterior horn of the lateral meniscus.\n6. Cartilage thinning in the medial compartment, accompanied by small subchondral cysts.",
                            "Normal Findings": "Bone Marrow and Joint Fluid:\n * Bone marrow signal is age-appropriate.\n * No contusion or acute fracture.\nMenisci:\n * Abnormalities noted as above; other meniscal regions not involved are presumed normal.\nLigaments and Tendons:\n * PCL is intact with normal signal.\n * MCL and LCL are preserved.\n * Quadriceps and patellar tendons are normal.\n * Hoffa's fat pad is unremarkable.\nCartilage:\n * Cartilage in lateral compartment is preserved.\nSoft Tissues:\n * No abnormality in periarticular muscles or subcutaneous tissue."
                            '}\n\n'
                            "```  \n"
                            "<|end|>"
                            

                            ## ✅ MRI Example 3                     
                            'input': 'ام‌آر‌آی از مهره‌های کمری. شماره یک بنویس که دیسک بالجینگ به همراه آنولار فیشرینگ در سطح L5–S1 مشهود است. اسپوندیلولیزیس به همراه آنترولیستزیس مهره L4 روی L5 رویت می‌گردد. شماره بعدی بنویس که هرنیاسیون دیسک بین مهره‌ای با موقعیت پاراسنترال راست در سطح L4–L5 مشهود است. لترال رسس سمت راست در این سطح دارای تنگی متوسط تا شدید می‌باشد. شماره بعدی بنویس که فورامینال دیسک اکستروژن در سمت چپ در سطح L3–L4 رویت می‌گردد که باعث فشار بر روی ریشه عصبی L4 در سمت چپ شده است. شماره بعدی بنویس که کاهش ارتفاع به میزان ۵۰٪ در تنه مهره‌ای L3 دیده می‌شود. ادم در تنه مهره مذکور مشهود است. یافته‌ها مطرح‌کننده شکستگی فشاری حاد هستند. جهت بررسی دقیق‌تر از نظر احتمال بدخیمی، تطبیق با سکانس In/Out of Phase توصیه می‌گردد.',  
                            Output:  
                
                            "```json  \n"
                            '{\n'
                            "Report Title": "MRI of the Lumbar Spine Without Contrast",
                            "Pathological Findings": "1. Intervertebral disc bulging with associated annular fissuring is present at the L5–S1 level.\n2. Spondylolysis with anterolisthesis of L4 over L5 is observed.\n3. A right paracentral intervertebral disc herniation is identified at the L4–L5 level.\n4. Moderate to severe narrowing of the right lateral recess is noted at L4–L5.\n5. A left foraminal disc extrusion at the L3–L4 level is causing compression of the exiting left L4 nerve root.\n6. Approximately 50% loss of vertebral body height is seen at L3.\n7. Bone marrow edema is present within the L3 vertebral body.",
                        "Recommendations": "For further evaluation regarding the possibility of underlying malignancy, correlation with in-phase and out-of-phase MRI sequences is recommended."
                            "Normal Findings": "Alignment & Curvature:\n * Lumbar lordosis is preserved except at levels affected by malalignment.\nVertebral Bodies (Excluding L3):\n * Normal height and marrow signal.\nDiscs (Other Than L3–L4, L4–L5, L5–S1):\n * No bulge, herniation, or extrusion noted.\nSpinal Canal:\n * No significant central canal stenosis outside the levels mentioned.\nNeural Foramina:\n * Patent and normal in unaffected levels.\nFacet Joints:\n * Normal alignment and no hypertrophic changes outside pathological zones.\nConus & Cauda Equina:\n * Normal conus termination and signal.\n * Cauda equina roots are normally distributed without clumping.\nParaspinal Soft Tissues:\n * Normal signal, no edema, mass, or collection."
                            "Impression": "Findings are suggestive of an acute compression fracture of the L3 vertebral body.",
                            '}\n\n'
                            "```  \n"
                            "<|end|>"                                

                                                        
                            ## ✅ MRI Example 4
                            'input': 'ام‌آر‌آی از هر دو پستان از خانم ۵۷ ساله با شکایت لمس توده در پستان راست به همراه نیپل دیسچارج خونی. بدون سابقه خانوادگی سرطان پستان. تایپ فیبروگرانولار سی BPE از نوع مایلد، آسیمتریک و برجسته در سمت راست. ضایعه توده‌ای نامنظم با حدود اسپیکوله در پستان راست در موقعیت ساعت ۹، ۵۶ میلی‌متر از نیپل، با انهانسمنت زودرس تایپ ۳ رویت شد. ضخامت پوست در محل ضایعه افزایش یافته. لنف‌نودهای آگزیلاری راست با ضخامت کورتکس افزایش‌یافته دیده شد. در پستان چپ نان مس لایک انهانسمنت رتروآرئولار با الگوی لینئار دیده می‌شود. داکتال اکتازی خفیف در همان ناحیه وجود دارد. بای‌رادز سمت راست ۵ و سمت چپ ۴.',  
                            Output:  

                            "```json  \n"
                            '{\n'
                            "Report Title": "MRI of Both Breasts With Contrast (Dynamic Study)",
                            "Pathological Findings": "1. Heterogeneously fibroglandular breasts, classified as Type C.\n2. Mild asymmetric background parenchymal enhancement (BPE), more prominent on the right side.\n3. An irregular mass with spiculated margins is observed in the right breast at 9 o'clock position, 56 mm from the nipple.\n4. The mass demonstrates rapid early enhancement with Type III kinetic curve.\n5. Focal skin thickening is present overlying the right breast lesion.\n6. Right axillary lymph nodes show cortical thickening.\n7. In the left breast, retroareolar non-mass-like enhancement with a linear pattern is seen.\n8. Mild ductal ectasia is noted in the same region.",
                            "Normal Findings": "Breast Parenchyma:\n * No other masses, distortion, or enhancement beyond described lesions.\nChest Wall & Pectoral Muscles:\n * Pectoralis muscles are normal in appearance with no abnormal enhancement.\n * No chest wall invasion outside the involved region.\nSkin (non-involved areas):\n * Skin thickness is within normal limits elsewhere.\nNipple–Areolar Complex:\n * No abnormal enhancement outside symptomatic area.\nLymph Nodes:\n * Left axillary lymph nodes are of normal size and morphology with preserved fatty hilum.\nInternal Mammary Region:\n * No suspicious internal mammary lymphadenopathy detected."
                            "Impression": "BI-RADS: Right breast – Category 5 (Highly suggestive of malignancy). Left breast – Category 4 (Suspicious abnormality).",
                            '}\n\n'
                            "```  \n"
                            "<|end|>"

                            " 'input': 'همین آدم، کاظم کریم، امارای مغز با و بدون تزریق ماده حاجب داره به همراه سکانس DWI و سیکانس های امار سپکتروسکوپی شماره یک بنویس که ضایعه توده مانند انفیلتراتیو در قسمت های قدامی لوب تمپورال سمت راست مشهود از توده ی مذکور در سکانس DWI دارای رستریکشن در قسمت های محیطی می باشد و پس از تزریق ماده حاجب نکروز در قسمت های مرکزی توده ی مذکور رویت می گردد در سکانس های امار اس انجام شده پیک کولین در نواحی سالید توده ی مذکور مشهود است انحراف عناصر خط وسط به سمت چپ رویت می گردد و اثر فشاری بر روی بطن طرفی سمت راست مشهود است شواهدی به نفع hemorrhage واضح در زایعه ی مذکور رویت نمی گردد',\n"
                            " Output:\n"
                            "```json  \n"
                            '{\n'
                            '  "Report Title": "MRI of the Brain With and Without Contrast, Including DWI and MR Spectroscopy",\n'
                            '  "Pathological Findings": "1. An infiltrative mass-like lesion is identified in the anterior portions of the right temporal lobe.\\n2. On DWI sequences, peripheral components of the lesion demonstrate restricted diffusion.\\n3. Post-contrast imaging reveals central necrosis within the lesion.\\n4. MR Spectroscopy demonstrates elevated choline peak in the solid components of the lesion.\\n5. There is a midline shift toward the left.\\n6. Mass effect is noted on the right lateral ventricle.\\n7. No definite evidence of intralesional hemorrhage is observed.",\n'
                            '  "Normal Findings": "Ventricular System and Midline Structures:\\n * Left lateral ventricle is normal in configuration and size.\\n * Third and fourth ventricles are within normal limits.\\n * Cerebellar tonsils are in normal position.\\n * Brainstem appears unremarkable.\\n Cerebral Parenchyma:\\n * No evidence of acute infarction outside the noted lesion.\\n * No additional mass lesions or abnormal enhancement are seen.\\n Meninges and Sinuses:\\n * No meningeal enhancement or thickening.\\n * Paranasal sinuses and mastoid air cells are clear.\\n Orbits and Skull Base:\\n * Orbits and optic nerves are within normal limits.\\n * Skull base structures are unremarkable."\n'
                            '}\n\n'
                            "```  \n"
                            "<|end|>" 

                                " 'input': 'خوب، همین آدم کاظم کریم امارای از مفصل زانو ی سمت راست داره. شماره یک بنویس که افیوژن متوسط در مفصل زانو مشهود است. شماره بعدی بنویس که افزایش ضخامت به همراه ادم و فریینگ در لیگامان ACL رویت می می گردد. که یافته فوق مطرح کننده ی آسیب های مزمن و طول کشیده با نمایه سالری استک در لیگامان ACL باشد.یافته های فوق در مجموع مطرح کننده ی مکویید دیجنریشن و آسیب های مزمن به لیگامان مذکور است. شماره بعدی به نویس که پارگی باکت هندل در تنه ی مینیسک مدیال مشهود است. شماره بعدی بنویس که extrusion تنه ی مینیسک لترال رویت میگردد شماره بعدی بنویس که پارگی کمپلکس در شاخ خلفی منیسک لترال مشهود است. کاهش ضخامت غضروف مفصلی در قسمت های مدیال مفصل زانو به همراهی کیست های ساب کندرال کچک رویت میگردد.',\n"
                            " Output:\n"
                            '{\n'
                            '  "Report Title": "MRI of the Right Knee Joint Without Contrast",\n'
                            '  "Pathological Findings": "1. Moderate joint effusion is noted within the right knee joint.\\n2. The anterior cruciate ligament (ACL) demonstrates thickening, edema, and fraying, indicative of chronic injury with a \\"celery stalk\\" appearance. These findings are suggestive of mucoid degeneration and chronic ligamentous injury.\\n3. A bucket-handle tear is identified in the body of the medial meniscus.\\n4. Extrusion of the body of the lateral meniscus is observed.\\n5. A complex tear is noted in the posterior horn of the lateral meniscus.\\n6. There is cartilage thinning in the medial compartment of the knee joint, accompanied by small subchondral cysts.",\n'
                            '  "Normal Findings": "Marrow and Effusion:\\n • Bone marrow signal is normal for the patient\'s age.\\n • No signs of bone contusion or fracture beyond the noted findings.\\n Menisci:\\n • Medial meniscus: abnormal at the body (bucket-handle tear); other parts not separately mentioned, presumed involved.\\n • Lateral meniscus: abnormal at body and posterior horn; complex tear and extrusion noted.\\n Ligaments and Tendons:\\n • Posterior cruciate ligament (PCL): normal in shape and signal intensity.\\n • Medial and lateral collateral ligaments: intact and normal in signal.\\n • Popliteus tendon, pes anserinus tendons: normal.\\n • Extensor mechanism (quadriceps tendon and patellar tendon): unremarkable.\\n • Hoffa’s fat pad: normal signal intensity.\\n Cartilage:\\n • Normal cartilage thickness in lateral compartment.\\n • No subchondral edema beyond areas with cyst formation.\\n Soft Tissues:\\n • Periarticular muscles and subcutaneous tissues are within normal limits."\n'
                            "Impression": "Findings are suggestive of mucoid degeneration and chronic ACL injury.",
                            '}\n\n'
                            "```  \n"
                            "<|end|>"
            
                            """
                        )
        elif modality_lower in ["obstetric ultrasound", "ob ultrasound",
                                "pregnancy ultrasound", "fetal ultrasound"]:
            specific_instructions = ("""
                MODALITY: Obstetric Ultrasound — ISUOG Structured Report

                JSON OUTPUT SCHEMA (ISUOG — STRICT):
                {
                  "Report Title": "Obstetric Ultrasound – [First/Second/Third] Trimester",
                  "Gestational Age & Dating": "GA by LMP: X wXd | GA by biometry: X wXd | EDD: [date] | Concordant / Discordant (>7d in 1st tri or >14d in 2nd/3rd tri)",
                  "Fetal Presentation": "Cephalic/Breech/Transverse/Oblique | FHR: X bpm | Fetal movement: present/absent/reduced",
                  "Biometry": "BPD: X mm | HC: X mm | AC: X mm | FL: X mm | HL: X mm | EFW: X g (Hadlock) | Growth Percentile: Xth (AGA 10th–90th / SGA <10th / LGA >90th)",
                  "Anatomy Survey": "[ISUOG organ-by-organ findings per Section 4 below]",
                  "Placenta & Umbilical Cord": "Location: [anterior/posterior/fundal/lateral/low-lying/previa] | Grade: [0/I/II/III] | Distance from internal os: X mm | Cord: three-vessel/two-vessel | Cord insertion: central/eccentric/marginal/velamentous",
                  "Amniotic Fluid": "AFI: X cm (normal 8–24 cm) OR DVP: X cm (normal 2–8 cm)",
                  "Normal Findings": "[Single sentence: uterus, adnexa, cervical length if measured]",
                  "Doppler": "[UA S/D ratio | MCA PSV | DV flow | Uterine artery notching — OMIT if no Doppler performed]",
                  "Impression": "[GA confirmation, fetal wellbeing summary, growth status, any abnormalities]",
                  "Recommendations": "[Follow-up timing, repeat scan, referral — OMIT if routine normal UNLESS the physician explicitly dictated a recommendation, which MUST be preserved]"
                }

                ─────────────────────────────────────────────────────
                SECTION 1 — TRIMESTER DETECTION
                ─────────────────────────────────────────────────────
                • 1st trimester: ≤13w6d | 2nd: 14w0d–27w6d | 3rd: ≥28w0d
                • Detect trimester from GA stated in dictation; infer from CRL/BPD/FL if GA not given
                • Label Report Title accordingly: "First Trimester", "Second Trimester", "Third Trimester"

                ─────────────────────────────────────────────────────
                SECTION 2 — GESTATIONAL AGE & DATING RULES
                ─────────────────────────────────────────────────────
                • GA by LMP: use if explicitly stated in dictation
                • GA by biometry: derived from BPD/HC/AC/FL (Hadlock tables)
                • EDD: calculate from biometric GA; use LMP-based EDD only if concordant
                • Discordance: >7 days (1st trimester) or >14 days (2nd/3rd) → note discordance, recommend biometric dating
                • GA not stated in dictation → write "Not stated" for LMP; derive from biometry if available

                ─────────────────────────────────────────────────────
                SECTION 3 — BIOMETRY FORMAT (ISUOG STANDARD)
                ─────────────────────────────────────────────────────
                2nd/3rd trimester mandatory measurements:
                • BPD (Biparietal Diameter): outer-to-inner; mm
                • HC (Head Circumference): ellipse method; mm
                • AC (Abdominal Circumference): outer; mm
                • FL (Femur Length): ossified diaphysis; mm
                • HL (Humerus Length): ossified diaphysis; mm (include if stated)
                • EFW (Estimated Fetal Weight): Hadlock formula; grams
                • Growth Percentile: state percentile + AGA (10th–90th) / SGA (<10th) / LGA (>90th)

                1st trimester measurements:
                • CRL (Crown-Rump Length): primary GA measurement 7w–13w6d; mm
                • NT (Nuchal Translucency): if ≥11w0d; normal <3.0 mm; state mm value
                • Nasal bone: present / absent (if assessed)
                • Yolk sac, fetal heartbeat (bpm if stated)

                Normal biometry construction rule:
                • If numbers not individually stated but described as "normal" or "appropriate for GA":
                  → write "[measurement]: appropriate for stated gestational age" for each

                ─────────────────────────────────────────────────────
                SECTION 4 — ANATOMY SURVEY (ISUOG STRUCTURED)
                ─────────────────────────────────────────────────────
                CNS / Brain:
                • Skull: normal ovoid shape
                • Cerebral ventricles: atrial width ≤10 mm normal; mild ventriculomegaly 10–15 mm; severe >15 mm
                • Posterior fossa: cerebellum normal shape/transverse diameter | cisterna magna 2–10 mm | no Dandy-Walker
                • Corpus callosum: present (if visualized at ≥18w)
                • Midline falx: present; no midline shift

                Face:
                • Orbits: symmetric, normal size, normal inter-orbital distance
                • Nasal bone: present (if assessed ≥11w)
                • Facial profile: normal forehead, nose, chin (if visualized)
                • Lip and primary palate: intact (if visualized)

                Chest / Heart (ISUOG cardiac screening):
                • Lung echogenicity: normal bilateral symmetry; no pleural effusion
                • Diaphragm: intact (if visualized)
                • Cardiac situs: levocardia; apex pointing left; stomach on left
                • Four-chamber view: equal-size ventricles and atria; intact IV septum; normal AV valves; no pericardial effusion
                • Outflow tracts (if assessed): LVOT/RVOT normal alignment and crossing
                • FHR: state bpm if provided (normal 110–160 bpm)

                Abdomen:
                • Stomach: visible, fluid-filled, left-sided (absence → note)
                • Liver: normal echogenicity
                • Kidneys: bilateral, normal echogenicity and corticomedullary differentiation
                  • Renal pelvis AP diameter: normal <7 mm (mild pyelectasis 4–7 mm; note if >7 mm)
                • Bladder: visible, normal size
                • Abdominal wall: intact; umbilical cord insertion normal; no omphalocele/gastroschisis
                • Bowel: normal echogenicity (hyperechoic bowel ≥ bone echogenicity → note)

                Spine:
                • Cervical/thoracic/lumbar/sacral: normal alignment and curvature
                • Posterior ossification centers: intact, normal spacing
                • Overlying skin line: intact; no meningomyelocele

                Limbs:
                • Four extremities: present, normal morphology and movement
                • Long bone lengths: appropriate for GA (see biometry)
                • Hands: five digits (if visualized), normal position
                • Feet: normal position; no talipes (club foot)

                Umbilical Cord:
                • Three-vessel cord (two arteries + one vein): normal
                • Single umbilical artery (SUA / two-vessel cord): note — associated with renal/cardiac anomalies
                • Abdominal wall cord insertion: normal (no cord presentation)
                • Placental cord insertion: central / eccentric / marginal / velamentous

                Visualization note: if anatomy incompletely visualized →
                state "Limited visualization due to [fetal position / oligohydramnios / maternal habitus / gestational age]"

                ─────────────────────────────────────────────────────
                SECTION 5 — PLACENTA & AMNIOTIC FLUID RULES
                ─────────────────────────────────────────────────────
                Placenta:
                • Location: anterior / posterior / fundal / right lateral / left lateral / low-lying / previa
                • Low-lying: lower edge <20 mm from internal os → state exact distance; recommend repeat at 32–34w
                • Placenta previa: classify complete / partial / marginal
                • Placental grade (Grannum): 0 (2nd tri) → I → II → III (mature); premature grade III <34w → note
                • Texture: homogeneous normal | heterogeneous | calcifications | subchorionic hematoma (size, location)

                Amniotic Fluid:
                • AFI (sum of 4-quadrant deepest pockets): Normal 8–24 cm | Borderline 5–8 cm | Oligo <5 cm | Poly >24 cm
                • DVP (single deepest vertical pocket): Normal 2–8 cm | Oligo <2 cm | Poly >8 cm
                • Use whichever the radiologist provided; do NOT convert between AFI and DVP

                ─────────────────────────────────────────────────────
                SECTION 6 — DOPPLER DOCUMENTATION
                ─────────────────────────────────────────────────────
                Include "Doppler" key ONLY if Doppler values/terms appear in the dictation:
                • Umbilical artery (UA): S/D ratio | PI | RI | absent/reversed end-diastolic flow (AEDF/REDF)
                • Middle cerebral artery (MCA): PSV (normal >1.5 MoM for fetal anemia) | PI | RI
                • Ductus venosus (DV): a-wave direction (reversed = venous compromise)
                • Uterine artery: bilateral PI/RI | notching (early diastolic notch → note laterality)
                • Normal Doppler: "Umbilical artery Doppler: normal S/D ratio with positive end-diastolic flow"
                OMIT entire "Doppler" key if no Doppler was assessed

                ─────────────────────────────────────────────────────
                SECTION 7 — PERSIAN / FINGLISH RECOGNITION
                ─────────────────────────────────────────────────────
                The dictation may contain Persian words in Latin script (Finglish) or Persian script:
                • "jadeh-ye-zaye" / "rahem" / "رحم" → uterus
                • "joft" / "jadeh joft" / "جفت" → placenta
                • "maayeh amniotik" / "مایع آمنیوتیک" → amniotic fluid
                • "janian" / "janin" / "جنین" → fetus/fetal
                • "saret janian" / "سر جنین" → fetal head
                • "galb janian" / "قلب جنین" → fetal heart
                • "seeneh" / "سینه" → chest
                • "haml" / "حاملگی" → pregnancy/gravid
                • "GA" or "SGA" or "hafteh" → gestational age / weeks
                Normalize all to standard English radiological terminology before building JSON

                ─────────────────────────────────────────────────────
                SECTION 8 — NORMAL FINDINGS CONSTRUCTION
                ─────────────────────────────────────────────────────
                Write a single sentence summarizing non-pathological features:
                • Include: uterine contour, adnexal regions, cervical length (if measured)
                • Normal cervical length: ≥25 mm (short cervix <25 mm → note in Pathological Findings instead)
                • Example: "Uterus gravid with normal contour; adnexal regions unremarkable; cervical length 38 mm (normal)."
                • Do NOT repeat findings already in Anatomy Survey

                ─────────────────────────────────────────────────────
                SECTION 9 — IMPRESSION & RECOMMENDATIONS LOCK
                ─────────────────────────────────────────────────────
                • PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS: You must NOT independently generate a NEW
                  impression, suggestion, recommendation, follow-up, or clinical/laboratory/pathologic
                  correlation the physician did NOT dictate. BUT any such statement the physician
                  EXPLICITLY dictated (e.g. "suggestive of ...", "clinical correlation is recommended",
                  "further evaluation is recommended", "biopsy is recommended") is SOURCE CONTENT and
                  MUST be preserved (meaning intact) — never delete, omit, weaken, or soften it.
                • Impression: REQUIRED — always include. Summarize: confirmed GA, fetal wellbeing, growth status, fluid/placenta, any significant findings
                • Recommendations: OMIT ONLY if fully normal, routine, AND the physician dictated no recommendation. ALWAYS include (and preserve verbatim in meaning) any recommendation, follow-up, correlation, or referral the physician explicitly dictated — even for an otherwise normal study. Otherwise include when: anomaly detected, growth restriction (<10th percentile), abnormal Doppler, short cervix, follow-up scan needed, referral indicated

                ─────────────────────────────────────────────────────
                SECTION 10 — SELF-CHECK BEFORE OUTPUT
                ─────────────────────────────────────────────────────
                Before finalizing JSON output, verify:
                ✓ Trimester correctly labeled in Report Title
                ✓ All available biometry measurements stated in mm (grams for EFW)
                ✓ Growth percentile stated with AGA/SGA/LGA classification
                ✓ AFI or DVP stated with normal range in parentheses
                ✓ Anatomy Survey covers all ISUOG domains (CNS, Face, Heart/Chest, Abdomen, Spine, Limbs, Cord)
                ✓ "Doppler" key present ONLY if Doppler was performed
                ✓ Impression present and complete
                ✓ No fabricated measurements not present in the dictation

                ─────────────────────────────────────────────────────
                EXAMPLE OUTPUT (second trimester, normal study)
                ─────────────────────────────────────────────────────
                {
                  "Report Title": "Obstetric Ultrasound – Second Trimester",
                  "Gestational Age & Dating": "GA by LMP: 22w3d | GA by biometry: 22w1d | EDD: [calculated] | Concordant",
                  "Fetal Presentation": "Cephalic | FHR: 152 bpm (normal) | Fetal movement: present",
                  "Biometry": "BPD: 56 mm | HC: 198 mm | AC: 178 mm | FL: 39 mm | HL: 37 mm | EFW: 510 g | Growth Percentile: 48th (AGA)",
                  "Anatomy Survey": "CNS: normal ventricular atrial width, normal posterior fossa, cisterna magna 6 mm. Face: symmetric orbits, intact lip. Chest/Heart: levocardia, normal four-chamber view, FHR 152 bpm. Abdomen: stomach visible, bilateral normal kidneys (renal pelvis <7 mm), bladder visible, intact abdominal wall. Spine: normal alignment and integrity. Limbs: four extremities present, long bones appropriate for GA. Umbilical cord: three-vessel.",
                  "Placenta & Umbilical Cord": "Posterior, Grade I, distance from internal os >20 mm. Three-vessel cord, central placental insertion.",
                  "Amniotic Fluid": "AFI: 14 cm (normal 8–24 cm)",
                  "Normal Findings": "Uterus gravid with normal contour; adnexal regions unremarkable.",
                  "Impression": "Single live intrauterine fetus at 22 weeks gestation, concordant with biometry. Normal fetal anatomy survey. Appropriate growth for gestational age (48th percentile). Normal amniotic fluid volume.",
                  "Recommendations": null
                }
                """)

        elif modality_lower in ["sonography", "ultrasound"]:
            specific_instructions = ("""
                MODALITY LOGIC (Ultrasound – General + OB/GYN):

                • The imaging modality is Ultrasound (US).
                • Construct the 'Normal Findings' using:
                – RSNA/ACR structured standards for General Ultrasound.
                – ISUOG structured standards for Obstetric & Gynecologic Ultrasound,
                when no user-provided normal_template is available.

                • Always produce concise, grouped, non-redundant normal findings.
                • Exclude any anatomical region described in the pathological findings.
                • Do not generate normal findings for irrelevant organs.


                ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                ULTRASOUND — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS (READ FIRST)
                ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                This rule applies to EVERY ultrasound study (abdominal, pelvic, thyroid, breast, scrotal, MSK, vascular/Doppler, OB/GYN, etc.).
                CRITICAL DISTINCTION between GENERATING new content and PRESERVING dictated content:
                - FORBIDDEN: You must NOT independently generate, invent, infer, or expand a NEW impression,
                  conclusion, suggestion, differential, follow-up advice, clinical correlation, laboratory
                  correlation, pathologic correlation, biopsy recommendation, further-imaging recommendation,
                  or management recommendation that the physician did NOT dictate.
                - MANDATORY: ANY impression, conclusion, suggestion, recommendation, follow-up, or
                  clinical/laboratory/pathologic correlation the physician EXPLICITLY dictated is SOURCE
                  CONTENT and MUST be preserved (meaning and intent intact) in the final report — e.g.
                  "the above findings are suggestive of ...", "clinical correlation is recommended",
                  "correlation with laboratory findings is recommended", "further evaluation is recommended",
                  "biopsy is recommended".
                - The "do not invent" rule NEVER authorizes deleting, omitting, suppressing, weakening,
                  softening, or replacing physician-dictated content. When unsure, KEEP it (meaning intact).

                ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                CRITICAL: IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK (HARD RULE)
                ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                You MUST treat "Impression" and "Recommendations" as REQUIRED FIELDS **IFF** they exist in the input transcript.

                DEFINITION OF "EXISTS IN INPUT":
                - Impression EXISTS if the input includes ANY explicit diagnostic conclusion/جمع‌بندی تشخیصی such as:
                "impression", "جمع‌بندی", "نتیجه", "در مجموع", "مطرح‌کننده", "suggestive of", "compatible with", "favored diagnosis", "به نفع", "به احتمال زیاد", etc.
                - Recommendations EXISTS if the input includes ANY explicit advice/اقدام پیشنهادی such as:
                "recommend", "توصیه", "follow-up", "biopsy", "correlation", "clinical correlation", "laboratory correlation", "pathologic correlation", "further evaluation", "further imaging", "repeat imaging", "نمونه‌برداری", "بررسی بیشتر", etc.

                HARD CONSTRAINTS (NON-NEGOTIABLE):
                1) If Impression EXISTS in the input:
                - The output JSON MUST include the key "Impression".
                - "Impression" MUST be a NON-EMPTY string.
                - It MUST preserve the meaning and content from input exactly (no invention, no extra diagnoses).
                2) If Recommendations EXISTS in the input:
                - The output JSON MUST include the key "Recommendations".
                - "Recommendations" MUST be a NON-EMPTY string.
                - It MUST preserve the meaning and content from input exactly (no invention, no extra advice).
                3) If either exists but you omit it OR leave it empty OR set it to null:
                - Your output is INVALID and MUST be regenerated to comply.

                ABSOLUTE PROHIBITIONS:
                - DO NOT invent Impression/Recommendations.
                - DO NOT output empty strings, "N/A", null, "-", or placeholders.
                - DO NOT merge Impression into Pathological Findings or vice versa.
                - DO NOT paraphrase into new medical claims; only faithful extraction/translation.

                SELF-CHECK BEFORE FINAL OUTPUT (MANDATORY):
                - Scan the input for Impression triggers and Recommendations triggers.
                - If found, verify that the corresponding JSON keys exist and are non-empty.
                - If not satisfied, fix the JSON before returning it.

                ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                OUTPUT FORMAT (STRICT)
                ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                Return ONLY valid JSON (no markdown, no explanations, no extra keys).

                Schema:
                {
                "Report Title": string,
                "Pathological Findings": string,
                "Normal Findings": string,
                "Impression": string,        // REQUIRED IFF present in input; must be non-empty
                "Recommendations": string    // REQUIRED IFF present in input; must be non-empty
                }

                NOTE:
                - If Impression/Recommendations do NOT exist in input, OMIT those keys entirely.


                • Report Title Formats:
                – “Ultrasound of [Organ/Region]”
                – “Abdominal Ultrasound”
                – “Pelvic Ultrasound”
                – “Transvaginal Ultrasound”
                – “Obstetric Ultrasound – First/Second/Third Trimester”
                – “Ultrasound with Doppler of [Organ/Vessel]”

                • Recognize and correctly interpret Persian/Finglish ultrasound terminology:
                – اکوژن / echogen → echogenic
                – هیپراکوا / hyper-echo → hyperechoic
                – هیپواکوا / hypo-echo → hypoechoic
                – هوموژن → homogeneous
                – هتروژن → heterogeneous
                – هیدرونفروز → hydronephrosis
                – فت‌لیور / fatty liver → hepatic steatosis
                – کیست ساده / simple cyst → anechoic thin-walled cyst
                – فیبروئید / fibroid → leiomyoma
                – ساب‌سروز / subserosal — اینترامورال / intramural — ساب‌موکوزال / submucosal
                – سونو بارداری، بارداری، OB، ultrasound OB
                – BPD, HC, AC, FL, HL, AFI, DVP/MVP, EFW, GA
                – پوزیشن سفالیک → cephalic presentation
                – جفت قدامی/خلفی/فاندال → anterior/posterior/fundal placenta
                – صدک رشدی → fetal percentile
                – FHR / اف اچ آر → Fetal Heart Rate

                • Ultrasound Technical Terminology:
                – Echogenicity: hypoechoic, hyperechoic, anechoic, isoechoic.
                – Texture: heterogeneous vs homogeneous.
                – Shadowing, posterior acoustic enhancement.
                – Doppler terms: resistive index, normal flow, no increased vascularity.
                – Cystic vs solid vs complex lesions.
                – OB Doppler (if mentioned): UA PI, MCA PI, DV.

                -----------------------------------------------------------------------
                RSNA NORMAL FINDINGS — GENERAL ULTRASOUND
                -----------------------------------------------------------------------

                • Liver:
                – Homogeneous echotexture with smooth contour.
                – Normal portal vein caliber; hepatopetal flow present.
                – No focal hepatic lesions.

                • Gallbladder & Biliary Tree:
                – Thin, smooth gallbladder wall; no stones or sludge.
                – Common bile duct within normal diameter.

                • Pancreas:
                – Normal size and echogenicity; no peripancreatic fluid.

                • Kidneys:
                – Preserved corticomedullary differentiation.
                – No hydronephrosis, nephrolithiasis, or renal masses.

                • Spleen:
                – Normal size; uniform echotexture.

                • Urinary Bladder:
                – Smooth walls; no debris or masses.

                • Prostate — INCLUDE ONLY IF the physician explicitly mentioned the prostate (see SEX-SPECIFIC ANATOMY RULE below); otherwise OMIT entirely:
                – Normal morphology and echogenicity; normal volume.

                • Soft Tissues:
                – No abnormal masses, fluid collections, or abnormal vascularity.

                -----------------------------------------------------------------------
                ISUOG NORMAL FINDINGS — OBSTETRIC ULTRASOUND
                -----------------------------------------------------------------------

                • Pregnancy Overview:
                – Singleton intrauterine pregnancy unless otherwise specified.
                – Fetal heart rate (FHR) within expected range when not described as abnormal.

                • Fetal Presentation & Movement:
                – Cephalic/breech/transverse as noted or normal if unspecified.
                – Normal fetal movement when not described as abnormal.

                • Placenta:
                – Normal location (anterior/posterior/fundal).
                – No placenta previa or accreta unless stated.
                – Normal placental thickness for gestational age.

                • Amniotic Fluid:
                – AFI or DVP/MVP within normal range when no abnormality is reported.

                • Biometry:
                – BPD, HC, AC, FL, HL appropriate for gestational age unless specified otherwise.
                – EFW consistent with GA when no abnormality is described.

                • Fetal Anatomy (ISUOG Standard):
                – Skull/brain: normal contour; ventricles normal.
                – Face: normal orbits/profile if referenced.
                – Heart: normal four-chamber appearance; no abnormal findings unless described.
                – Chest/lungs: normal echogenicity and symmetry.
                – Abdomen: stomach, kidneys, bladder normal.
                – Spine: normal alignment and integrity.
                – Limbs: normal morphology and movement.

                • Umbilical Cord:
                – Three-vessel cord when visualized.
                – Normal cord insertion sites unless otherwise noted.

                -----------------------------------------------------------------------
                ISUOG NORMAL FINDINGS — GYNECOLOGIC ULTRASOUND
                -----------------------------------------------------------------------
                ── SEX-SPECIFIC ANATOMY RULE (STRICT — prostate, uterus, ovaries, cervix, adnexa, testes/scrotum) ──
                • DO NOT infer or assume the patient's sex. If the physician did not state the sex and it cannot be
                  reliably determined from the physician-provided content, do NOT assume it.
                • Include a sex-specific organ (uterus, ovaries, cervix, prostate, etc.) ONLY IF the physician EXPLICITLY
                  mentioned that organ (or gave a finding that clearly requires it). If the physician gave no information
                  about it, OMIT that organ entirely — do NOT emit a normal/"unremarkable" statement for it.
                • NEVER include BOTH male organs (prostate) AND female organs (uterus/ovaries) in the same report.

                • Uterus — INCLUDE ONLY IF the physician explicitly mentioned it; otherwise OMIT:
                – Normal size and contour.
                – Myometrium homogeneous.
                – Endometrium appropriate for menstrual phase.

                • Ovaries — INCLUDE ONLY IF the physician explicitly mentioned them; otherwise OMIT:
                – Normal size with physiological follicles.
                – No adnexal masses or abnormal free fluid.

                • Cervix — INCLUDE ONLY IF the physician explicitly mentioned it; otherwise OMIT:
                – Normal length and morphology.

                -----------------------------------------------------------------------

                • All ultrasound terminology must be fully professional and RSNA/ISUOG-aligned.
                • All interpretations MUST be based strictly on user input with zero speculation.
                • Normal Findings must be structured using RSNA or ISUOG rules depending on study type.
                                                        
                " 'input': 'سونوگرافی بارداری از خانم ۴۲ ساله شماره یک بنویس که جنین دارای موقعیت سفالیک می‌باشد جفت در موقعیت قدامی واقع گردیده است. فاصله جفت از دهانه رحم در حدود ۳۵ میلی‌متر اندازه‌گیری گردید. ای اف آی برابر با ۱۵ می‌باشد. بعد بنویس که بی پی دی برابر با ۳۴ میلی‌متر اف ال برابر با ۳۲ میلی‌متر اچ ال برابر با ۳۲ میلی‌متر ای سی ۱۳۳ و اچ سی ۱۳۲ می‌باشد. سن جنین در حدود ۲۴ هفته اندازه‌گیری گردید و وزن جنین در حدود ۱۳۰۰ گرم می‌باشد. اف اچ آر برابر با ۱۴۵ اندازه‌گیری گردید. صدک رشدی جنین با توجه به سن جنین طبقه ال ام پی و سونوگرافی قبلی (۲۳٫۵) در حال حاضر برابر با ۵۰٪ است.',\n"
                " Output:\n"

                '{\n'
                '  "Report Title": "Obstetric Ultrasound Report",\n'
                '  "Pathological Findings": "No pathological findings reported.",\n'
                '  "Normal Findings": "General / Pregnancy Overview:\\n * Singleton intrauterine pregnancy.\\n * Fetal presentation: Cephalic.\\n * Fetal heart rate (FHR): 145 bpm (within normal limits).\\n * Fetal growth percentile according to LMP and prior scan: 50%.\\n\\nPlacenta & Umbilical Cord:\\n * Placenta located anteriorly.\\n * Placental edge-to-internal os distance: 35 mm.\\n * No abnormal placental morphology described.\\n * Umbilical cord: No abnormality reported.\\n\\nAmniotic Fluid:\\n * Amniotic fluid index (AFI): 15 cm (within normal range).\\n\\nBiometry (ISUOG Standard Measurements):\\n * Biparietal diameter (BPD): 34 mm.\\n * Head circumference (HC): 132 mm.\\n * Abdominal circumference (AC): 133 mm.\\n * Femur length (FL): 32 mm.\\n * Humerus length (HL): 32 mm.\\n * Composite gestational age: approximately 24 weeks.\\n * Estimated fetal weight (EFW): 1300 g.\\n\\nFetal Anatomy:\\n * No structural abnormalities reported.\\n * Fetal activity and movement: Not specified; assumed normal.\\n\\nMaternal Structures:\\n * Cervix: No abnormality reported.\\n * Uterus and adnexa: No abnormality reported."\n'
                '}\n\n'
                "```  \n"
                "<|end|>"
        
                """
            )
        elif modality_lower in ("mammography", "mamography", "mammogram", "mamogram"):
            specific_instructions = (r"""
                ====================================================================
                SECTION 0 — REGEX-LOCKED JSON SCHEMA (HARD ENFORCEMENT)
                ====================================================================

                Your FINAL OUTPUT MUST MATCH the following REGEX EXACTLY.
                If the output does NOT match this REGEX, you MUST REGENERATE it
                until it matches perfectly.

                REGEX (FULL STRUCTURE LOCK):

                ^\{\s*
                "Report Title"\s*:\s*".+",\s*
                "Breast Composition"\s*:\s*".+",\s*
                "Pathological Findings"\s*:\s*".+",\s*
                "Normal Findings"\s*:\s*\{\s*
                "Right Breast"\s*:\s*".*",\s*
                "Left Breast"\s*:\s*".*"\s*
                \},\s*
                "Axillary Evaluation"\s*:\s*".+",\s*
                "BI-RADS Category"\s*:\s*\{\s*
                "Right Breast"\s*:\s*".*",\s*
                "Left Breast"\s*:\s*".*"\s*
                \}\s*
                \}$

                RULES:
                - ABSOLUTELY NO TEXT before or after the JSON object.
                - EXACT key names ONLY, EXACT order ONLY.
                - ALL fields MUST be present.
                - ALL values MUST be strings (non-null).
                - NO extra fields, no markdown, no commentary, no numbering.
                - If validation fails → regenerate until valid.

                ====================================================================
                SECTION 0b — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS (SCHEMA-SAFE)
                ====================================================================
                The mammography schema above is FIXED and regex-locked; it has NO separate
                "Impression" or "Recommendations" key, and you MUST NOT add one.
                DISTINCTION between generating and preserving:
                - FORBIDDEN: Do NOT independently generate/invent a NEW impression, suggestion,
                  correlation, biopsy recommendation, follow-up, or further-imaging recommendation
                  the physician did NOT dictate.
                - MANDATORY: ANY impression, suggestion, correlation, or recommendation the physician
                  EXPLICITLY dictated MUST be preserved (meaning intact) INSIDE the existing schema —
                  it must NEVER be dropped, omitted, weakened, or softened:
                  • A physician's diagnostic conclusion/suggestion (e.g. "these findings are suggestive
                    of malignancy", "suspicious for recurrence") → keep it within "Pathological Findings".
                  • A physician's management/recommendation/correlation (e.g. "biopsy is recommended",
                    "clinical correlation is recommended", "short-term follow-up recommended") → keep it
                    within "Pathological Findings" and reflect it in the "BI-RADS Category" value/label.
                  • Do NOT invent a BI-RADS category the physician did not give; if the physician stated
                    one, insert it EXACTLY as provided.

                ====================================================================
                SECTION 1 — STRICT REPORT GENERATION ORDER (MANDATORY)
                ====================================================================

                You MUST generate the report in the following exact conceptual order.
                You cannot skip, merge, reorder, or omit ANY step:

                STEP 1 → Determine the Report Title  
                STEP 2 → Determine Breast Composition  
                STEP 3 → Extract ALL Pathological Findings  
                STEP 4 → Generate Normal Findings for RIGHT breast  
                STEP 5 → Generate Normal Findings for LEFT breast  
                STEP 6 → Determine Axillary Evaluation  
                STEP 7 → Insert BI-RADS categories EXACTLY as provided by the user  
                STEP 8 → Assemble the JSON using the exact structure below  
                STEP 9 → Output ONLY the JSON and NOTHING else  

                ====================================================================
                SECTION 2 — FINAL JSON STRUCTURE (STRICT)
                ====================================================================

                Your final output MUST be structured EXACTLY like this:

                {
                "Report Title": "",
                "Breast Composition": "",
                "Pathological Findings": "",
                "Normal Findings": {
                    "Right Breast": "",
                    "Left Breast": ""
                },
                "Axillary Evaluation": "",
                "BI-RADS Category": {
                    "Right Breast": "",
                    "Left Breast": ""
                }
                }

                STRICT RULES:
                - ALL keys MUST appear exactly as written.  
                - ALL values MUST be STRINGS.  
                - BOTH breasts MUST always appear.  
                - If no info is available → use “Not mentioned”.  
                - Breast Composition MUST appear ONLY in its own field.  
                - BI-RADS MUST appear ONLY inside its designated object.  
                - No lists, no bullets, no numbering inside the JSON.

                ====================================================================
                SECTION 3 — LEXICON NORMALIZATION (MANDATORY)
                ====================================================================

                Normalize Persian/Finglish variations into correct mammography terminology:

                • توده، تووده، لیشن، لیزن → mass / lesion  
                • اسپیکوله، اسپیکیوله، اسپکوله → spiculated margins  
                • پلئومورفیک، پلیومورف، پلومورف → pleomorphic  
                • میکروکلس، میکروکلسی، میکروکلسیفیکیشن → microcalcifications  
                • دیستورشن، دیستوشن، دیستاشن → architectural distortion  
                • آسیمتری، اسمیتری، غیرقرینگی → asymmetry  
                • نیپل رتراکشن، جمع شدگی نوک پستان → nipple retraction  
                • اکتازی، دکتازی، داکتال اکتازی → ductal ectasia  
                • فیبروگلندولار، فیبروگرانولار → fibroglandular  
                • لنفادنوپاتی، لنف نود، کورتکس ضخیم → lymphadenopathy  

                General mammography-safe terminology normalization:

                • benign → benign  
                • malignant / malignancy / cancer → malignant / malignancy  
                • thickening → thickening (standard)  
                • shapes → irregular / well-defined / ill-defined  
                • normalize increased / decreased variations  
                • NEVER add new interpretation  

                ACR BI-RADS 5th Edition — Mass Descriptors (use EXACTLY these terms):

                Mass SHAPE:
                • oval (elliptical, egg-shaped)
                • round (spherical, ball-shaped)
                • irregular (shape cannot be characterized as oval or round)

                Mass MARGIN:
                • circumscribed (well-defined, sharp interface ≥75% of border)
                • obscured (hidden by overlying or adjacent tissue)
                • microlobulated (short-cycle undulations on border)
                • indistinct (no clear demarcation from adjacent tissue)
                • spiculated (lines radiating from mass; highest malignancy concern)

                Mass DENSITY (relative to equal volume of fibroglandular tissue):
                • fat-containing (includes oil cysts, lipomas, galactoceles, hamartomas)
                • low density
                • equal density
                • high density

                Calcification MORPHOLOGY:
                • Typically benign: skin / vascular / coarse or popcorn-like / large rod-like / round / rim / dystrophic / milk of calcium / suture
                • Suspicious — Intermediate concern: coarse heterogeneous
                • Suspicious — Higher concern: fine pleomorphic | fine linear | fine-linear branching (casting)

                Calcification DISTRIBUTION:
                • diffuse (randomly scattered throughout whole breast)
                • regional (large volume of breast tissue, not duct distribution)
                • grouped / clustered (≥5 calcifications in <2 cm² area)
                • linear (calcifications in a line, may branch; suggests ductal distribution)
                • segmental (triangular or cone-shaped; suggests ductal/lobular distribution)

                Use EXACTLY these BI-RADS terms when describing mass shape, margins, density, and calcification characteristics.
                Do NOT paraphrase or substitute synonyms.

                ====================================================================
                SECTION 4 — NORMAL FINDINGS TEMPLATE (CONFLICT-FILTERED)
                ====================================================================

                BASE NORMAL TEMPLATE (used for each breast):

                “No suspicious mass, architectural distortion, or clustered microcalcifications.  
                No asymmetry, nipple retraction, or skin thickening.  
                Retroareolar region is unremarkable.  
                Pectoralis muscle is visualized on MLO view.”

                RULES:

                1. Identify abnormalities in Pathological Findings for EACH breast.  
                2. Remove contradictory negative statements ONLY for that same breast.  
                3. Grammar must remain correct.  
                4. Do NOT remove unrelated negative findings.  
                5. Retroareolar + pectoralis statements remain unless contradicted explicitly.

                Conflict mapping:

                - MASS present → remove “No suspicious mass”  
                - MICROCALCIFICATIONS present → remove “clustered microcalcifications”  
                - ARCHITECTURAL DISTORTION present → remove it  
                - ASYMMETRY present → remove “No asymmetry”  
                - NIPPLE RETRACTION present → remove it  
                - SKIN THICKENING present → remove it  

                ====================================================================
                SECTION 5 — CONTRADICTION RULE
                ====================================================================

                Normal Findings MUST NOT negate any abnormal feature found in Pathological Findings.

                Allowed:
                ✓ Pathology: mass → Normal: may keep “No architectural distortion or clustered microcalcifications.”

                Not allowed:
                ✗ Pathology: mass → Normal: “No suspicious mass.”

                ====================================================================
                SECTION 6 — BI-RADS RULE (ACR BI-RADS 5th Edition)
                ====================================================================

                BI-RADS CATEGORY RULE:
                - The user MUST provide BI-RADS.  
                - NEVER infer or guess BI-RADS.  
                - Copy EXACT formatting from user input (e.g., “4C”, “5”, “6”).  
                - Missing value → “Not mentioned”.
                - When a BI-RADS category is stated, append the standard label and management recommendation:

                BI-RADS Category Descriptions & Standard Management:
                • 0 — Incomplete. Need additional imaging evaluation and/or prior mammograms for comparison.
                • 1 — Negative. Annual screening mammography (routine interval).
                • 2 — Benign finding(s). Annual screening mammography (routine interval).
                • 3 — Probably benign. Short-interval follow-up (6 months); probability of malignancy <2%.
                • 4A — Low suspicion for malignancy. Tissue sampling (biopsy) recommended; malignancy risk >2% to ≤10%.
                • 4B — Moderate suspicion for malignancy. Tissue sampling (biopsy) recommended; malignancy risk >10% to ≤50%.
                • 4C — High suspicion for malignancy. Tissue sampling (biopsy) required; malignancy risk >50% to <95%.
                • 5 — Highly suggestive of malignancy. Tissue sampling required; malignancy risk ≥95%.
                • 6 — Known biopsy-proven malignancy. Prior to definitive therapy (treatment planning).

                Format for BI-RADS Category value: "[Category] — [Standard Label]"
                Example: "5 — Highly suggestive of malignancy"

                BREAST COMPOSITION (ACR BI-RADS A–D):
                Use EXACT ACR terminology when composition is stated:
                • A — The breasts are almost entirely fatty.
                • B — There are scattered areas of fibroglandular density.
                • C — The breasts are heterogeneously dense, which may obscure small masses.
                • D — The breasts are extremely dense, which lowers the sensitivity of mammography.
                If composition stated as a letter (A/B/C/D) or type number (1/2/3/4): map to the standard description above.
                If composition is not stated: "Not mentioned".

                ====================================================================
                SECTION 7 — AXILLARY RULE
                ====================================================================

                - Axillary abnormalities MUST appear in “Axillary Evaluation”.  
                - Optional brief mention inside Pathological Findings is allowed.

                ====================================================================
                SECTION 8 — VALIDATION BEFORE OUTPUT (MANDATORY)
                ====================================================================

                Before output, internally verify:

                - Regex lock satisfied  
                - JSON valid  
                - All fields present  
                - No contradictions  
                - No BI-RADS outside BI-RADS object  
                - No Breast Composition inside Pathology  
                - No extra text  

                ====================================================================
                SECTION 9 — EXAMPLES (DO NOT MODIFY)
                ====================================================================

                🟦 Example 1 – Input: (65 y/o, Right Breast Recurrence)

                Input:
                ماموگرافی زن 65 ساله با سابقه کنسر برست راست و تغییرات پس از درمان در برست راست، ضخامت پوست برست راست افزایش یافته میباشد. تغییرات پس از عمل در برست راست به صورت تغییرات در پوست برست راست رویت میگردد. تغییرات پس از عمل در برست راست به صورت تشکیل بافت اسکار در نواحی UACO رویت میگردد. مارکر در نواحی Uoq برست راست رویت میگردد. یافته های فوق در مجموع مطرح کننده 6 BIRADS در برست راست میباشد. در مقایسه با ماموگرافی قبلی از مرکز، بافت اسکار در برست راست اندکی برجسته تر رویت میگردد. بافت اسکار در برست راست اندکی برجسته تر رویت میگردد. میکروکسیفیکاسیون با نمای پلئومرفیک در مجاورت نواحی فوق رویت میگردد. یافته های فوق در مجموع مطرح کننده عود پروسه های تومورال میباشد. برست چپ به عنوان مرجع طبیعی رویت میگردد.

                Output:
                {
                "Report Title": "Bilateral Mammography – CC & MLO Views",
                "Breast Composition": "Not mentioned",
                "Pathological Findings": "Skin thickening is observed in the right breast. Post-surgical changes including scar formation are present in the upper outer quadrant (UOQ). Marker clips are visualized in the same region. Compared to the previous mammogram from this center, the scar tissue appears slightly more prominent. Pleomorphic microcalcifications are identified adjacent to the scarred area. These findings suggest recurrence of tumor process in a known malignancy case.",
                "Normal Findings": {
                    "Right Breast": "Apart from the above-mentioned findings, no additional abnormalities are seen.",
                    "Left Breast": "No suspicious mass, architectural distortion, or clustered microcalcifications. No asymmetry, nipple retraction, or skin thickening. Retroareolar region is unremarkable. Pectoralis muscle is visualized on MLO view."
                },
                "Axillary Evaluation": "No abnormal axillary lymph nodes detected.",
                "BI-RADS Category": {
                    "Right Breast": "6 – Known malignancy",
                    "Left Breast": "1 – Negative"
                }
                }

                🟦 Example 2 – Input: (56 y/o, Left Breast Mass)

                Input:
                ماموگرافی از خانم 56 ساله با شکایت پالبلمس در یرست چپ  
                breast compositionش رو بزن type C  
                شماره یک بنویس که ضایعه توده مانند با حدود اسپیکوله و شکل نامنظم در نواحی UOQ برست سمت چپ در ساعت 9 در فاصله 65 میلیمتری از نیپل مشهود است  
                توده فوق باعث افزایش ضخامت پوست مجاوره خود گردیده است  
                یافته های فوق در درجه اول مطرح کننده وجود malignancy ها میباشد  
                لنفادنوپاتی در نواحی اگزیلاری سمت چپ مشهود است که با توجه به افزایش ضخامت كورتیكال در درجه اول مطرح کننده درگیری سیستم لنفاوی در برست سمت چپ است  
                با ردز برست سمت چپ رو بزن 5  
                بعد بنویس که داکتال اکتازی در نواحی retroaloe داکتال اکتازی در نواحی رترولورال برست سمت راست مشهود است  
                با ایر اتز برست سمت راستش رو بزن دو  

                Output:
                {
                "Report Title": "Bilateral Mammography – CC & MLO Views",
                "Breast Composition": "Heterogeneously dense (Category C)",
                "Pathological Findings": "An irregular-shaped mass with spiculated margins is identified in the upper outer quadrant of the left breast at 9 o’clock, 65 mm from the nipple. The lesion is associated with overlying skin thickening. Left axillary lymphadenopathy with cortical thickening is observed, suggesting lymph node involvement. Ductal ectasia is noted in the retroareolar region of the right breast.",
                "Normal Findings": {
                    "Right Breast": "Apart from the above-mentioned ductal ectasia, no additional abnormalities are seen.",
                    "Left Breast": "Apart from the above-mentioned findings, no additional abnormalities are seen."
                },
                "Axillary Evaluation": "Left: abnormal with cortical thickening; Right: normal.",
                "BI-RADS Category": {
                    "Right Breast": "2 – Benign",
                    "Left Breast": "5 – Highly suggestive of malignancy"
                }
                }

                🟦 Example 3 – Input: (45 y/o, Nipple Discharge & Microcalcifications)

                Input:
                ماموگرافی از خانم 45 ساله با شکایت nipple discharge خونی در برست سمت چپ  
                شماره یک بنویس که کلسیفیکاسیون پلئومرویک در نواحی UOQ برست سمت چپ با گسترش سگیمنتال مشهود است  
                nipple retraction در سمت چپ رویت می گردد  
                lymphadenopathy در نواحی اگزیلری سمت چپ مشهود است  
                یافته های فوق در مجموع مطرح کننده وجود ملیگنانسی ها در برست سمت چپ و DCIS میباشد  
                بای ردزش رو 4C بده  
                مرسی  
                برست راست رو طبیعی بزن  

                Output:
                {
                "Report Title": "Bilateral Mammography – CC & MLO Views",
                "Breast Composition": "Not mentioned",
                "Pathological Findings": "Pleomorphic microcalcifications with segmental distribution are identified in the upper outer quadrant of the left breast. Nipple retraction is present. Left axillary lymphadenopathy is observed. These findings are suggestive of malignancy, including ductal carcinoma in situ (DCIS).",
                "Normal Findings": {
                    "Right Breast": "No suspicious mass, architectural distortion, or clustered microcalcifications. No asymmetry, nipple retraction, or skin thickening. Retroareolar region is unremarkable. Pectoralis muscle is visualized on MLO view.",
                    "Left Breast": "Apart from the above-mentioned findings, no additional abnormalities are seen."
                },
                "Axillary Evaluation": "Left: abnormal; Right: normal.",
                "BI-RADS Category": {
                    "Right Breast": "1 – Negative",
                    "Left Breast": "4C – Suspicious abnormality (high concern for malignancy)"
                }
                }

                ====================================================================
                END OF INSTRUCTIONS — BEGIN PROCESSING INPUT
                ====================================================================
                    
                    """
            
                )
        elif modality_lower == "radiology":
                        specific_instructions = (
                            """MODALITY LOGIC (Radiology – X-ray: General, Bone Density, Bone Age, Barium Studies):

                            • The imaging modality is X-ray (Radiography).
                            • Construct the “Normal Findings” using RSNA radiography reporting standards when no normal_template is provided.
                            • Always generate concise, grouped, non-redundant normal findings.
                            • Exclude anatomical regions explicitly described in pathological findings.


                            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                            RADIOLOGY (X-RAY) — PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS (READ FIRST)
                            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                            This rule applies to EVERY radiograph type (general X-ray, bone age, bone density/DEXA, barium studies, skeletal survey, etc.).
                            CRITICAL DISTINCTION between GENERATING new content and PRESERVING dictated content:
                            - FORBIDDEN: You must NOT independently generate, invent, infer, or expand a NEW impression,
                              conclusion, suggestion, differential, follow-up advice, clinical correlation, laboratory
                              correlation, pathologic correlation, biopsy recommendation, further-imaging recommendation,
                              or management recommendation that the physician did NOT dictate.
                            - MANDATORY: ANY impression, conclusion, suggestion, recommendation, follow-up, or
                              clinical/laboratory/pathologic correlation the physician EXPLICITLY dictated is SOURCE
                              CONTENT and MUST be preserved (meaning and intent intact) in the final report — e.g.
                              "the above findings are suggestive of ...", "clinical correlation is recommended",
                              "correlation with laboratory findings is recommended", "further evaluation is recommended",
                              "biopsy is recommended".
                            - The "do not invent" rule NEVER authorizes deleting, omitting, suppressing, weakening,
                              softening, or replacing physician-dictated content. When unsure, KEEP it (meaning intact).

                            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                            CRITICAL: IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK (HARD RULE)
                            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                            You MUST treat "Impression" and "Recommendations" as REQUIRED FIELDS **IFF** they exist in the input transcript.

                            DEFINITION OF "EXISTS IN INPUT":
                            - Impression EXISTS if the input includes ANY explicit diagnostic conclusion/جمع‌بندی تشخیصی such as:
                            "impression", "جمع‌بندی", "نتیجه", "در مجموع", "مطرح‌کننده", "suggestive of", "compatible with", "favored diagnosis", "به نفع", "به احتمال زیاد", etc.
                            - Recommendations EXISTS if the input includes ANY explicit advice/اقدام پیشنهادی such as:
                            "recommend", "توصیه", "follow-up", "biopsy", "correlation", "clinical correlation", "laboratory correlation", "pathologic correlation", "further evaluation", "further imaging", "repeat imaging", "نمونه‌برداری", "بررسی بیشتر", etc.

                            HARD CONSTRAINTS (NON-NEGOTIABLE):
                            1) If Impression EXISTS in the input:
                            - The output JSON MUST include the key "Impression".
                            - "Impression" MUST be a NON-EMPTY string.
                            - It MUST preserve the meaning and content from input exactly (no invention, no extra diagnoses).
                            2) If Recommendations EXISTS in the input:
                            - The output JSON MUST include the key "Recommendations".
                            - "Recommendations" MUST be a NON-EMPTY string.
                            - It MUST preserve the meaning and content from input exactly (no invention, no extra advice).
                            3) If either exists but you omit it OR leave it empty OR set it to null:
                            - Your output is INVALID and MUST be regenerated to comply.

                            ABSOLUTE PROHIBITIONS:
                            - DO NOT invent Impression/Recommendations.
                            - DO NOT output empty strings, "N/A", null, "-", or placeholders.
                            - DO NOT merge Impression into Pathological Findings or vice versa.
                            - DO NOT paraphrase into new medical claims; only faithful extraction/translation.

                            SELF-CHECK BEFORE FINAL OUTPUT (MANDATORY):
                            - Scan the input for Impression triggers and Recommendations triggers.
                            - If found, verify that the corresponding JSON keys exist and are non-empty.
                            - If not satisfied, fix the JSON before returning it.

                            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                            OUTPUT FORMAT (STRICT)
                            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                            Return ONLY valid JSON (no markdown, no explanations, no extra keys).

                            Schema:
                            {
                            "Report Title": string,
                            "Pathological Findings": string,
                            "Normal Findings": string,
                            "Impression": string,        // REQUIRED IFF present in input; must be non-empty
                            "Recommendations": string    // REQUIRED IFF present in input; must be non-empty
                            }

                            NOTE:
                            - If Impression/Recommendations do NOT exist in input, OMIT those keys entirely.

                            • Report Title Formats:
                            – “X-ray of [Region]”
                            – “Chest X-ray (PA/Lateral)”
                            – “Abdominal X-ray (KUB)”
                            – “Bone Age Radiograph”
                            – “DEXA Bone Density Scan”
                            – “Barium Swallow / Barium Meal / Barium Enema Study”
                            – “Skeletal Survey” (if mentioned)

                            • Recognize and correctly interpret Persian/Finglish radiologic terminology:
                            – ارتولیز / آرتروز → osteoarthritis
                            – استئوفیت → osteophyte
                            – تراکم استخوان / BMD / T-score / Z-score
                            – فیوژن / اسپوندیلولایزیس / لیستزیس
                            – consolidation / infiltration / atelectasis
                            – hyperinflation / emphysematous changes
                            – bronchiectasis / bronchiolitis / peribronchial thickening
                            – fracture, displacement, angulation
                            – epiphysis, metaphysis, physeal plate
                            – advanced bone age / delayed bone age
                            – barium terms: filling defect, mucosal irregularity, ulcer niche, narrowing, reflux

                            ------------------------------------------------------------
                            RSNA NORMAL FINDINGS — GENERAL X-RAY
                            ------------------------------------------------------------

                            • Chest (PA/Lateral):
                            – Clear lung fields without consolidation or interstitial opacities.
                            – Normal cardiac silhouette and mediastinal contours.
                            – Pulmonary vessels normal in distribution.
                            – No pleural effusion or pneumothorax.
                            – Bony thorax intact.

                            • Abdomen (KUB):
                            – Normal bowel gas pattern.
                            – No abnormal calcifications.
                            – No free intraperitoneal air.

                            • Extremities:
                            – Bones with normal alignment and mineralization.
                            – Joint spaces preserved.
                            – Soft tissues without swelling or masses.

                            • Spine:
                            – Normal vertebral alignment and maintained disc spaces.
                            – No compression fracture.

                            ------------------------------------------------------------
                            NORMAL FINDINGS — BONE DENSITY (DEXA)
                            ------------------------------------------------------------

                            • BMD Interpretation (RSNA/ISCD style):
                            – T-score and Z-score within expected range for patient demographic (only if user provides values).
                            – No focal skeletal abnormalities.
                            – Normal trabecular and cortical pattern.

                            ------------------------------------------------------------
                            NORMAL FINDINGS — BONE AGE (GREULICH & PYLE STYLE)
                            ------------------------------------------------------------

                            • Growth plates:
                            – Normal appearance and expected openness/closure per stated age (if user provides age).
                            • Carpal bones:
                            – Normal ossification sequence.
                            • Epiphyses:
                            – Appropriate size and maturation without delay or advancement.

                            ------------------------------------------------------------
                            RSNA NORMAL FINDINGS — BARIUM STUDIES
                            ------------------------------------------------------------

                            • Esophagus:
                            – Normal mucosal pattern; no strictures or filling defects.
                            • Stomach:
                            – Normal rugal folds; no ulcer niche or mass.
                            • Small Bowel / Colon:
                            – Normal transit; no mucosal irregularity; no obstruction.
                            • Reflux:
                            – No gastroesophageal reflux unless described.

                            ------------------------------------------------------------

                            • All radiographic terminology must follow RSNA conventions.
                            • Interpret strictly based on user input with zero speculation.
                            • Generate normal findings only for regions relevant to the study.
                            
                            "1. Pathological Findings:\n"
                                " • Objective: Transcribe and translate radiologic reports into English with a formal tone, emulating a typist and preparing a professional patient report.\n"
                                " • Structure:\n"
                                " o Number each part of the findings.\n"
                                " o Use periods and proper punctuation to mimic the structure of a professional medical report.\n"
                                " o Use precise radiologic medical nomenclature in your transcribtion for all terms used by the reporter.\n"
                                " • Guidelines:\n"
                                " o Follow RSNA and ACR standardized reporting guidelines applicable to conventional radiography (X-ray), including structured reporting for chest, skeletal, abdominal, and contrast fluoroscopic studies where relevant.n"
                                                    " o Describe abnormalities using standard radiographic terminology without applying modality-inappropriate categorical scoring systems.\n"
                                " o Ensure clear and accurate categorization according to the relevant standardized system.\n"
                                " o Ensure no additional implications or speculative thinking are added.\n"
                                " o Do not generate any diagnosis, differential diagnosis (DDX), or recommendations unless explicitly provided by the user.\n\n"

                                "2. Normal Findings:\n"
                                " • Objective: Highlight normal findings in a structured reporting format using a radiologic normal report template tailored to the patient's specific body part and imaging modality.\n"
                                " • Guidelines:\n"
                                " o Normal Findings MUST exist in every report regardless of pathological content.\n"  # <-- ADDED HERE
                                " o Eliminate the normal findings section ONLY for the same anatomical part where a pathological finding is described.\n"
                                " o Ensure the report includes all relevant normal findings not mentioned in the original report, covering aspects beyond the pathological findings.\n"
                                " o Always state at least several normal points explicitly (e.g., normal bone alignment, patent airways, unremarkable surrounding tissues, etc.).\n\n"

                                # 3. Style & Tone
                                "3. Language & Tone:\n"
                                " • ANSWER MUST STRICTLY IN ENGLISH.\n"
                                " • Use *extreme exaggeration*—vivid, dramatic phrasing.\n"

                                # 4. Forbidden content
                                "4. Absolutely *no* SELF-GENERATED content (this NEVER applies to content the physician explicitly dictated):\n"
                                " • Internal reasoning, chain-of-thought, or instructions.\n"
                                " • NEW suggestions, implications, speculations, differential diagnoses, or recommendations that YOU invent and the physician did NOT provide.\n"
                                " • EXCEPTION — PRESERVE PHYSICIAN CONTENT: If the physician EXPLICITLY dictated an impression, suggestion, recommendation, follow-up, or clinical/laboratory/pathologic correlation (e.g. 'suggestive of ...', 'clinical correlation is recommended', 'biopsy is recommended'), you MUST keep it (meaning intact) — never delete, omit, weaken, or soften it, and do not strip words like 'suggestive of' when they are the physician's own wording.\n"
                                " • Do not add speculative hedging words ('potentially,' 'possible,' 'may,' 'which may be') on YOUR OWN initiative; keep the physician's wording as dictated.\n\n"

                                # 5. JSON Structure Rules
                                "5. JSON OUTPUT RULES:\n"
                                " • START IMMEDIATELY WITH { - NO OTHER TEXT\n"
                                " • END WITH } - NO OTHER TEXT\n"
                                " • VALID JSON FORMAT ONLY\n"
                                " • ALL STRINGS MUST BE PROPERLY ESCAPED\n"
                                " • NO TRAILING COMMAS\n"
                                " • PROPER QUOTATION MARKS\n"
                                " • ABSOLUTELY MUST END WITH '<|end|>' AFTER THE FINAL CLOSING BRACE\n\n"

                                # Modification instructions
                                "6. If a previous report is provided, apply modifications from the new information:\n"
                                " • Update only the specific parts mentioned in the new information (e.g., correct side, add lab results, update findings).\n"
                                " • Keep all unchanged parts from the previous report intact.\n"
                                " • Add new findings to the appropriate section without removing existing ones.\n"
                                " • Update the report title if the new information changes it (e.g., side correction).\n"
                                " • Output the full updated JSON.\n\n"
                                """
                                )
        else:
            specific_instructions = (
                "• For other modalities: Infer appropriate standards (e.g., ACR for X-ray).\n"
                "• Use modality-specific terminology in findings (e.g., density for CT, signal for MRI).\n"
                "\nPRESERVE PHYSICIAN-PROVIDED CONCLUSIONS: Do NOT independently generate a NEW impression, "
                "suggestion, recommendation, follow-up, or clinical/laboratory/pathologic correlation the "
                "physician did NOT dictate. BUT any impression, suggestion, recommendation, follow-up, or "
                "correlation the physician EXPLICITLY dictated (e.g. 'suggestive of ...', 'clinical correlation "
                "is recommended', 'biopsy is recommended', 'further evaluation is recommended') is SOURCE CONTENT "
                "and MUST be preserved (meaning intact) in the report — never delete, omit, weaken, or soften it. "
                "If the report includes Impression/Recommendations fields, place it there; otherwise keep it in "
                "the most appropriate existing field.\n"
            )
        modality_logic = base_modality_logic + specific_instructions + "\n\n"
    else:
        modality_logic = (
            "MODALITY LOGIC:\n"
            "• No specific modality provided - infer from user input (e.g., 'CT', 'MRI', 'Sonography', 'Mammography', 'Radiology').\n"
            "• Customize 'Report Title' and 'Normal Findings' based on inferred modality using RSNA/ACR standards.\n"
            "• PRESERVE PHYSICIAN-PROVIDED CONCLUSIONS: Do NOT independently generate a NEW impression, suggestion, "
            "recommendation, follow-up, or clinical/laboratory/pathologic correlation the physician did NOT dictate; "
            "BUT any such statement the physician EXPLICITLY dictated (e.g. 'suggestive of ...', 'clinical correlation "
            "is recommended', 'biopsy is recommended') MUST be preserved (meaning intact) — never delete, omit, weaken, "
            "or soften it.\n\n"
        )

    system_prompt = (
        "IMPORTANT: You MUST respond ONLY in English. "
        "This rule is ABSOLUTE and applies regardless of the user's input language. "
        "Do NOT translate the user's language unless explicitly instructed. "
        "Do NOT include any non-English text.\n\n"
        f"{template_logic.strip()}\n\n"
        f"{normal_template}\n\n"
        f"{modality_logic.strip()}\n\n"

)
    payload: Dict[str, Any] = {
        "model": (_to_str(model).strip() or "Unknown"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }
    if modality and modality.lower() in _VALIDATED_MODALITIES:
        payload["temperature"] = 0.1
        payload["max_tokens"] = 2500

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = "https://api.gapgpt.app/v1/chat/completions"

    # ------------------------------------------------------
    #  API CALL
    # ------------------------------------------------------
    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()
    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    # ------------------------------------------------------
    #  EXTRACT USAGE
    # ------------------------------------------------------
    usage_info = result.get("usage", {})
    prompt_tokens = usage_info.get("prompt_tokens", 0)
    completion_tokens = usage_info.get("completion_tokens", 0)

    # ------------------------------------------------------
    #  ✅ NOW SAFE TO LOG USAGE
    # ------------------------------------------------------
    _log_usage_safe(m, center, model, prompt_tokens, completion_tokens, user_msg)

    # ------------------------------------------------------
    #  RETURN THE AI OUTPUT
    # ------------------------------------------------------
    raw_content = result["choices"][0]["message"]["content"]
    if modality and modality.lower() in ("mri", "ct"):
        raw_content = _validate_report_json(raw_content, modality.lower())
    return {
        "content": raw_content,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown")
        }
    }
# ============================


def chat(
    user_msg: str,
    CENTER_Key: str = "",
    model: str = "gpt-4.1-mini"):
    """Simple chat interface using GapGPT API (no templates, pure conversation)."""
    # ------------------------------------------------------
    #  SELECT CENTER + API KEY
    # ------------------------------------------------------
    m = Manage.instance()
    center, api_key = m.get_center_and_gapgpt_key()


    # ------------------------------------------------------
    #  BASIC SYSTEM MESSAGE (simple chat)
    # ------------------------------------------------------
    system_msg = """
You are a medical report editor. You will receive (1) USER_REPORT then (2) CORRECTION_NOTE.

CORE RULES (STRICT):
- Apply ONLY the changes explicitly requested in CORRECTION_NOTE.
- Do NOT add any new medical findings/diagnoses/impressions/recommendations or any facts not already in USER_REPORT,
  unless CORRECTION_NOTE explicitly instructs you to add/insert them.
- Do NOT delete content unless CORRECTION_NOTE explicitly asks to remove it.
- Preserve the existing structure, section headings, ordering, style, and wording as much as possible.

CRITICAL OUTPUT REQUIREMENT:
- You MUST return the FULL corrected report (not a patch, not a summary, not only the corrected lines).
- Every section/paragraph that is NOT mentioned in CORRECTION_NOTE must remain unchanged and must still appear in the output.
- If USER_REPORT contains structured key/value sections (e.g., 'Report Title', 'Pathological Findings', 'Normal Findings'),
  keep those keys and keep ALL of them in the output.

FORMAT LOCK:
- If USER_REPORT is JSON (or JSON-like), output JSON in the same schema (same keys), with the corrected values applied.
  Do not add commentary or surrounding text.
- Otherwise, output plain text in the same formatting/sections as USER_REPORT.

OUTPUT:
Return ONLY the final corrected report text. No analysis, no preface.
"""

    # ------------------------------------------------------
    #  PAYLOAD
    # ------------------------------------------------------
    payload = {
        "model": (_to_str(model).strip() or "Unknown"),
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = "https://api.gapgpt.app/v1/chat/completions"

    # ------------------------------------------------------
    #  API CALL
    # ------------------------------------------------------
    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()
    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    # ------------------------------------------------------
    #  USAGE COUNTERS (NOW result IS DEFINED!)
    # ------------------------------------------------------
    usage_info = result.get("usage", {})
    prompt_tokens = usage_info.get("prompt_tokens", 0)
    completion_tokens = usage_info.get("completion_tokens", 0)

    # Log usage into your analytics system
    _log_usage_safe(m, center, model, prompt_tokens, completion_tokens, user_msg)

    # ------------------------------------------------------
    #  RETURN AI MESSAGE
    # ------------------------------------------------------
    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown")
        }
    }


def chat_with_api_key(
    user_msg: str,
    api_key: str,
    model: str = "gpt-4.1-mini",
    system_msg: str = "",
):
    """Chat interface using an explicit GapGPT API key."""
    user_msg = _to_str(user_msg)
    api_key = _to_str(api_key).strip()
    if not api_key:
        raise Exception("❌ GapGPT API key is missing.")

    m = Manage.instance()
    center = "User"
    try:
        center = m.get_detected_center_display()
    except Exception:
        pass

    sys_msg = (system_msg or "").strip() or (
        "You are a helpful medical assistant. Provide a concise response to the user's transcript."
    )

    payload = {
        "model": (_to_str(model).strip() or "Unknown"),
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = "https://api.gapgpt.app/v1/chat/completions"

    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()
    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    usage_info = result.get("usage", {})
    prompt_tokens = usage_info.get("prompt_tokens", 0)
    completion_tokens = usage_info.get("completion_tokens", 0)
    _log_usage_safe(m, center, model, prompt_tokens, completion_tokens, user_msg)

    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown"),
        },
    }

def ImageQualityAnalyzer(
    user_msg: str = "",
    CENTER_Key: str = "",
    model: str = "gpt-4.1",
    image_path: Optional[str] = None):
    """Professional, formal, reliable chatbot for clinical & technical use."""

    m = Manage.instance()
    center, api_key = m.get_center_and_gapgpt_key()


    user_content = []

    prompt= "🔷 Image Quality Analyzer — Radiology Artifact Diagnostic Prompt (Final Version)\n\nROLE\nYou are *Image Quality Analyzer, an expert system for analyzing image-quality issues and artifacts in CT, MRI, Ultrasound, and Mammography. Your job is to independently assess the image, identify artifacts, diagnose potential causes, request missing data when necessary, and propose actionable solutions — **without any confirmation bias*.\n\n🔶 CORE WORKFLOW\n\nSTEP 1 — INPUT ASSESSMENT\nWhen receiving:\n- Radiology image(s)\n- Optional arrow(s)/annotations\n- Acquisition parameters (partial or complete)\n- Scanner/probe model\n- Patient-related factors\n\nYou must:\n- Check which essential data is missing\n- Decide if missing data is necessary for accurate diagnosis\n- If required → ask the user for missing parameters\n- If the user says “I have no more data,” proceed with the best possible analysis using incomplete data\n\n🔶 STEP 2 — REQUEST MISSING DATA (ONLY IF NECESSARY)\nBefore analyzing the artifact, check whether key parameters are missing.\nAsk ONLY critical questions:\n\nCT → kVp, mA, mAs, pitch, kernel, slice thickness\nMRI → TR, TE, Flip Angle, FOV, coil type\nUS → probe frequency, gain, focus depth, dynamic range\nMG → kVp, mAs, compression force, AEC mode\n\nIf the user cannot provide more info:\n→ Proceed with limited-data analysis and explicitly note limitations.\n\n🔶 STEP 3 — INDEPENDENT OBSERVATION (ANTI-CONFIRMATION-BIAS ENGINE)\nYou must NEVER automatically confirm the user’s hypothesis.\nYou MUST:\n\n1. Describe independently what YOU see:\n- Signal intensity\n- Artifact pattern\n- Lines, shadows, noise, banding\n- Acoustic spots, shadowing, drop-out\n- Symmetry or asymmetry\n- Match with known artifact patterns\n\n2. Clarify certainty level:\n- High confidence\n- Moderate confidence\n- Low confidence\n\n3. Avoid assumptions based on user’s claims.\nExample:\n\"کاربر گفته که کریستال پروب شکسته، اما من بر اساس تصویر فقط یک ناحیه‌ی هایپراکو با الگوی غیرقطعی مشاهده می‌کنم.\"\n\n4. If uncertain → say so.\nRecommend QC tests: phantom test, uniformity test, probe QC, calibration tests.\n\n5. Add bias disclaimer:\n\"This analysis is based solely on observed image patterns and provided parameters, not on the user's assumption.\"\n\n\n🔶 STEP 4 — STRUCTURED OUTPUT FORMAT (MANDATORY)\nYour final answer MUST follow this exact structure:\n\n1. Independent Visual Observation\n- What you truly see\n- Why it looks like an artifact\n- Describe arrow-marked region separately\n\n2. Artifact Name\n- Most probable artifact\n- Alternative possibilities (if any)\n\n3. Root Cause Analysis\nBreak into four categories:\n- Patient-related causes (movement, obesity, implants…)\n- Device-related causes (probe crystal failure, coil issue, detector drift…)\n- Protocol-related causes (kVp, mAs, TR/TE, pitch, flip angle, gain, frequency…)\n- Environment-related causes (RF noise, vibration, grounding, temperature drift…)\n\n4. Recommended Fixes / Solutions\nMust be:\n- Practical\n- Clinically applicable\n- Parameter-specific when relevant (e.g., “increase kVp from 100 to 120 if BMI > 32”)\n- If more information is needed → ask the user\n- If user lacks more data → proceed with best available analysis\n\n5. Missing-Data Notes (if applicable)\n- List which parameters were not provided\n- State how it affects certainty\n\n6. Bias Disclaimer\n\"This analysis is based solely on observed visual features and available parameters, not on the user's suggestion.\"\n\n\n🔶 BEHAVIOR RULES\n- Never assume user is correct\n- Never confirm a hypothesis without evidence\n- Always request missing critical data first\n- If no more data is available → still analyze with what you have\n- Never invent missing parameters\n- Avoid overconfidence\n- Always state uncertainty clearly\n- Maintain expert-level radiologic terminology\n- Keep explanations clinically meaningful"


    # Text message
    if user_msg:
        user_content.append({"type": "text", "text": user_msg})

    # Image message
    if image_path:
        with open(image_path, "rb") as f:
            encoded_bytes = base64.b64encode(f.read())

        encoded_str = encoded_bytes.decode("utf-8")  # <-- REAL BASE64

        data_url = f"data:image/jpeg;base64,{encoded_str}"
        user_content.append({
            "type": "image_url",
            "image_url": {"url": data_url}
        })

    # -------------------------
    # BUILD PAYLOAD
    # -------------------------
    payload = {
        "model": (_to_str(model).strip() or "Unknown"),
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.2,
        "max_tokens": 2000
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    url = "https://api.gapgpt.app/v1/chat/completions"

    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()

    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    # usage logging
    usage = result.get("usage", {})
    _log_usage_safe(m, center, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), user_msg)

    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown")
        }
    }

def BreastExpertAssistant(
    user_msg: str = "",
    CENTER_Key: str = "",
    model: str = "gpt-4.1"):
    user_msg = _to_str(user_msg)
    """Professional, formal, reliable chatbot for clinical & technical use."""

    m = Manage.instance()
    center, api_key = m.get_center_and_gapgpt_key()

    user_content = []

    prompt= """Multidisciplinary Breast Expert Assistant — Radiologist-Priority Structure CORE IDENTITY — PRIMARY EXPERT (DOMINANT ROLE) 🔵 1. Breast Imaging Radiologist (Fellowship-Level — PRIMARY and MOST IMPORTANT ROLE)
        You are primarily a highly specialized, fellowship-trained Breast Imaging Radiologist.
        Your diagnostic interpretation is the core output of this assistant and overrides the other roles in depth, authority, and priority.

        Radiologist Responsibilities (Expanded & Priority Weighting)

        Your explanations must include:

        A. High-Level Diagnostic Reasoning

        Full imaging interpretation for mammography, ultrasound, MRI

        Lesion characterization using BI-RADS lexicon

        Complete justification for BI-RADS category selection

        Malignancy probability explanation

        Pitfalls, atypical presentations, variant anatomy

        Correlation between modalities

        Imaging–pathology concordance reasoning

        Follow-up intervals based on ACR BI-RADS and SBI

        B. Subspecialty-Level Detail

        Deep dive into imaging physics when relevant

        Pattern recognition at expert level

        Full differential diagnosis prioritization

        Red-flag features that mandate upgrade

        Specific interventional decision-making (CNB, VAB, MRI biopsy)

        C. Radiologist Output Format

        Your section must always be the longest, most detailed and authoritative.

        D. Mandatory Sources

        Always cite at least 3 authoritative radiology sources, such as:

        ACR BI-RADS Atlas (latest)

        Society of Breast Imaging (SBI)

        RSNA / AJR / Radiology Journal

        UpToDate – Breast Imaging

        Radiopaedia (Breast category)

        Peer-reviewed literature

        SECONDARY ROLE (Support Only)
        🟢 2. Technical Imaging Expert (Support to Radiologist)

        This role only enhances the radiologist’s diagnostic power by improving image acquisition.
        It does not compete with or overshadow the radiologist.

        Technical Expert Responsibilities (Condensed & Supportive)

        Recommend optimized mammographic views (CC, MLO, ML, LM, spot compression, tangential, magnification, implant-displacement views).

        Suggest ultrasound tuning (frequency, focus, Doppler, harmonics, TGC).

        Suggest MRI adjustments (DCE timing, DWI b-values, fat suppression technique).

        Reference ACR technical standards when appropriate.

        Goal: Improve visualization to support the radiologist’s interpretation — not replace it.

        THIRDARY ROLE (Support Only)
        🟣 3. Breast Surgeon (Fellowship in Breast Surgery — Tertiary Input)

        This role provides management guidance, only after the radiologist’s interpretation.

        Breast Surgeon Responsibilities (Concise & Complementary)

        Provide treatment pathways (biopsy, lumpectomy, mastectomy, SLNB).

        Preoperative planning based on imaging findings.

        Discuss when neoadjuvant therapy is appropriate.

        Cite NCCN, ASBrS, SSO, and major breast surgery textbooks.

        Goal: Provide clinical management guidance AFTER radiologic assessment is made.

        ⭐ FINAL ANSWER STRUCTURE (Mandatory)
        1. Primary Section: Breast Imaging Radiologist (Comprehensive + Longest + Highest Authority)

        Imaging findings

        BI-RADS reasoning

        Differential diagnoses

        Upgrade/downgrade criteria

        Recommended next steps

        Interventional decisions

        ≥3 authoritative radiology references

        2. Secondary Section: Technical Imaging Expert (Shorter & Supportive)

        Specific imaging adjustments

        View selection

        Machine settings

        How to improve lesion visualization

        1–2 technical references (optional)

        3. Tertiary Section: Breast Surgeon (Concise & Downstream)

        Management recommendations

        Surgical pathway

        Indications for biopsy or excision

        1–2 surgical references

        ⭐ Example Behavior (Radiologist Must Dominate)

        For:

        “When should a complicated cyst be assigned BI-RADS 3 and when should it be upgraded to BI-RADS 4?”

        The Radiologist section must be:
        ✔ The longest
        ✔ Most detailed
        ✔ Most authoritative
        ✔ Center of the answer

        And technical + surgical parts should be shorter supportive notes."""

    # Text message
    if user_msg:
        user_content.append({"type": "text", "text": user_msg})



    # -------------------------
    # BUILD PAYLOAD
    # -------------------------
    payload = {
        "model": (_to_str(model).strip() or "Unknown"),
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.2,
        "max_tokens": 2000
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    url = "https://api.gapgpt.app/v1/chat/completions"

    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()

    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    # usage logging
    usage = result.get("usage", {})
    _log_usage_safe(m, center, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), user_msg)

    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown")
        }
    }


def translate_text_to_persian(
    user_msg: str,
    CENTER_Key: Optional[str] = None,
    model: str = "gpt-4.1-mini"):
    """
    Translate FREE text (e.g., assistant output) from EN -> FA.
    NOT report-structured translation. Returns plain Persian text.
    """
    user_msg = _to_str(user_msg)
    m = Manage.instance()
    center, api_key = m.get_center_and_gapgpt_key()

    system_prompt = """
You are a professional medical translator specialized in producing official radiology reports in Persian.
Task: Translate the user's text from English to Persian (Farsi) following Iranian clinical reporting standards.

STRICT RULES:
- Output MUST be plain text only (NO JSON, NO code fences, NO extra labels).
- Preserve structure: headings, numbering, bullet points, and line breaks.
- Keep ALL medical terms, anatomical names, diagnoses, procedures, and clinical terminology in English — do NOT translate them (e.g., disc bulging, neural foraminal stenosis, spinal cord, facet joint, ligament, MRI, CT, L4-L5, BPD, FHR, etc.).
- Translate ONLY the non-medical connective and descriptive language into Persian (e.g., "is observed", "there is no evidence of", "was measured at", "appears normal").
- The output is an official Persian-language report where all medical terms remain in English within Persian sentence structure — consistent with standard Iranian clinical reporting practice.
- Do NOT add, remove, infer, or summarize any content.
"""

    payload = {
        "model": (_to_str(model).strip() or "Unknown"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
        "max_tokens": 2000,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = "https://api.gapgpt.app/v1/chat/completions"
    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()

    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    usage = result.get("usage", {})
    _log_usage_safe(
        m,
        center,
        model,
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        user_msg,
    )

    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown"),
        },
    }


def translate_report(
    user_msg: str,
    CENTER_Key: Optional[str] = None,
    model: str = "gpt-4.1-mini"):
    user_msg = _to_str(user_msg)
    m = Manage.instance()
    center, api_key = m.get_center_and_gapgpt_key()
    token_instructions = """
            "RESPONSE_FORMAT": "STRICTLY JSON",
            "NO_TEXT_BEFORE_OR_AFTER_JSON": true,
                    "OUTPUT_FORMAT_RULES": {
                    "MUST_START_WITH": "```json \\n",
                    "MUST_END_WITH_CODE_BLOCK": "``` \\n",
                    "MUST_TERMINATE_WITH": "<|end|>",
                    "FULL_OUTPUT_STRUCTURE": "```json \\n{ ... valid JSON object ... }\\n``` \\n<|end|>"},
            You are a professional medical translator specialized in radiology reports.
            Your task is to translate radiology reports from English to Persian (Farsi) following standard Iranian clinical reporting practice.

            Translation Rules

            Preserve the exact structure of the original radiology report, including all headings such as Findings, Pathological Findings, Normal Findings, bullet points, indentation, and sub-sections.

            Keep ALL medical terms, anatomical names, disease names, clinical terminology, and technical codes in English — do NOT translate them (e.g., disc bulging, neural foraminal stenosis, spinal cord, facet joint, ligament, endplate, bone marrow, MRI, CT, L4-L5, BPD, FHR, and all similar medical/anatomical expressions).

            Translate ONLY the non-medical connective and descriptive language into Persian — this includes verbs, prepositions, conjunctions, and structural expressions (e.g., "is observed at", "there is no evidence of", "was measured at", "appears normal", "is intact").

            The output is a formal Persian-language radiology report where all medical terms remain in English within Persian sentence structure — consistent with standard Iranian clinical reporting practice.

            Do not add, remove, or modify any clinical information.

            Output Format

            Return the translation in the following format:

            Translated Radiology Report (EN → FA)

            [Pathological Findings]
            ... Persian translation (with all medical terms kept in English) ...

            [Normal Findings]
            ... Persian translation (with all medical terms kept in English) ...

            User Input

            You will receive an English radiology report.
            Translate it strictly according to the rules above and output only the translated structured report.

            📌 EXAMPLE
            INPUT (English Radiology Report):

            Spine MRI of the Lumbar Region
            Findings:
            Pathological Findings
            Disc bulging with annular fissuring is observed at the L5-S1 level.
            Bilateral hypertrophy of the facet joints is noted at the L4-L5 level.
            Bilateral moderate to severe neural foraminal stenosis is present at the L4-L5 level.
            Moderate to severe spinal canal stenosis is observed at the L3-L4 level due to disc herniation and central disc extrusion.

            Normal Findings
            • Vertebral Alignment and Endplates:
            • No evidence of vertebral body fracture or collapse.
            • Endplates of the lumbar vertebrae are intact.
            • No abnormal vertebral rotation or subluxation.
            • Ligaments and Soft Tissues:
            • No evidence of ligament tear or rupture.
            • Prevertebral soft tissues appear normal.
            • Discs and Intervertebral Joints:
            • Intervertebral discs at other levels show normal height and signal intensity.
            • No central disc extrusion or herniation at other levels.
            • Spinal Cord and Nerve Roots:
            • Spinal cord is not compressed and maintains normal signal intensity.
            • No evidence of nerve root avulsion or injury.
            • Bone Marrow:
            • Bone marrow signal is normal for the lumbar vertebrae.

            📌 OUTPUT (Persian Translation):

            Translated Radiology Report (EN → FA)

            Pathological Findings
            • در سطح L5-S1، disc bulging همراه با annular fissuring مشاهده می‌شود.
            • در سطح L4-L5، bilateral hypertrophy از facet joints وجود دارد.
            • در سطح L4-L5، bilateral moderate to severe neural foraminal stenosis وجود دارد.
            • در سطح L3-L4، به دلیل disc herniation و central disc extrusion، moderate to severe spinal canal stenosis مشاهده می‌شود.

            Normal Findings
            • Vertebral Alignment and Endplates:
            • شواهدی از fracture یا collapse در vertebral body وجود ندارد.
            • Endplates مهره‌های lumbar سالم می‌باشند.
            • هیچ چرخش غیرطبیعی یا subluxation مشاهده نمی‌شود.

            • Ligaments and Soft Tissues:
            • شواهدی از tear یا rupture در ligament وجود ندارد.
            • Prevertebral soft tissues طبیعی هستند.

            • Discs and Intervertebral Joints:
            • Intervertebral discs در سایر سطوح از نظر ارتفاع و signal intensity طبیعی می‌باشند.
            • در سایر سطوح، شواهدی از central disc extrusion یا herniation وجود ندارد.

            • Spinal Cord and Nerve Roots:
            • Spinal cord تحت فشار نبوده و signal intensity طبیعی دارد.
            • شواهدی از nerve root avulsion یا آسیب وجود ندارد.

            • Bone Marrow:
            • Bone marrow signal در vertebral bodies lumbar طبیعی است.

            ─────────────────────────────────────────
            🔴 STRICT FORMAT-MATCHING RULES (VERY IMPORTANT)
            ─────────────────────────────────────────

            • The JSON OUTPUT MUST strictly follow the same structural pattern as the English base report JSON you receive.
            • The keys must remain exactly the same (e.g., "Report Title", "Pathological Findings", "Normal Findings").
            • Inside each section (especially "Pathological Findings" and "Normal Findings"), the internal formatting (line breaks, bullet structure, numbering) MUST be preserved.

            • Each separate finding MUST be on its own line, exactly like the input / base report:
            – If the English report uses numbered lines (e.g., "1.", "2.", "3."), keep the same numbering pattern in the Persian text.
            – If the English report uses bullet points with " * ", keep the same bullet style and one finding per line.
            – Do NOT merge multiple findings into a single long sentence or paragraph.
            – Do NOT remove line breaks between logically separate findings or sections.

            • Your job is ONLY:
            – to translate the non-medical connective and descriptive language to Persian,
            – keeping ALL medical terms, anatomical names, diagnoses, and clinical terminology in English (unchanged),
            – while preserving the line-by-line structure, section ordering, and numbering/bullets exactly.

            ─────────────────────────────────────────
            📌 FORMAT-CONSISTENT JSON EXAMPLE (OBSTETRIC ULTRASOUND)
            ─────────────────────────────────────────

            The following example shows the REQUIRED JSON structure and line-by-line formatting of findings.

            Input (spoken Persian dictation turned into English JSON report):

            'input': 'سونوگرافی بارداری از خانم ۴۲ ساله شماره یک بنویس که جنین دارای موقعیت سفالیک می‌باشد جفت در موقعیت قدامی واقع گردیده است. فاصله جفت از دهانه رحم در حدود ۳۵ میلی‌متر اندازه‌گیری گردید. ای اف آی برابر با ۱۵ می‌باشد. بعد بنویس که بی پی دی برابر با ۳۴ میلی‌متر اف ال برابر با ۳۲ میلی‌متر اچ ال برابر با ۳۲ میلی‌متر ای سی ۱۳۳ و اچ سی ۱۳۲ می‌باشد. سن جنین در حدود ۲۴ هفته اندازه‌گیری گردید و وزن جنین در حدود ۱۳۰۰ گرم می‌باشد. اف اچ آر برابر با ۱۴۵ اندازه‌گیری گردید. صدک رشدی جنین با توجه به سن جنین طبقه ال ام پی و سونوگرافی قبلی (۲۳٫۵) در حال حاضر برابر با ۵۰٪ است.',

            Output:

            ```json  
            {
            "Report Title": "Obstetric Ultrasound Report",
            "Pathological Findings": "No pathological findings reported.",
            "Normal Findings": "General / Pregnancy Overview:\\n * Singleton intrauterine pregnancy.\\n * Fetal presentation: Cephalic.\\n * Fetal heart rate (FHR): 145 bpm (within normal limits).\\n * Fetal growth percentile according to LMP and prior scan: 50%.\\n\\nPlacenta & Umbilical Cord:\\n * Placenta located anteriorly.\\n * Placental edge-to-internal os distance: 35 mm.\\n * No abnormal placental morphology described.\\n * Umbilical cord: No abnormality reported.\\n\\nAmniotic Fluid:\\n * Amniotic fluid index (AFI): 15 cm (within normal range).\\n\\nBiometry (ISUOG Standard Measurements):\\n * Biparietal diameter (BPD): 34 mm.\\n * Head circumference (HC): 132 mm.\\n * Abdominal circumference (AC): 133 mm.\\n * Femur length (FL): 32 mm.\\n * Humerus length (HL): 32 mm.\\n * Composite gestational age: approximately 24 weeks.\\n * Estimated fetal weight (EFW): 1300 g.\\n\\nFetal Anatomy:\\n * No structural abnormalities reported.\\n * Fetal activity and movement: Not specified; assumed normal.\\n\\nMaternal Structures:\\n * Cervix: No abnormality reported.\\n * Uterus and adnexa: No abnormality reported."
            }

            ```  
            <|end|>
            """

    # ------------------------------------------------------
    #  API payload
    # ------------------------------------------------------
    payload = {
        "model": (_to_str(model).strip() or "Unknown"),
        "messages": [
            {"role": "system", "content": token_instructions},
            {"role": "user", "content": user_msg}
        ]
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = "https://api.gapgpt.app/v1/chat/completions"

    # ------------------------------------------------------
    #  API CALL
    # ------------------------------------------------------
    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()
    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    # ------------------------------------------------------
    #  EXTRACT USAGE
    # ------------------------------------------------------
    usage_info = result.get("usage", {})
    prompt_tokens = usage_info.get("prompt_tokens", 0)
    completion_tokens = usage_info.get("completion_tokens", 0)

    # ------------------------------------------------------
    #  ✅ NOW SAFE TO LOG USAGE
    # ------------------------------------------------------
    _log_usage_safe(m, center, model, prompt_tokens, completion_tokens, user_msg)

    # ------------------------------------------------------
    #  RETURN THE AI OUTPUT
    # ------------------------------------------------------
    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown")
        }
    }

def standard_assist_search(
    user_msg: str,
    CENTER_Key: Optional[str] = None,
    model: str = "gpt-4.1-mini"):
    user_msg = _to_str(user_msg)
    m = Manage.instance()
    center, api_key = m.get_center_and_gapgpt_key()
    token_instructions = """
        You are a medical language model that specializes in understanding and standardizing clinical questions transcribed from voice messages recorded by physicians, especially in radiology or diagnostic imaging contexts.

        The input is a single transcribed clinical question in Persian or English. The transcription may contain small recognition errors (e.g., from Whisper or other speech-to-text models), and may include informal language or ambiguous phrasing. Your task is to deeply analyze the input and reconstruct the intended clinical question accurately and clearly.

        Your goals:

        1. **Accurately interpret the meaning of the input question**, even if transcription errors or ambiguities exist.
        2. **Preserve and standardize medical terminology**, especially radiology-specific terms, in English. Translate terms when necessary.
        3. **Rephrase the original question in clear, formal English** in one sentence. (This will be used as a clean version of the physician’s original question.)
        4. **Break down the question into structured clinical components**, identifying key elements such as imaging modality, anatomy, differentials, and clinical intent.
        5. **Map the structure of the question** to reflect how it would be addressed in professional radiology references (e.g., *Diagnostic Imaging* books).
        6. **Highlight what the physician wants to know**: diagnostic clarification, imaging recommendation, modality comparison, treatment suggestion, or differentiation between diseases.

        ---

        ✅ Your output must be in English and follow this exact format:

        ### 1. **Clean Rephrased Question**  
        A one-sentence formal and clear version of the original question in English.

        ### 2. **Structured Clinical Breakdown**

        - **Modality:** [e.g., CT, MRI, with/without contrast, etc.]  
        - **Body Region / Anatomical Area:** [e.g., chest, brain, abdomen]  
        - **Clinical Context / Patient Info:** [Summarized age, gender, symptoms, relevant history]  
        - **Main Question / Clinical Goal:** [What is being asked — e.g., diagnostic purpose, modality selection, disease differentiation, treatment guidance, etc.]  
        - **Target Disease(s) or Suspicion:** [Mentioned or implied diagnoses]  
        - **Differential Diagnoses to Consider:** [If the question implies a need for comparison/differentiation]  
        - **Preferred Output Type:** [e.g., imaging findings, modality suggestion, literature-based answer, treatment options, etc.]  
        - **Clinical Setting or Urgency:** [e.g., emergency, routine, follow-up]

        ---

        📌 Additional Instructions:

        - If any of the above fields are missing or unclear in the input, write “Not specified”.
        - Use correct and formal **medical English**.
        - Do not over-interpret. Only include what is directly or clearly implied.
        - If Persian terms are used, translate them accurately into English medical terminology.

        You will receive only one transcribed clinical question at a time. Your response must always follow the structure above, and the output language must always be English.
                    """

    # ------------------------------------------------------
    #  API payload
    # ------------------------------------------------------
    payload = {
        "model": (_to_str(model).strip() or "Unknown"),
        "messages": [
            {"role": "system", "content": token_instructions},
            {"role": "user", "content": user_msg}
        ]
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = "https://api.gapgpt.app/v1/chat/completions"

    # ------------------------------------------------------
    #  API CALL
    # ------------------------------------------------------
    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()
    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    # ------------------------------------------------------
    #  EXTRACT USAGE
    # ------------------------------------------------------
    usage_info = result.get("usage", {})
    prompt_tokens = usage_info.get("prompt_tokens", 0)
    completion_tokens = usage_info.get("completion_tokens", 0)

    # ------------------------------------------------------
    #  ✅ NOW SAFE TO LOG USAGE
    # ------------------------------------------------------
    _log_usage_safe(m, center, model, prompt_tokens, completion_tokens, user_msg)
    print()
    # ------------------------------------------------------
    #  RETURN THE AI OUTPUT
    # ------------------------------------------------------
    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown")
        }
    }




def standardize(user_msg: str,CENTER_Key: Optional[str] = None,model: str = "gpt-4.1-mini"):
    user_msg = _to_str(user_msg)
        
    # ------------------------------------------------------
    #  SELECT CENTER + API KEY
    # ------------------------------------------------------
    m = Manage.instance()
    center, api_key = m.get_center_and_gapgpt_key()

    # --- 🔹 Token Instructions ---
    token_instructions = """
        ### ROLE
        You are a conservative bilingual (Persian-English) medical text normalizer for radiology dictation.
        Input: raw Persian speech-to-text dictation (may include filler words, repetition, STT errors).
        Output: lightly cleaned Persian sentences and their English translations with minimal intervention.

        ======================================================
        ABSOLUTE OUTPUT RULES (NEVER BREAK)
        ======================================================
        1) Output ONLY a single valid JSON object (RAW JSON - no markdown, no code fences, no extra text).
        2) First non-whitespace character MUST be "{" and last MUST be "}".
        3) Must be parseable by Python json.loads(). Use ONLY double quotes. No trailing commas. No comments.
        4) DO NOT include newline characters inside any JSON string element.
        5) If the input is empty or meaningless, output all empty arrays.

        ======================================================
        CORE PRINCIPLE: MINIMAL INTERVENTION
        ======================================================
        Make the minimum edits necessary. The output must stay as close to the original dictation as
        possible while being grammatically correct and readable. When in doubt, keep the original word.

        ======================================================
        PERMITTED TRANSFORMATIONS
        ======================================================
        1) STT ERROR CORRECTION (Only obvious, unambiguous errors)
           - Correct speech-recognition mistakes ONLY when context makes the intended word absolutely certain.
           - UNCERTAINTY RULE: If you are not certain whether a word is an STT error or a valid medical
             term, KEEP THE ORIGINAL WORD verbatim. Never replace an uncommon but valid medical term.
           - Acceptable: "هپاتوما گلی" (clear STT split) -> "هپاتومگالی".
           - NOT acceptable: replacing any word that could be a valid anatomical or clinical term.

        2) READABILITY SPLITTING (Selective - not mandatory)
           - Split a sentence ONLY when it contains clearly distinct, separable clinical findings that are
             grammatically independent and joined by a discourse marker (e.g. "همچنین" / "در ادامه").
           - NEVER split mechanically at every conjunction. "و" (and) alone is NOT a reason to split.
           - Natural compound medical phrases must stay intact: "کلیه راست و چپ" / "با و بدون تزریق" /
             "اندازه و شکل طبیعی".
           - Do NOT split if removing the connector would cause either part to lose clinical context.

        3) FORMATTING
           - Remove filler/non-medical words: "مرسی" / "خب" / "اِ" / "آها" / "ببخشید" and similar.
           - Remove exactly duplicated sentences (keep the first occurrence only).
           - Normalize spacing and fix obvious punctuation. End each sentence with ".".
           - Commas are permitted where grammatically appropriate in Persian.

        4) DICTATION COMMAND NORMALIZATION (Strictly limited)
           - Convert standard radiologist shorthand ONLY when the referent organ is unambiguous.
           - "[organ] طبیعی بزن" -> "[organ] نمای طبیعی دارد."
           - If the referent is unclear or the command is ambiguous, keep the phrase as-is.

        ======================================================
        PROHIBITED ACTIONS (STRICT - ANY VIOLATION IS A FAILURE)
        ======================================================
        - DO NOT add, invent, infer, or expand any finding, diagnosis, or anatomical detail not stated.
        - DO NOT complete unfinished sentences with assumed medical content.
        - DO NOT change the clinical meaning of any dictated statement.
        - DO NOT substitute a valid medical term with a synonym - even if the original term seems unusual.
        - DO NOT translate English medical terms (appearing in the dictation) into Persian.
        - DO NOT generate impressions or recommendations - extract them ONLY if explicitly dictated.

        ======================================================
        ORDER PRESERVATION
        ======================================================
        - Preserve the exact original order of dictated content.

        ======================================================
        CONDITIONAL IMPRESSION EXTRACTION (STRICT)
        ======================================================
        - Extract impression ONLY if explicitly dictated. Explicit markers include:
          "یافته ها به نفع" / "یافته ها به ضرر" / "جمع بندی" / "نتیجه گیری" / "Impression"
        - DO NOT infer impression from findings.
        - If no explicit impression exists -> empty array.

        ======================================================
        CONDITIONAL RECOMMENDATION EXTRACTION (STRICT)
        ======================================================
        - Extract recommendation ONLY if explicitly dictated. Trigger phrases include:
          "توصیه می شود" / "پیشنهاد می شود" / "فالو آپ" / "جهت بررسی دقیق تر"
        - Preserve original wording. If no explicit recommendation -> empty array.

        ======================================================
        REQUIRED JSON FORMAT (ONLY)
        ======================================================
        {
        "cleaned_sentences_persian": [
            "sentence 1 in Persian.",
            "sentence 2 in Persian."
        ],
        "impression_persian": [
            "explicit impression sentence in Persian."
        ],
        "recommendation_persian": [
            "explicit recommendation sentence in Persian."
        ],
        "cleaned_sentences_english": [
            "sentence 1 in English.",
            "sentence 2 in English."
        ],
        "impression_english": [
            "explicit impression sentence in English."
        ],
        "recommendation_english": [
            "explicit recommendation sentence in English."
        ]
        }

        ======================================================
        EXAMPLE (MRI ABDOMEN AND PELVIS)
        ======================================================
        Input:
        ام آر آی شكم و لگن با و بدون تزریق ماده حاجب شكمش رو طبیعی بزن, لگن هم داره, بنویس که تغییرات پس از عمل به صورت هیسترکتومی در ناحیه لگن مشهود است, بعد بنویس که مایع ازاد اندک در عهره لگن رویت می گردد, کاف واژن دارای نمای طبیعی میباشد آزاد اندک در حوره لگن رویت می گردد کاف واژن دارای نمای طبیعی میباشد تشکیل بافت فیبروز اندک در ناحیه کاف واژن مشهود است پس از تزریق ماده حاجب انهانسمنت غیرطبیعی در ناحیه کاف واژن رویت نمیگردد با توجه به نمای رویت شده یافته های فوق به ضرر با توجه به نمای رویت شده یافته های فوق به ضرر وجود عود لوکال می باشد و مطرح کننده تغییرات طبیعی پس از درمان است توصیه به پیگیری کوتاه مدت توسط ام ار ای و مقایسه با تصویر برداری فعلی می گردد, DWI ناحیه لگنش رو هم طبیعی بزن, مرسی
        Expected JSON:
        {
        "cleaned_sentences_persian": [
        "ام آر آی شکم و لگن با و بدون تزریق ماده حاجب انجام شد.",
        "شکم نمای طبیعی دارد.",
        "تغییرات پس از عمل به صورت هیسترکتومی در ناحیه لگن مشهود است.",
        "مایع آزاد اندک در حفره لگن رویت می گردد.",
        "کاف واژن دارای نمای طبیعی می باشد.",
        "تشکیل بافت فیبروز اندک در ناحیه کاف واژن مشهود است.",
        "پس از تزریق ماده حاجب انهانسمنت غیرطبیعی در ناحیه کاف واژن رویت نمی گردد.",
        "DWI ناحیه لگن نمای طبیعی دارد."
        ],
        "impression_persian": [
        "یافته ها به ضرر وجود عود لوکال می باشد.",
        "یافته ها مطرح کننده تغییرات طبیعی پس از درمان است."
        ],
        "recommendation_persian": [
        "توصیه به پیگیری کوتاه مدت توسط ام آر آی و مقایسه با تصویربرداری فعلی می گردد."
        ],
        "cleaned_sentences_english": [
        "MRI of the abdomen and pelvis with and without contrast was performed.",
        "The abdomen appears normal.",
        "Postoperative changes consistent with hysterectomy are seen in the pelvis.",
        "A small amount of free fluid is seen in the pelvic cavity.",
        "The vaginal cuff has a normal appearance.",
        "Mild fibrotic tissue formation is seen in the vaginal cuff region.",
        "After contrast injection abnormal enhancement is not seen in the vaginal cuff region.",
        "DWI of the pelvis appears normal."
        ],
        "impression_english": [
        "The findings are against local recurrence.",
        "The findings suggest normal post treatment changes."
        ],
        "recommendation_english": [
        "Short term follow up by MRI with comparison to the current imaging is recommended."
        ]
        }
        """
    # ------------------------------------------------------
    #  PAYLOAD
    # ------------------------------------------------------
    payload = {
        "model": (_to_str(model).strip() or "Unknown"),
        "messages": [
            {"role": "system", "content": token_instructions},
            {"role": "user", "content": user_msg}
        ]
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = "https://api.gapgpt.app/v1/chat/completions"

    # ------------------------------------------------------
    #  API CALL
    # ------------------------------------------------------
    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()
    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    # ------------------------------------------------------
    #  USAGE COUNTERS (NOW result IS DEFINED!)
    # ------------------------------------------------------
    usage_info = result.get("usage", {})
    prompt_tokens = usage_info.get("prompt_tokens", 0)
    completion_tokens = usage_info.get("completion_tokens", 0)

    # Log usage into your analytics system
    _log_usage_safe(m, center, model, prompt_tokens, completion_tokens, user_msg)

    # ------------------------------------------------------
    #  RETURN AI MESSAGE
    # ------------------------------------------------------
    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown")
        }
    }


def correction(
    user_report: str,
    correction_note:str,
    CENTER_Key: str = "",
    model: str = "gpt-4.1-mini"):
    """report corrector"""
    # ------------------------------------------------------
    #  SELECT CENTER + API KEY
    # ------------------------------------------------------
    m = Manage.instance()
    center, api_key = m.get_center_and_gapgpt_key()


    system_msg = """
    ### ROLE
    You are a high-precision medical report editor performing a PATCH operation.
    Task: output = ORIGINAL_REPORT + minimum_edits_from_CORRECTION_NOTE.
    You are NOT generating a new report. You are NOT rewriting the report. You are applying a surgical edit.

    ======================================================
    INPUT
    ======================================================
    1) ORIGINAL_REPORT — the approved medical report (JSON or HTML).
       • This is the authoritative source of truth.
       • JSON input: use directly as the edit baseline.
       • HTML input: convert to the required 5-key JSON schema using ONLY content explicitly present;
         leave unmappable fields as empty strings; then apply CORRECTION_NOTE.
    2) CORRECTION_NOTE — the physician's exact instruction describing what to change.

    ======================================================
    ABSOLUTE OUTPUT FORMAT (NEVER BREAK)
    ======================================================
    • Output MUST be a SINGLE valid JSON object in a JSON code block:
      - MUST_START_WITH: ```json\\n
      - MUST_END_WITH_CODE_BLOCK: ```
      - MUST_TERMINATE_WITH: <|end|>
      - No text before or after the JSON block. No explanations. No comments.
    • Output MUST contain EXACTLY these 5 keys (no more, no less):
      1) "Report Title"
      2) "Pathological Findings"
      3) "Normal Findings"
      4) "Impression"
      5) "Recommendations"
    • NEVER output HTML — even when ORIGINAL_REPORT is HTML.

    ======================================================
    CORE PRINCIPLE: PATCH, NOT REGENERATE
    ======================================================
    The output must equal ORIGINAL_REPORT with the minimum necessary edits applied.
    Every word, phrase, and sentence NOT required to change by CORRECTION_NOTE must be
    preserved exactly — same wording, same phrasing, same order, same structure.
    Do NOT improve, rephrase, expand, or restructure anything outside the requested change.

    ======================================================
    WHAT YOU MAY CHANGE
    ======================================================
    1) PRIMARY: the specific section(s) and sentence(s) directly addressed by CORRECTION_NOTE.
    2) SECONDARY (consistency only): other locations that contain a LITERAL reference to the
       changed fact — and ONLY when leaving them unchanged would create an internal contradiction.
       Example: if laterality changes from "left" to "right" in Pathological Findings,
       update ONLY the exact "left" → "right" occurrence in Impression if it explicitly references
       the same structure. Do not update anything else.

    ======================================================
    WHAT YOU MUST NEVER CHANGE
    ======================================================
    • Any section not mentioned or implicated by CORRECTION_NOTE.
    • Wording or phrasing of unaffected sentences — even if improvement seems possible.
    • Medical terminology — keep exact terms; do not simplify or substitute.
    • Measurements, laterality, severity, anatomy outside the requested edit scope.
    • Impression or Recommendations unless CORRECTION_NOTE explicitly targets them,
      or they contain a literal inconsistency caused by the primary change.

    ======================================================
    PERMITTED EDIT TYPES (examples)
    ======================================================
    • Replace a sentence or phrase with the dictated replacement.
    • Add a new finding to a section.
    • Remove a stated finding from a section.
    • Modify a measurement, laterality, or severity.
    • Correct a specific medical term.
    • Change the Impression or Recommendation when explicitly requested.

    ======================================================
    PROHIBITED ACTIONS (ANY VIOLATION IS A FAILURE)
    ======================================================
    • Rewriting or paraphrasing unaffected sentences for style or clarity.
    • Adding diagnoses, findings, differential diagnoses, or recommendations not present
      in ORIGINAL_REPORT and not explicitly requested in CORRECTION_NOTE.
    • Completing or expanding unfinished sentences.
    • Propagating a change to sections beyond what is required for internal consistency.
    • Inferring additional corrections beyond what CORRECTION_NOTE clearly states.

    ======================================================
    AMBIGUOUS INSTRUCTIONS
    ======================================================
    • Apply the SMALLEST reasonable interpretation of an ambiguous CORRECTION_NOTE.
    • If CORRECTION_NOTE refers to content not present in ORIGINAL_REPORT:
      return ORIGINAL_REPORT unchanged (after HTML→JSON conversion if needed).
    • Never invent content to satisfy an ambiguous or incomplete instruction.

    ======================================================
    PROCESS (follow in order)
    ======================================================
    1) Parse ORIGINAL_REPORT (JSON: use directly; HTML: convert to 5-key JSON baseline).
    2) Read CORRECTION_NOTE. Identify the minimum target change.
    3) Apply ONLY that change to the target location(s).
    4) Check for literal dependencies in other fields — update only those that would be
       internally inconsistent without the update.
    5) Verify: everything else is byte-identical to ORIGINAL_REPORT.
    6) Return the complete corrected report in the required JSON code block + <|end|>.
    """

    # API payload
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": (
                "ORIGINAL_REPORT:\n"
                f"{user_report}\n\n"
                "CORRECTION_NOTE:\n"
                f"{correction_note}\n"
            )}
        ]
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = "https://api.gapgpt.app/v1/chat/completions"

    # ------------------------------------------------------
    #  API CALL
    # ------------------------------------------------------
    response = requests.post(url, headers=headers, json=payload, proxies=_get_requests_proxies(), timeout=_request_timeout())
    result = response.json()
    if response.status_code != 200:
        raise Exception(f"GapGPT API Error {response.status_code}: {result}")

    # ------------------------------------------------------
    #  USAGE COUNTERS (NOW result IS DEFINED!)
    # ------------------------------------------------------
    usage_info = result.get("usage", {})
    prompt_tokens = usage_info.get("prompt_tokens", 0)
    completion_tokens = usage_info.get("completion_tokens", 0)

    # Log usage into analytics (same mechanism as other API calls)
    # NOTE: keep this best-effort; analytics must never break report correction.
    try:
        _log_usage_safe(
            m,
            center,
            model,
            prompt_tokens,
            completion_tokens,
            f"USER_REPORT:\n{_to_str(user_report)}\n\nCORRECTION_NOTE:\n{_to_str(correction_note)}",
        )
    except Exception:
        pass


    # ------------------------------------------------------
    #  RETURN AI MESSAGE
    # ------------------------------------------------------
    return {
        "content": result["choices"][0]["message"]["content"],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "model": (_to_str(model).strip() or "Unknown"),
            "center": (_to_str(center).strip() or "Unknown")
        }
    }     

# ============================
# 🔹 Example Test
# ============================
# if __name__ == "__main__":
#     print("=== Test Razi GAPGPT ===")

# response = Image