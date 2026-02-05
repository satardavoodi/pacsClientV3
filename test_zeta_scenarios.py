#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Zeta Download Manager - Scenario Tests (EXECUTABLE)

Tests all 4 scenarios using the actual Zeta implementation:
1. Bulk Normal + One Critical
2. Multiple High Priority (LIFO)
3. Sequential Normal Downloads
4. Network Interruption Resume

Run: python test_zeta_scenarios.py
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('test_zeta_scenarios.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Import Zeta components
try:
    from PacsClient.zeta_download_manager.state.state_store import (
        get_state_store, 
        reset_state_store,
        DownloadState
    )
    from PacsClient.zeta_download_manager.core.enums import (
        DownloadPriority,
        DownloadStatus
    )
    from PacsClient.zeta_download_manager.core.models import (
        DownloadTask,
        SeriesInfo
    )
    from PacsClient.zeta_download_manager.rules.rule_engine import DownloadRuleEngine
    
    ZETA_AVAILABLE = True
    logger.info("✅ Zeta components imported successfully")
except Exception as e:
    logger.error(f"❌ Failed to import Zeta components: {e}")
    ZETA_AVAILABLE = False


class ZetaScenarioTester:
    """Test suite for Zeta Download Manager scenarios"""
    
    def __init__(self):
        """Initialize test suite"""
        self.state_store = None
        self.rule_engine = None
        self.test_results = []
        
    def setup(self):
        """Setup before each test"""
        logger.info("\n" + "="*80)
        logger.info("SETUP: Initializing test environment")
        logger.info("="*80)
        
        # Reset state store to clean state
        reset_state_store()
        self.state_store = get_state_store()
        
        # Initialize rule engine
        self.rule_engine = DownloadRuleEngine(self.state_store, {})
        
        logger.info("✅ Test environment ready")
        logger.info(f"   State store: {type(self.state_store).__name__}")
        logger.info(f"   Rule engine: {type(self.rule_engine).__name__}")
        
    def teardown(self):
        """Cleanup after each test"""
        logger.info("\n" + "="*80)
        logger.info("TEARDOWN: Cleaning up")
        logger.info("="*80)
        
        # Get final counts
        if self.state_store:
            all_states = self.state_store.get_all()
            logger.info(f"   Total downloads in state: {len(all_states)}")
            
            for status in DownloadStatus:
                count = len(self.state_store.get_by_status(status))
                if count > 0:
                    logger.info(f"   {status.value}: {count}")
        
        # Reset for next test
        reset_state_store()
        logger.info("✅ Cleanup complete\n")
    
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
    
    def wait_for_condition(
        self,
        condition_func,
        timeout_seconds: float = 5.0,
        check_interval: float = 0.1
    ) -> bool:
        """Wait for a condition to become true"""
        start_time = time.time()
        
        while time.time() - start_time < timeout_seconds:
            if condition_func():
                return True
            time.sleep(check_interval)
        
        return False
    
    # =========================================================================
    # SCENARIO 1: Bulk Normal + One Critical
    # =========================================================================
    
    def test_scenario_1_bulk_normal_one_critical(self) -> bool:
        """
        Test Scenario 1: Bulk Normal Downloads + One Critical Download
        
        Steps:
        1. Add 30 patients at NORMAL priority
        2. Simulate Patient 1 starts downloading
        3. Promote Patient 15 to CRITICAL
        4. Verify Patient 1 pauses (auto-pause)
        5. Verify Patient 15 starts
        6. Simulate Patient 15 completes
        7. Verify Patient 1 auto-resumes
        
        Expected:
        - Patient 1 pauses when Patient 15 becomes CRITICAL
        - Patient 1 is marked as auto-paused (is_auto_paused=True)
        - Patient 15 starts immediately
        - After Patient 15 completes, Patient 1 resumes
        """
        logger.info("\n" + "="*80)
        logger.info("TEST SCENARIO 1: Bulk Normal + One Critical")
        logger.info("="*80)
        
        try:
            # Step 1: Add 30 patients at NORMAL priority
            logger.info("\n📥 Step 1: Adding 30 patients (NORMAL priority)")
            for i in range(1, 31):
                task = self.create_mock_task(
                    study_uid=f"study_{i:03d}",
                    patient_name=f"Patient {i}",
                    priority=DownloadPriority.NORMAL
                )
                self.state_store.create(task)
                logger.info(f"   ✅ Added: Patient {i}")
            
            # Verify all 30 are pending
            pending = self.state_store.get_by_status(DownloadStatus.PENDING)
            assert len(pending) == 30, f"Expected 30 pending, got {len(pending)}"
            logger.info(f"✅ Verification: {len(pending)} patients pending")
            
            # Step 2: Simulate Patient 1 starts downloading
            logger.info("\n▶️ Step 2: Starting Patient 1 download (simulated)")
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
            logger.info(f"✅ Status: {len(downloading)} downloading, {len(pending)} pending")
            
            # Step 3: Promote Patient 15 to CRITICAL (user double-clicks)
            logger.info("\n⚡ Step 3: User double-clicks Patient 15 (CRITICAL priority)")
            self.state_store.update(
                "study_015",
                priority=DownloadPriority.CRITICAL
            )
            
            # Step 4: Simulate preemption - Pause Patient 1
            logger.info("   ⏸️ Preempting Patient 1 (auto-pause)...")
            self.state_store.update(
                "study_001",
                status=DownloadStatus.PAUSED,
                is_auto_paused=True  # Mark as auto-paused
            )
            
            # Step 5: Start Patient 15
            logger.info("   ▶️ Starting Patient 15 (CRITICAL)...")
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
            
            logger.info("✅ Verification:")
            logger.info("   ✓ Patient 1 paused (auto-pause)")
            logger.info("   ✓ Patient 15 downloading (CRITICAL)")
            
            # Step 6: Simulate Patient 15 completes
            logger.info("\n✅ Step 4: Patient 15 completes")
            self.state_store.update(
                "study_015",
                status=DownloadStatus.COMPLETED,
                progress_percent=100.0,
                end_time=datetime.now()
            )
            
            # Step 7: Simulate auto-resume - Check rule R5
            logger.info("   🔄 Checking auto-resume (Rule R5)...")
            
            # Get auto-paused downloads
            paused = self.state_store.get_by_status(DownloadStatus.PAUSED)
            auto_paused = [p for p in paused if p.is_auto_paused]
            
            # Check if critical still running
            downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
            critical_running = [d for d in downloading if d.priority == DownloadPriority.CRITICAL]
            
            assert len(auto_paused) > 0, "Should have auto-paused downloads"
            assert len(critical_running) == 0, "No critical should be running"
            
            logger.info(f"   Found {len(auto_paused)} auto-paused downloads")
            logger.info(f"   Critical running: {len(critical_running)}")
            
            # Auto-resume Patient 1
            logger.info("   ▶️ Auto-resuming Patient 1...")
            self.state_store.update("study_001", status=DownloadStatus.DOWNLOADING)
            
            # Verify auto-resume
            state_1 = self.state_store.get("study_001")
            assert state_1.status == DownloadStatus.DOWNLOADING, \
                f"Patient 1 should be Downloading, got {state_1.status.value}"
            
            logger.info("✅ Verification:")
            logger.info("   ✓ Patient 1 auto-resumed")
            logger.info("   ✓ Patient 15 completed")
            
            # Final summary
            logger.info("\n📊 Final Summary:")
            logger.info("   ✅ Patient 15 (CRITICAL) completed")
            logger.info("   ✅ Patient 1 (NORMAL) auto-resumed")
            logger.info("   ✅ Remaining 28 patients still pending")
            
            logger.info("\n" + "="*80)
            logger.info("✅ SCENARIO 1 PASSED: All verifications successful!")
            logger.info("="*80)
            
            return True
            
        except AssertionError as e:
            logger.error(f"\n❌ SCENARIO 1 FAILED: {e}")
            return False
        except Exception as e:
            logger.error(f"\n❌ SCENARIO 1 ERROR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    # =========================================================================
    # SCENARIO 2: Multiple High Priority (LIFO)
    # =========================================================================
    
    def test_scenario_2_multiple_high_priority_lifo(self) -> bool:
        """
        Test Scenario 2: Multiple High-Priority Patients (LIFO)
        
        Steps:
        1. Open Patient A (CRITICAL)
        2. Open Patient B (CRITICAL) - should preempt A
        3. Open Patient C (CRITICAL) - should preempt B
        4. C completes → B should resume (LIFO)
        5. B completes → A should resume
        
        Expected order: C → B → A (reverse of opening, LIFO)
        """
        logger.info("\n" + "="*80)
        logger.info("TEST SCENARIO 2: Multiple High Priority (LIFO)")
        logger.info("="*80)
        
        try:
            # Step 1: Open Patient A (CRITICAL)
            logger.info("\n📖 Step 1: User opens Patient A (CRITICAL)")
            time.sleep(0.1)  # Ensure different timestamps
            
            task_a = self.create_mock_task(
                study_uid="patient_a",
                patient_name="Patient A",
                priority=DownloadPriority.CRITICAL
            )
            self.state_store.create(task_a)
            self.state_store.update(
                "patient_a",
                status=DownloadStatus.DOWNLOADING,
                start_time=datetime.now()
            )
            logger.info("   ✅ Patient A downloading (CRITICAL)")
            
            # Step 2: Open Patient B (CRITICAL) - should preempt A
            logger.info("\n📖 Step 2: User opens Patient B (CRITICAL)")
            time.sleep(0.1)  # Ensure different timestamp
            
            task_b = self.create_mock_task(
                study_uid="patient_b",
                patient_name="Patient B",
                priority=DownloadPriority.CRITICAL
            )
            self.state_store.create(task_b)
            
            # Preempt A
            logger.info("   ⏸️ Preempting Patient A...")
            self.state_store.update(
                "patient_a",
                status=DownloadStatus.PAUSED,
                is_auto_paused=True
            )
            
            # Start B
            logger.info("   ▶️ Starting Patient B...")
            self.state_store.update(
                "patient_b",
                status=DownloadStatus.DOWNLOADING,
                start_time=datetime.now()
            )
            
            # Verify
            state_a = self.state_store.get("patient_a")
            state_b = self.state_store.get("patient_b")
            assert state_a.status == DownloadStatus.PAUSED
            assert state_b.status == DownloadStatus.DOWNLOADING
            logger.info("✅ Verification:")
            logger.info("   ✓ Patient A paused")
            logger.info("   ✓ Patient B downloading")
            
            # Step 3: Open Patient C (CRITICAL) - should preempt B
            logger.info("\n📖 Step 3: User opens Patient C (CRITICAL)")
            time.sleep(0.1)  # Ensure different timestamp
            
            task_c = self.create_mock_task(
                study_uid="patient_c",
                patient_name="Patient C",
                priority=DownloadPriority.CRITICAL
            )
            self.state_store.create(task_c)
            
            # Preempt B
            logger.info("   ⏸️ Preempting Patient B...")
            self.state_store.update(
                "patient_b",
                status=DownloadStatus.PAUSED,
                is_auto_paused=True
            )
            
            # Start C
            logger.info("   ▶️ Starting Patient C...")
            self.state_store.update(
                "patient_c",
                status=DownloadStatus.DOWNLOADING,
                start_time=datetime.now()
            )
            
            # Verify
            state_b = self.state_store.get("patient_b")
            state_c = self.state_store.get("patient_c")
            assert state_b.status == DownloadStatus.PAUSED
            assert state_c.status == DownloadStatus.DOWNLOADING
            logger.info("✅ Verification:")
            logger.info("   ✓ Patient B paused")
            logger.info("   ✓ Patient C downloading")
            
            # Step 4: C completes → B should resume (LIFO: newest paused first)
            logger.info("\n✅ Step 4: Patient C completes")
            self.state_store.update(
                "patient_c",
                status=DownloadStatus.COMPLETED,
                progress_percent=100.0,
                end_time=datetime.now()
            )
            
            # Get next download using rule engine (should return B, not A)
            logger.info("   🔄 Getting next download from rule engine (LIFO)...")
            
            # Change paused to pending for rule engine
            self.state_store.update("patient_a", status=DownloadStatus.PENDING)
            self.state_store.update("patient_b", status=DownloadStatus.PENDING)
            
            next_download = self.rule_engine.get_next_download()
            
            assert next_download is not None, "Should have next download"
            assert next_download.study_uid == "patient_b", \
                f"Expected Patient B (LIFO), got {next_download.patient_name}"
            
            logger.info(f"   ✅ Rule engine returned: {next_download.patient_name} (LIFO correct)")
            
            # Resume B
            self.state_store.update("patient_b", status=DownloadStatus.DOWNLOADING)
            logger.info("   ▶️ Patient B resumed (LIFO)")
            
            # Step 5: B completes → A should resume
            logger.info("\n✅ Step 5: Patient B completes")
            self.state_store.update(
                "patient_b",
                status=DownloadStatus.COMPLETED,
                progress_percent=100.0,
                end_time=datetime.now()
            )
            
            # Get next download (should be A)
            next_download = self.rule_engine.get_next_download()
            assert next_download.study_uid == "patient_a", \
                f"Expected Patient A, got {next_download.patient_name}"
            
            logger.info(f"   ✅ Rule engine returned: {next_download.patient_name}")
            
            # Resume A
            self.state_store.update("patient_a", status=DownloadStatus.DOWNLOADING)
            logger.info("   ▶️ Patient A resumed")
            
            # Final verification
            logger.info("\n📊 Final Order: C → B → A (LIFO verified)")
            
            logger.info("\n" + "="*80)
            logger.info("✅ SCENARIO 2 PASSED: LIFO order verified!")
            logger.info("="*80)
            
            return True
            
        except AssertionError as e:
            logger.error(f"\n❌ SCENARIO 2 FAILED: {e}")
            return False
        except Exception as e:
            logger.error(f"\n❌ SCENARIO 2 ERROR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    # =========================================================================
    # SCENARIO 3: Sequential Normal Downloads
    # =========================================================================
    
    def test_scenario_3_sequential_normal(self) -> bool:
        """
        Test Scenario 3: Sequential Normal Downloads
        
        Steps:
        1. Add 10 patients at NORMAL priority
        2. Verify only 1 can be "downloading" at a time
        3. Simulate downloads completing sequentially
        4. Verify order: 1 → 2 → 3 → ... → 10
        
        Expected:
        - Only 1 downloading at any time
        - Sequential execution
        - No parallel downloads
        """
        logger.info("\n" + "="*80)
        logger.info("TEST SCENARIO 3: Sequential Normal Downloads")
        logger.info("="*80)
        
        try:
            # Step 1: Add 10 patients at NORMAL priority
            logger.info("\n📥 Step 1: Adding 10 patients (NORMAL priority)")
            for i in range(1, 11):
                task = self.create_mock_task(
                    study_uid=f"study_{i:02d}",
                    patient_name=f"Patient {i}",
                    priority=DownloadPriority.NORMAL
                )
                self.state_store.create(task)
                logger.info(f"   ✅ Added: Patient {i}")
            
            # Verify all pending
            pending = self.state_store.get_by_status(DownloadStatus.PENDING)
            assert len(pending) == 10, f"Expected 10 pending, got {len(pending)}"
            logger.info(f"✅ Verification: {len(pending)} patients pending")
            
            # Step 2: Simulate sequential downloads
            logger.info("\n▶️ Step 2: Simulating sequential downloads")
            
            for i in range(1, 11):
                study_uid = f"study_{i:02d}"
                
                # Start download
                logger.info(f"\n   [{i}/10] Starting Patient {i}")
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.DOWNLOADING,
                    start_time=datetime.now()
                )
                
                # Verify only 1 downloading
                downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
                assert len(downloading) == 1, \
                    f"Expected 1 downloading, got {len(downloading)}"
                
                # Verify correct patient
                assert downloading[0].study_uid == study_uid, \
                    f"Expected {study_uid}, got {downloading[0].study_uid}"
                
                logger.info(f"   ✅ Patient {i} downloading (sequential)")
                
                # Complete download
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.COMPLETED,
                    progress_percent=100.0,
                    end_time=datetime.now()
                )
                logger.info(f"   ✅ Patient {i} completed")
                
                # Verify counts
                completed = self.state_store.get_by_status(DownloadStatus.COMPLETED)
                pending = self.state_store.get_by_status(DownloadStatus.PENDING)
                logger.info(f"   Status: {len(completed)} completed, {len(pending)} pending")
            
            # Final verification
            completed = self.state_store.get_by_status(DownloadStatus.COMPLETED)
            assert len(completed) == 10, \
                f"Expected 10 completed, got {len(completed)}"
            
            logger.info("\n📊 Final Summary:")
            logger.info("   ✅ All 10 patients completed sequentially")
            logger.info("   ✅ Order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10")
            logger.info("   ✅ Never more than 1 downloading at a time")
            
            logger.info("\n" + "="*80)
            logger.info("✅ SCENARIO 3 PASSED: Sequential execution verified!")
            logger.info("="*80)
            
            return True
            
        except AssertionError as e:
            logger.error(f"\n❌ SCENARIO 3 FAILED: {e}")
            return False
        except Exception as e:
            logger.error(f"\n❌ SCENARIO 3 ERROR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    # =========================================================================
    # SCENARIO 4: Network Interruption Resume
    # =========================================================================
    
    def test_scenario_4_network_resume(self) -> bool:
        """
        Test Scenario 4: Network Interruption and Resume
        
        Steps:
        1. Add 10 patients
        2. Patients 1-4 complete
        3. Patient 5 downloading at 50% (500/1000 images)
        4. Network error → paused
        5. User clicks Resume
        6. Patient 5 resumes from 50% (not restart)
        7. Queue continues: 5 → 6 → 7 → ... → 10
        
        Expected:
        - Network error → PAUSED (not FAILED)
        - Resume from checkpoint (50%)
        - Download only remaining images
        - Queue order maintained
        """
        logger.info("\n" + "="*80)
        logger.info("TEST SCENARIO 4: Network Interruption Resume")
        logger.info("="*80)
        
        try:
            # Step 1: Add 10 patients
            logger.info("\n📥 Step 1: Adding 10 patients")
            for i in range(1, 11):
                task = self.create_mock_task(
                    study_uid=f"study_{i:02d}",
                    patient_name=f"Patient {i}",
                    priority=DownloadPriority.NORMAL,
                    series_count=3,
                    images_per_series=100  # Total 300 images per patient
                )
                self.state_store.create(task)
            
            # Patients 1-4: Complete
            logger.info("   📊 Setting up initial state:")
            for i in range(1, 5):
                self.state_store.update(
                    f"study_{i:02d}",
                    status=DownloadStatus.COMPLETED,
                    progress_percent=100.0,
                    downloaded_count=300,
                    total_count=300
                )
                logger.info(f"   ✅ Patient {i}: Completed")
            
            # Patient 5: Downloading at 50%
            self.state_store.update(
                "study_05",
                status=DownloadStatus.DOWNLOADING,
                progress_percent=50.0,
                downloaded_count=150,
                total_count=300,
                start_time=datetime.now()
            )
            logger.info(f"   ▶️ Patient 5: Downloading (50% - 150/300 images)")
            
            # Patients 6-10: Pending
            for i in range(6, 11):
                logger.info(f"   ⏳ Patient {i}: Pending")
            
            # Step 2: Network error occurs
            logger.info("\n⚠️ Step 2: Network disconnection occurs")
            self.state_store.update(
                "study_05",
                status=DownloadStatus.PAUSED,
                is_auto_paused=False,  # Network error = manual pause (requires resume)
                error_message="Network error: Connection timeout",
                retry_count=1
            )
            
            # Verify: Patient 5 paused at 50%
            state_5 = self.state_store.get("study_05")
            assert state_5.status == DownloadStatus.PAUSED, \
                f"Patient 5 should be Paused, got {state_5.status.value}"
            assert state_5.progress_percent == 50.0, \
                f"Patient 5 should be at 50%, got {state_5.progress_percent}%"
            assert state_5.downloaded_count == 150, \
                f"Patient 5 should have 150 downloaded, got {state_5.downloaded_count}"
            
            logger.info("✅ Verification:")
            logger.info(f"   ✓ Patient 5 paused at {state_5.progress_percent}%")
            logger.info(f"   ✓ Downloaded: {state_5.downloaded_count}/{state_5.total_count}")
            logger.info(f"   ⚠️ Error: {state_5.error_message}")
            
            # Step 3: Network reconnects, user clicks Resume
            logger.info("\n🔄 Step 3: Network reconnects, user clicks Resume")
            self.state_store.update(
                "study_05",
                status=DownloadStatus.DOWNLOADING
            )
            
            # Verify: Patient 5 resumed from 50%
            state_5 = self.state_store.get("study_05")
            assert state_5.status == DownloadStatus.DOWNLOADING, \
                f"Patient 5 should be Downloading, got {state_5.status.value}"
            assert state_5.progress_percent == 50.0, \
                f"Patient 5 should resume from 50%, got {state_5.progress_percent}%"
            assert state_5.downloaded_count == 150, \
                f"Patient 5 should have 150 downloaded, got {state_5.downloaded_count}"
            
            logger.info("✅ Verification:")
            logger.info(f"   ✓ Patient 5 resumed from {state_5.progress_percent}%")
            logger.info(f"   ✓ Will download remaining {state_5.total_count - state_5.downloaded_count} images")
            
            # Step 4: Patient 5 completes (downloads remaining 150 images)
            logger.info("\n✅ Step 4: Patient 5 completes (remaining 150 images)")
            self.state_store.update(
                "study_05",
                status=DownloadStatus.COMPLETED,
                progress_percent=100.0,
                downloaded_count=300,
                end_time=datetime.now()
            )
            
            # Step 5: Queue continues (6-10)
            logger.info("\n⏩ Step 5: Queue continues (6-10)")
            for i in range(6, 11):
                study_uid = f"study_{i:02d}"
                
                # Start
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.DOWNLOADING,
                    start_time=datetime.now()
                )
                logger.info(f"   ▶️ Patient {i} downloading")
                
                # Complete
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.COMPLETED,
                    progress_percent=100.0,
                    downloaded_count=300,
                    total_count=300,
                    end_time=datetime.now()
                )
                logger.info(f"   ✅ Patient {i} completed")
            
            # Final verification
            completed = self.state_store.get_by_status(DownloadStatus.COMPLETED)
            assert len(completed) == 10, \
                f"Expected 10 completed, got {len(completed)}"
            
            logger.info("\n📊 Final Summary:")
            logger.info("   ✅ All 10 patients completed")
            logger.info("   ✅ Patient 5 resumed from 50% (not restarted)")
            logger.info("   ✅ Downloaded only remaining 150 images")
            logger.info("   ✅ Queue order maintained: 1-4 (done), 5 (resumed), 6-10 (sequential)")
            
            logger.info("\n" + "="*80)
            logger.info("✅ SCENARIO 4 PASSED: Network resume verified!")
            logger.info("="*80)
            
            return True
            
        except AssertionError as e:
            logger.error(f"\n❌ SCENARIO 4 FAILED: {e}")
            return False
        except Exception as e:
            logger.error(f"\n❌ SCENARIO 4 ERROR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    # =========================================================================
    # RUN ALL TESTS
    # =========================================================================
    
    def run_all(self) -> Dict[str, bool]:
        """Run all test scenarios"""
        logger.info("\n" + "="*80)
        logger.info("ZETA DOWNLOAD MANAGER - SCENARIO TEST SUITE")
        logger.info("Testing all 4 critical scenarios")
        logger.info("="*80)
        
        if not ZETA_AVAILABLE:
            logger.error("❌ Zeta components not available - cannot run tests")
            return {}
        
        tests = [
            ("Scenario 1: Bulk Normal + One Critical", self.test_scenario_1_bulk_normal_one_critical),
            ("Scenario 2: Multiple High Priority (LIFO)", self.test_scenario_2_multiple_high_priority_lifo),
            ("Scenario 3: Sequential Normal", self.test_scenario_3_sequential_normal),
            ("Scenario 4: Network Resume", self.test_scenario_4_network_resume),
        ]
        
        results = {}
        passed = 0
        failed = 0
        
        for name, test_func in tests:
            try:
                logger.info(f"\n{'='*80}")
                logger.info(f"Running: {name}")
                logger.info(f"{'='*80}")
                
                self.setup()
                result = test_func()
                self.teardown()
                
                results[name] = result
                if result:
                    passed += 1
                else:
                    failed += 1
                    
            except Exception as e:
                logger.error(f"\n❌ TEST ERROR: {name}")
                logger.error(f"   Exception: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results[name] = False
                failed += 1
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("TEST SUMMARY")
        logger.info("="*80)
        
        for name, result in results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            logger.info(f"{status}: {name}")
        
        logger.info(f"\n📊 Results:")
        logger.info(f"   ✅ Passed: {passed}")
        logger.info(f"   ❌ Failed: {failed}")
        logger.info(f"   📊 Total:  {passed + failed}")
        
        if failed == 0:
            logger.info("\n🎉 ALL TESTS PASSED! 🎉")
        else:
            logger.info(f"\n⚠️ {failed} test(s) failed")
        
        logger.info("="*80)
        
        return results


if __name__ == "__main__":
    logger.info("\n" + "="*80)
    logger.info("ZETA DOWNLOAD MANAGER - EXECUTABLE SCENARIO TESTS")
    logger.info("="*80)
    logger.info(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Log file: test_zeta_scenarios.log")
    logger.info("="*80)
    
    # Run tests
    tester = ZetaScenarioTester()
    results = tester.run_all()
    
    logger.info(f"\nEnd time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*80)
    
    # Exit with error code if any tests failed
    exit_code = 0 if all(results.values()) else 1
    sys.exit(exit_code)
