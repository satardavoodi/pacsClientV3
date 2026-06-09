# AI-PACS Recording Run Sheet (OBS → `D:\AI-PACS-Recordings\raw\`)

**Scene:** "AI-PACS Window Capture" (clean window crop, follows the app).
**Per clip:** record each item **separately** (Start → do it → Stop), **2–3 takes**, move the mouse **slowly**, pause ~1s between actions. OBS writes a timestamped `.mkv` to `raw\` each time.
**Anonymize:** use a **demo/teaching patient** if you have one; otherwise just record — I'll blur the name/ID overlays in edit. For the **3D**, prefer a **body CT (abdomen/chest)**, not a head/face.
**After you record:** tell me you're done (or note the times) — I'll pull each `.mkv` from `raw\`, extract frames to verify content + quality, flag the best take, remux to MP4, and assemble.

> Detailed step-by-step for the two teaser beats is in `A1_Capture_Sheet.md`. This sheet is the ordered shot list.

---

## PRIORITY A — A1 teaser real-UI beats (record these first)

**A1-B1 · Open → MPR → 3D** *(CT, ~8s)*
Load a CT series → click **MPR** → hold as tri-planar + **3D** appears → **slow-rotate the 3D** ~20–30° → (optional) nudge the green crosshair.

**A1-B2 · Scroll → Window/Level → Measure** *(CT or MR, ~8s)*
Scroll the **stack** 8–12 slices → pick **Window/Level**, drag to change contrast (overlay updates) → pick the **ruler**, click two points for a **measurement**.

---

## PRIORITY B — Tutorial clips (each standalone, <60s)

**T1 · Open a DICOM study** *(~45s)*
Server tab → confirm "razi / Server Ready" → tick a **modality** + set **date** → **Search** → **single-click** a patient (thumbnails load) → **double-click** to open → click a **series** to load it.

**T2 · Window / Level** *(~40s)*
Load a CT series → select **Window/Level** → drag (L-R = window, U-D = level) → show the **W/L overlay** changing → use a **preset** (lung/bone/soft-tissue) if present → reset.

**T3 · MPR** *(~50s)*
Open a CT series → click **MPR** → show **Axial/Sagittal/Coronal + 3D** → **drag the crosshair** (all planes follow) → **scroll** one plane → **rotate** the 3D.

**T4 · MIP / MinIP** *(~50s — confirm first)*
In MPR, open the **projection menu next to MPR** → if it offers **MIP / MinIP / Thick-Slab**, demo **MIP** (bright vessels/bone) → set a **slab thickness** → compare **MinIP** → reset. *(If the labels differ, just record what's there and tell me.)*

**T5 · Study information / metadata** *(~45s)*
Open a study → show the **corner overlays** (ID, date, slice, thickness, W/L) → open **Study Information** / **Reception Data** → step through the **series list + counts**.

---

## Optional extras (nice b-roll for promo)
- A slow pass over the **patient worklist** (modality filters, server, thumbnails) — *anonymize*.
- The **ECHO MIND** assistant panel opening.
- A clean **3D volume rotate** on a body CT (hero promo shot).

## Naming (so I can match takes)
OBS names files by timestamp. Either:
- after each clip, **jot the time + clip code** (e.g. `11:42 → A1-B1 take 2`), or
- rename the `.mkv` in `raw\` to the clip code after recording.
Either way I can identify them; the note just saves guesswork.
