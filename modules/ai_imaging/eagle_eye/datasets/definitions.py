"""UI-independent, versioned form schemas. No defaults imply a normal finding."""
from __future__ import annotations

import copy
import math
import re


FIELD_TYPES = ("choice", "text", "number", "multiline")
LEVELS = ["L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1"]


def lumbar_template():
    binary = ("disc_bulge", "disc_herniation", "disc_protrusion", "disc_extrusion",
              "disc_sequestration", "disc_desiccation", "disc_height_loss", "annular_fissure")
    stenosis = ("central_canal_stenosis", "right_recess_stenosis", "left_recess_stenosis",
                "right_foraminal_stenosis", "left_foraminal_stenosis")
    fields = []
    for names, options in ((binary, ["absent", "present"]),
                           (stenosis, ["none", "mild", "moderate", "severe"]),
                           (("right_root_effect", "left_root_effect"),
                            ["none", "contact", "displacement", "compression"])):
        for name in names:
            fields.append({"id": name, "label": name.replace("_", " ").capitalize(),
                           "type": "choice", "scope": "region", "required": False,
                           "options": list(options)})
    fields.append({"id": "notes", "label": "Case notes", "type": "multiline",
                   "scope": "case", "required": False, "options": []})
    return {"name": "Lumbar Pathology", "modality": "MR", "anatomy": "Lumbar Spine",
            "regions": list(LEVELS), "fields": fields}


def blank_template():
    return {"name": "", "modality": "MR", "anatomy": "", "regions": [], "fields": []}


def _text(value, label, limit=120):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"Enter a valid {label} (up to {limit} characters).")
    return value.strip()


def validate_template(template):
    result = copy.deepcopy(template)
    for key in ("name", "modality", "anatomy"):
        result[key] = _text(result.get(key), key)
    result["modality"] = result["modality"].upper()
    if result["modality"] == "MRI":
        result["modality"] = "MR"
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,15}", result["modality"]):
        raise ValueError("Enter a valid DICOM modality code.")
    regions = result.get("regions", [])
    if not isinstance(regions, list) or len(regions) > 30:
        raise ValueError("Use at most 30 anatomical regions.")
    result["regions"] = [_text(x, "region", 60) for x in regions]
    if (len({x.casefold() for x in result["regions"]}) != len(regions)
            or any("/" in x or x.casefold() == "case" for x in result["regions"])):
        raise ValueError("Region names must be unique and cannot contain '/'.")
    fields = result.get("fields")
    if not isinstance(fields, list) or not 1 <= len(fields) <= 100:
        raise ValueError("Add between 1 and 100 fields.")
    ids = set()
    for field in fields:
        key = field.get("id", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,79}", key) or key in ids:
            raise ValueError("Field identifiers must be valid and unique.")
        ids.add(key)
        field["label"] = _text(field.get("label"), "field label")
        if field.get("type") not in FIELD_TYPES or field.get("scope") not in ("case", "region"):
            raise ValueError("Choose a supported field type and scope.")
        if field["scope"] == "region" and not regions:
            raise ValueError("Add anatomical regions for fields repeated per region.")
        if type(field.get("required")) is not bool:
            raise ValueError("A field's required setting must be true or false.")
        if field["type"] == "choice":
            options = field.get("options")
            if not isinstance(options, list) or not 2 <= len(options) <= 100:
                raise ValueError("Choice fields need 2 to 100 choices separated by semicolons.")
            field["options"] = [_text(x, "choice", 100) for x in options]
            if len({x.casefold() for x in field["options"]}) != len(options):
                raise ValueError("Choices must be unique.")
        else:
            field["options"] = []
    return {k: result[k] for k in ("name", "modality", "anatomy", "regions", "fields")}


def form_fields(template):
    for field in template["fields"]:
        for region in (["case"] if field["scope"] == "case" else template["regions"]):
            yield f"{region}/{field['id']}", field


def validate_values(template, values, complete=False):
    if not isinstance(values, dict):
        raise ValueError("Invalid form values.")
    allowed = dict(form_fields(template))
    if set(values) - set(allowed):
        raise ValueError("The form contains fields outside its saved template.")
    clean = {}
    for key, field in allowed.items():
        value = values.get(key)
        if value is None or value == "":
            if complete and field["required"]:
                raise ValueError(f"A required field is missing: {field['label']} ({key.split('/')[0]}).")
            continue
        if field["type"] == "number":
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"Enter a finite number for {field['label']}.")
        elif not isinstance(value, str) or len(value) > 16000:
            raise ValueError(f"Invalid text for {field['label']}.")
        elif field["type"] == "choice" and value not in field["options"]:
            raise ValueError(f"Choose an allowed value for {field['label']}.")
        clean[key] = value
    if complete and not clean:
        raise ValueError("Fill at least one field before marking the form complete.")
    return clean
