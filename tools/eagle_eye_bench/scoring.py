"""Parse an Eagle Eye FINAL REPORT and score it against a reference read.

The report is prose, so parsing is deliberately conservative: every extraction
keeps the clause it came from, negations are honoured, and anything the parser
cannot resolve is surfaced as ``unparsed`` rather than silently scored as a
miss. The parsed structure is meant to be eyeballed, not trusted blindly.

Pure python. No Qt, no network, no patient data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCORER_VERSION = "1.1.0"
LEVELS: Tuple[str, ...] = ("T12-L1", "L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1")

MORPHOLOGY_ORDER: Tuple[str, ...] = (
    "none", "bulge", "protrusion", "extrusion", "sequestration",
)
SEVERITY_ORDER: Tuple[str, ...] = ("none", "mild", "moderate", "severe")
ROOT_EFFECT_ORDER: Tuple[str, ...] = ("none", "contact", "deviation", "compression")

_LEVEL_LINE = re.compile(
    r"^\s{1,8}(T12-L1|L[1-5]-(?:L[1-5]|S1))\s*[:–-]\s*(.+?)\s*$", re.IGNORECASE
)
_SECTION = re.compile(r"^\s*([A-Z][A-Z /-]{3,})\s*$")

# A negation cue anywhere in the clause before a keyword suppresses it.
_NEG_CUES = (
    "no ", "not ", "without", "absent", "negative for", "free of",
    "excludes", "excluded", "rather than", "no definite", "none",
    "does not", "is not", "unsupported", "rejected",
)


def _clause_before(text: str, start: int, window: int = 90) -> str:
    """The clause preceding ``start`` - back to the last sentence boundary."""
    head = text[max(0, start - window):start].lower()
    for boundary in (". ", "; ", ".\n", ";\n"):
        cut = head.rfind(boundary)
        if cut != -1:
            head = head[cut + len(boundary):]
    return head


def _negated(text: str, start: int) -> bool:
    clause = _clause_before(text, start)
    return any(cue in clause for cue in _NEG_CUES)


def _sentence_at(text: str, start: int) -> str:
    """The sentence containing ``start``, used to scope side/zone lookups."""
    left = max(text.rfind(". ", 0, start), text.rfind("; ", 0, start))
    left = 0 if left == -1 else left + 2
    right = len(text)
    for boundary in (". ", "; "):
        cut = text.find(boundary, start)
        if cut != -1:
            right = min(right, cut)
    return text[left:right]


def _hits(text: str, pattern: str) -> List[int]:
    """Start offsets of every non-negated match of ``pattern``."""
    return [
        match.start()
        for match in re.finditer(pattern, text, re.IGNORECASE)
        if not _negated(text, match.start())
    ]


def _side_in(fragment: str) -> str:
    low = fragment.lower()
    left = bool(re.search(r"\bleft\b|\bleft-sided\b", low))
    right = bool(re.search(r"\bright\b|\bright-sided\b", low))
    if re.search(r"\bbilateral\b|\bboth\b", low) or (left and right):
        return "bilateral"
    if right:
        return "right"
    if left:
        return "left"
    if re.search(r"\bcentral\b(?!\s+canal)|\bmidline\b", low):
        return "central"
    return ""


_ZONE_SPECIFICITY = (
    "extraforaminal", "foraminal", "paracentral", "subarticular", "central",
)

# Reports routinely write "paracentral/subarticular" for one lesion; the two
# describe overlapping territory and must not score as a flat miss.
_ZONE_NEIGHBOURS = {
    frozenset(("paracentral", "subarticular")),
    frozenset(("foraminal", "extraforaminal")),
}


def _zone_in(fragment: str) -> str:
    """The most specific zone named in the fragment.

    "Central to left paracentral" names two; the narrower one is the finding.
    ``\\bcentral\\b`` cannot match inside "paracentral", so the two are
    genuinely separate matches rather than a prefix collision.
    """
    low = fragment.lower()
    found = {
        zone for zone in _ZONE_SPECIFICITY
        if re.search(rf"\b{zone}\b" + (r"(?!\s+canal)" if zone == "central" else ""), low)
    }
    for zone in _ZONE_SPECIFICITY:
        if zone in found:
            return zone
    return ""


def _severity_in(fragment: str) -> str:
    low = fragment.lower()
    grade = re.search(r"grade\s*([0-3])", low)
    if grade:
        return SEVERITY_ORDER[int(grade.group(1))]
    for word in ("severe", "marked", "high-grade"):
        if word in low:
            return "severe"
    for word in ("moderate",):
        if word in low:
            return "moderate"
    for word in ("mild", "minimal", "slight", "shallow", "small"):
        if word in low:
            return "mild"
    return ""


def _grade_in(fragment: str) -> Optional[int]:
    grade = re.search(r"grade\s*([0-3])", fragment.lower())
    return int(grade.group(1)) if grade else None


_MORPHOLOGY_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("sequestration", r"sequestrat"),
    ("extrusion", r"extrus|extruded"),
    ("protrusion", r"protrus|protruded|herniat"),
    ("bulge", r"bulg"),
)

_CONSEQUENCE_PATTERNS: Dict[str, str] = {
    "central_canal": r"central canal|canal stenosis|canal narrowing|thecal sac",
    "lateral_recess": r"lateral recess|subarticular",
    "neural_foramen": r"foramin",
    "facet": r"facet",
    "ligamentum_flavum": r"ligamentum",
}

_ROOT_MENTION = re.compile(
    r"\b(?:(?:traversing|exiting|right|left|bilateral)\s+)*"
    r"(?:[LS][1-5]\s+)?(?:nerve[- ]?)?roots?\b|\b(?:traversing|exiting)[- ]root\b",
    re.IGNORECASE,
)
_ROOT_EFFECT_TOKEN = re.compile(
    r"\b(?P<compression>compress(?:ion|ed|es|ive)?)\b|"
    r"\b(?P<deviation>deviat(?:ion|ed|es|e)|displac(?:ement|ed|es|e))\b|"
    r"\b(?P<contact>contact(?:s|ed)?|abut(?:s|ted|ment)?)\b",
    re.IGNORECASE,
)
_ROOT_SCOPE_BOUNDARY = re.compile(
    r"\b(?:but|however|yet)\b|(?=\bwithout\b)|,\s*(?=with\b)", re.IGNORECASE
)
_ROOT_NEGATION = re.compile(
    r"\b(?:no|not|without|absent|negative for|free of|excluded|unsupported|rejected)\b",
    re.IGNORECASE,
)


def _parse_root_effect(text: str) -> Dict[str, Any]:
    """Bind effects to nearby root mentions; negation belongs to the effect.

    A negated deviation between an affirmed contact and its root name must
    not suppress that root. This is a bounded prose parser, not a general
    clinical NLP system; the benchmark still requires adjudicated review.
    """
    observations = []
    for sentence in re.split(r"(?<=[.;])\s+", text):
        roots = list(_ROOT_MENTION.finditer(sentence))
        if not roots:
            continue
        boundaries = [0, *[m.end() for m in _ROOT_SCOPE_BOUNDARY.finditer(sentence)], len(sentence)]
        for effect in _ROOT_EFFECT_TOKEN.finditer(sentence):
            if re.match(r"\s+fracture\b", sentence[effect.end():], re.IGNORECASE):
                continue
            left = max(b for b in boundaries if b <= effect.start())
            right = min(b for b in boundaries if b > effect.start())
            prefix = sentence[left:effect.start()]
            tail = sentence[effect.end():right]
            next_effect = _ROOT_EFFECT_TOKEN.search(tail)
            if next_effect:
                tail = tail[:next_effect.start()]
            denied = bool(_ROOT_NEGATION.search(prefix)) or bool(re.search(
                r"\b(?:is|are|was|were)\s+(?:absent|excluded|not\s+(?:seen|present|identified))\b",
                tail, re.IGNORECASE,
            ))
            root = min(roots, key=lambda m: min(
                abs(m.start() - effect.end()), abs(effect.start() - m.end())
            ))
            label = re.search(r"\b([LS][1-5])\b", root.group(), re.IGNORECASE)
            side = _side_in(root.group()) or _side_in(sentence[left:right])
            observations.append({
                "effect": effect.lastgroup, "present": not denied,
                "side": side, "root": label.group(1).upper() if label else "",
                "clause": sentence.strip(),
            })
    positive = [item for item in observations if item["present"]]
    if not positive:
        return {}
    chosen = max(positive, key=lambda item: ROOT_EFFECT_ORDER.index(item["effect"]))
    assertions = {}
    for name in ROOT_EFFECT_ORDER[1:]:
        relevant = [item["present"] for item in observations if
                    item["effect"] == name and item["root"] == chosen["root"]
                    and item["side"] == chosen["side"]]
        assertions[name] = (
            "conflicting" if True in relevant and False in relevant else
            "present" if True in relevant else "absent" if relevant else "unmentioned"
        )
    return {key: chosen[key] for key in ("effect", "side", "root", "clause")} | {
        "effect_assertions": assertions,
    }


@dataclass
class LevelFinding:
    """What one level's prose actually asserts."""

    level: str
    text: str = ""
    morphology: str = "none"
    morphology_denied: Tuple[str, ...] = ()
    zone: str = ""
    side: str = ""
    annular_fissure: bool = False
    desiccation: bool = False
    height_loss: bool = False
    modic: str = ""
    consequences: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    root: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "morphology": self.morphology,
            "morphology_denied": list(self.morphology_denied),
            "zone": self.zone,
            "side": self.side,
            "annular_fissure": self.annular_fissure,
            "desiccation": self.desiccation,
            "height_loss": self.height_loss,
            "modic": self.modic,
            "consequences": self.consequences,
            "root": self.root,
            "text": self.text,
        }


@dataclass
class ParsedReport:
    level_map: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    level_map_monotonic: bool = True
    findings: Dict[str, LevelFinding] = field(default_factory=dict)
    not_assessable: str = ""
    parse_notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "level_map": {k: list(v) for k, v in self.level_map.items()},
            "level_map_monotonic": self.level_map_monotonic,
            "not_assessable": self.not_assessable,
            "parse_notes": list(self.parse_notes),
            "findings": {k: v.as_dict() for k, v in self.findings.items()},
        }


def parse_level_prose(level: str, text: str) -> LevelFinding:
    """Turn one level's report sentence(s) into a structured finding."""
    finding = LevelFinding(level=level, text=text.strip())
    low = text

    best_rank = 0
    denied: List[str] = []
    morph_offset: Optional[int] = None
    for name, pattern in _MORPHOLOGY_PATTERNS:
        offsets = _hits(low, pattern)
        if offsets:
            rank = MORPHOLOGY_ORDER.index(name)
            if rank > best_rank:
                best_rank = rank
                morph_offset = offsets[0]
        elif re.search(pattern, low, re.IGNORECASE):
            denied.append(name)
    finding.morphology = MORPHOLOGY_ORDER[best_rank]
    finding.morphology_denied = tuple(denied)

    if morph_offset is not None:
        # Scope side and zone to the disc phrase itself, not the whole
        # sentence: "central disc protrusion, producing ... Bartynski grade 1
        # bilateral lateral recess stenosis" would otherwise make the DISC
        # bilateral because a consequence further down the sentence is.
        sentence = _sentence_at(low, morph_offset)
        anchor = sentence.lower().find(low[morph_offset:morph_offset + 6].lower())
        phrase = sentence[:anchor + 36] if anchor != -1 else sentence
        finding.side = _side_in(phrase)
        finding.zone = _zone_in(phrase)

    finding.annular_fissure = bool(
        _hits(low, r"annular (fissure|tear)|high[- ]intensity zone|\bHIZ\b")
    )
    finding.desiccation = bool(_hits(low, r"desicca"))
    finding.height_loss = bool(
        _hits(low, r"height loss|height narrowing|disc[- ]space narrowing|height reduction")
    )

    modic = re.search(r"modic[^.;]{0,20}?(type\s*)?(i{1,3}|1|2|3)\b", low, re.IGNORECASE)
    if modic and not _negated(low, modic.start()):
        token = modic.group(2).lower()
        finding.modic = {"1": "i", "2": "ii", "3": "iii"}.get(token, token)

    for name, pattern in _CONSEQUENCE_PATTERNS.items():
        offsets = _hits(low, pattern)
        if not offsets:
            continue
        sentence = _sentence_at(low, offsets[0])
        finding.consequences[name] = {
            "side": _side_in(sentence),
            "severity": _severity_in(sentence),
            "grade": _grade_in(sentence),
            "clause": sentence.strip(),
        }

    finding.root = _parse_root_effect(low)
    return finding


def parse_report(text: str) -> ParsedReport:
    """Split a FINAL REPORT into its LEVEL MAP and per-level findings."""
    report = ParsedReport()
    section = ""
    pending: Dict[str, List[str]] = {}
    order: List[str] = []
    last_level = ""

    for raw in (text or "").splitlines():
        header = _SECTION.match(raw)
        if header:
            section = header.group(1).strip().upper()
            last_level = ""
            continue
        if not raw.strip():
            last_level = ""
            continue

        match = _LEVEL_LINE.match(raw)
        if match:
            level = match.group(1).upper().replace("–", "-")
            body = match.group(2).strip()
            if section.startswith("LEVEL MAP"):
                frames = re.search(r"(\d+)\s*-\s*(\d+)", body)
                if frames:
                    report.level_map[level] = (int(frames.group(1)), int(frames.group(2)))
                continue
            pending.setdefault(level, []).append(body)
            if level not in order:
                order.append(level)
            last_level = level
            continue

        if section.startswith("NOT ASSESSABLE"):
            report.not_assessable += raw.strip() + " "
        elif last_level and raw.startswith((" ", "\t")):
            pending[last_level].append(raw.strip())

    for level, parts in pending.items():
        report.findings[level] = parse_level_prose(level, " ".join(parts))

    mapped = [lvl for lvl in LEVELS if lvl in report.level_map]
    starts = [report.level_map[lvl][0] for lvl in mapped]
    report.level_map_monotonic = starts == sorted(starts)
    if not report.level_map_monotonic:
        report.parse_notes.append(
            "LEVEL MAP is not monotonic superior-to-inferior - every finding in "
            "this run is attached to a level that cannot be trusted."
        )
    if report.not_assessable.strip():
        report.parse_notes.append("Report carries a NOT ASSESSABLE section.")
    if not report.findings:
        report.parse_notes.append("No per-level findings were parsed.")
    return report


# ---------------------------------------------------------------- scoring --

HIT = "hit"
PARTIAL = "partial"
UNDER = "under"
OVER = "over"
WRONG_SIDE = "wrong_side"
MISS = "miss"
FALSE_POSITIVE = "false_positive"

_POSITIVE = (HIT,)


@dataclass
class ClaimResult:
    claim_id: str
    kind: str
    level: str
    expected: Any
    observed: Any
    outcome: str
    critical: bool = False
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "kind": self.kind,
            "level": self.level,
            "expected": self.expected,
            "observed": self.observed,
            "outcome": self.outcome,
            "critical": self.critical,
            "note": self.note,
        }


@dataclass
class RunScore:
    case_id: str
    run_id: str = ""
    claims: List[ClaimResult] = field(default_factory=list)
    false_positives: List[Dict[str, Any]] = field(default_factory=list)
    parse_notes: List[str] = field(default_factory=list)

    @property
    def critical_misses(self) -> List[ClaimResult]:
        return [c for c in self.claims if c.critical and c.outcome not in _POSITIVE]

    def counts(self) -> Dict[str, int]:
        tally: Dict[str, int] = {}
        for claim in self.claims:
            tally[claim.outcome] = tally.get(claim.outcome, 0) + 1
        tally["false_positive"] = tally.get("false_positive", 0) + len(self.false_positives)
        return tally

    def as_dict(self) -> Dict[str, Any]:
        return {
            "scorer_version": SCORER_VERSION,
            "case_id": self.case_id,
            "run_id": self.run_id,
            "counts": self.counts(),
            "critical_misses": [c.claim_id for c in self.critical_misses],
            "claims": [c.as_dict() for c in self.claims],
            "false_positives": list(self.false_positives),
            "parse_notes": list(self.parse_notes),
        }


def _morphology_outcome(expected: str, observed: str) -> str:
    want = MORPHOLOGY_ORDER.index(expected)
    got = MORPHOLOGY_ORDER.index(observed or "none")
    if want == got:
        return HIT
    if got < want:
        return UNDER if want - got > 1 else PARTIAL
    return OVER if got - want > 1 else PARTIAL


def _severity_outcome(expected: str, observed: str) -> str:
    if not expected:
        return HIT
    if not observed:
        return MISS
    want = SEVERITY_ORDER.index(expected)
    got = SEVERITY_ORDER.index(observed)
    if want == got:
        return HIT
    return PARTIAL if abs(want - got) == 1 else (UNDER if got < want else OVER)


def _zone_outcome(expected: str, observed: str) -> str:
    if not expected:
        return HIT
    if not observed:
        return MISS
    if observed == expected:
        return HIT
    if frozenset((expected, observed)) in _ZONE_NEIGHBOURS:
        return PARTIAL
    return MISS


def _side_outcome(expected: str, observed: str) -> str:
    if not expected:
        return HIT
    if not observed:
        return MISS
    if observed == expected:
        return HIT
    if observed == "bilateral":
        return PARTIAL
    return WRONG_SIDE


def score_report(reference: Dict[str, Any], report: ParsedReport,
                 run_id: str = "") -> RunScore:
    """Score one parsed report against a reference read."""
    score = RunScore(case_id=str(reference.get("case_id", "")), run_id=run_id)
    score.parse_notes = list(report.parse_notes)
    findings = report.findings

    for level, expect in (reference.get("levels") or {}).items():
        found = findings.get(level)
        if expect.get("normal"):
            if found is not None and (
                found.morphology != "none" or found.consequences or found.root
            ):
                score.false_positives.append(
                    {"level": level, "reason": "reference calls this level normal",
                     "text": found.text}
                )
            continue

        disc = expect.get("disc") or {}
        if disc:
            critical = bool(disc.get("critical"))
            observed = found.morphology if found else "none"
            score.claims.append(ClaimResult(
                claim_id=f"{level}/disc/morphology", kind="morphology", level=level,
                expected=disc.get("morphology"), observed=observed,
                outcome=_morphology_outcome(disc.get("morphology", "none"), observed),
                critical=critical,
                note="" if found else "level absent from report",
            ))
            if disc.get("side"):
                score.claims.append(ClaimResult(
                    claim_id=f"{level}/disc/side", kind="side", level=level,
                    expected=disc["side"], observed=(found.side if found else ""),
                    outcome=_side_outcome(disc["side"], found.side if found else ""),
                    critical=critical,
                ))
            if disc.get("zone"):
                observed_zone = found.zone if found else ""
                score.claims.append(ClaimResult(
                    claim_id=f"{level}/disc/zone", kind="zone", level=level,
                    expected=disc["zone"], observed=observed_zone,
                    outcome=_zone_outcome(disc["zone"], observed_zone),
                    critical=False,
                ))

        if expect.get("annular_fissure"):
            observed = bool(found and found.annular_fissure)
            score.claims.append(ClaimResult(
                claim_id=f"{level}/annular_fissure", kind="annular_fissure",
                level=level, expected=True, observed=observed,
                outcome=HIT if observed else MISS,
            ))

        for structure in ("lateral_recess", "central_canal", "neural_foramen"):
            want = expect.get(structure)
            if not want:
                continue
            seen = (found.consequences.get(structure) if found else None) or {}
            critical = bool(want.get("critical"))
            present = bool(seen)
            outcome = HIT if present else MISS
            if present:
                side = _side_outcome(want.get("side", ""), seen.get("side", ""))
                sev = _severity_outcome(want.get("severity", ""), seen.get("severity", ""))
                if side != HIT:
                    outcome = side
                elif sev != HIT:
                    outcome = sev
            score.claims.append(ClaimResult(
                claim_id=f"{level}/{structure}", kind=structure, level=level,
                expected=want, observed=seen or None, outcome=outcome,
                critical=critical,
            ))

        want_root = expect.get("root")
        if want_root:
            seen = (found.root if found else {}) or {}
            critical = bool(want_root.get("critical"))
            outcome = MISS
            if seen:
                want_rank = ROOT_EFFECT_ORDER.index(want_root.get("effect", "none"))
                got_rank = ROOT_EFFECT_ORDER.index(seen.get("effect", "none") or "none")
                if got_rank == want_rank:
                    outcome = HIT
                elif got_rank == 0:
                    outcome = MISS
                elif got_rank < want_rank:
                    outcome = UNDER if want_rank - got_rank > 1 else PARTIAL
                else:
                    outcome = OVER
                if outcome == HIT:
                    outcome = _side_outcome(want_root.get("side", ""), seen.get("side", ""))
                if outcome == HIT and want_root.get("root"):
                    if seen.get("root") and seen["root"] != want_root["root"]:
                        outcome = PARTIAL
            score.claims.append(ClaimResult(
                claim_id=f"{level}/root", kind="root", level=level,
                expected=want_root, observed=seen or None, outcome=outcome,
                critical=critical,
            ))

    for entry in (reference.get("endplates") or []):
        accept = [lvl for lvl in entry.get("accept_levels", []) if lvl in findings]
        observed = ""
        where = ""
        for lvl in accept:
            if findings[lvl].modic:
                observed = findings[lvl].modic
                where = lvl
                break
        score.claims.append(ClaimResult(
            claim_id=f"endplate/{entry.get('vertebra')}/modic", kind="modic",
            level=where or ",".join(entry.get("accept_levels", [])),
            expected=entry.get("modic"), observed=observed or None,
            outcome=HIT if observed == entry.get("modic") else (
                MISS if not observed else PARTIAL),
        ))

    for structure, normal_levels in (reference.get("normal_structures") or {}).items():
        soft = structure in (reference.get("soft_normal_structures") or [])
        for level in normal_levels:
            found = findings.get(level)
            if not found:
                continue
            seen = found.consequences.get(structure)
            if structure == "facet_joints":
                seen = found.consequences.get("facet")
            if seen:
                score.false_positives.append({
                    "level": level, "structure": structure, "soft": soft,
                    "clause": seen.get("clause", ""),
                })
    return score


def aggregate(scores: Sequence[RunScore]) -> Dict[str, Any]:
    """Collapse N runs into per-claim hit rates - the only honest summary.

    A single run of this pipeline carries roughly a coin flip of noise on the
    disc-morphology decision, so a rate over N runs is the unit of comparison,
    never one run's outcome.
    """
    total = len(scores)
    if not total:
        return {"runs": 0, "claims": {}, "critical_miss_rate": None}

    per_claim: Dict[str, Dict[str, Any]] = {}
    for score in scores:
        for claim in score.claims:
            row = per_claim.setdefault(claim.claim_id, {
                "kind": claim.kind, "level": claim.level,
                "expected": claim.expected, "critical": claim.critical,
                "outcomes": {}, "observed": [],
            })
            row["outcomes"][claim.outcome] = row["outcomes"].get(claim.outcome, 0) + 1
            row["observed"].append(claim.observed)
            row["critical"] = row["critical"] or claim.critical

    for row in per_claim.values():
        row["hit_rate"] = round(row["outcomes"].get(HIT, 0) / total, 3)

    critical_runs = sum(1 for s in scores if s.critical_misses)
    fp_total = sum(len(s.false_positives) for s in scores)
    unstable = sorted(
        (cid for cid, row in per_claim.items() if 0.0 < row["hit_rate"] < 1.0),
        key=lambda cid: per_claim[cid]["hit_rate"],
    )
    return {
        "runs": total,
        "critical_miss_rate": round(critical_runs / total, 3),
        "false_positives_per_run": round(fp_total / total, 2),
        "unstable_claims": unstable,
        "claims": per_claim,
    }


def summarize(aggregated: Dict[str, Any]) -> str:
    """A short human-readable table for the terminal."""
    if not aggregated.get("runs"):
        return "no runs scored"
    lines = [
        f"runs: {aggregated['runs']}   "
        f"critical-miss rate: {aggregated['critical_miss_rate']}   "
        f"false positives/run: {aggregated['false_positives_per_run']}",
        "",
        f"{'claim':<34}{'expected':<26}{'hit rate':>9}  outcomes",
    ]
    for claim_id, row in sorted(aggregated["claims"].items()):
        expected = row["expected"]
        if isinstance(expected, dict):
            expected = ",".join(f"{k}={v}" for k, v in expected.items() if k != "critical")
        flag = "!" if row["critical"] else " "
        outcomes = " ".join(f"{k}:{v}" for k, v in sorted(row["outcomes"].items()))
        lines.append(
            f"{flag}{claim_id:<33}{str(expected)[:25]:<26}{row['hit_rate']:>9}  {outcomes}"
        )
    if aggregated.get("unstable_claims"):
        lines += ["", "unstable across runs (0 < hit rate < 1):"]
        lines += [f"  {cid}" for cid in aggregated["unstable_claims"]]
    return "\n".join(lines)
