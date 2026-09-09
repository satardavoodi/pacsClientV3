"""Active volBrain reference policy and explicit applicability, without fabricated scores.
"""
from dataclasses import asdict, dataclass
import math

from .contracts import BrainError


@dataclass(frozen=True)
class BrainDemographics:
    age_years: float | None = None
    sex: str = "unknown"

    def __post_init__(self):
        if self.age_years is not None and (
            type(self.age_years) not in (int, float)
            or not math.isfinite(self.age_years) or not 0 <= self.age_years <= 120
        ):
            raise BrainError("Age at examination must be between 0 and 120 years.")
        if self.sex not in ("female", "male", "unknown"):
            raise BrainError("Choose the recorded sex or leave it unspecified.")


@dataclass(frozen=True)
class Reference:
    id: str
    name: str
    source: str
    requirements: str


REFERENCES = (
    Reference("volbrain", "volBrain published 95% intervals",
              "https://doi.org/10.1002/hbm.23743",
              "Offline age/sex intervals, ages 1-90. Cross-method validation pending. "
              "Cortical atlas analogues are marked separately. No inferred Z/T scores."),
)


def reference_assessment(demographics=None, reference_id="volbrain"):
    """Only volBrain is active; explicit no-reference mode is for measurement QA."""
    demographics = demographics or BrainDemographics()
    if not isinstance(demographics, BrainDemographics):
        raise BrainError("Invalid demographic context.")
    if reference_id == "none":
        reference = Reference("none", "No normative reference", "", "Measurement-only review; reference comparison disabled.")
    elif reference_id == "volbrain":
        reference = REFERENCES[0]
    else:
        raise BrainError("This reference is retired or unsupported. Use the published volBrain reference.")
    reasons = [reference.requirements]
    if demographics.age_years is None:
        reasons.append("Age at examination is not supplied.")
    elif reference_id == "volbrain" and not 1 <= demographics.age_years <= 90:
        reasons.append("Age is outside the published reference range (1-90); no extrapolation.")
    if demographics.sex == "unknown":
        reasons.append("Recorded sex is unavailable; the publisher's general table is used.")
    return {"status": "unavailable", "reference_id": reference.id,
            "reference_name": reference.name, "source": reference.source,
            "reasons": reasons, "demographics": asdict(demographics),
            "percentile": None, "z_score": None, "t_score": None,
            "brain_age": None, "curves": [], "qualified": False}


def active_report_context(result):
    """Do not republish saved research references through the current renderer."""
    reference = result.get('normative') or {}
    if reference.get('reference_id') in ('volbrain', 'none') or not reference:
        return result
    clean = dict(result)
    clean['normative'] = reference_assessment()
    clean['normative']['reasons'].append(
        'The saved reference has been retired. Regenerate this report to apply the published volBrain intervals.')
    clean['normative_status'] = 'Retired reference removed; regenerate the report'
    return clean
