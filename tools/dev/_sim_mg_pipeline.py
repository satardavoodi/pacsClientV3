"""Simulate _compute_boxes_scores_for_metadata after GEOM_CONVERT."""
import sys
import pandas as pd
from pathlib import Path, PureWindowsPath

print("=== Simulating _compute_boxes_scores_for_metadata after GEOM_CONVERT ===")

cls_path = r"user_data/patients/attachments/2.16.840.1.113669.632.20.20260519.104019747.2.28/classification_0.45_9.csv"
df_cls = pd.read_csv(cls_path)
print(f"df_cls loaded, rows={len(df_cls)}, cols={list(df_cls.columns)}")
print(f"dicom_full_path sample: {df_cls['dicom_full_path'].iloc[0]}")

boxes = [[2254.7259006500244, 1513.8595886230469, 2577.9821362495422, 1887.3790588378906]]
scores = [0.45573559403419495]
new_boxes = []
removed_boxes = []

series_uid = "2.16.840.1.113669.632.20.20260519.104306983.9865.43"

boxes = list(boxes or [])
scores = list(scores or [])
new_boxes = list(new_boxes or [])
removed_boxes = list(removed_boxes or [])

print(f"After list(): boxes={len(boxes)}, scores={len(scores)}, new={len(new_boxes)}, removed={len(removed_boxes)}")

if new_boxes:
    boxes += new_boxes
    scores += [None] * len(new_boxes)

if len(scores) < len(boxes):
    print(f"  SCORE_LENGTH_MISMATCH: scores={len(scores)} boxes={len(boxes)}")

print("Starting for loop...")
boxes_scores = []
for i in range(len(boxes)):
    print(f"  i={i}: box={boxes[i]}")
    if boxes[i] in removed_boxes:
        print(f"  i={i}: SKIPPED (in removed)")
        continue
    score_value = scores[i] if i < len(scores) else None
    score = float(f"{score_value:.2f}") if score_value is not None else "Custom"
    print(f"  i={i}: score={score}")

    # Simulate _match_rows_for_series
    matches = []
    for dicom_path_str in df_cls["dicom_full_path"]:
        s = str(dicom_path_str).strip().strip('"').strip("'")
        p = PureWindowsPath(s) if ("\\" in s and "/" not in s) else Path(s)
        parent_dir = p.parent
        dicom_series_uid = parent_dir.name
        print(f"    path_str={dicom_path_str}")
        print(f"    dicom_series_uid={dicom_series_uid}")
        if dicom_series_uid == series_uid:
            matches.append(dicom_path_str)

    print(f"  i={i}: matches={len(matches)}")
    series_ai_data = df_cls[df_cls["dicom_full_path"].isin(matches)] if matches else None

    classification_label = None
    if series_ai_data is not None and len(series_ai_data) > 0:
        lst_ai_data = series_ai_data.to_dict()
        xmins = lst_ai_data.get("xmin", {})
        ymins = lst_ai_data.get("ymin", {})
        xmaxs = lst_ai_data.get("xmax", {})
        ymaxs = lst_ai_data.get("ymax", {})
        labels = lst_ai_data.get("labels_pred", {})
        print(f"  xmins={xmins}, ymins={ymins}")

        for k in xmins.keys():
            box_from_csv = [xmins[k], ymins[k], xmaxs[k], ymaxs[k]]
            round_n = 1
            sel_r = [round(x, round_n) for x in boxes[i]]
            csv_r = [round(x, round_n) for x in box_from_csv]
            equal = sel_r == csv_r
            print(f"  check_equal: selected={sel_r} csv={csv_r} equal={equal}")
            if equal:
                try:
                    classification_label = eval(labels[k])
                    print(f"  classification_label={classification_label}")
                except Exception as e:
                    classification_label = labels.get(k)
                    print(f"  eval failed: {e}, fallback={classification_label}")

    if classification_label is not None:
        boxes_scores.append({"box": boxes[i], "score": score, "classification": classification_label})
    else:
        boxes_scores.append({"box": boxes[i], "score": score})
    print(f"  i={i}: appended, boxes_scores now {len(boxes_scores)}")

print(f"Loop complete. boxes_scores={boxes_scores}")
print("==> SIMULATION COMPLETE: all steps passed through GEOM_CONVERT to boxes_scores build")
print(f"==> len(boxes_scores)={len(boxes_scores)}")
