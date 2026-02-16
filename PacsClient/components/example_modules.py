"""
Example Module Implementations

Shows how to implement modules for MPR, Eagle Eye, Toolbar, and custom operations.
Each module demonstrates different execution patterns and resource usage.
"""

import asyncio
import logging
import time
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

try:
    from PacsClient.components.module_manager import (
        BaseModule, ModuleResult, ModuleStatus, ModuleContext, UIEvent, UIEventType
    )
except ModuleNotFoundError:
    # Allow running this file directly: python PacsClient/components/example_modules.py
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from PacsClient.components.module_manager import (
        BaseModule, ModuleResult, ModuleStatus, ModuleContext, UIEvent, UIEventType
    )

logger = logging.getLogger(__name__)


# ============================================================================
# EXAMPLE 1: MPR MODULE (Heavy Computation)
# ============================================================================

class MPRModule(BaseModule):
    """
    Multi-Planar Reformatting - Computes axial, sagittal, coronal planes.
    
    Demonstrates:
    - Heavy computation in background thread
    - Cache integration (read & write)
    - Database persistence
    - Stop signal handling
    """
    
    def __init__(self, module_id: str = "mpr_module"):
        super().__init__(module_id, display_name="MPR Module")
        self.progress = 0
        self.current_operation = "Idle"
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Compute MPR planes for a series"""
        
        if not context.series_uid:
            return ModuleResult(
                status=ModuleStatus.ERROR,
                error="No series UID provided"
            )
        
        try:
            logger.info(f"  [MPR] Starting computation for {context.series_uid}")
            
            # Step 1: Load series data (try cache first)
            self.current_operation = "Loading series..."
            series_data = context.get_cached_series(context.series_uid)
            
            if not series_data:
                # Query database if not in cache
                logger.info(f"  [MPR] Cache miss, querying database...")
                result = context.execute_query(
                    "SELECT pixel_data FROM series WHERE uid = ?",
                    (context.series_uid,)
                )
                if not result:
                    return ModuleResult(status=ModuleStatus.ERROR, error="Series not found in DB")
                series_data = result[0][0]
            
            if self.should_stop():
                return ModuleResult(status=ModuleStatus.TIMEOUT, error="Stop requested")
            
            # Step 2: Compute axial planes
            self.current_operation = "Computing axial..."
            self.progress = 25
            logger.info(f"  [MPR] Computing axial plane...")
            axial = await self._compute_plane(series_data, "axial")
            
            if self.should_stop():
                return ModuleResult(status=ModuleStatus.TIMEOUT, error="Stop requested")
            
            # Step 3: Compute sagittal planes
            self.current_operation = "Computing sagittal..."
            self.progress = 50
            logger.info(f"  [MPR] Computing sagittal plane...")
            sagittal = await self._compute_plane(series_data, "sagittal")
            
            if self.should_stop():
                return ModuleResult(status=ModuleStatus.TIMEOUT, error="Stop requested")
            
            # Step 4: Compute coronal planes
            self.current_operation = "Computing coronal..."
            self.progress = 75
            logger.info(f"  [MPR] Computing coronal plane...")
            coronal = await self._compute_plane(series_data, "coronal")
            
            if self.should_stop():
                return ModuleResult(status=ModuleStatus.TIMEOUT, error="Stop requested")
            
            # Step 5: Cache and persist results
            self.current_operation = "Saving results..."
            self.progress = 90
            
            mpr_result = {
                'series_uid': context.series_uid,
                'axial': axial,
                'sagittal': sagittal,
                'coronal': coronal,
                'timestamp': time.time()
            }
            
            # Cache result for fast retrieval
            cache_key = f"mpr_{context.series_uid}"
            context.cache_result(cache_key, mpr_result, size_bytes=30*1024*1024)
            
            # Persist to database (non-blocking)
            try:
                context.execute_update(
                    """INSERT OR REPLACE INTO computed_mpr 
                       (series_uid, axial, sagittal, coronal, computed_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (context.series_uid, str(axial), str(sagittal), str(coronal), 
                     time.time())
                )
            except Exception as e:
                logger.warning(f"  [MPR] Failed to save to DB: {e} (cache ok)")
            
            self.progress = 100
            logger.info(f"  [MPR] Computation complete (cached + persisted)")
            
            return ModuleResult(status=ModuleStatus.COMPLETED, data=mpr_result)
        
        except Exception as e:
            logger.error(f"  [MPR] Error: {e}")
            return ModuleResult(status=ModuleStatus.ERROR, error=str(e))
    
    async def _compute_plane(self, series_data: Any, plane_type: str) -> str:
        """Simulate heavy computation"""
        # In real implementation: VTK processing
        await asyncio.sleep(0.3)  # Simulate 300ms computation
        return f"{plane_type}_computed"
    
    def on_ui_event(self, event: UIEvent) -> None:
        """Handle UI events (pause, resume, cancel)"""
        if event.event_type == UIEventType.PAUSE_REQUEST:
            logger.info(f"  [MPR] Pause requested")
            self.request_stop()
        
        elif event.event_type == UIEventType.PARAMETER_CHANGE:
            logger.info(f"  [MPR] Parameters changed: {event.data}")
    
    def save_state(self) -> Dict[str, Any]:
        """Save module state"""
        state = super().save_state()
        state.update({
            'progress': self.progress,
            'current_operation': self.current_operation
        })
        return state
    
    def load_state(self, state: Dict[str, Any]) -> None:
        """Restore module state"""
        self.progress = state.get('progress', 0)
        self.current_operation = state.get('current_operation', 'Idle')


# ============================================================================
# EXAMPLE 2: EAGLE EYE MODULE (UI-Driven)
# ============================================================================

class EagleEyeModule(BaseModule):
    """
    Thumbnail preview with zoom/pan controls.
    
    Demonstrates:
    - Lightweight, quick execution
    - Interactive event handling
    - UI state management
    """
    
    def __init__(self, module_id: str = "eagle_eye_module"):
        super().__init__(module_id, display_name="Eagle Eye Module")
        self.zoom_level = 1.0
        self.pan_offset = (0, 0)
        self.thumbnail = None
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Prepare thumbnail data"""
        
        logger.info(f"  [EagleEye] Preparing thumbnail for {context.series_uid}")
        
        # Get series from cache (fast)
        series = context.get_cached_series(context.series_uid)
        
        if not series:
            # Fall back to database
            result = context.execute_query(
                "SELECT thumbnail FROM series_thumbnails WHERE series_uid = ?",
                (context.series_uid,)
            )
            
            if result:
                self.thumbnail = result[0][0]
            else:
                self.thumbnail = None
        else:
            # Create thumbnail from series first slice
            self.thumbnail = f"thumb_from_{context.series_uid}"
        
        # Cache for fast display
        if self.thumbnail:
            context.cache_result(
                f"thumb_{context.series_uid}",
                self.thumbnail,
                size_bytes=2*1024*1024
            )
        
        logger.info(f"  [EagleEye] Thumbnail ready: {self.thumbnail}")
        
        return ModuleResult(
            status=ModuleStatus.COMPLETED,
            data={'thumbnail': self.thumbnail}
        )
    
    def on_ui_event(self, event: UIEvent) -> None:
        """Handle user interaction"""
        
        if event.event_type == UIEventType.USER_INPUT:
            action = event.data.get('action')
            
            if action == 'zoom_in':
                self.zoom_level *= 1.2
                logger.debug(f"  [EagleEye] Zoom: {self.zoom_level:.1f}x")
            
            elif action == 'zoom_out':
                self.zoom_level /= 1.2
                logger.debug(f"  [EagleEye] Zoom: {self.zoom_level:.1f}x")
            
            elif action == 'pan':
                self.pan_offset = event.data.get('offset', (0, 0))
                logger.debug(f"  [EagleEye] Pan: {self.pan_offset}")
        
        elif event.event_type == UIEventType.PAUSE_REQUEST:
            self.request_stop()
    
    def save_state(self) -> Dict[str, Any]:
        """Save zoom/pan state"""
        state = super().save_state()
        state.update({
            'zoom_level': self.zoom_level,
            'pan_offset': self.pan_offset
        })
        return state
    
    def load_state(self, state: Dict[str, Any]) -> None:
        """Restore zoom/pan state"""
        self.zoom_level = state.get('zoom_level', 1.0)
        self.pan_offset = state.get('pan_offset', (0, 0))


# ============================================================================
# EXAMPLE 3: TOOLBAR MODULE (Quick Operations)
# ============================================================================

class ToolbarModule(BaseModule):
    """
    Lightweight toolbar with quick access to tools and operations.
    
    Demonstrates:
    - Very fast execution
    - Minimal resource usage
    - Database queries for configuration
    """
    
    def __init__(self, module_id: str = "toolbar_module"):
        super().__init__(module_id, display_name="Toolbar Module")
        self.tools = []
        self.quick_actions = []
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Load toolbar configuration"""
        
        logger.info(f"  [Toolbar] Loading toolbar configuration")
        
        # Query available tools for this series
        try:
            results = context.execute_query(
                """SELECT tool_id, tool_name, tool_icon FROM available_tools 
                   WHERE active = 1 ORDER BY priority DESC"""
            )
            
            self.tools = [
                {'id': row[0], 'name': row[1], 'icon': row[2]}
                for row in results
            ]
            
            logger.info(f"  [Toolbar] Loaded {len(self.tools)} tools")
            
            return ModuleResult(
                status=ModuleStatus.COMPLETED,
                data={'tools': self.tools}
            )
        
        except Exception as e:
            logger.error(f"  [Toolbar] Error loading tools: {e}")
            return ModuleResult(status=ModuleStatus.ERROR, error=str(e))
    
    def on_ui_event(self, event: UIEvent) -> None:
        """Handle toolbar actions"""
        
        if event.event_type == UIEventType.USER_INPUT:
            action = event.data.get('action')
            tool_id = event.data.get('tool_id')
            
            if action == 'tool_selected':
                logger.info(f"  [Toolbar] Tool selected: {tool_id}")
                # Signal main UI to activate tool
            
            elif action == 'quick_action':
                logger.info(f"  [Toolbar] Quick action: {event.data.get('action_id')}")


# ============================================================================
# EXAMPLE 4: MEASUREMENT MODULE (Database Operations)
# ============================================================================

class MeasurementModule(BaseModule):
    """
    Measurement tools with persistent storage.
    
    Demonstrates:
    - Database write operations
    - State persistence
    - Measurement calculations
    """
    
    def __init__(self, module_id: str = "measurement_module"):
        super().__init__(module_id, display_name="Measurement Module")
        self.measurements = []
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Load existing measurements for series"""
        
        logger.info(f"  [Measurement] Loading measurements for {context.series_uid}")
        
        # Query existing measurements
        try:
            results = context.execute_query(
                """SELECT measurement_id, measurement_type, value FROM measurements
                   WHERE series_uid = ? ORDER BY created_at DESC""",
                (context.series_uid,)
            )
            
            self.measurements = [
                {'id': row[0], 'type': row[1], 'value': row[2]}
                for row in results
            ]
            
            logger.info(f"  [Measurement] Loaded {len(self.measurements)} measurements")
            
            return ModuleResult(
                status=ModuleStatus.COMPLETED,
                data={'measurements': self.measurements}
            )
        
        except Exception as e:
            logger.error(f"  [Measurement] Error: {e}")
            return ModuleResult(status=ModuleStatus.ERROR, error=str(e))
    
    def on_ui_event(self, event: UIEvent) -> None:
        """Handle measurement operations"""
        
        if event.event_type == UIEventType.USER_INPUT:
            action = event.data.get('action')
            
            if action == 'add_measurement':
                measurement = {
                    'type': event.data.get('type'),
                    'value': event.data.get('value'),
                    'timestamp': time.time()
                }
                self.measurements.append(measurement)
                logger.info(f"  [Measurement] Added: {measurement}")
            
            elif action == 'delete_measurement':
                m_id = event.data.get('measurement_id')
                self.measurements = [m for m in self.measurements if m['id'] != m_id]
                logger.info(f"  [Measurement] Deleted: {m_id}")
    
    def save_state(self) -> Dict[str, Any]:
        """Save measurements"""
        state = super().save_state()
        state['measurements'] = self.measurements
        return state


# ============================================================================
# EXAMPLE 5: REPORT GENERATOR MODULE (Heavy Processing)
# ============================================================================

class ReportGeneratorModule(BaseModule):
    """
    Generate reports from study data.
    
    Demonstrates:
    - Long-running operations
    - Progress tracking
    - File output operations
    """
    
    def __init__(self, module_id: str = "report_generator"):
        super().__init__(module_id, display_name="Report Generator")
        self.progress = 0
    
    async def execute(self, context: ModuleContext) -> ModuleResult:
        """Generate report for study"""
        
        logger.info(f"  [Report] Generating report for patient {context.patient_uid}")
        
        try:
            # Fetch study data
            self.progress = 10
            results = context.execute_query(
                "SELECT study_id, description FROM studies WHERE patient_uid = ?",
                (context.patient_uid,)
            )
            
            if not results:
                return ModuleResult(status=ModuleStatus.ERROR, error="No studies found")
            
            # Aggregate measurements
            self.progress = 30
            measurements = context.execute_query(
                "SELECT COUNT(*) FROM measurements WHERE patient_uid = ?",
                (context.patient_uid,)
            )
            
            if self.should_stop():
                return ModuleResult(status=ModuleStatus.TIMEOUT)
            
            # Generate report
            self.progress = 70
            report_data = {
                'patient_uid': context.patient_uid,
                'studies': len(results),
                'measurements': measurements[0][0] if measurements else 0,
                'generated_at': time.time()
            }
            
            # Cache report
            context.cache_result(
                f"report_{context.patient_uid}",
                report_data,
                size_bytes=5*1024*1024
            )
            
            self.progress = 100
            logger.info(f"  [Report] Report generated successfully")
            
            return ModuleResult(status=ModuleStatus.COMPLETED, data=report_data)
        
        except Exception as e:
            logger.error(f"  [Report] Error: {e}")
            return ModuleResult(status=ModuleStatus.ERROR, error=str(e))


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    import sys
    sys.path.insert(0, r'c:\AI-Pacs codes\PacsClient V2(5jan)\PacsClientV2')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Create modules
    mpr = MPRModule()
    eagle_eye = EagleEyeModule()
    toolbar = ToolbarModule()
    measurement = MeasurementModule()
    report = ReportGeneratorModule()
    
    print("✅ Module examples created successfully")
    print(f"  - MPR Module: {mpr.display_name}")
    print(f"  - Eagle Eye Module: {eagle_eye.display_name}")
    print(f"  - Toolbar Module: {toolbar.display_name}")
    print(f"  - Measurement Module: {measurement.display_name}")
    print(f"  - Report Generator: {report.display_name}")
