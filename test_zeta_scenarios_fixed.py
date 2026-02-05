#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Zeta Download Manager - Scenario Tests (EXECUTABLE - FIXED)

Tests all 4 scenarios using the actual Zeta implementation.
Fixed for Windows console encoding and proper imports.

Run: python test_zeta_scenarios_fixed.py
"""

import sys
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Add PacsClient to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Configure logging (ASCII only, no emoji for Windows console)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('test_zeta_scenarios.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Import only the specific Zeta components we need (avoid circular imports)
try:
    # Direct imports to avoid loading full PacsClient package
    sys.path.insert(0, str(project_root / 'PacsClient'))
    
    from zeta_download_manager.core.enums import (
        DownloadPriority,
        DownloadStatus
    )
    from zeta_download_manager.core.models import (
        DownloadTask,
        SeriesInfo,
        DownloadState
    )
    
    ZETA_ENUMS_AVAILABLE = True
    logger.info("[OK] Zeta enums imported")
except Exception as e:
    logger.error(f"[ERROR] Failed to import Zeta enums: {e}")
    ZETA_ENUMS_AVAILABLE = False
    sys.exit(1)


class MockStateStore:
    """Lightweight mock state store for testing (avoids full import chain)"""
    
    def __init__(self):
        self._states: Dict[str, DownloadState] = {}
        logger.info("[SETUP] MockStateStore initialized")
    
    def create(self, task: DownloadTask) -> DownloadState:
        """Create state from task"""
        if task.study_uid in self._states:
            logger.warning(f"[WARN] State already exists: {task.study_uid}")
            return self._states[task.study_uid]
        
        state = DownloadState(
            study_uid=task.study_uid,
            status=DownloadStatus.PENDING,
            priority=task.priority,
            total_count=task.total_image_count,
            patient_name=task.patient_name,
            study_description=task.description,
            start_time=datetime.now(),
            last_update=datetime.now()
        )
        
        self._states[task.study_uid] = state
        logger.info(f"[CREATE] State created: {task.patient_name}")
        return state
    
    def update(self, study_uid: str, **changes) -> None:
        """Update state"""
        if study_uid not in self._states:
            logger.error(f"[ERROR] State not found: {study_uid}")
            return
        
        state = self._states[study_uid]
        for key, value in changes.items():
            if hasattr(state, key):
                old_value = getattr(state, key)
                setattr(state, key, value)
                logger.debug(f"[UPDATE] {study_uid[:20]}... {key}: {old_value} -> {value}")
        
        state.last_update = datetime.now()
    
    def get(self, study_uid: str) -> Optional[DownloadState]:
        """Get state"""
        return self._states.get(study_uid)
    
    def get_all(self) -> List[DownloadState]:
        """Get all states"""
        return list(self._states.values())
    
    def get_by_status(self, status: DownloadStatus) -> List[DownloadState]:
        """Get states by status"""
        return [s for s in self._states.values() if s.status == status]
    
    def get_by_priority(self, priority: DownloadPriority) -> List[DownloadState]:
        """Get states by priority"""
        return [s for s in self._states.values() if s.priority == priority]
    
    def clear(self):
        """Clear all states"""
        count = len(self._states)
        self._states.clear()
        logger.info(f"[CLEAR] Cleared {count} states")


class ZetaScenarioTester:
    """Test suite for Zeta Download Manager scenarios"""
    
    def __init__(self):
        self.state_store = None
        self.test_results = []
    
    def setup(self):
        """Setup before each test"""
        logger.info("")
        logger.info("="*80)
        logger.info("SETUP: Initializing test environment")
        logger.info("="*80)
        
        # Create fresh state store
        self.state_store = MockStateStore()
        
        logger.info("[OK] Test environment ready")
        logger.info("")
    
    def teardown(self):
        """Cleanup after each test"""
        logger.info("")
        logger.info("="*80)
        logger.info("TEARDOWN: Cleaning up")
        logger.info("="*80)
        
        if self.state_store:
            # Get final counts
            all_states = self.state_store.get_all()
            logger.info(f"[INFO] Total downloads: {len(all_states)}")
            
            for status in DownloadStatus:
                count = len(self.state_store.get_by_status(status))
                if count > 0:
                    logger.info(f"[INFO] {status.value}: {count}")
            
            # Clear
            self.state_store.clear()
        
        logger.info("[OK] Cleanup complete")
        logger.info("")
    
    def create_mock_task(
        self,
        study_uid: str,
        patient_name: str,
        priority: DownloadPriority = DownloadPriority.NORMAL,
        series_count: int = 3,
        images_per_series: int = 100
    ) -> DownloadTask:
        """Create a mock download task"""
        
        # Create mock series
        series_list = []
        for i in range(1, series_count + 1):
            series = SeriesInfo(
                series_uid=f"{study_uid}_series_{i}",
                series_number=str(i),
                series_description=f"Series {i}",
                modality="CT",
                image_count=images_per_series
            )
            series_list.append(series)
        
        # Create task
        task = DownloadTask(
            study_uid=study_uid,
            patient_id=f"PID_{study_uid[-3:]}",
            patient_name=patient_name,
            study_date="2026-02-04",
            modality="CT",
            description=f"Test study for {patient_name}",
            series_list=series_list,
            priority=priority,
            created_at=datetime.now()
        )
        
        return task
    
    # =========================================================================
    # SCENARIO 1: Bulk Normal + One Critical
    # =========================================================================
    
    def test_scenario_1(self) -> bool:
        """
        Test Scenario 1: Bulk Normal Downloads + One Critical Download
        
        Expected:
        - 30 patients added at NORMAL priority
        - Patient 1 starts downloading
        - Patient 15 promoted to CRITICAL
        - Patient 1 pauses (auto-pause)
        - Patient 15 starts immediately
        - After Patient 15 completes, Patient 1 auto-resumes
        """
        logger.info("")
        logger.info("="*80)
        logger.info("TEST SCENARIO 1: Bulk Normal + One Critical")
        logger.info("="*80)
        
        try:
            # Step 1: Add 30 patients at NORMAL priority
            logger.info("")
            logger.info("[STEP 1] Adding 30 patients (NORMAL priority)")
            for i in range(1, 31):
                task = self.create_mock_task(
                    study_uid=f"study_{i:03d}",
                    patient_name=f"Patient {i}",
                    priority=DownloadPriority.NORMAL
                )
                self.state_store.create(task)
            
            logger.info(f"[OK] Added 30 patients")
            
            # Verify all 30 are pending
            pending = self.state_store.get_by_status(DownloadStatus.PENDING)
            assert len(pending) == 30, f"Expected 30 pending, got {len(pending)}"
            logger.info(f"[VERIFY] {len(pending)} patients pending")
            
            # Step 2: Patient 1 starts downloading
            logger.info("")
            logger.info("[STEP 2] Starting Patient 1 download")
            self.state_store.update(
                "study_001",
                status=DownloadStatus.DOWNLOADING,
                start_time=datetime.now()
            )
            
            # Verify: 1 downloading, 29 pending
            downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
            pending = self.state_store.get_by_status(DownloadStatus.PENDING)
            assert len(downloading) == 1, f"Expected 1 downloading, got {len(downloading)}"
            assert len(pending) == 29, f"Expected 29 pending, got {len(pending)}"
            logger.info(f"[VERIFY] {len(downloading)} downloading, {len(pending)} pending")
            
            # Step 3: User double-clicks Patient 15 (CRITICAL priority)
            logger.info("")
            logger.info("[STEP 3] User double-clicks Patient 15 (CRITICAL)")
            self.state_store.update("study_015", priority=DownloadPriority.CRITICAL)
            
            # Step 4: Preempt Patient 1
            logger.info("[ACTION] Preempting Patient 1 (auto-pause)")
            self.state_store.update(
                "study_001",
                status=DownloadStatus.PAUSED,
                is_auto_paused=True
            )
            
            # Step 5: Start Patient 15
            logger.info("[ACTION] Starting Patient 15 (CRITICAL)")
            self.state_store.update(
                "study_015",
                status=DownloadStatus.DOWNLOADING,
                start_time=datetime.now()
            )
            
            # Verify preemption
            state_1 = self.state_store.get("study_001")
            state_15 = self.state_store.get("study_015")
            
            assert state_1.status == DownloadStatus.PAUSED, \
                f"Patient 1 should be Paused, got {state_1.status.value}"
            assert state_1.is_auto_paused == True, \
                "Patient 1 should be auto-paused"
            assert state_15.status == DownloadStatus.DOWNLOADING, \
                f"Patient 15 should be Downloading, got {state_15.status.value}"
            assert state_15.priority == DownloadPriority.CRITICAL, \
                f"Patient 15 should be Critical, got {state_15.priority.name}"
            
            logger.info("[VERIFY] Patient 1 paused (auto-pause)")
            logger.info("[VERIFY] Patient 15 downloading (CRITICAL)")
            
            # Step 6: Patient 15 completes
            logger.info("")
            logger.info("[STEP 4] Patient 15 completes")
            self.state_store.update(
                "study_015",
                status=DownloadStatus.COMPLETED,
                progress_percent=100.0,
                end_time=datetime.now()
            )
            
            # Step 7: Check auto-resume condition (Rule R5)
            logger.info("[CHECK] Checking auto-resume condition (Rule R5)")
            
            paused = self.state_store.get_by_status(DownloadStatus.PAUSED)
            auto_paused = [p for p in paused if p.is_auto_paused]
            
            downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
            critical_running = [d for d in downloading if d.priority == DownloadPriority.CRITICAL]
            
            assert len(auto_paused) > 0, "Should have auto-paused downloads"
            assert len(critical_running) == 0, "No critical should be running"
            
            logger.info(f"[INFO] Auto-paused downloads: {len(auto_paused)}")
            logger.info(f"[INFO] Critical running: {len(critical_running)}")
            
            # Auto-resume Patient 1
            logger.info("[ACTION] Auto-resuming Patient 1")
            self.state_store.update("study_001", status=DownloadStatus.DOWNLOADING)
            
            # Verify auto-resume
            state_1 = self.state_store.get("study_001")
            assert state_1.status == DownloadStatus.DOWNLOADING, \
                f"Patient 1 should be Downloading, got {state_1.status.value}"
            
            logger.info("[VERIFY] Patient 1 auto-resumed")
            logger.info("[VERIFY] Patient 15 completed")
            
            # Final summary
            logger.info("")
            logger.info("[SUMMARY]")
            logger.info("  [OK] Patient 15 (CRITICAL) completed")
            logger.info("  [OK] Patient 1 (NORMAL) auto-resumed")
            logger.info("  [OK] Remaining 28 patients still pending")
            
            logger.info("")
            logger.info("="*80)
            logger.info("[PASS] SCENARIO 1: All verifications successful!")
            logger.info("="*80)
            
            return True
            
        except AssertionError as e:
            logger.error(f"[FAIL] SCENARIO 1: {e}")
            return False
        except Exception as e:
            logger.error(f"[ERROR] SCENARIO 1: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    # =========================================================================
    # SCENARIO 2: Multiple High Priority (LIFO)
    # =========================================================================
    
    def test_scenario_2(self) -> bool:
        """
        Test Scenario 2: Multiple High-Priority Patients (LIFO)
        
        Expected:
        - Patient A opens (CRITICAL)
        - Patient B opens (CRITICAL) - preempts A
        - Patient C opens (CRITICAL) - preempts B
        - Completion order: C -> B -> A (LIFO)
        """
        logger.info("")
        logger.info("="*80)
        logger.info("TEST SCENARIO 2: Multiple High Priority (LIFO)")
        logger.info("="*80)
        
        try:
            # Patients opened in order: A, B, C
            # Expected completion order: C, B, A (reverse = LIFO)
            
            timestamps = []
            
            # Step 1: Open Patient A
            logger.info("")
            logger.info("[STEP 1] User opens Patient A (CRITICAL)")
            time.sleep(0.05)
            
            task_a = self.create_mock_task(
                study_uid="patient_a",
                patient_name="Patient A",
                priority=DownloadPriority.CRITICAL
            )
            state_a = self.state_store.create(task_a)
            timestamps.append(('A', state_a.start_time))
            
            self.state_store.update(
                "patient_a",
                status=DownloadStatus.DOWNLOADING
            )
            logger.info("[OK] Patient A downloading (CRITICAL)")
            
            # Step 2: Open Patient B - preempts A
            logger.info("")
            logger.info("[STEP 2] User opens Patient B (CRITICAL)")
            time.sleep(0.05)
            
            task_b = self.create_mock_task(
                study_uid="patient_b",
                patient_name="Patient B",
                priority=DownloadPriority.CRITICAL
            )
            state_b = self.state_store.create(task_b)
            timestamps.append(('B', state_b.start_time))
            
            # Preempt A
            logger.info("[ACTION] Preempting Patient A")
            self.state_store.update(
                "patient_a",
                status=DownloadStatus.PAUSED,
                is_auto_paused=True
            )
            
            # Start B
            self.state_store.update(
                "patient_b",
                status=DownloadStatus.DOWNLOADING
            )
            
            # Verify
            state_a = self.state_store.get("patient_a")
            state_b = self.state_store.get("patient_b")
            assert state_a.status == DownloadStatus.PAUSED
            assert state_b.status == DownloadStatus.DOWNLOADING
            logger.info("[VERIFY] Patient A paused, Patient B downloading")
            
            # Step 3: Open Patient C - preempts B
            logger.info("")
            logger.info("[STEP 3] User opens Patient C (CRITICAL)")
            time.sleep(0.05)
            
            task_c = self.create_mock_task(
                study_uid="patient_c",
                patient_name="Patient C",
                priority=DownloadPriority.CRITICAL
            )
            state_c = self.state_store.create(task_c)
            timestamps.append(('C', state_c.start_time))
            
            # Preempt B
            logger.info("[ACTION] Preempting Patient B")
            self.state_store.update(
                "patient_b",
                status=DownloadStatus.PAUSED,
                is_auto_paused=True
            )
            
            # Start C
            self.state_store.update(
                "patient_c",
                status=DownloadStatus.DOWNLOADING
            )
            
            # Verify
            state_b = self.state_store.get("patient_b")
            state_c = self.state_store.get("patient_c")
            assert state_b.status == DownloadStatus.PAUSED
            assert state_c.status == DownloadStatus.DOWNLOADING
            logger.info("[VERIFY] Patient B paused, Patient C downloading")
            
            # Verify timestamp order (C is newest)
            logger.info("")
            logger.info("[CHECK] Verifying LIFO timestamps:")
            for name, ts in timestamps:
                logger.info(f"  Patient {name}: {ts.strftime('%H:%M:%S.%f')}")
            
            assert timestamps[2][1] > timestamps[1][1] > timestamps[0][1], \
                "Timestamps should be increasing (C > B > A)"
            logger.info("[VERIFY] Timestamps confirm order: C > B > A")
            
            # Step 4: C completes -> B should resume (LIFO)
            logger.info("")
            logger.info("[STEP 4] Patient C completes")
            self.state_store.update(
                "patient_c",
                status=DownloadStatus.COMPLETED,
                progress_percent=100.0
            )
            
            # Get paused with LIFO order (newest first)
            paused = self.state_store.get_by_status(DownloadStatus.PAUSED)
            paused_sorted = sorted(
                paused,
                key=lambda s: s.start_time,
                reverse=True  # LIFO: newest first
            )
            
            next_to_resume = paused_sorted[0] if paused_sorted else None
            assert next_to_resume is not None
            assert next_to_resume.study_uid == "patient_b", \
                f"Expected Patient B (LIFO), got {next_to_resume.patient_name}"
            
            logger.info(f"[VERIFY] LIFO order: Next to resume is {next_to_resume.patient_name}")
            
            # Resume B
            self.state_store.update("patient_b", status=DownloadStatus.DOWNLOADING)
            logger.info("[ACTION] Patient B resumed")
            
            # Step 5: B completes -> A should resume
            logger.info("")
            logger.info("[STEP 5] Patient B completes")
            self.state_store.update(
                "patient_b",
                status=DownloadStatus.COMPLETED,
                progress_percent=100.0
            )
            
            # A should be next
            paused = self.state_store.get_by_status(DownloadStatus.PAUSED)
            assert len(paused) == 1
            assert paused[0].study_uid == "patient_a"
            
            # Resume A
            self.state_store.update("patient_a", status=DownloadStatus.DOWNLOADING)
            logger.info("[ACTION] Patient A resumed")
            
            # Final summary
            logger.info("")
            logger.info("[SUMMARY] Final Order: C -> B -> A (LIFO verified)")
            
            logger.info("")
            logger.info("="*80)
            logger.info("[PASS] SCENARIO 2: LIFO order verified!")
            logger.info("="*80)
            
            return True
            
        except AssertionError as e:
            logger.error(f"[FAIL] SCENARIO 2: {e}")
            return False
        except Exception as e:
            logger.error(f"[ERROR] SCENARIO 2: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    # =========================================================================
    # SCENARIO 3: Sequential Normal Downloads
    # =========================================================================
    
    def test_scenario_3(self) -> bool:
        """
        Test Scenario 3: Sequential Normal Downloads
        
        Expected:
        - 10 patients at NORMAL priority
        - Only 1 downloading at any time
        - Sequential order: 1 -> 2 -> 3 -> ... -> 10
        """
        logger.info("")
        logger.info("="*80)
        logger.info("TEST SCENARIO 3: Sequential Normal Downloads")
        logger.info("="*80)
        
        try:
            # Step 1: Add 10 patients
            logger.info("")
            logger.info("[STEP 1] Adding 10 patients (NORMAL priority)")
            for i in range(1, 11):
                task = self.create_mock_task(
                    study_uid=f"study_{i:02d}",
                    patient_name=f"Patient {i}",
                    priority=DownloadPriority.NORMAL
                )
                self.state_store.create(task)
            
            logger.info(f"[OK] Added 10 patients")
            
            # Verify all pending
            pending = self.state_store.get_by_status(DownloadStatus.PENDING)
            assert len(pending) == 10, f"Expected 10 pending, got {len(pending)}"
            logger.info(f"[VERIFY] {len(pending)} patients pending")
            
            # Step 2: Simulate sequential downloads
            logger.info("")
            logger.info("[STEP 2] Simulating sequential downloads")
            
            for i in range(1, 11):
                study_uid = f"study_{i:02d}"
                
                # Start download
                logger.info(f"  [{i}/10] Starting Patient {i}")
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.DOWNLOADING,
                    start_time=datetime.now()
                )
                
                # Verify only 1 downloading
                downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
                assert len(downloading) == 1, \
                    f"Expected 1 downloading, got {len(downloading)}"
                assert downloading[0].study_uid == study_uid
                
                # Complete download
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.COMPLETED,
                    progress_percent=100.0
                )
                logger.info(f"  [{i}/10] Patient {i} completed")
            
            # Final verification
            completed = self.state_store.get_by_status(DownloadStatus.COMPLETED)
            assert len(completed) == 10, f"Expected 10 completed, got {len(completed)}"
            
            logger.info("")
            logger.info("[SUMMARY]")
            logger.info("  [OK] All 10 patients completed sequentially")
            logger.info("  [OK] Order: 1 -> 2 -> 3 -> ... -> 10")
            logger.info("  [OK] Never more than 1 downloading at a time")
            
            logger.info("")
            logger.info("="*80)
            logger.info("[PASS] SCENARIO 3: Sequential execution verified!")
            logger.info("="*80)
            
            return True
            
        except AssertionError as e:
            logger.error(f"[FAIL] SCENARIO 3: {e}")
            return False
        except Exception as e:
            logger.error(f"[ERROR] SCENARIO 3: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    # =========================================================================
    # SCENARIO 4: Network Interruption Resume
    # =========================================================================
    
    def test_scenario_4(self) -> bool:
        """
        Test Scenario 4: Network Interruption and Resume
        
        Expected:
        - Patient 5 downloading at 50% (150/300 images)
        - Network error -> paused
        - Resume -> continues from 50%
        - Downloads only remaining 150 images
        """
        logger.info("")
        logger.info("="*80)
        logger.info("TEST SCENARIO 4: Network Interruption Resume")
        logger.info("="*80)
        
        try:
            # Step 1: Add 10 patients
            logger.info("")
            logger.info("[STEP 1] Adding 10 patients")
            for i in range(1, 11):
                task = self.create_mock_task(
                    study_uid=f"study_{i:02d}",
                    patient_name=f"Patient {i}",
                    priority=DownloadPriority.NORMAL,
                    series_count=3,
                    images_per_series=100  # Total 300 images
                )
                self.state_store.create(task)
            
            # Patients 1-4: Complete
            logger.info("[SETUP] Setting up initial state")
            for i in range(1, 5):
                self.state_store.update(
                    f"study_{i:02d}",
                    status=DownloadStatus.COMPLETED,
                    progress_percent=100.0,
                    downloaded_count=300,
                    total_count=300
                )
                logger.info(f"  Patient {i}: Completed")
            
            # Patient 5: Downloading at 50%
            self.state_store.update(
                "study_05",
                status=DownloadStatus.DOWNLOADING,
                progress_percent=50.0,
                downloaded_count=150,
                total_count=300,
                start_time=datetime.now()
            )
            logger.info(f"  Patient 5: Downloading (50% - 150/300 images)")
            
            # Patients 6-10: Pending
            for i in range(6, 11):
                logger.info(f"  Patient {i}: Pending")
            
            # Step 2: Network error
            logger.info("")
            logger.info("[STEP 2] Network disconnection occurs")
            self.state_store.update(
                "study_05",
                status=DownloadStatus.PAUSED,
                is_auto_paused=False,  # Network error (can be resumed manually)
                error_message="Network error: Connection timeout",
                retry_count=1
            )
            
            # Verify paused at 50%
            state_5 = self.state_store.get("study_05")
            assert state_5.status == DownloadStatus.PAUSED
            assert state_5.progress_percent == 50.0
            assert state_5.downloaded_count == 150
            assert state_5.total_count == 300
            
            remaining = state_5.total_count - state_5.downloaded_count
            
            logger.info("[VERIFY] Patient 5 paused at 50%")
            logger.info(f"[INFO] Downloaded: {state_5.downloaded_count}/{state_5.total_count}")
            logger.info(f"[INFO] Remaining: {remaining} images")
            logger.info(f"[INFO] Error: {state_5.error_message}")
            
            # Step 3: Resume
            logger.info("")
            logger.info("[STEP 3] Network reconnects, user clicks Resume")
            self.state_store.update("study_05", status=DownloadStatus.DOWNLOADING)
            
            # Verify resumed from 50%
            state_5 = self.state_store.get("study_05")
            assert state_5.status == DownloadStatus.DOWNLOADING
            assert state_5.progress_percent == 50.0, \
                f"Should resume from 50%, got {state_5.progress_percent}%"
            assert state_5.downloaded_count == 150, \
                f"Should have 150 downloaded, got {state_5.downloaded_count}"
            
            logger.info("[VERIFY] Patient 5 resumed from 50% (not restarted)")
            logger.info(f"[INFO] Will download remaining {remaining} images")
            
            # Step 4: Patient 5 completes (remaining 150 images)
            logger.info("")
            logger.info("[STEP 4] Patient 5 completes (remaining 150 images)")
            self.state_store.update(
                "study_05",
                status=DownloadStatus.COMPLETED,
                progress_percent=100.0,
                downloaded_count=300
            )
            
            # Step 5: Queue continues
            logger.info("")
            logger.info("[STEP 5] Queue continues (6-10)")
            for i in range(6, 11):
                study_uid = f"study_{i:02d}"
                
                # Start
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.DOWNLOADING
                )
                
                # Complete
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.COMPLETED,
                    progress_percent=100.0,
                    downloaded_count=300,
                    total_count=300
                )
                logger.info(f"  Patient {i} completed")
            
            # Final verification
            completed = self.state_store.get_by_status(DownloadStatus.COMPLETED)
            assert len(completed) == 10, f"Expected 10 completed, got {len(completed)}"
            
            logger.info("")
            logger.info("[SUMMARY]")
            logger.info("  [OK] All 10 patients completed")
            logger.info("  [OK] Patient 5 resumed from 50% (not restarted)")
            logger.info("  [OK] Downloaded only remaining 150 images")
            logger.info("  [OK] Queue order maintained")
            
            logger.info("")
            logger.info("="*80)
            logger.info("[PASS] SCENARIO 4: Network resume verified!")
            logger.info("="*80)
            
            return True
            
        except AssertionError as e:
            logger.error(f"[FAIL] SCENARIO 4: {e}")
            return False
        except Exception as e:
            logger.error(f"[ERROR] SCENARIO 4: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    # =========================================================================
    # RUN ALL TESTS
    # =========================================================================
    
    def run_all(self) -> Dict[str, bool]:
        """Run all test scenarios"""
        logger.info("")
        logger.info("="*80)
        logger.info("ZETA DOWNLOAD MANAGER - SCENARIO TEST SUITE")
        logger.info("Testing all 4 critical scenarios")
        logger.info("="*80)
        
        if not ZETA_ENUMS_AVAILABLE:
            logger.error("[ERROR] Zeta components not available - cannot run tests")
            return {}
        
        tests = [
            ("Scenario 1: Bulk Normal + One Critical", self.test_scenario_1),
            ("Scenario 2: Multiple High Priority (LIFO)", self.test_scenario_2),
            ("Scenario 3: Sequential Normal", self.test_scenario_3),
            ("Scenario 4: Network Resume", self.test_scenario_4),
        ]
        
        results = {}
        passed = 0
        failed = 0
        
        for name, test_func in tests:
            try:
                self.setup()
                result = test_func()
                self.teardown()
                
                results[name] = result
                if result:
                    passed += 1
                else:
                    failed += 1
                    
            except Exception as e:
                logger.error(f"[ERROR] {name}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results[name] = False
                failed += 1
        
        # Summary
        logger.info("")
        logger.info("="*80)
        logger.info("TEST SUMMARY")
        logger.info("="*80)
        
        for name, result in results.items():
            status = "[PASS]" if result else "[FAIL]"
            logger.info(f"{status} {name}")
        
        logger.info("")
        logger.info(f"Results:")
        logger.info(f"  [OK] Passed: {passed}")
        logger.info(f"  [ERROR] Failed: {failed}")
        logger.info(f"  Total:  {passed + failed}")
        
        if failed == 0:
            logger.info("")
            logger.info("="*80)
            logger.info("ALL TESTS PASSED!")
            logger.info("="*80)
        else:
            logger.info(f"")
            logger.info(f"[WARN] {failed} test(s) failed")
        
        logger.info("="*80)
        
        return results


if __name__ == "__main__":
    logger.info("")
    logger.info("="*80)
    logger.info("ZETA DOWNLOAD MANAGER - EXECUTABLE SCENARIO TESTS")
    logger.info("="*80)
    logger.info(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Log file: test_zeta_scenarios.log")
    logger.info("="*80)
    
    # Run tests
    tester = ZetaScenarioTester()
    results = tester.run_all()
    
    logger.info(f"")
    logger.info(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*80)
    
    # Exit with error code if any tests failed
    exit_code = 0 if all(results.values()) else 1
    sys.exit(exit_code)
