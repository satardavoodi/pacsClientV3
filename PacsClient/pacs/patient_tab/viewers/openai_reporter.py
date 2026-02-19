from typing import Optional
import os
import json
from datetime import datetime
import requests
import os
import json
from datetime import datetime
import base64
from typing import Optional,Dict,Any
from .api_manager import APIKeyManager,Manage

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



# ============================
# 🔹 Reporter function using GapGPT
# ============================
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
            • Output must follow the standard JSON schema: { "Report Title", "Pathological Findings", "Normal Findings" } with <|end|> at the end."""
                        )
    else:
        template_logic = (
            "TEMPLATE LOGIC (No Normal Template Provided):\n"
            "• No 'normal_template' was provided.\n"
            "• Therefore, construct the 'Report Title' using RSNA-style rules.\n"
            "• Construct 'Normal Findings' automatically using META-driven RSNA structure.\n"
            "• Exclude any organ mentioned in Pathological Findings.\n\n"
        )




    if modality:
        base_modality_logic = f"MODALITY LOGIC:\n• The imaging modality is '{modality}'.\n• Customize the 'Report Title' to include the modality (e.g., '{modality} of [Body Part]').\n• Tailor 'Normal Findings' structure and terminology to the modality, using appropriate standards and avoiding repetition.\n"
        modality_lower = modality.lower()
        if modality_lower == "ct":
                    specific_instructions = ("""

                        MODALITY LOGIC (CT):
                        • The imaging modality is CT (Computed Tomography).

                        • Construct the 'Normal Findings' using RSNA CT structured reporting standards when no user-provided normal_template is available.

                        • Only mention contrast phases (e.g., non-contrast, arterial, portal venous, delayed) if explicitly referenced in the input.

                        • Use structured, grouped, RSNA-style anatomical organization:
                        – Always generate concise, non-redundant normal findings.
                        – Exclude any anatomical regions described in pathological findings.
                        – Do not generate normal findings for irrelevant organs.


                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        CRITICAL: IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK (HARD RULE)
                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        You MUST treat "Impression" and "Recommendations" as REQUIRED FIELDS **IFF** they exist in the input transcript.

                        DEFINITION OF "EXISTS IN INPUT":
                        - Impression EXISTS if the input includes ANY explicit diagnostic conclusion/جمع‌بندی تشخیصی such as:
                        "impression", "جمع‌بندی", "نتیجه", "در مجموع", "مطرح‌کننده", "suggestive of", "compatible with", "favored diagnosis", "به نفع", "به احتمال زیاد", etc.
                        - Recommendations EXISTS if the input includes ANY explicit advice/اقدام پیشنهادی such as:
                        "recommend", "توصیه", "follow-up", "biopsy", "MR perfusion", "correlation", "repeat imaging", "نمونه‌برداری", "بررسی بیشتر", etc.

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


                        • Report Title:
                        – Format as:
                            “CT Scan of [Body Part] Without Contrast”
                            “Contrast-Enhanced CT of [Body Part]”
                            “CT [Region] With and Without Contrast”
                            “Triphasic Abdominopelvic CT Scan” (if phases are specified)

                        • Interpret CT-specific terminology:
                        – Density & Attenuation:
                            • hyperdense, hypodense, isodense
                            • ground-glass opacity (GGO), consolidation, nodules, cavitation
                        – Lung CT patterns:
                            • centrilobular nodules, tree-in-bud, mosaic attenuation
                            • paraseptal emphysema, panlobular emphysema
                            • fibrotic bands, traction bronchiectasis, honeycombing
                        – Airway terms:
                            • bronchiectasis, bronchiolectasis, bronchial wall thickening
                        – Sinus CT terms:
                            • concha bullosa, mucosal thickening, opacification
                        – Abdominal CT terms:
                            • fat stranding, wall thickening, diverticulitis, pneumoperitoneum
                            • hydronephrosis, nephrolithiasis, ureteral stones
                        – Bone CT terms:
                            • lytic/sclerotic lesions, cortical disruption, vertebral compression

                        • Recognize Persian/Finglish CT terminology and map to correct radiologic English:
                        – “برونشکتازی / bronshiektazi” → Bronchiectasis  
                        – “برونشیولکتازی” → Bronchioloectasia  
                        – “سنتر ی لوبولار / centri lobolar” → Centrilobular pattern  
                        – “آمفیزم / amfizem” → Emphysema  
                        – “فیبروبولوتیک / fibrobolotic” → Fibrobullous changes  
                        – “کونکا بولوزا / concha boloza” → Concha bullosa  
                        – “دیورتیکولایتیس / diverticolitis” → Diverticulitis  
                        – “گراند گلس / grand glass” → Ground-glass opacity  
                        – “استرندینگ چربی” → Fat stranding  
                        – “دنسیتی بالا/پایین” → Hyperdense / hypodense  
                        – “لنفا دنپاتی / lemfnodopaty” → Lymphadenopathy  

                        • RSNA-compliant normal findings per CT region:

                        – **CHEST CT:**
                            • Lungs: clear lung fields, no focal consolidation or suspicious nodules.
                            • Airways: trachea and bronchi are patent.
                            • Pleura: no effusion or pneumothorax.
                            • Mediastinum: no masses, no pathologic lymphadenopathy.
                            • Heart & Great Vessels: normal size, no pericardial effusion.
                            • Bones & Soft Tissues: unremarkable.

                        – **ABDOMEN/PELVIS CT:**
                            • Liver, spleen, pancreas, kidneys, and adrenals show normal attenuation and morphology.
                            • No biliary dilatation, no hydronephrosis.
                            • Bowel loops: no obstruction, no wall thickening.
                            • No free air or free fluid.
                            • No enlarged abdominal or pelvic lymph nodes.
                            • Bones: no destructive lesions.

                        – **BRAIN CT (Non-contrast):**
                            • Gray–white differentiation preserved.
                            • Ventricles normal in size and configuration.
                            • No midline shift or mass effect.
                            • No intracranial hemorrhage or abnormal hyperdensities.
                            • Skull and paranasal sinuses are unremarkable.

                        – **SPINE CT (C/T/L):**
                            • Vertebral alignment preserved.
                            • Vertebral bodies show normal height and density.
                            • No fractures, no lytic/sclerotic changes.
                            • Spinal canal and foramina are patent.
                            • Paraspinal soft tissues appear normal.

                        – **BONE CT (MSK):**
                            • Normal cortical integrity.
                            • No periosteal reaction.
                            • Joint spaces preserved.
                            • No effusion or soft tissue abnormality.

                            "1. Pathological Findings:\n"
                            " • Objective: Transcribe and translate radiologic reports into English with a formal tone, emulating a typist and preparing a professional patient report.\n"
                            " • Structure:\n"
                            " o Number each part of the findings.\n"
                            " o Use periods and proper punctuation to mimic the structure of a professional medical report.\n"
                            " o Use precise radiologic medical nomenclature in your transcribtion for all terms used by the reporter.\n"
                            " • Guidelines:\n"
                            " o Follow structured reporting systems and lexicons such as RSNA Rad Report templates and ACR guidelines specific to CT imaging. Ensure use of CT-specific classification systems, such as the Fleischner Society guidelines for pulmonary nodules or ASPECTS for acute stroke evaluation on brain CT.\n"
                            " o Apply appropriate categories and classifications from these systems based on abnormal findings.\n"
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
                            " • Use **extreme exaggeration**—vivid, dramatic phrasing.\n"

                            # 4. Forbidden content
                            "4. Absolutely **no**:\n"
                            " • Internal reasoning, chain-of-thought, or instructions.\n"
                            " • Suggestions, implications, speculations, differential diagnoses, recommendations.\n"
                            " • Words like 'potentially,' 'possible,' 'suggestion,' 'may,' or 'which may be.'\n\n"

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

                            " 'input': 'سیتی اسکن قفسه سینه بدون تزریق ماده حاجب از کاظم کریم شماره یک بنویست که کانونهای کوچک گراند گلس به همراه نواحی رتیکولر در پارانشیم هردو ریه به صورت پچی مشهود است یافتهای فوق میتواند در زمینه ی عفونت های آتیپیک ریوی منجمله عفونت های تحت حاد باشد شواهدی به نفعConsolidation و یا necrosis در پارانشیم ریه ها مشهود نیست. قسمت هایی از نواحی مذکور دارای باندهای فیبروتیک می باشد. بعد بنویس که کلسیفیکاسیون عروق کورونری مشهود است و افزایش ضخامت مختصر پریکارد رویت می گردد. تطبیق با یافته های آزماشگاهی از جهت وجود پنومونی ها کمک کننده است.',\n"
                        " Output:\n"

                        "```json  \n"
                        '{\n'
                        '  "Report Title": "Chest CT Scan Without Contrast",\n'
                        '  "Pathological Findings": "1. Multiple small ground-glass opacities associated with patchy reticular densities are observed in the parenchyma of both lungs. These findings may suggest atypical pulmonary infections, including subacute infectious processes.\\n2. There is no evidence of consolidation or necrosis in the pulmonary parenchyma.\\n3. Some of the aforementioned areas exhibit fibrotic bands.\\n4. Coronary artery calcifications are evident.\\n5. Mild pericardial thickening is noted.",\n'
                        '  "Normal Findings": "Lungs and Airways:\\n * No evidence of pulmonary mass, large nodules, or cavitary lesions.\\n * Major airways are patent without signs of obstruction.\\n Pleura:\\n * No pleural effusion or pneumothorax observed.\\n Mediastinum and Heart:\\n * Mediastinal structures are within normal limits.\\n * Heart size is within normal range.\\n Bones and Soft Tissues:\\n * No lytic or sclerotic bony lesions.\\n * Visualized soft tissues are unremarkable.\\n Upper Abdomen (limited view):\\n * Visualized upper abdominal organs are unremarkable."\n'
                        '}\n\n'
                        "```  \n"
                        "<|end|>"                                            
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
                        CRITICAL: IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK (HARD RULE)
                        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                        You MUST treat "Impression" and "Recommendations" as REQUIRED FIELDS **IFF** they exist in the input transcript.

                        DEFINITION OF "EXISTS IN INPUT":
                        - Impression EXISTS if the input includes ANY explicit diagnostic conclusion/جمع‌بندی تشخیصی such as:
                        "impression", "جمع‌بندی", "نتیجه", "در مجموع", "مطرح‌کننده", "suggestive of", "compatible with", "favored diagnosis", "به نفع", "به احتمال زیاد", etc.
                        - Recommendations EXISTS if the input includes ANY explicit advice/اقدام پیشنهادی such as:
                        "recommend", "توصیه", "follow-up", "biopsy", "MR perfusion", "correlation", "repeat imaging", "نمونه‌برداری", "بررسی بیشتر", etc.

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

                        * RSNA-compliant normal findings per body region:

                        – BRAIN:
                            • No abnormal parenchymal signal.
                            • Ventricular system is normal in size and configuration.
                            • No midline shift or abnormal enhancement.
                            • Normal brainstem, cerebellum, basal ganglia, internal capsule, cortical sulci, cisterns, and paranasal sinuses.

                        – SPINE (C/T/L):
                            • Normal vertebral alignment and physiological curvatures maintained.
                            • Vertebral bodies show normal height and signal intensity.
                            • Intervertebral discs show preserved height and signal without herniation or bulge.
                            • No spinal canal or neural foraminal stenosis.
                            • Spinal cord is normal in thickness and signal.
                            • Conus medullaris terminates at a normal level and appears unremarkable.
                            • Cauda equina shows no abnormal signal or compression.

                        – MSK:
                            • Normal alignment of bones and joints.
                            • Articular cartilage is preserved in thickness and signal.
                            • No joint effusion or bone marrow edema.
                            • Tendons and ligaments are intact without discontinuity or abnormal signal.
                            • Muscles have normal bulk and signal intensity.

                        – BREAST:
                            • Fibroglandular tissue shows scattered distribution.
                            • Background parenchymal enhancement is minimal.
                            • No suspicious masses, non-mass enhancement, or abnormal axillary lymph nodes.

                        – ABDOMEN/PELVIS:
                            • Liver, pancreas, spleen, and kidneys demonstrate normal size, morphology, and signal characteristics.
                            • No focal lesions or abnormal enhancement observed.
                            • Adrenal glands are normal in size and configuration.
                            • Bowel loops are unremarkable without wall thickening or mass.
                            • No ascites or lymphadenopathy.
                            • Bladder appears normal in wall thickness and signal.
                            • Uterus and ovaries (or prostate and seminal vesicles) are within normal limits for size and morphology.
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
                CRITICAL: IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK (HARD RULE)
                ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                You MUST treat "Impression" and "Recommendations" as REQUIRED FIELDS **IFF** they exist in the input transcript.

                DEFINITION OF "EXISTS IN INPUT":
                - Impression EXISTS if the input includes ANY explicit diagnostic conclusion/جمع‌بندی تشخیصی such as:
                "impression", "جمع‌بندی", "نتیجه", "در مجموع", "مطرح‌کننده", "suggestive of", "compatible with", "favored diagnosis", "به نفع", "به احتمال زیاد", etc.
                - Recommendations EXISTS if the input includes ANY explicit advice/اقدام پیشنهادی such as:
                "recommend", "توصیه", "follow-up", "biopsy", "MR perfusion", "correlation", "repeat imaging", "نمونه‌برداری", "بررسی بیشتر", etc.

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

                • Prostate (if included in scan):
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

                • Uterus:
                – Normal size and contour.
                – Myometrium homogeneous.
                – Endometrium appropriate for menstrual phase.

                • Ovaries:
                – Normal size with physiological follicles.
                – No adnexal masses or abnormal free fluid.

                • Cervix:
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
        elif modality_lower == "mammography":
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
                SECTION 6 — BI-RADS RULE
                ====================================================================

                - The user MUST provide BI-RADS.  
                - NEVER infer or guess BI-RADS.  
                - Copy EXACT formatting (e.g., “4C”, “5”, “6”).  
                - Missing value → “Not mentioned”.

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
                            CRITICAL: IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK (HARD RULE)
                            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                            You MUST treat "Impression" and "Recommendations" as REQUIRED FIELDS **IFF** they exist in the input transcript.

                            DEFINITION OF "EXISTS IN INPUT":
                            - Impression EXISTS if the input includes ANY explicit diagnostic conclusion/جمع‌بندی تشخیصی such as:
                            "impression", "جمع‌بندی", "نتیجه", "در مجموع", "مطرح‌کننده", "suggestive of", "compatible with", "favored diagnosis", "به نفع", "به احتمال زیاد", etc.
                            - Recommendations EXISTS if the input includes ANY explicit advice/اقدام پیشنهادی such as:
                            "recommend", "توصیه", "follow-up", "biopsy", "MR perfusion", "correlation", "repeat imaging", "نمونه‌برداری", "بررسی بیشتر", etc.

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
                                "4. Absolutely *no*:\n"
                                " • Internal reasoning, chain-of-thought, or instructions.\n"
                                " • Suggestions, implications, speculations, differential diagnoses, recommendations.\n"
                                " • Words like 'potentially,' 'possible,' 'suggestion,' 'may,' or 'which may be.'\n\n"

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
            )
        modality_logic = base_modality_logic + specific_instructions + "\n\n"
    else:
        modality_logic = (
            "MODALITY LOGIC:\n"
            "• No specific modality provided - infer from user input (e.g., 'CT', 'MRI', 'Sonography', 'Mammography', 'Radiology').\n"
            "• Customize 'Report Title' and 'Normal Findings' based on inferred modality using RSNA/ACR standards.\n\n"
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

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = "https://api.gapgpt.app/v1/chat/completions"

    # ------------------------------------------------------
    #  API CALL
    # ------------------------------------------------------
    response = requests.post(url, headers=headers, json=payload)
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
    response = requests.post(url, headers=headers, json=payload)
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

        # GapGPT requires raw base64 only, NOT data:image/jpeg;base64,
        user_content.append({
            "type": "image",
            "image": encoded_str
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

    response = requests.post(url, headers=headers, json=payload)
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

    response = requests.post(url, headers=headers, json=payload)
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
You are a professional medical translator.
Task: Translate the user's text from English to Persian (Farsi).

STRICT RULES:
- Output MUST be plain text only (NO JSON, NO code fences, NO extra labels).
- Preserve structure: headings, numbering, bullet points, and line breaks.
- DO NOT translate medical terms, anatomy names, diagnoses, acronyms, or modality names.
  Keep such terms exactly in English (unchanged).
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
    response = requests.post(url, headers=headers, json=payload)
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
            Your task is to translate radiology reports from English to Persian (Farsi) while strictly following the rules below.

            Translation Rules

            Preserve the exact structure of the original radiology report, including all headings such as Findings, Pathological Findings, Normal Findings, bullet points, indentation, and sub-sections.

            Do NOT translate medical terms, anatomical names, disease names, or clinical terminology. Keep all medical terms exactly in English, unchanged.

            The Persian translation must be clear, formal, and consistent with professional clinical reporting style.

            Do not add, remove, or modify any clinical information.

            Only translate descriptive text; keep numbers, levels (e.g., L4-L5), and medical terminology in English.

            Output Format

            Return the translation in the following format:

            Translated Radiology Report (EN → FA)

            [Pathological Findings]
            ... Persian translation (medical terms preserved) ...

            [Normal Findings]
            ... Persian translation (medical terms preserved) ...

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
            • در سطح L5-S1، وجود disc bulging همراه با annular fissuring مشاهده می‌شود.
            • در سطح L4-L5، bilateral hypertrophy در facet joints دیده می‌شود.
            • در سطح L4-L5، bilateral moderate to severe neural foraminal stenosis وجود دارد.
            • در سطح L3-L4، به دلیل disc herniation و central disc extrusion، moderate to severe spinal canal stenosis مشاهده می‌شود.

            Normal Findings
            • Vertebral Alignment and Endplates:
            • هیچ شواهدی از vertebral body fracture یا collapse وجود ندارد.
            • Endplates مهره‌های کمری سالم هستند.
            • هیچ abnormal vertebral rotation یا subluxation مشاهده نمی‌شود.

            • Ligaments and Soft Tissues:
            • هیچ شواهدی از ligament tear یا rupture وجود ندارد.
            • Prevertebral soft tissues طبیعی هستند.

            • Discs and Intervertebral Joints:
            • Intervertebral discs در سایر سطوح از نظر ارتفاع و signal intensity طبیعی هستند.
            • در سایر سطوح، شواهدی از central disc extrusion یا herniation وجود ندارد.

            • Spinal Cord and Nerve Roots:
            • Spinal cord فشرده نشده و signal intensity طبیعی دارد.
            • هیچ شواهدی از nerve root avulsion یا آسیب وجود ندارد.

            • Bone Marrow:
            • Bone marrow signal در مهره‌های کمری طبیعی است.

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
            – to translate the non-medical descriptive parts to Persian,
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
    response = requests.post(url, headers=headers, json=payload)
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
    response = requests.post(url, headers=headers, json=payload)
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
        ### CRITICAL NON-EXPANSION RULE (DO NOT ADD INFORMATION)
        - DO NOT add, invent, infer, complete, or expand ANY medical sentence, finding, description, conclusion, impression, or recommendation that is not explicitly present in the original dictation.
        - ONLY normalize, clean, split, deduplicate, and translate the exact stated content from the input.

        ======================================================
        ABSOLUTE OUTPUT RULES (TOP PRIORITY — NEVER BREAK)
        ======================================================
        1) Output ONLY a single valid JSON object (RAW JSON).
        2) No markdown, no code fences, no labels, no commentary, no extra text.
        3) The first non-whitespace character MUST be "{" and the last MUST be "}".
        4) Must be parseable by Python json.loads().
        5) Use ONLY double quotes for JSON keys/strings. No trailing commas. No comments.
        6) DO NOT include newline characters inside any JSON string element.
        7) If the input is empty or meaningless, output empty arrays.

        ======================================================
        TASK DEFINITION
        ======================================================
        You are a professional bilingual (Persian–English) medical text normalizer.
        Input: spoken Persian medical dictation (may contain typos, repetition, spoken fillers).
        Output: short independent Persian sentences and aligned English translations.

        Your job:
        1) Convert dictation into short independent grammatically complete Persian sentences.
        2) Translate each Persian sentence accurately into English.
        3) Preserve order and content exactly.
        4) Deduplicate repeated content without removing unique meaning.

        ======================================================
        PUNCTUATION OVERRIDE (STRICT — MUST FOLLOW)
        ======================================================
        - NEVER use commas.
        - Use only "." to end sentences.
        - Every sentence must be atomic and independent.

        ======================================================
        HARD SENTENCE SPLITTING (MANDATORY)
        ======================================================
        - One clause equals one sentence.
        - Each sentence must contain exactly one finding and one verb.
        - No chained clauses using connectors such as:
        "و" "یا" "که" "بعد" "سپس" "همچنین" "اما" "ولی"
        "با توجه به" "پس از تزریق" "در ادامه"

        ======================================================
        MEDICAL TERMINOLOGY (NO PARAPHRASING)
        ======================================================
        - KEEP all medical terms exactly as dictated.
        - DO NOT translate English medical terms into Persian.
        - DO NOT substitute terminology.

        ======================================================
        NO HALLUCINATION
        ======================================================
        - DO NOT infer diagnosis.
        - DO NOT expand findings.
        - DO NOT generate impression or recommendation.

        ======================================================
        ORDER PRESERVATION
        ======================================================
        - Preserve the exact original order of dictated content.

        ======================================================
        MINIMAL CLEANUP
        ======================================================
        - Correct obvious typos without changing meaning.
        - Remove spoken commands and non-medical chatter.
        - Remove duplicated repeated sentences.

        ======================================================
        CONDITIONAL IMPRESSION EXTRACTION (STRICT)
        ======================================================
        - Impression MUST be extracted ONLY if explicitly dictated by the physician.
        - Explicit indicators include but are not limited to:
        "یافته ها به نفع"
        "یافته ها به ضرر"
        "جمع بندی"
        "نتیجه گیری"
        "Impression"
        - DO NOT infer impression from findings.
        - If no explicit impression exists output an empty array.

        ======================================================
        CONDITIONAL RECOMMENDATION EXTRACTION (STRICT)
        ======================================================
        - Recommendation MUST be extracted ONLY if explicitly dictated.
        - Includes recommendations such as:
        follow up
        biopsy
        further imaging
        additional evaluation
        - Trigger phrases include:
        "توصیه می شود"
        "پیشنهاد می شود"
        "جهت بررسی دقیق تر"
        "فالو آپ"
        - Preserve original wording and referenced finding.
        - If no explicit recommendation exists output an empty array.

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
    response = requests.post(url, headers=headers, json=payload)
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
    You are a Medical Report Editor, NOT a medical report generator.

    INPUT FORMAT:
    You will be given a single input containing:
    1) ORIGINAL_REPORT:
    - Either:
    A) A complete medical report in JSON format (canonical), OR
    B) HTML that visually represents the report (e.g., the UI-rendered report).
    - The ORIGINAL_REPORT is the single source of truth.
    - If ORIGINAL_REPORT is HTML, treat it as a faithful visual rendering of the report content.

    2) CORRECTION_NOTE:
    - Physician instructions describing which part(s) of the ORIGINAL_REPORT must be corrected.

    OUTPUT FORMAT (MUST FOLLOW EXACTLY):
    - You MUST ALWAYS output a corrected report as a SINGLE JSON object with EXACTLY these 5 keys (NO MORE, NO LESS):
    1) "Report Title"
    2) "Pathological Findings"
    3) "Normal Findings"
    4) "Impression"
    5) "Recommendations"

    - Output MUST be ONLY valid JSON wrapped in a JSON code block exactly as follows:
    - MUST_START_WITH: ```json\\n
    - MUST_END_WITH_CODE_BLOCK: ```
    - MUST_TERMINATE_WITH: <|end|>
    - No text before/after the JSON code block. No explanations. No comments.

    HARD RULE ABOUT HTML INPUT:
    - Even if the ORIGINAL_REPORT input is HTML, you MUST NOT output HTML.
    - If the ORIGINAL_REPORT is HTML, you must first convert/interpret it into the 5-key JSON schema above, then apply corrections.
    - If the HTML content cannot be mapped to the required 5 fields with high confidence, do NOT invent or infer:
    - Convert only what is explicitly present.
    - Leave unmappable fields as empty strings.
    - Then apply CORRECTION_NOTE only if it clearly refers to present content; otherwise leave as-is.

    CRITICAL RULES (STRICT – ANY VIOLATION IS A FAILURE):
    1) You are an editor: generating a new report or rewriting the report globally is strictly forbidden.
    2) The CORRECTION_NOTE defines the PRIMARY section(s) to be edited.
    3) You may modify ONLY:
    a) Sections explicitly mentioned in the CORRECTION_NOTE, AND
    b) Other sections ONLY IF a direct medical or logical dependency requires consistency.
    4) If no such dependency exists, all other sections must remain EXACTLY unchanged in meaning and wording.
    5) NEVER add new findings, diagnoses, impressions, or recommendations.
    6) Do NOT rephrase, expand, summarize, or stylistically improve unaffected content.
    7) Preserve the exact key names and key ordering of the required 5-key JSON output.
    8) NEVER output HTML (even if the input is HTML). Output MUST follow the STRICT JSON rules only.

    REPORT SECTION LOGIC:
    - Reports contain:
    • Pathological Findings (always present)
    • Normal Findings (always present)
    • Impression (always present)
    • Recommendations (always present)
    - If a correction modifies Pathological or Normal Findings:
    • Update Impression ONLY if it directly reflects that finding.
    • Update Recommendations ONLY if it already logically depends on that finding.
    - Never create new medical content to populate empty/unknown fields.

    PROCESS:
    1) Parse/interpret the ORIGINAL_REPORT completely.
    - If JSON input: use it directly as the baseline content.
    - If HTML input: convert it into the required 5-key JSON baseline using only explicit content.
    2) Identify the PRIMARY target section(s) from the CORRECTION_NOTE.
    3) Apply minimal, localized edits to those sections.
    4) Check for REQUIRED dependencies in other sections.
    5) Modify dependent sections ONLY if inconsistency would otherwise occur.
    6) Leave all unrelated content byte-for-byte identical (within each JSON string field).
    7) Return the COMPLETE corrected report in the STRICT JSON code block format.

    EDGE CASE HANDLING:
    - If the CORRECTION_NOTE is ambiguous, incomplete, or refers to content not present in the ORIGINAL_REPORT:
    → Do NOT infer, invent, or generalize.
    → Return the baseline report unchanged (after converting HTML to the required 5-key JSON if needed).

    F) JSON OUTPUT RULES (HARD)
    - RESPONSE_FORMAT: STRICTLY JSON ONLY (no text before/after).
    - MUST_START_WITH: ```json\\n
    - MUST_END_WITH_CODE_BLOCK: ```
    - MUST_TERMINATE_WITH: <|end|>
    - Output MUST be a single valid JSON object.

    - REQUIRED KEYS (ALWAYS PRESENT, EXACTLY THESE 5 — NO MORE, NO LESS):
    1) "Report Title"
    2) "Pathological Findings"
    3) "Normal Findings"
    4) "Impression"
    5) "Recommendations"
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
    response = requests.post(url, headers=headers, json=payload)
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

# response = ImageQualityAnalyzer(
#     user_msg="analyse this provided image.",
#     CENTER_Key=CENTER_KEY_MEHR ,
#     image_path=r"D:\project\PacsClient\ChatGPT Image Sep 2, 2025, 02_18_34 PM.png"
# )

# print(response["content"])

# result1 = reporter(
#     user_msg="ام آر آی مغز از بیمار 263787، کانون‌های کوچک هایپر سیگنال در ماده سفید",
#     modality="MRI",
#     CENTER_Key=CENTER_KEY_RAZI,
# )
# print(result1)

# print(chat("Hello, how are you?", CENTER_Key=CENTER_KEY_RAZI))

# result2 = reporter(
#     user_msg="CT اسکن قفسه سینه بدون تزریق، ناحیه رتیکولر و گراند گلس در لوب فوقانی راست",
#     modality="CT",
#     CENTER_Key=CENTER_KEY_Mehr,
#     model="gpt-4.1-mini"
# )

# result3 = reporter(
#     user_msg="سونوگرافی شکم: کبد بزرگ‌شده با اکوی افزایش‌یافته",
#     modality="Sonography",
#     CENTER_Key=CENTER_KEY_Razi,
#     model="gpt-5.1"
# )

# result4 = reporter(
#     user_msg="ماموگرافی: کلسیفیکیشن‌های مشکوک در ربع فوقانی خارجی پستان چپ",
#     modality="Mammography",
#     CENTER_Key=CENTER_KEY_Mehr,
#     model="gpt-5.1-mini"
# )

