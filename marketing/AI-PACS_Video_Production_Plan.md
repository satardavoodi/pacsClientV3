# AI-PACS — Video Production Plan (First Deliverable)

**Prepared for:** Dr. Alizadeh / vahid — Alizadeh Medical Imaging Center
**Product:** AI-PACS — *Intelligent Medical Imaging* (DICOM Workstation / PACS) · company: INO-Pooyan
**Primary brand in videos:** **AI-PACS** · **Language:** English
**Date:** 2026-06-09
**Status:** Plan for your approval. No final videos generated yet. Higgsfield not yet connected (see §1).

---

## 0. Status at a glance

| Item | Status |
|------|--------|
| 1. Higgsfield MCP connection | **Not connected yet** — confirmed no Higgsfield tools in this session; not in Claude's built-in connector registry. Manual custom-connector setup required (§1). |
| 2. Higgsfield tools/models | Researched from Higgsfield's site/docs (§2). Exact tool names to be confirmed in-app after connecting. |
| 3. Observed AI-PACS features | **Verified live** on your running source build, monitors DELL S2421HN + LCD1970NXp (§3). |
| 4. Three promotional concepts | Ready (§4). |
| 5. Five tutorial concepts | Ready (§5), plus 3 more stubbed. |
| 6. Recommended first video | **A1 — 15-second teaser** (§6). |
| 7. First-video Higgsfield prompts | Ready, copy-paste (§6). |

> **Golden rule for this project:** Real software UI for everything clinical; Higgsfield only for cinematic intro/outro, atmosphere, and abstract AI-imaging visuals. Never replace the real UI with an AI-hallucinated interface.

---

## 1. Higgsfield MCP — connection (Claude Desktop / Cowork)

**Current state:** I checked this session — there are **no `higgsfield` tools available**, and Higgsfield is **not** in Claude's built-in connector directory. So it must be added manually as a **custom connector** using the official URL you provided.

### 1a. Add the connector (do this once, in Claude Desktop)
1. Open **Claude Desktop → Settings** (your name / gear, bottom-left) **→ Connectors** (a.k.a. *Extensions / MCP*).
2. Click **Add custom connector**.
3. **Name:** `Higgsfield`  ·  **URL:** `https://mcp.higgsfield.ai/mcp`  ·  **Transport:** HTTP (Streamable HTTP).
4. Save. Claude will trigger an **OAuth sign-in** in your browser — approve it on the browser where your **Higgsfield Plus** account is already logged in.
5. **Restart Claude Desktop** so the new tools load. (MCP tools are read at startup — they will not appear mid-session.)

### 1b. (Optional) Claude Code CLI — if you also want it in VS Code
```
claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp
```
Then run `/mcp` inside Claude Code to complete OAuth and verify.

### 1c. Verify before generating anything
After restart, ask me to **list the Higgsfield tools**. We proceed only once tools like *generate image / generate video / list models / job status* are visible and a 1-frame test render succeeds.

### 1d. Constraints that shape the plan
- **Clip length:** Higgsfield clips are **up to ~15 seconds each**. A 30s or 60s promo is **several clips edited together** (in Camtasia), not one render.
- **Official server only:** we use `https://mcp.higgsfield.ai/mcp`. We do **not** use third-party/unofficial Higgsfield MCP servers. (Several exist on GitHub; ignore them unless the official server fails, in which case I'll explain why before suggesting an alternative.)

---

## 2. Higgsfield tools & models (expected — confirm in-app after connecting)

Higgsfield's hosted MCP exposes 30+ models behind a small tool surface. Based on current Higgsfield documentation:

**Likely tools:** generate **image**, generate **video** (text-to-video and image-to-video), **train character** (Soul ID), **list models**, **job/status** polling, **browse history**, and **Marketing Studio** presets.

**Video models:** Seedance 2.0, Sora 2, Kling 3.0, Veo 3.1, WAN 2.6/2.7, Hailuo 02.
**Image models:** Soul 2.0, Nano Banana Pro, Flux 2, Seedream 5.0 Lite, GPT Image 2.

**Capabilities we will use:**
- **Image-to-video** — generate a still (logo plate, abstract imaging visual), then animate it with a camera move.
- **Camera/motion presets** — pan, tilt, dolly, zoom, FPV drone, crash zoom (250+ presets).
- **Soul ID** — optional: train one consistent "radiologist" character from 3–5 photos so they recur across clips. (For medical credibility, prefer neutral professional faces; never imply a real named clinician endorses the product.)
- **Marketing Studio presets** — UGC / product-review / TV-spot styles for fast social cuts.

**Model picks for this project (cinematic realism, medical-professional tone):** **Veo 3.1** or **Kling 3.0** for live-action reading-room/hospital atmosphere; **Seedream/Flux 2** for abstract AI-imaging plates and logo backgrounds. We'll A/B two models on the first hero clip.

---

## 3. Observed AI-PACS features (verified live)

> Captured directly from your running workstation. **"Confirmed on screen"** = I saw it this session. **"Present — confirm before scripting"** = the entry/tab exists but I did not open it (so we verify the exact UI before recording a tutorial). I have **not** invented any feature.

### 3a. Confirmed on screen
**Home / PACS patient browser**
- Source tabs: **Local · Server · Import**. PACS server picker (**"razi" — Server Ready**).
- **Modality filter** checkboxes: **CT, MR, MG, CR, DX, US, XA, OT, PX**.
- Search by **Patient ID**, **Patient Name**, and **date range** (custom date).
- Patient table columns: **Patient Name, Patient ID, Body Part, Status, Report, Assign, Time, Date, Images, Modality, Age**, with a multi-modality study-count badge (e.g. "48 US, 20 MRI, 11 CT…") and per-row download indicators.
- Top actions: **Offline Sync, Print, Download, Study Information**, font size A−/A+, refresh, settings, delete, "Adaptive to Screen Size".
- **Study Information** right panel = **per-series thumbnails** (Series 0/1/2/3 with sequence labels + image counts).

**Left navigation modules** (expanded rail): **Home · Data Analysis · Print · Settings · Download Manager · Web Browser · Educational Courses · Theme · Information · Get Help**.

**DICOM viewer (2D)**
- Studies open as **tabs** (multiple patients at once).
- **Series Thumbnails** panel grouped by study (e.g. "Study 1 — CSPINE (6 series)") with sequence names (localizer, t2_tse_sag, t1_tse_sag, t2_haste_cor/sag, t2_me2d_tra) and slice counts.
- **Multi-viewport layout** (2-up shown; layout selector present) with **synced cross-reference lines** between planes (sagittal↔axial).
- **DICOM corner overlays**: patient name/ID/age/sex, date, slice index, series description, slice thickness, matrix size, scale, **window/level**, plus institution footer "**ALIZADEH MEDICAL IMAGING CENTER (Dr. Alizadeh)**".
- **Toolbar tools:** reset · viewport-layout · measurement/ruler · window/level · eraser/clear · zoom · pan · stack/layers · rotate · crosshair/reference · **camera capture** · **microphone (voice)** · annotation/pen · **MPR** · cloud upload.
- Viewer side-tabs: **Series · Reception Data · ECHO MIND · EAGLE EYE · Advanced Analysis**.

**MPR + 3D (flagship)**
- True **tri-planar reconstruction** — Axial, Sagittal, Coronal — with **interactive green crosshair** navigation and orientation markers (A/P/R/L/S/I) and live slice indices.
- **Real-time 3D volume rendering** in the 4th pane. Demonstrated on **MR cervical spine**, **abdomen/pelvis CT** (Bone + Tissue recons, 303 slices each), and **head CT** (clear **3D facial reconstruction** from a 192-slice volume).

**AI assistant:** **ECHO MIND** orb on the home page and as a viewer side-tab; microphone/voice control in the viewer toolbar.

### 3b. Present — confirm before scripting (don't film until verified)
- **MIP / MinIP / Thick-Slab** projection modes — accessed via the projection menu next to **MPR** (menu control seen; exact on-screen labels to confirm). *High priority — you requested a MIP/MinIP tutorial.*
- **Reporting workflow** — a **Report** column/status exists on the home table; the report editor itself was not opened.
- **EAGLE EYE** and **Advanced Analysis** — viewer side-tabs visible (per project history: comparison/mammography review and advanced/3D visualization); contents not opened.
- **Educational Courses** — nav item visible; module not opened.
- **Data Analysis**, **Download Manager**, **Web Browser**, **Theme**, **Settings** — nav items visible; not opened.

### 3c. Suitability map

| Feature | Promo | Tutorial |
|---|:---:|:---:|
| 3D volume render (CT face / vessels / bone) | ★★★ | ★★ |
| MPR tri-planar + crosshair | ★★★ | ★★★ |
| MIP/MinIP projection | ★★ | ★★★ |
| Multi-viewport sync + reference lines | ★★ | ★★★ |
| PACS browser + modality search | ★ | ★★★ |
| Window/Level | ★ | ★★★ |
| Study Information / metadata overlays | ★ | ★★★ |
| ECHO MIND voice assistant | ★★★ | ★★ |
| Reporting workflow | ★ | ★★★ |
| Offline Sync / Download Manager | ★ | ★★ |
| Educational Courses | ★★ | ★★ |

### 3d. PHI / anonymization (mandatory before any public use)
Your live archive shows **real patient identifiers**. Every frame that ships publicly must be de-identified:
- Prefer a **dedicated demo/teaching patient** with non-identifying data, **or** AI-PACS's anonymize/de-identify function if available (your CD-burner already supports anonymize-on-publish; confirm an equivalent for screen capture).
- **3D face renders are identifiable** — for public videos, **deface/blur**, use a consented head, or switch to a **skull/bone or vessel 3D preset** (equally dramatic, not identifiable).
- In editing, **blur/black-box** the name/ID/age/sex corner overlay and the browser tab title. Keep the **institution footer** (it's your brand — good to show).
- Keep raw recordings on local/internal storage only.

---

## 4. Track A — Promotional concepts (3)

> Hybrid format throughout: **real UI** carries the clinical message; **Higgsfield** supplies intro/outro + atmosphere. Palette matches the app: near-black background, **teal/blue** accents, clean sans-serif. Music: modern, restrained, "medical-tech."

### A1 — 15-second social teaser — *"See more. Decide faster."*
- **Audience:** radiologists & imaging-center owners scrolling LinkedIn / Instagram / Telegram.
- **Main message:** AI-PACS turns any scan into instant 2D, MPR, and 3D — one fast workstation.
- **Shot list (0:00–0:15):**
  - 0–3s — *Higgsfield:* slow push-in on a dark radiology reading room, monitors glowing teal.
  - 3–8s — *Real capture:* open a study → **MPR tri-planar** appears → **3D render rotates**.
  - 8–12s — *Real capture:* scroll the stack, a quick **window/level** swipe, a **measurement**.
  - 12–15s — *Higgsfield/lemotion graphic:* **AI-PACS** logo lockup + tagline + CTA.
- **Visual style:** cinematic, high-contrast, vertical **9:16**, fast cuts on the beat.
- **Voice-over (~32 words):** "Every scan — fully explored, in seconds. AI-PACS brings 2D, multi-planar reconstruction, and 3D into one fast workstation. Intelligent medical imaging, built for radiologists."
- **On-screen text:** "Open. Reconstruct. Report." → "**AI-PACS** · Intelligent Medical Imaging".
- **Higgsfield prompts:** see §6 (this is the recommended first video).
- **Required real captures:** (1) open study→MPR→3D rotate; (2) stack scroll + W/L + measure. *(anonymized)*
- **Editing plan:** 9:16; burn-in captions; 1 logo sting; license-safe music; export 1080×1920 H.264.

### A2 — 30-second product-feature video — *"One workstation. Every view."*
- **Audience:** imaging-center decision-makers, radiology department heads, distributors.
- **Main message:** AI-PACS is a complete DICOM workstation — browse PACS, read in 2D, reconstruct in MPR/MIP/3D, report, and drive it by voice.
- **Shot list (0:00–0:30):**
  - 0–4s — *Higgsfield:* hospital/reading-room atmosphere, a radiologist sits down (no identifiable real person).
  - 4–9s — *Real:* PACS browser — modality filters, "razi" server, study list + thumbnails.
  - 9–15s — *Real:* viewer — dual-pane **synced** sagittal+axial with reference line.
  - 15–21s — *Real:* **MPR tri-planar + 3D** (CT) navigating with the crosshair.
  - 21–26s — *Real:* **ECHO MIND** voice assistant / reporting touchpoint.
  - 26–30s — *Higgsfield + graphic:* logo, tagline, contact/CTA.
- **Visual style:** confident, slightly slower than A1; **16:9** master + **9:16** cut-down.
- **Voice-over (~70 words):** "Radiology shouldn't mean ten different tools. AI-PACS unifies them. Pull any study from your PACS, read it in synchronized views, and reconstruct it in multi-planar and 3D with a single click. Measure, window, and report without leaving the screen — or just ask ECHO MIND, your built-in assistant. One workstation. Every view. AI-PACS — intelligent medical imaging."
- **On-screen text:** feature chips — "PACS browse" · "MPR & 3D" · "MIP / MinIP" · "Voice assistant" · "Reporting".
- **Higgsfield prompts (atmosphere):** reading-room dolly-in; abstract DICOM-slices-to-3D morph; logo plate. *(full prompts on approval)*
- **Required real captures:** browser; dual-pane sync; MPR/3D; assistant; reporting. *(anonymized)*
- **Editing plan:** 16:9 1080p master; chaptered captions; export 16:9 + 9:16 + 1:1.

### A3 — 45–60-second professional introduction — *"AI-PACS — Intelligent Medical Imaging"*
- **Audience:** prospective imaging centers/hospitals, conference & website hero, distributor decks.
- **Main message:** a credible, end-to-end tour: the problem (fragmented, slow tools) → AI-PACS as one intelligent workstation → proof across modules → close.
- **Shot list (0:00–0:60):**
  - 0–6s — *Higgsfield:* cinematic open — dark department, monitors waking, soft VO hook.
  - 6–14s — *Real:* PACS browser + offline sync + multi-modality archive.
  - 14–24s — *Real:* viewer depth — layouts, sync, overlays, measurements, window/level.
  - 24–36s — *Real:* **MPR + MIP/MinIP + 3D** hero sequence (CT) — the flagship.
  - 36–46s — *Real:* **ECHO MIND** assistant + **reporting** + **Educational Courses**.
  - 46–54s — *Higgsfield:* abstract "AI sees more" imaging visual (vessels/organs forming from slices).
  - 54–60s — Logo, tagline, **INO-Pooyan**, website/contact CTA.
- **Visual style:** premium, measured pacing, **16:9**; consistent teal accent and lower-thirds.
- **Voice-over (~120 words):** full script drafted on approval (problem → solution → modules → AI → close).
- **On-screen text:** section lower-thirds: "Connect to your PACS" · "Read faster" · "Reconstruct in 3D" · "Report in place" · "Powered by AI".
- **Higgsfield prompts:** open atmosphere, mid abstract morph, closing logo world — 3–4 clips, ≤15s each.
- **Required real captures:** all five module sequences above. *(anonymized)*
- **Editing plan:** 16:9 1080p (4K optional); branded intro/outro templates reused from A1/A2; export web + YouTube + Instagram + internal.

---

## 5. Track B — Tutorial concepts (5 + 3 stubbed)

> **Real screen recording only** (Camtasia 2024 — installed). Higgsfield is **not** used inside tutorials. Each ≤ 60s, 1080p, with zoom-to-cursor, callout arrows/boxes, and a calm instructional VO. Use an **anonymized demo patient**. Export master **16:9 1080p** + verticals **9:16** for Shorts/Reels; same file serves website + internal training.

### T1 — Open a DICOM study
- **Learning objective:** load a patient's study from the PACS into the viewer.
- **Click sequence:** Home → **Server** tab → confirm "razi / Server Ready" → tick a **modality** (e.g. CT) → set **date** → **Search Patients** → **single-click** a patient (thumbnails load in Study Information) → **double-click** to open → in the viewer, click a **series thumbnail** to load it into a viewport.
- **Required clips:** server select; search; single-click→thumbnails; double-click→viewer; series load.
- **Narration:** "Start on the Server tab and confirm your PACS is ready. Filter by modality and date, then search. A single click previews the patient's series; a double click opens the study. Click any series to load it."
- **Callouts:** highlight Server/Ready, modality row, single-vs-double-click, series panel.
- **Length:** ~45s.

### T2 — Adjust window / level
- **Objective:** set brightness/contrast for the tissue of interest.
- **Click sequence:** load a CT series → select the **Window/Level** tool → **drag** in the image (horizontal = window, vertical = level) → read the live **W/L** in the corner overlay → (confirm preset list e.g. lung/abdomen/bone/brain if present) → reset.
- **Required clips:** tool select; drag with overlay changing; preset pick; reset.
- **Narration:** "Window and level control contrast. Pick the tool and drag — left-right widens or narrows the window, up-down shifts the level. Watch the values update in the corner. Presets jump straight to lung, bone, or soft-tissue."
- **Callouts:** W/L tool, drag direction diagram, overlay W/L value.
- **Length:** ~40s.

### T3 — Multi-planar reconstruction (MPR)
- **Objective:** turn an axial stack into synchronized Axial/Sagittal/Coronal + 3D.
- **Click sequence:** open a **CT** series → click **MPR** → observe tri-planar + 3D → **drag the green crosshair** to move all planes → scroll a plane to change slice → rotate the 3D.
- **Required clips:** click MPR (load); crosshair drag (planes update together); slice scroll; 3D rotate.
- **Narration:** "One click reconstructs the volume. Now you have axial, sagittal, and coronal — all linked. Drag the crosshair and every plane follows; the 3D updates in real time."
- **Callouts:** MPR button, crosshair handles, orientation letters, 3D pane.
- **Length:** ~50s.

### T4 — MIP / MinIP (and Thick-Slab) *(verify labels first — §3b)*
- **Objective:** use projection modes — **MIP** for bright structures (vessels/bone), **MinIP** for air/low-density, Thick-Slab for a chosen thickness.
- **Click sequence:** in MPR, open the **projection menu** (next to MPR) → choose **MIP** → set slab thickness (e.g. 10 mm) → compare **MinIP** → return to Standard.
- **Required clips:** open projection menu; MIP on; thickness change; MinIP compare; reset.
- **Narration:** "Projection modes change what the slab shows. MIP keeps the brightest voxels — ideal for vessels and bone. MinIP keeps the darkest — useful for airways. Thick-slab lets you set the depth."
- **Callouts:** projection menu, MIP/MinIP/Thick-Slab options, thickness control.
- **Length:** ~50s. **Pre-req:** 10-min confirm session to capture exact labels.

### T5 — Review study information & metadata
- **Objective:** read DICOM overlays and the Study Information / series details.
- **Click sequence:** open a study → read the **corner overlays** (ID, date, slice, thickness, W/L) → open the **Study Information** panel / **Reception Data** tab → step through series thumbnails and counts.
- **Required clips:** overlays close-up; Study Information panel; series list.
- **Narration:** "Every image is labelled — patient and study data top-left, geometry and window settings in the corners. The Study Information panel lists each series, its description, and image count, so you always know what you're looking at."
- **Callouts:** each overlay corner; Study Information panel; series counts. **Anonymize overlays.**
- **Length:** ~45s.

### Stubbed (ready to script after a short confirm session)
- **T6 — Reporting workflow** *(confirm report editor)* — objective: dictate/type and finalize a report from the viewer; show the Report status returning to the home table.
- **T7 — ECHO MIND voice assistant** — objective: open a study / navigate by voice; show one or two confirmed voice actions.
- **T8 — Educational Courses** — objective: tour the in-app education module for staff training.

---

## 6. Recommended first video + exact Higgsfield prompts

### Recommendation: **A1 — the 15-second teaser.**
**Why first:** fastest to finish, lowest risk, highest shareability, and it **validates the whole pipeline** end-to-end (2 Higgsfield clips + 2 real captures + 1 logo sting). Once A1 works, A2 and A3 reuse the same intro/outro templates and capture style.

### What A1 needs
- **2 Higgsfield clips** (intro + outro), each ≤ 15s, **9:16**.
- **2 anonymized real captures** (open→MPR→3D; stack scroll + W/L + measure).
- **1 logo sting** (your AI-PACS logo over the outro plate).

### Exact Higgsfield prompts (copy-paste after the MCP is connected)

**CLIP 1 — Cinematic intro (image-to-video):**
First generate a still, then animate it.
- *Image prompt (model: Flux 2 or Seedream):*
  > "Cinematic wide shot of a modern radiology reading room at night, three large medical monitors glowing soft teal-blue, dark desk, subtle bokeh, clean minimal high-tech hospital interior, no text, no logos, no visible patient data, photorealistic, shallow depth of field, cool color grade." — **aspect 9:16, 4K.**
- *Animate to video (model: Veo 3.1 or Kling 3.0):*
  > "Slow cinematic push-in toward the glowing monitors, gentle dolly forward, faint ambient particles, calm professional mood, no people in frame, no on-screen text." — **duration 5s, aspect 9:16, camera: dolly-in (slow).**

**CLIP 2 — Abstract AI-imaging outro plate (image-to-video):**
- *Image prompt (model: Seedream or Flux 2):*
  > "Abstract medical imaging visual: translucent volumetric scan slices assembling into a glowing 3D anatomical form (vessels and organs), teal and deep-blue on near-black, elegant, high-tech, no text, no real patient likeness, no faces." — **aspect 9:16, 4K.**
- *Animate to video (model: Kling 3.0 or Veo 3.1):*
  > "Slices sweep and coalesce into the 3D form, soft volumetric light, slow rotation, ending on a calm centered composition with empty space at the lower third for a logo, no text." — **duration 6s, aspect 9:16, camera: slow orbit / crash-zoom-out.**

*(Optional CLIP 3 — Soul character:* if you want a recurring radiologist later, train a Soul ID from 3–5 neutral professional photos and reuse it in A2/A3. Not needed for A1.)*

### A1 real-capture shot list (record in AI-PACS with Camtasia, anonymized)
1. **Open→reconstruct (≈5s):** open a CT study → click a series → click **MPR** → let tri-planar + 3D appear → rotate the 3D once.
2. **Read (≈4s):** scroll the stack a few slices → one **window/level** drag → drop one **measurement**.
> Use a demo/anonymized patient; if filming a head 3D, deface or use a skull/vessel preset; blur the name/ID overlay and tab title in editing.

### A1 assembly plan (Camtasia)
1. Sequence: Clip 1 (0–3s) → Capture 1 (3–8s) → Capture 2 (8–12s) → Clip 2 + logo sting (12–15s).
2. Add burn-in captions ("Open. Reconstruct. Report." → "AI-PACS · Intelligent Medical Imaging").
3. License-safe music bed; cut on the beat; subtle whoosh on transitions.
4. Color-match Higgsfield clips to the app's teal so AI and UI feel like one piece.
5. Export **1080×1920 H.264** (9:16) for social; optional 1:1 crop.

---

## 7. Compliance & quality checklist (every public video)
- [ ] No real patient identifiers visible (name, ID, age, sex, accession) — overlays blurred.
- [ ] No identifiable 3D face unless consented/defaced (or bone/vessel preset used).
- [ ] Real UI never replaced by AI-generated UI.
- [ ] No invented features or fake numbers/specs; claims match §3a or a confirmed item.
- [ ] No implication that a real named clinician endorses the product.
- [ ] Music/stock is licensed; Higgsfield clips contain no embedded text/logos.
- [ ] Brand consistent: "AI-PACS · Intelligent Medical Imaging", teal palette, INO-Pooyan in credits.

## 8. Recommended toolchain & next steps
- **Capture/edit:** Camtasia 2024 (installed) for recording + assembly.
- **AI clips:** Higgsfield (after §1).
- **Anonymization:** demo patient + overlay blur (+ app anonymize if available).

**Next steps (after you approve):**
1. You connect Higgsfield (§1) and restart; I verify the tools.
2. I generate the **two A1 Higgsfield clips** (A/B two models on Clip 1).
3. We do a **10-minute confirm session** for MIP/MinIP labels + Reporting/ECHO MIND, and I guide the **A1 screen captures** (or walk you through them).
4. I hand you an A1 assembly sheet; we cut it; then roll the templates into A2 and A3.

---

## 9. A1 Production Log (generated 2026-06-09)

**Higgsfield:** Plus plan. Credits used this session: **27** (balance **983**). All assets 9:16.

### Research-informed direction (locked)
- **Realism brief:** radiology reading room is **dim (~25–50 lux)**, dual **medical-grade monitors** on arms, **white coat over business casual** (or navy scrubs), desk props = **coffee, radiology textbooks/journals, dictation microphone, gooseneck lamp from the left**, ergonomic chair. **Avoid:** stethoscope at desk, surgical cap/mask, bright daylight office, glowing sci-fi holograms, legible fake UI. In edit, **composite the real AI-PACS UI onto the monitors**.
- **Teaser mechanics:** hook in first 3s, one message, tight cuts, end on logo + CTA, <60s.
- **Category motif we own:** the **3D volume render** = the premium "cinematic rendering" beauty shot — and ours is *real*, not faked.

### Bookend clips (Kling 3.0, std, audio off, 5s each)
**INTRO — hero (realistic reading room)**
- Still (nano_banana_pro 2K, 2 cr) → `4175e81b-8ac6-481d-94a4-8e563eeaeb7d`
  - https://d8j0ntlcm91z4.cloudfront.net/user_3EraNYdvYTM64hjLeuRNq37c3Co/hf_20260608_213951_4175e81b-8ac6-481d-94a4-8e563eeaeb7d.png
- Clip (kling3_0, 7.5 cr) → `23692e56-9271-4cd4-9809-47f10984bf60`
  - https://d8j0ntlcm91z4.cloudfront.net/user_3EraNYdvYTM64hjLeuRNq37c3Co/hf_20260608_214848_23692e56-9271-4cd4-9809-47f10984bf60.mp4

**OUTRO — beauty (slices → 3D anatomy)**
- Still (nano_banana_pro 2K, 2 cr) → `02af1fb6-e4d3-4004-9588-1eaa2e387c8a`
  - https://d8j0ntlcm91z4.cloudfront.net/user_3EraNYdvYTM64hjLeuRNq37c3Co/hf_20260608_214812_02af1fb6-e4d3-4004-9588-1eaa2e387c8a.png
- Clip (kling3_0, 7.5 cr) → `764b2700-4f55-4d74-8ecd-74e05c671646`
  - https://d8j0ntlcm91z4.cloudfront.net/user_3EraNYdvYTM64hjLeuRNq37c3Co/hf_20260608_215040_764b2700-4f55-4d74-8ecd-74e05c671646.mp4

### Finalized prompts (reusable)
- **Hero image:** over-the-shoulder radiologist, open white coat, dim ~30 lux reading room, dual medical-grade monitors on arms (left = soft grayscale scans, right = soft report glow), coffee/textbooks/dictation mic/gooseneck lamp, shallow DoF, no text/logos/stethoscope, 9:16, title space upper third.
- **Hero motion:** slow push-in over the shoulder; small natural movement (mouse scroll, posture shift); faint coffee steam; subtle monitor flicker; no camera shake; cool teal grade.
- **Beauty image:** translucent CT/MRI slices assembling into a glowing 3D torso (vessels/organs), teal on near-black, volumetric light, lower-third logo space, no text/faces, 9:16.
- **Beauty motion:** slices coalesce + slow few-degree rotation; drifting particles; ends centered with lower-third logo space; cool teal grade. *(Higgsfield preset "IN THE DARK" available for a more dramatic variant.)*

### Still to capture (real AI-PACS, Camtasia, anonymized)
- Open a study → **MPR tri-planar snaps in → 3D volume rotates** (the credibility beat).
- **Stack scroll** + a **window/level** swipe + one **measurement**.

### Assembly (15s, 9:16)
INTRO clip (0–3s) → real UI open→MPR→3D (3–8s) → real UI scroll/W-L/measure (8–12s) → OUTRO clip + logo & CTA (12–15s). Burn-in captions: "Open. Reconstruct. Report." → "AI-PACS · Intelligent Medical Imaging". Color-match clips to the app's teal; license-safe music; export 1080×1920 H.264.
