"""Native DK cortical parcel grouping and sums; no whole-lobe GM+WM inference.

Reference: https://freesurfer.net/fswiki/CorticalParcellation
Cingulate cortex and insula remain separate from the four conventional lobes.
"""

CORTICAL_GROUPS = (
    ("Frontal lobe", ("superiorfrontal", "rostralmiddlefrontal", "caudalmiddlefrontal",
                      "parsopercularis", "parstriangularis", "parsorbitalis",
                      "lateralorbitofrontal", "medialorbitofrontal", "precentral",
                      "paracentral", "frontalpole")),
    ("Parietal lobe", ("superiorparietal", "inferiorparietal", "supramarginal", "postcentral", "precuneus")),
    ("Temporal lobe", ("superiortemporal", "middletemporal", "inferiortemporal", "bankssts",
                       "fusiform", "transversetemporal", "entorhinal", "temporalpole", "parahippocampal")),
    ("Occipital lobe", ("lateraloccipital", "lingual", "cuneus", "pericalcarine")),
    ("Cingulate cortex", ("rostralanteriorcingulate", "caudalanteriorcingulate", "posteriorcingulate", "isthmuscingulate")),
    ("Insular cortex", ("insula",)),
)

DEEP_GROUPS = (
    ("Basal ganglia", ("caudate", "putamen", "pallidum", "accumbens area")),
    ("Diencephalon", ("thalamus", "ventral DC")),
    ("Subcortical limbic structures", ("hippocampus", "amygdala")),
)

TISSUE_GROUPS = (
    ("Cerebellum", ("cerebellum cortex", "cerebellum white matter")),
    ("Cerebral tissue compartments", ("cerebral cortex", "cerebral white matter")),
    ("Paired ventricles", ("lateral ventricle", "inferior lateral ventricle")),
)


def group_pairs(pairs, definitions):
    by_name = {row["structure"]: row for row in pairs}
    return [(title, [by_name[name] for name in names if name in by_name]) for title, names in definitions]


def cortical_summaries(rows):
    """Sum complete cortical groups only, without parent-volume double counting."""
    from math import isfinite
    values = {}
    for row in rows:
        value = row.get("volume_cm3")
        if isinstance(value, (int, float)) and isfinite(value) and value >= 0:
            values[row["structure"]] = value
    icv = values.get("total intracranial")
    summaries = []
    for title, names in CORTICAL_GROUPS:
        item = {"structure": title}
        for side, prefix in (("left", "lh"), ("right", "rh")):
            keys = [f"ctx-{prefix}-{name}" for name in names]
            present = [values[key] for key in keys if key in values]
            item[f"{side}_coverage"] = f"{len(present)}/{len(keys)}"
            item[f"{side}_cm3"] = sum(present) if len(present) == len(keys) else None
        left, right = item["left_cm3"], item["right_cm3"]
        total = left + right if left is not None and right is not None else None
        item["total_cm3"] = total
        item["icv_percent"] = 100 * total / icv if total is not None and icv else None
        summaries.append(item)
    return summaries
