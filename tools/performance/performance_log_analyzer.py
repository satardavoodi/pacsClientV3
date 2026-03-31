"""
Performance Log Analyzer for Mode B Testing

Parses instrumented performance logs and generates statistical reports.

Usage:
    python performance_log_analyzer.py <log_file> [--output <report_file>]
"""

import re
import sys
import statistics
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict


class PerformanceEvent:
    def __init__(self, line: str):
        self.raw_line = line
        self.timestamp = None
        self.component = None
        self.corr_id = None
        self.event_type = None
        self.duration_ms = None
        self.extra_data = {}
        
        self._parse()
    
    def _parse(self):
        # Extract timestamp
        ts_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})', self.raw_line)
        if ts_match:
            self.timestamp = ts_match.group(1)
        
        # Extract component
        comp_match = re.search(r'\[PERF\]\[(\w+)\]', self.raw_line)
        if comp_match:
            self.component = comp_match.group(1)
        
        # Extract correlation ID
        corr_match = re.search(r'\[PERF\]\[\w+\]\[([^\]]+)\]', self.raw_line)
        if corr_match:
            self.corr_id = corr_match.group(1)
        
        # Extract event type (ENTRY/EXIT)
        if 'ENTRY' in self.raw_line:
            self.event_type = 'ENTRY'
        elif 'EXIT' in self.raw_line:
            self.event_type = 'EXIT'
        elif 'BLOCKED' in self.raw_line:
            self.event_type = 'BLOCKED'
        elif 'START' in self.raw_line:
            self.event_type = 'START'
        elif 'END' in self.raw_line:
            self.event_type = 'END'
        
        # Extract duration
        dur_match = re.search(r'duration_ms=([0-9.]+)', self.raw_line)
        if dur_match:
            self.duration_ms = float(dur_match.group(1))
        
        # Extract duration in seconds if present
        dur_s_match = re.search(r'duration_s=([0-9.]+)', self.raw_line)
        if dur_s_match:
            self.duration_ms = float(dur_s_match.group(1)) * 1000
        
        # Extract other key-value pairs
        kv_pattern = r'(\w+)=([^\s\|]+)'
        for match in re.finditer(kv_pattern, self.raw_line):
            key = match.group(1)
            value = match.group(2)
            if key not in ['duration_ms', 'duration_s']:
                self.extra_data[key] = value


class PerformanceAnalyzer:
    def __init__(self, log_file: str):
        self.log_file = Path(log_file)
        self.events: List[PerformanceEvent] = []
        self.by_component: Dict[str, List[PerformanceEvent]] = defaultdict(list)
    
    def parse(self):
        """Parse log file and extract performance events."""
        print(f"Parsing log file: {self.log_file}")
        
        with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if '[PERF]' in line:
                    event = PerformanceEvent(line)
                    if event.component:
                        self.events.append(event)
                        self.by_component[event.component].append(event)
        
        print(f"Found {len(self.events)} performance events")
        print(f"Components: {list(self.by_component.keys())}")
    
    def analyze_viewer(self) -> Dict[str, Any]:
        """Analyze viewer performance metrics."""
        viewer_events = [e for e in self.by_component.get('VIEWER', [])
                        if e.duration_ms is not None]
        
        if not viewer_events:
            return {'error': 'No viewer events with duration found'}
        
        durations = [e.duration_ms for e in viewer_events]
        
        # Find set_slice operations
        set_slice_events = [e for e in viewer_events 
                           if 'set_slice' in e.raw_line.lower()]
        set_slice_durations = [e.duration_ms for e in set_slice_events]
        
        # Find switch_series operations
        switch_events = [e for e in viewer_events 
                        if 'switch_series' in e.raw_line.lower()]
        switch_durations = [e.duration_ms for e in switch_events]
        
        result = {
            'total_operations': len(viewer_events),
            'set_slice_count': len(set_slice_events),
            'switch_series_count': len(switch_events),
        }
        
        if set_slice_durations:
            result['set_slice'] = {
                'mean': statistics.mean(set_slice_durations),
                'median': statistics.median(set_slice_durations),
                'min': min(set_slice_durations),
                'max': max(set_slice_durations),
                'p95': sorted(set_slice_durations)[int(len(set_slice_durations)*0.95)] 
                       if len(set_slice_durations) > 20 else None,
                'p99': sorted(set_slice_durations)[int(len(set_slice_durations)*0.99)]
                       if len(set_slice_durations) > 100 else None,
                'slow_ops_50ms': len([d for d in set_slice_durations if d > 50]),
                'slow_ops_100ms': len([d for d in set_slice_durations if d > 100]),
            }
        
        if switch_durations:
            result['switch_series'] = {
                'mean': statistics.mean(switch_durations),
                'median': statistics.median(switch_durations),
                'min': min(switch_durations),
                'max': max(switch_durations),
            }
        
        return result
    
    def analyze_download(self) -> Dict[str, Any]:
        """Analyze download performance metrics."""
        download_events = self.by_component.get('DOWNLOAD', [])
        
        if not download_events:
            return {'error': 'No download events found'}
        
        # Find lifecycle events
        start_events = [e for e in download_events if e.event_type == 'START']
        end_events = [e for e in download_events if e.event_type == 'END']
        
        # Find IPC queue stats
        ipc_events = [e for e in download_events if 'IPC Queue' in e.raw_line]
        ipc_rates = []
        for event in ipc_events:
            if 'msg_rate' in event.extra_data:
                try:
                    rate = float(event.extra_data['msg_rate'].replace('/s', ''))
                    ipc_rates.append(rate)
                except:
                    pass
        
        # Find DB write timing
        db_events = [e for e in download_events 
                    if e.duration_ms and 'DB write' in e.raw_line]
        db_durations = [e.duration_ms for e in db_events]
        
        result = {
            'total_events': len(download_events),
            'download_sessions': len(start_events),
            'ipc_measurements': len(ipc_events),
            'db_writes': len(db_events),
        }
        
        if ipc_rates:
            result['ipc_message_rate'] = {
                'mean': statistics.mean(ipc_rates),
                'max': max(ipc_rates),
            }
        
        if db_durations:
            result['db_write_timing'] = {
                'mean': statistics.mean(db_durations),
                'median': statistics.median(db_durations),
                'max': max(db_durations),
            }
        
        return result
    
    def analyze_zetaboost(self) -> Dict[str, Any]:
        """Analyze ZetaBoost performance metrics."""
        zeta_events = self.by_component.get('ZETABOOST', [])
        
        if not zeta_events:
            return {'error': 'No ZetaBoost events found'}
        
        # Find lane blocking events
        blocked_events = [e for e in zeta_events if e.event_type == 'BLOCKED']
        
        # Find job execution events
        job_events = [e for e in zeta_events 
                     if e.duration_ms and 'Job' in e.raw_line]
        
        # Group by lane
        by_lane = defaultdict(list)
        for event in job_events:
            lane = event.extra_data.get('lane', 'unknown')
            by_lane[lane].append(event.duration_ms)
        
        # Find cache hit/miss
        cache_hits = len([e for e in zeta_events if 'Cache HIT' in e.raw_line])
        cache_misses = len([e for e in zeta_events if 'Cache MISS' in e.raw_line])
        
        result = {
            'total_events': len(zeta_events),
            'lane_blocked_count': len(blocked_events),
            'jobs_executed': len(job_events),
            'cache_hits': cache_hits,
            'cache_misses': cache_misses,
            'cache_hit_rate': cache_hits / (cache_hits + cache_misses) * 100
                             if (cache_hits + cache_misses) > 0 else None,
        }
        
        # Add per-lane statistics
        for lane, durations in by_lane.items():
            result[f'lane_{lane}'] = {
                'jobs': len(durations),
                'mean_duration_s': statistics.mean(durations) / 1000,
                'max_duration_s': max(durations) / 1000,
            }
        
        return result
    
    def find_overlap_periods(self) -> List[Dict[str, Any]]:
        """Find time periods where viewer and download are both active."""
        # This is a simplified version - in real analysis you'd parse timestamps properly
        viewer_times = [e.timestamp for e in self.by_component.get('VIEWER', [])
                       if e.timestamp and e.duration_ms and e.duration_ms > 30]
        download_times = [e.timestamp for e in self.by_component.get('DOWNLOAD', [])
                         if e.timestamp]
        
        overlaps = []
        for v_time in viewer_times:
            for d_time in download_times:
                if v_time == d_time:  # Same minute
                    overlaps.append({
                        'timestamp': v_time,
                        'viewer_active': True,
                        'download_active': True,
                    })
        
        return overlaps
    
    def generate_report(self) -> str:
        """Generate comprehensive text report."""
        report = []
        report.append("=" * 80)
        report.append("PERFORMANCE ANALYSIS REPORT")
        report.append("=" * 80)
        report.append(f"Log file: {self.log_file.name}")
        report.append(f"Total events: {len(self.events)}")
        report.append("")
        
        # Viewer analysis
        report.append("-" * 80)
        report.append("VIEWER PERFORMANCE")
        report.append("-" * 80)
        viewer_stats = self.analyze_viewer()
        if 'error' in viewer_stats:
            report.append(f"  {viewer_stats['error']}")
        else:
            report.append(f"  Total operations: {viewer_stats['total_operations']}")
            report.append(f"  set_slice calls: {viewer_stats['set_slice_count']}")
            
            if 'set_slice' in viewer_stats:
                ss = viewer_stats['set_slice']
                report.append(f"\n  set_slice timing:")
                report.append(f"    Mean:   {ss['mean']:.2f} ms")
                report.append(f"    Median: {ss['median']:.2f} ms")
                report.append(f"    Min:    {ss['min']:.2f} ms")
                report.append(f"    Max:    {ss['max']:.2f} ms")
                if ss['p95']:
                    report.append(f"    P95:    {ss['p95']:.2f} ms")
                if ss['p99']:
                    report.append(f"    P99:    {ss['p99']:.2f} ms")
                report.append(f"\n  Slow operations:")
                report.append(f"    > 50ms:  {ss['slow_ops_50ms']}")
                report.append(f"    > 100ms: {ss['slow_ops_100ms']}")
            
            if 'switch_series' in viewer_stats:
                sw = viewer_stats['switch_series']
                report.append(f"\n  switch_series timing:")
                report.append(f"    Mean: {sw['mean']:.2f} ms")
                report.append(f"    Max:  {sw['max']:.2f} ms")
        
        report.append("")
        
        # Download analysis
        report.append("-" * 80)
        report.append("DOWNLOAD PERFORMANCE")
        report.append("-" * 80)
        download_stats = self.analyze_download()
        if 'error' in download_stats:
            report.append(f"  {download_stats['error']}")
        else:
            report.append(f"  Download sessions: {download_stats['download_sessions']}")
            report.append(f"  Database writes: {download_stats['db_writes']}")
            
            if 'ipc_message_rate' in download_stats:
                ipc = download_stats['ipc_message_rate']
                report.append(f"\n  IPC message rate:")
                report.append(f"    Mean: {ipc['mean']:.1f} msg/sec")
                report.append(f"    Max:  {ipc['max']:.1f} msg/sec")
            
            if 'db_write_timing' in download_stats:
                db = download_stats['db_write_timing']
                report.append(f"\n  Database write timing:")
                report.append(f"    Mean:   {db['mean']:.2f} ms")
                report.append(f"    Median: {db['median']:.2f} ms")
                report.append(f"    Max:    {db['max']:.2f} ms")
        
        report.append("")
        
        # ZetaBoost analysis
        report.append("-" * 80)
        report.append("ZETABOOST PERFORMANCE")
        report.append("-" * 80)
        zeta_stats = self.analyze_zetaboost()
        if 'error' in zeta_stats:
            report.append(f"  {zeta_stats['error']}")
        else:
            report.append(f"  Jobs executed: {zeta_stats['jobs_executed']}")
            report.append(f"  Lane blocks: {zeta_stats['lane_blocked_count']}")
            report.append(f"  Cache hits: {zeta_stats['cache_hits']}")
            report.append(f"  Cache misses: {zeta_stats['cache_misses']}")
            if zeta_stats['cache_hit_rate'] is not None:
                report.append(f"  Cache hit rate: {zeta_stats['cache_hit_rate']:.1f}%")
            
            # Per-lane stats
            for key, value in zeta_stats.items():
                if key.startswith('lane_'):
                    lane_name = key.replace('lane_', '')
                    report.append(f"\n  Lane: {lane_name}")
                    report.append(f"    Jobs: {value['jobs']}")
                    report.append(f"    Mean duration: {value['mean_duration_s']:.2f} s")
                    report.append(f"    Max duration:  {value['max_duration_s']:.2f} s")
        
        report.append("")
        report.append("=" * 80)
        
        # Critical findings
        report.append("\nCRITICAL FINDINGS:")
        report.append("-" * 80)
        
        # Check for ZetaBoost running during download
        if zeta_stats.get('lane_blocked_count', 0) == 0 and zeta_stats.get('jobs_executed', 0) > 0:
            report.append("[!] ZetaBoost lanes NOT blocked - jobs executed without download gate")
            report.append("    This indicates the global download counter is not wired.")
        elif zeta_stats.get('lane_blocked_count', 0) > 0:
            report.append("[✓] ZetaBoost lane blocking detected - download gate is working")
        
        # Check for slow viewer operations
        if 'set_slice' in viewer_stats:
            ss = viewer_stats['set_slice']
            if ss['mean'] > 30:
                report.append(f"[!] Slow viewer performance - mean set_slice {ss['mean']:.2f}ms (target: <20ms)")
            else:
                report.append(f"[✓] Good viewer performance - mean set_slice {ss['mean']:.2f}ms")
        
        # Check IPC overhead
        if 'ipc_message_rate' in download_stats:
            ipc = download_stats['ipc_message_rate']
            if ipc['max'] > 100:
                report.append(f"[!] High IPC message rate - {ipc['max']:.1f} msg/sec (possible overhead)")
            else:
                report.append(f"[✓] Reasonable IPC message rate - {ipc['max']:.1f} msg/sec")
        
        report.append("")
        report.append("=" * 80)
        
        return "\n".join(report)


def main():
    if len(sys.argv) < 2:
        print("Usage: python performance_log_analyzer.py <log_file> [--output <report_file>]")
        sys.exit(1)
    
    log_file = sys.argv[1]
    output_file = None
    
    if '--output' in sys.argv:
        idx = sys.argv.index('--output')
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]
    
    analyzer = PerformanceAnalyzer(log_file)
    analyzer.parse()
    
    report = analyzer.generate_report()
    
    print(report)
    
    if output_file:
        Path(output_file).write_text(report, encoding='utf-8')
        print(f"\nReport saved to: {output_file}")


if __name__ == '__main__':
    main()
