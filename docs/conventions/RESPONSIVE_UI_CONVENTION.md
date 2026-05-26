# AI-PACS Responsive-UI Convention
**Version:** 1.0 (2026-05-26)
**Audience:** anyone writing or reviewing PySide6 UI code in this repository.
**Authority:** this convention is the project-wide rule. Deviations require a one-line justification in the commit message.

Background and the seven archetypes are in `docs/plans/RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md`. This file is the *one-page rule* that every new layout commit is checked against.

---

## The rule, in one sentence

**Never call `setFixedSize` / `setFixedWidth` / `setFixedHeight` on a non-leaf widget without also providing a fallback negotiation primitive (`QScrollArea`, `setWordWrap`, `QFontMetrics.elidedText`, `QSplitter`, `setMinimum*` + size policy, `QHeaderView::Stretch`, or `QStackedWidget`).**

A "leaf" widget is an icon, a 1-px separator, a badge dot, or a radio-button indicator — something that genuinely has no business growing or shrinking. Everything else is non-leaf and needs a negotiation path.

---

## Decision tree for any new layout code

```
You want to set a widget's size.
│
├── Is it a leaf (icon / 1-px line / badge dot)?
│   └── Use setFixed* — it's correct here.
│
├── Is it a horizontal strip of pinned widgets (toolbar, chips, button row)?
│   └── Wrap the strip in wrap_in_horizontal_scroll() — Archetype 1.
│
├── Is it a multi-line description QLabel?
│   └── Use make_wrapping_label() — Archetype 2.
│
├── Is it single-line text that could be longer than its container?
│   └── Use ElidedLabel — Archetype 3.
│
├── Is it a container that the user might want to resize against its siblings?
│   └── Use horizontal_splitter() — Archetype 4.
│
├── Is it a form field (QLineEdit, QComboBox, QPushButton in a form)?
│   └── Use set_form_field_size(min_height=N) — Archetype 5.
│
├── Is it a QTableView column?
│   └── Use set_table_column_policy() — Archetype 6.
│
└── Is it a centre pane that goes empty in some states?
    └── Wrap variants in QStackedWidget — Archetype 7 (per-screen design).
```

All helpers live in `PacsClient/utils/responsive_layout.py`.

---

## When you must commit to a number

Sometimes there's a real reason to pin a dimension — e.g. a dialog must be at least 600 × 400 to host its content meaningfully. In those cases:

- Use `setMinimumSize(600, 400)` — not `setFixedSize(600, 400)`. The minimum floor protects layout integrity; the absence of a maximum lets Qt grow the widget when the user enlarges the window.
- Document the reason as a code comment: `# minimum size required to host the embedded plot panel without overlap`.

---

## When you cannot avoid setFixed*

Some libraries we depend on (e.g. third-party widgets) call `setFixed*` internally — we cannot change that. For our own code, the rule is non-negotiable for non-leaf widgets.

If you genuinely need `setFixed*` on a non-leaf widget for a reason not covered above, write a one-line justification in the commit message:

```
fix(ui): pin server-status badge to 24 px (icon-only badge — visual semantics rely on consistent diameter)
```

The reviewer's job is then to confirm the justification, not to argue against the use.

---

## Reviewing a PR against this convention

1. Run `python tools/dev/audit_fixed_sizes.py --diff <BASE>..<HEAD>` to list new `setFixed*` calls added by the PR.
2. For each new call, ask: which archetype? Did the author use the corresponding helper, or write a one-line justification?
3. If neither, request changes.

The audit script also produces a project-wide remaining-migration count. If a PR increases the count without justification, request changes.

---

## What this convention does NOT regulate

- Visual design (colors, spacing in CSS, padding tokens) — those are separate concerns in the relevant stylesheet files.
- The `sf()` user-preference scale-factor work (`docs/plans/RESPONSIVE_UI_SCALING_PLAN.md`) — a separate layer on top of this one; both can be in flight without conflict.
- Existing `setFixed*` calls that haven't been migrated yet — those are tracked by the audit tool. The rule applies to *new* code from this version forward.

---

## See also

- `docs/plans/RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md` — full analysis of why this convention exists.
- `docs/plans/responsive_ui_baselines/comparison_AB.md` — the test data that motivated the convention.
- `PacsClient/utils/responsive_layout.py` — the helpers themselves.
- `tools/dev/audit_fixed_sizes.py` — the auditor.
