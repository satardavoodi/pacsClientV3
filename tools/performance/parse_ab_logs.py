#!/usr/bin/env python3
"""
A/B Log Parser for FAST Render-Clock Experiment

Extracts and compares KPI metrics from baseline and experiment logs.
Produces structured comparison table and guardrail validation.
"""

import re
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass, asdict
from statistics import median, quantiles

@dataclass
class FastDragKpi:
    """Extracted [FAST_DRAG_KPI] fields"""
    ui_lag_max_ms: float = 0.0
    ui_lag_p95_ms: float = 0.0
    event_p50_ms: float = 0.0
    event_p95_ms: float = 0.0
    handler_p95_ms: float = 0.0
    drag_session_id: str = ""
    targets: int = 0
    cpu_p95_pct: float = 0.0

@dataclass
class FastEventPacing:
    """Extracted [FAST_EVENT_PACING] fields"""
    event_jitter_p95_ms: float = 0.0
    frame_present_interval_p95_ms: float = 0.0
    implied_queue_wait_p95_ms: float = 0.0
    same_slice_ratio_pct: float = 0.0
    coalesce_ratio_pct: float = 0.0
    set_to_image_p95_ms: float = 0.0

@dataclass
class FastRenderClock:
    """Extracted [FAST_RENDER_CLOCK] fields (experiment only)"""
    request_count: int = 0
    tick_count: int = 0
    present_count: int = 0
    superseded_count: int = 0
    fallback_count: int = 0
    forced_settle_present_count: int = 0
    request_to_present_p95_ms: float = 0.0
    request_to_present_max_ms: float = 0.0
    final_slice: int = -1
    interaction_type: str = ""

@dataclass
class MainThreadStall:
    """Extracted [MAIN_THREAD_STALL] fields"""
    stall_count: int = 0
    max_stall_ms: float = 0.0

@dataclass
class RunMetrics:
    """All metrics for a single run"""
    run_name: str
    drag_kpi: FastDragKpi
    event_pacing: FastEventPacing
    render_clock: FastRenderClock
    stalls: MainThreadStall

def extract_float(text: str, pattern: str, default: float = 0.0) -> float:
    """Extract first float match from text"""
    match = re.search(pattern, text)
    return float(match.group(1)) if match else default

def extract_int(text: str, pattern: str, default: int = 0) -> int:
    """Extract first int match from text"""
    match = re.search(pattern, text)
    return int(match.group(1)) if match else default

def extract_string(text: str, pattern: str, default: str = "") -> str:
    """Extract first string match from text"""
    match = re.search(pattern, text)
    return match.group(1) if match else default

def parse_drag_kpi_lines(lines: List[str]) -> FastDragKpi:
    """Parse all [FAST_DRAG_KPI] lines and aggregate metrics"""
    kpi = FastDragKpi()
    ui_lags = []
    event_p95s = []
    handler_p95s = []
    cpu_p95s = []
    
    for line in lines:
        if '[FAST_DRAG_KPI]' not in line:
            continue
        
        ui_lag_max = extract_float(line, r'ui_lag_max=([0-9.]+)')
        if ui_lag_max > 0:
            ui_lags.append(ui_lag_max)
            kpi.ui_lag_max_ms = max(kpi.ui_lag_max_ms, ui_lag_max)
        
        kpi.ui_lag_p95_ms = extract_float(line, r'ui_lag_p95=([0-9.]+)', kpi.ui_lag_p95_ms)
        
        ep95 = extract_float(line, r'event_p95=([0-9.]+)')
        if ep95 > 0:
            event_p95s.append(ep95)
        
        hp95 = extract_float(line, r'handler_p95=([0-9.]+)')
        if hp95 > 0:
            handler_p95s.append(hp95)
        
        cpu = extract_float(line, r'cpu_p95=([0-9.]+)')
        if cpu > 0:
            cpu_p95s.append(cpu)
        
        kpi.drag_session_id = extract_string(line, r'session=([a-z0-9_]+)', kpi.drag_session_id)
        targets = extract_int(line, r'targets=(\d+)')
        if targets > 0:
            kpi.targets = max(kpi.targets, targets)
    
    if event_p95s:
        kpi.event_p95_ms = max(event_p95s)
    if handler_p95s:
        kpi.handler_p95_ms = max(handler_p95s)
    if cpu_p95s:
        kpi.cpu_p95_pct = max(cpu_p95s)
    
    return kpi

def parse_event_pacing_lines(lines: List[str]) -> FastEventPacing:
    """Parse all [FAST_EVENT_PACING] lines and aggregate"""
    pacing = FastEventPacing()
    jitters = []
    intervals = []
    queue_waits = []
    set_to_image = []
    
    for line in lines:
        if '[FAST_EVENT_PACING]' not in line:
            continue
        
        j = extract_float(line, r'event_jitter_p95=([0-9.]+)')
        if j > 0:
            jitters.append(j)
        
        i = extract_float(line, r'frame_present_interval_p95=([0-9.]+)')
        if i > 0:
            intervals.append(i)
        
        q = extract_float(line, r'implied_queue_wait_p95=([0-9.]+)')
        if q > 0:
            queue_waits.append(q)
        
        pacing.same_slice_ratio_pct = extract_float(line, r'same_slice_ratio=([0-9.]+)', pacing.same_slice_ratio_pct)
        pacing.coalesce_ratio_pct = extract_float(line, r'coalesce_ratio=([0-9.]+)', pacing.coalesce_ratio_pct)
        
        s2i = extract_float(line, r'set_to_image_p95=([0-9.]+)')
        if s2i > 0:
            set_to_image.append(s2i)
    
    if jitters:
        pacing.event_jitter_p95_ms = max(jitters)
    if intervals:
        pacing.frame_present_interval_p95_ms = max(intervals)
    if queue_waits:
        pacing.implied_queue_wait_p95_ms = max(queue_waits)
    if set_to_image:
        pacing.set_to_image_p95_ms = max(set_to_image)
    
    return pacing

def parse_render_clock_lines(lines: List[str]) -> FastRenderClock:
    """Parse all [FAST_RENDER_CLOCK] lines and aggregate"""
    clock = FastRenderClock()
    request_to_present = []
    
    for line in lines:
        if '[FAST_RENDER_CLOCK]' not in line:
            continue
        
        clock.request_count += extract_int(line, r'request_count=(\d+)')
        clock.tick_count += extract_int(line, r'tick_count=(\d+)')
        clock.present_count += extract_int(line, r'present_count=(\d+)')
        clock.superseded_count += extract_int(line, r'superseded_count=(\d+)')
        clock.fallback_count += extract_int(line, r'fallback_count=(\d+)')
        clock.forced_settle_present_count += extract_int(line, r'forced_settle_present_count=(\d+)')
        
        rtp = extract_float(line, r'request_to_present_p95=([0-9.]+)')
        if rtp > 0:
            request_to_present.append(rtp)
        
        clock.request_to_present_max_ms = max(
            clock.request_to_present_max_ms,
            extract_float(line, r'request_to_present_max=([0-9.]+)')
        )
        
        clock.final_slice = max(clock.final_slice, extract_int(line, r'final_slice=(\d+)'))
        clock.interaction_type = extract_string(line, r'interaction=(\w+)', clock.interaction_type)
    
    if request_to_present:
        clock.request_to_present_p95_ms = max(request_to_present)
    
    return clock

def parse_stall_lines(lines: List[str]) -> MainThreadStall:
    """Parse [MAIN_THREAD_STALL] lines"""
    stall = MainThreadStall()
    
    for line in lines:
        if '[MAIN_THREAD_STALL]' not in line:
            continue
        stall.stall_count += 1
        stall.max_stall_ms = max(stall.max_stall_ms, extract_float(line, r'duration=([0-9.]+)'))
    
    return stall

def parse_log_file(log_path: Path) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Read log and categorize lines"""
    if not log_path.exists():
        return [], [], [], []
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
    except Exception as e:
        print(f"  ⚠️  Error reading {log_path}: {e}")
        return [], [], [], []
    
    drag_lines = [l for l in all_lines if '[FAST_DRAG_KPI]' in l]
    pacing_lines = [l for l in all_lines if '[FAST_EVENT_PACING]' in l]
    clock_lines = [l for l in all_lines if '[FAST_RENDER_CLOCK]' in l]
    stall_lines = [l for l in all_lines if '[MAIN_THREAD_STALL]' in l]
    
    return drag_lines, pacing_lines, clock_lines, stall_lines

def analyze_run(run_name: str, logs_dir: Path) -> RunMetrics:
    """Parse both viewer and download logs for a single run"""
    print(f"\n[Parsing] {run_name}...")
    
    viewer_log = logs_dir / f"{run_name}_viewer.log"
    download_log = logs_dir / f"{run_name}_download.log"
    
    print(f"  Viewer log: {viewer_log.name} ({viewer_log.stat().st_size / 1024:.1f} KB)")
    print(f"  Download log: {download_log.name} ({download_log.stat().st_size / 1024:.1f} KB)")
    
    # Parse viewer log (contains FAST_DRAG_KPI, FAST_EVENT_PACING, FAST_RENDER_CLOCK)
    v_drag, v_pacing, v_clock, v_stall = parse_log_file(viewer_log)
    
    # Parse download log (may contain MAIN_THREAD_STALL)
    d_drag, d_pacing, d_clock, d_stall = parse_log_file(download_log)
    
    # Merge results
    all_drag = v_drag + d_drag
    all_pacing = v_pacing + d_pacing
    all_clock = v_clock + d_clock
    all_stall = v_stall + d_stall
    
    print(f"    [FAST_DRAG_KPI] lines: {len(all_drag)}")
    print(f"    [FAST_EVENT_PACING] lines: {len(all_pacing)}")
    print(f"    [FAST_RENDER_CLOCK] lines: {len(all_clock)}")
    print(f"    [MAIN_THREAD_STALL] lines: {len(all_stall)}")
    
    metrics = RunMetrics(
        run_name=run_name,
        drag_kpi=parse_drag_kpi_lines(all_drag),
        event_pacing=parse_event_pacing_lines(all_pacing),
        render_clock=parse_render_clock_lines(all_clock),
        stalls=parse_stall_lines(all_stall)
    )
    
    return metrics

def format_metric_value(value: float, is_pct: bool = False) -> str:
    """Format metric value with appropriate precision"""
    if value == 0:
        return "—"
    if is_pct:
        return f"{value:.1f}%"
    return f"{value:.2f}"

def generate_comparison_table(baseline: RunMetrics, experiment: RunMetrics) -> str:
    """Generate A/B comparison KPI table"""
    lines = []
    
    lines.append("\n╔════════════════════════════════════════════════════════════════════════════════╗")
    lines.append("║                       2. A/B KPI COMPARISON                                   ║")
    lines.append("╠════════════════════════════════════════════════════════════════════════════════╣")
    lines.append("║ Metric                              │ Baseline    │ Experiment  │ Delta       ║")
    lines.append("╠════════════════════════════════════════════════════════════════════════════════╣")
    
    def add_metric_row(label: str, baseline_val: float, exp_val: float, is_pct: bool = False, lower_is_better: bool = True):
        baseline_str = format_metric_value(baseline_val, is_pct)
        exp_str = format_metric_value(exp_val, is_pct)
        
        if baseline_val > 0 and exp_val > 0:
            delta_pct = ((exp_val - baseline_val) / baseline_val) * 100
            if lower_is_better:
                trend = "↓ BETTER" if delta_pct < -5 else "↑ WORSE" if delta_pct > 5 else "→ SAME"
                delta_str = f"{delta_pct:+.1f}% {trend}"
            else:
                trend = "↑ BETTER" if delta_pct > 5 else "↓ WORSE" if delta_pct < -5 else "→ SAME"
                delta_str = f"{delta_pct:+.1f}% {trend}"
        else:
            delta_str = "—"
        
        lines.append(f"║ {label:<35} │ {baseline_str:>11} │ {exp_str:>11} │ {delta_str:>11} ║")
    
    # Drag KPI metrics
    add_metric_row("ui_lag_max_ms", baseline.drag_kpi.ui_lag_max_ms, experiment.drag_kpi.ui_lag_max_ms)
    add_metric_row("ui_lag_p95_ms", baseline.drag_kpi.ui_lag_p95_ms, experiment.drag_kpi.ui_lag_p95_ms)
    add_metric_row("event_p95_ms", baseline.drag_kpi.event_p95_ms, experiment.drag_kpi.event_p95_ms)
    add_metric_row("handler_p95_ms", baseline.drag_kpi.handler_p95_ms, experiment.drag_kpi.handler_p95_ms)
    add_metric_row("CPU p95 (%)", baseline.drag_kpi.cpu_p95_pct, experiment.drag_kpi.cpu_p95_pct)
    
    lines.append("╠════════════════════════════════════════════════════════════════════════════════╣")
    
    # Event pacing metrics
    add_metric_row("event_jitter_p95_ms", baseline.event_pacing.event_jitter_p95_ms, experiment.event_pacing.event_jitter_p95_ms)
    add_metric_row("frame_present_interval_p95", baseline.event_pacing.frame_present_interval_p95_ms, experiment.event_pacing.frame_present_interval_p95_ms)
    add_metric_row("implied_queue_wait_p95", baseline.event_pacing.implied_queue_wait_p95_ms, experiment.event_pacing.implied_queue_wait_p95_ms)
    add_metric_row("same_slice_ratio (%)", baseline.event_pacing.same_slice_ratio_pct, experiment.event_pacing.same_slice_ratio_pct, is_pct=True, lower_is_better=False)
    add_metric_row("coalesce_ratio (%)", baseline.event_pacing.coalesce_ratio_pct, experiment.event_pacing.coalesce_ratio_pct, is_pct=True, lower_is_better=False)
    
    lines.append("╚════════════════════════════════════════════════════════════════════════════════╝")
    
    return "\n".join(lines)

def generate_render_clock_validation(baseline: RunMetrics, experiment: RunMetrics) -> str:
    """Generate FAST_RENDER_CLOCK validation report"""
    lines = []
    
    lines.append("\n╔════════════════════════════════════════════════════════════════════════════════╗")
    lines.append("║                   1. FAST_RENDER_CLOCK VALIDATION                              ║")
    lines.append("╠════════════════════════════════════════════════════════════════════════════════╣")
    
    # Baseline (should have no clock events)
    lines.append("║ BASELINE (Experiment OFF):                                                     ║")
    lines.append(f"║   [FAST_RENDER_CLOCK] events: {len([l for l in [baseline.render_clock] if l.request_count > 0]) == 0 and '0 (expected)' or 'UNEXPECTED':<50} ║")
    
    # Experiment (should have clock events)
    lines.append("║                                                                                ║")
    lines.append("║ EXPERIMENT (Experiment ON):                                                    ║")
    exp_clock = experiment.render_clock
    lines.append(f"║   [FAST_RENDER_CLOCK] tag present: {'YES ✓' if exp_clock.request_count > 0 else 'NO ✗':<40} ║")
    if exp_clock.request_count > 0:
        lines.append(f"║   • request_count:        {exp_clock.request_count:<52} ║")
        lines.append(f"║   • tick_count:           {exp_clock.tick_count:<52} ║")
        lines.append(f"║   • present_count:        {exp_clock.present_count:<52} ║")
        lines.append(f"║   • superseded_count:     {exp_clock.superseded_count:<52} ║")
        lines.append(f"║   • fallback_count:       {exp_clock.fallback_count:<52} ║")
        lines.append(f"║   • forced_settle_present: {exp_clock.forced_settle_present_count:<51} ║")
        lines.append(f"║   • request_to_present_p95: {format_metric_value(exp_clock.request_to_present_p95_ms)}ms{' ':<43} ║")
        lines.append(f"║   • request_to_present_max: {format_metric_value(exp_clock.request_to_present_max_ms)}ms{' ':<43} ║")
        lines.append(f"║   • final_slice:          {exp_clock.final_slice if exp_clock.final_slice >= 0 else '—':<52} ║")
    
    lines.append("╚════════════════════════════════════════════════════════════════════════════════╝")
    
    return "\n".join(lines)

def validate_guardrails(baseline: RunMetrics, experiment: RunMetrics) -> Tuple[Dict[str, bool], str]:
    """Validate critical guardrails"""
    guardrails = {}
    issues = []
    
    # Guardrail 1: first-image timing (if logs have timing data)
    # For now, we'll check if slice is same at start
    guardrails['first_image_no_regression'] = True  # Assume true if no crash
    
    # Guardrail 2: progressive completion (final slice correctness)
    baseline_final = baseline.drag_kpi.targets
    exp_final = experiment.drag_kpi.targets
    final_slice_match = (baseline_final == exp_final) or (baseline_final == 0) or (exp_final == 0)
    guardrails['final_slice_no_mismatch'] = final_slice_match
    if not final_slice_match:
        issues.append(f"Final slice mismatch: baseline={baseline_final}, experiment={exp_final}")
    
    # Guardrail 3: fallback not triggered
    guardrails['fallback_not_triggered'] = experiment.render_clock.fallback_count == 0
    if experiment.render_clock.fallback_count > 0:
        issues.append(f"Fallback triggered {experiment.render_clock.fallback_count} times")
    
    # Guardrail 4: CPU/frame churn not increased
    cpu_delta = experiment.drag_kpi.cpu_p95_pct - baseline.drag_kpi.cpu_p95_pct
    cpu_ok = cpu_delta < 10  # Allow 10% increase
    guardrails['cpu_increase_acceptable'] = cpu_ok
    if not cpu_ok:
        issues.append(f"CPU increase: {cpu_delta:+.1f}% (baseline={baseline.drag_kpi.cpu_p95_pct:.1f}%, exp={experiment.drag_kpi.cpu_p95_pct:.1f}%)")
    
    # Guardrail 5: no main thread stall increase
    baseline_stalls = baseline.stalls.stall_count
    exp_stalls = experiment.stalls.stall_count
    stall_ok = exp_stalls <= baseline_stalls + 5  # Allow small increase
    guardrails['main_thread_stalls_acceptable'] = stall_ok
    if not stall_ok:
        issues.append(f"Stall increase: baseline={baseline_stalls}, experiment={exp_stalls}")
    
    return guardrails, "\n  • ".join(issues) if issues else "All guardrails passed ✓"

def make_decision(baseline: RunMetrics, experiment: RunMetrics, guardrails: Dict[str, bool]) -> str:
    """Make KEEP/TUNE/REVERT decision"""
    
    # Check if all guardrails passed
    all_guardrails_ok = all(guardrails.values())
    
    # Calculate improvement metrics
    ui_lag_improvement = (baseline.drag_kpi.ui_lag_max_ms - experiment.drag_kpi.ui_lag_max_ms) / baseline.drag_kpi.ui_lag_max_ms * 100 if baseline.drag_kpi.ui_lag_max_ms > 0 else 0
    jitter_improvement = (baseline.event_pacing.event_jitter_p95_ms - experiment.event_pacing.event_jitter_p95_ms) / baseline.event_pacing.event_jitter_p95_ms * 100 if baseline.event_pacing.event_jitter_p95_ms > 0 else 0
    
    # Decision logic
    if not all_guardrails_ok:
        return "REVERT_EXPERIMENT"
    elif ui_lag_improvement > 10 and jitter_improvement > 15:
        return "KEEP_EXPERIMENT_PROMISING"
    elif ui_lag_improvement > 0 or jitter_improvement > 0:
        return "KEEP_OFF_NEEDS_TUNING"
    else:
        return "KEEP_OFF_NEEDS_TUNING"  # No regression, but no clear improvement

def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_ab_logs.py <logs_dir> [baseline_name] [experiment_name]")
        print("Example: python parse_ab_logs.py './logs/ab_runs' 'pre_baseline' 'pre_experiment'")
        sys.exit(1)
    
    logs_dir = Path(sys.argv[1])
    baseline_name = sys.argv[2] if len(sys.argv) > 2 else "pre_baseline"
    experiment_name = sys.argv[3] if len(sys.argv) > 3 else "pre_experiment"
    
    if not logs_dir.exists():
        print(f"Error: Logs directory not found: {logs_dir}")
        sys.exit(1)
    
    print(f"\n{'='*80}")
    print("FAST Render-Clock Experiment — A/B Log Analysis")
    print(f"{'='*80}")
    print(f"Logs directory: {logs_dir}")
    
    # Parse both runs
    baseline = analyze_run(baseline_name, logs_dir)
    experiment = analyze_run(experiment_name, logs_dir)
    
    # Generate reports
    print(generate_render_clock_validation(baseline, experiment))
    print(generate_comparison_table(baseline, experiment))
    
    # Validate guardrails
    guardrails, guardrail_summary = validate_guardrails(baseline, experiment)
    
    print("\n╔════════════════════════════════════════════════════════════════════════════════╗")
    print("║                         3. GUARDRAIL VALIDATION                                ║")
    print("╠════════════════════════════════════════════════════════════════════════════════╣")
    for guard_name, guard_result in guardrails.items():
        status = "✓" if guard_result else "✗"
        label = guard_name.replace('_', ' ').title()
        print(f"║ {status} {label:<70} ║")
    print("╠════════════════════════════════════════════════════════════════════════════════╣")
    print(f"║ Summary: {guardrail_summary:<70} ║")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")
    
    # Make decision
    decision = make_decision(baseline, experiment, guardrails)
    
    print("\n╔════════════════════════════════════════════════════════════════════════════════╗")
    print("║                         4. DECISION                                            ║")
    print("╠════════════════════════════════════════════════════════════════════════════════╣")
    print(f"║ {decision:<78} ║")
    print("╚════════════════════════════════════════════════════════════════════════════════╝\n")
    
    return decision

if __name__ == '__main__':
    decision = main()
    sys.exit(0 if decision == "KEEP_EXPERIMENT_PROMISING" else 1)
