# Module Document: Zeta MPR / 3-D Reconstruction
**module_id:** `mpr_zeta`
**Document version:** 1.0
**Sent in Phase 2 when the LLM needs to control multi-planar or 3-D rendering.**

---

## 1. What This Module Does

Zeta MPR provides interactive multi-planar reconstruction (MPR) and 3-D
surface/volume rendering for CT and MRI series.  Key capabilities:

* Standard MPR: axial, coronal, sagittal linked views
* Curved MPR (panoramic)
* Surface reconstruction (bone, vessel, airway, …)
* Volume rendering with preset library
* Measurement tools: distance, angle, HU value
* Segmentation overlay
* Rotation controls and oblique cut planes

---

## 2. Available Actions

### `open_mpr`

Opens the MPR viewer for the active series.

| Entity | Type | Notes |
|---|---|---|
| `layout` | string | `"standard"` \| `"curved"` \| `"3d"` (default `"standard"`) |
| `preset` | string | rendering preset name, e.g. `"bone"`, `"soft_tissue"`, `"lung"` |
| `plane` | string | initial plane: `"axial"` \| `"coronal"` \| `"sagittal"` |

**needs_confirmation:** `false`

### `apply_preset`

Applies a window/rendering preset without re-opening the viewer.

| Entity | Type | Notes |
|---|---|---|
| `preset` | string | Required — preset name |

**needs_confirmation:** `false`

### `measure`

Activates measurement tool in the current MPR view.

| Entity | Type | Notes |
|---|---|---|
| `tool` | string | `"distance"` \| `"angle"` \| `"hu"` |

**needs_confirmation:** `false`

---

## 3. Output Contract

```json
{
  "action": "open_mpr",
  "entities": {
    "layout": "standard",
    "preset": "bone",
    "plane": "axial"
  },
  "confidence": 0.9,
  "needs_confirmation": false,
  "reason": "User asked for bone-windowed axial MPR view"
}
```

---

## 4. Preset Synonyms

| User says | Preset value |
|---|---|
| bone, اسکلت, استخوان | `bone` |
| soft tissue, بافت نرم | `soft_tissue` |
| lung, ریه | `lung` |
| brain, مغز | `brain` |
| vessel, عروق | `vessel` |

---

## 5. Example Interactions

**Input:** `"نمای MPR استخوان"`
```json
{"action":"open_mpr","entities":{"layout":"standard","preset":"bone"},"confidence":0.92,"needs_confirmation":false,"reason":"User asked for bone-preset MPR view"}
```

**Input:** `"show 3D reconstruction"`
```json
{"action":"open_mpr","entities":{"layout":"3d"},"confidence":0.9,"needs_confirmation":false,"reason":"User requested 3D reconstruction view"}
```
