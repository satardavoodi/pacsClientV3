"""KPI collection machinery — see docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md."""
from .collector import KpiCollector, KpiVerdict, kpi
from .schema import KPI_REGISTRY, KpiSpec, get_spec

__all__ = ["KpiCollector", "KpiVerdict", "kpi", "KPI_REGISTRY", "KpiSpec", "get_spec"]
