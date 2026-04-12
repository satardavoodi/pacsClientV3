"""Reception data: load, receive, error, apply"""
# Auto-generated from main_widget.py — Phase 2 split



import logging

logger = logging.getLogger(__name__)

class _DMReceptionMixin:
    """Reception data: load, receive, error, apply"""

    def _load_reception_data(self, patient_id: str, study_uid: str = None) -> None:
        """Load reception data for the selected patient - always fetch fresh data from server."""
        if not patient_id:
            logger.info("📋 [RECEPTION] No patient ID provided, skipping reception data load")
            return
        # Skip duplicate in-flight requests for the same patient
        if patient_id in self._pending_reception_requests:
            logger.info(f"📋 [RECEPTION] Request already pending for patient {patient_id}, skipping")
            return

        logger.info("=" * 120)
        logger.info(f"📋 [RECEPTION_REQUEST] 🔄 Loading reception data for patient")
        logger.info(f"   🆔 Patient ID: {patient_id}")
        logger.info(f"   📄 Study UID: {study_uid[:60] if study_uid else 'None'}...")
        logger.info(f"   🖱️ Triggered by: Patient click in Download Manager")
        logger.info(f"   📡 Action: Fetching FRESH data from server")
        logger.info("=" * 120)
        
        # FIX: Store request in dictionary (allows tracking multiple concurrent requests)
        self._pending_reception_requests[patient_id] = study_uid
        logger.info(f"   📝 Registered pending request: patient_id={patient_id} → study_uid={study_uid[:40] if study_uid else 'None'}...")

        # IMPORTANT: Always fetch fresh data from server when a patient is clicked
        # Even if we have cached data, fetch fresh to ensure up-to-date information
        logger.info(f"   🚀 Sending request to ReceptionDataService for patient_id: {patient_id}")
        self._reception_service.fetch_patient_data(patient_id)
        logger.info(f"   ✅ Request sent, waiting for response...")

    def _on_reception_data_received(self, data: dict) -> None:
        """Handle reception data response - apply only if it's for currently selected patient."""
        # FIX: Extract patient_id from response data (not from pending variables)
        # This allows handling multiple concurrent reception data responses
        patient_data = None
        if isinstance(data, dict):
            if "data" in data:
                patient_data = data.get("data")
                logger.info(f"   📦 Extracted 'data' field from response")
            else:
                patient_data = data
                logger.info(f"   📦 Using full response as patient data")
        if isinstance(patient_data, list):
            patient_data = patient_data[0] if patient_data else None
            logger.info(f"   📦 Response was list, taking first element")

        if not isinstance(patient_data, dict):
            logger.warning(f"   ❌ Invalid patient data format received")
            return
        
        # Extract patient_id from response (receptionId field)
        patient_id = str(patient_data.get("receptionId", ""))
        
        # Look up the study_uid that requested this data
        study_uid = self._pending_reception_requests.get(patient_id)
        
        if not patient_id:
            logger.info("📋 [RECEPTION] No patient ID in response, ignoring reception data")
            return

        logger.info("=" * 120)
        logger.info(f"📋 [RECEPTION_RESPONSE] ✅ Reception data received from server")
        logger.info(f"   🆔 Patient ID: {patient_id}")
        logger.info(f"   📄 Study UID: {study_uid[:60] if study_uid else 'Not found in pending requests'}...")
        logger.info(f"   📊 Response contains: {list(data.keys()) if isinstance(data, dict) else 'Invalid format'}")
        logger.info("=" * 120)

        logger.info(f"   💾 Caching fresh reception data for patient: {patient_id}")
        
        # CRITICAL FIX: Implement LRU eviction for reception cache to prevent unbounded memory growth
        # in high-frequency loops (1000+ cycles = potentially 1000+ patient entries)
        max_cache_size = 50  # Keep last 50 patients only
        if len(self._reception_cache) >= max_cache_size:
            # Remove oldest entry (FIFO since we're using dict which maintains insertion order in Python 3.7+)
            oldest_patient_id = next(iter(self._reception_cache))
            del self._reception_cache[oldest_patient_id]
            logger.debug(f"🗑️ Evicted oldest reception cache entry for patient: {oldest_patient_id}")
        
        self._reception_cache[patient_id] = patient_data
        self._last_reception_patient_id = patient_id
        
        # Apply the data ONLY if it's for currently selected study
        # This is critical: we should only update the UI if this data is for the patient being displayed
        if self._selected_study_uid:
            should_apply = False
            
            # Check if this data is for the currently selected study
            if study_uid and study_uid == self._selected_study_uid:
                logger.info(f"   ✅ Data IS for currently selected study: {study_uid[:60]}...")
                should_apply = True
            else:
                # Check if current selection has matching patient_id
                current_task = self._tasks.get(self._selected_study_uid)
                current_state = self.state_store.get(self._selected_study_uid)
                current_patient_id = None
                
                if current_task and current_task.patient_id:
                    current_patient_id = current_task.patient_id
                elif current_state:
                    current_patient_id = getattr(current_state, 'patient_id', None)
                
                # Also try database for current selection
                if not current_patient_id:
                    try:
                        study_info = self.database_manager.get_study_info(self._selected_study_uid)
                        if study_info and 'patient_id' in study_info:
                            current_patient_id = study_info['patient_id']
                    except:
                        pass
                
                if current_patient_id == patient_id:
                    logger.info(f"   ✅ Current selection has matching patient_id: {patient_id}")
                    should_apply = True
            if should_apply:
                logger.info(f"   🎨 Applying reception data to UI for patient {patient_id}")
                self._apply_reception_data(patient_data)
            else:
                logger.info(f"   ⏭️ Data cached but not for current selection")
        else:
            logger.info(f"📋 [RECEPTION] ℹ️ No patient currently selected, data cached for {patient_id}")
        
        # FIX: Remove patient_id from pending requests dictionary
        if patient_id in self._pending_reception_requests:
            del self._pending_reception_requests[patient_id]
            logger.info(f"   🧹 Removed patient {patient_id} from pending requests (remaining: {len(self._pending_reception_requests)})")

    def _on_reception_data_error(self, error_message: str) -> None:
        """Handle reception data error (non-fatal)."""
        logger.warning("=" * 100)
        logger.warning(f"❌ [RECEPTION] Reception data fetch failed: {error_message}")
        logger.warning("=" * 100)
        try:
            if hasattr(self, 'patient_identifier_label') and self.patient_identifier_label:
                self.patient_identifier_label.setText("Identifier: Unavailable")
                logger.info(f"⚠️ [RECEPTION] Set identifier to Unavailable")
            if hasattr(self, 'requesting_physician_label') and self.requesting_physician_label:
                self.requesting_physician_label.setText("Requesting Physician: Unavailable")
                logger.info(f"⚠️ [RECEPTION] Set physician to Unavailable")
            if hasattr(self, 'reception_status_label') and self.reception_status_label:
                self.reception_status_label.setText("Reception Status: Unavailable")
                logger.info(f"⚠️ [RECEPTION] Set status to Unavailable")
        except Exception as e:
            logger.error(f"❌ [RECEPTION] Error updating reception labels: {e}")
        
        # Clear pending references
        self._pending_reception_patient_id = None
        self._pending_reception_study_uid = None
        logger.info("📋 [RECEPTION] Reception data fields reset to unavailable")

    def _apply_reception_data(self, patient_data: dict) -> None:
        """Apply reception data to details panel fields."""
        logger.info("=" * 100)
        logger.info(f"🎨 [RECEPTION] Applying reception data to details panel")
        logger.info("=" * 100)

        if not self._selected_study_uid:
            logger.info("⚠️ [RECEPTION] No selected study, skipping reception data application")
            return

        task = self._tasks.get(self._selected_study_uid)
        if not task:
            logger.info(f"⚠️ [RECEPTION] No task for selected study {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}..., skipping")
            return

        logger.info(f"📋 [RECEPTION] Processing reception data for study: {self._selected_study_uid[:60]}...")

        patient_info = patient_data.get("patient", {}) if isinstance(patient_data, dict) else {}

        # Extract comprehensive patient information
        logger.info(f"📋 [RECEPTION] Extracting patient information from server response")
        
        patient_name_raw = (
            patient_info.get("Name")
            or patient_info.get("FullName")
            or patient_info.get("PatientName")
            or task.patient_name
            or "Unknown"
        )

        # Process patient name to extract first and last names
        if patient_name_raw and patient_name_raw != "Unknown":
            if '^' in patient_name_raw:
                # DICOM format: LAST^FIRST^MIDDLE
                parts = patient_name_raw.split('^')
                last_name = parts[0] if len(parts) > 0 else 'Unknown'
                first_name = parts[1] if len(parts) > 1 else 'Unknown'
                middle_name = parts[2] if len(parts) > 2 else ''
                full_display_name = f"{first_name} {middle_name} {last_name}".strip()
            else:
                full_display_name = patient_name_raw
        else:
            full_display_name = "Unknown"

        patient_identifier = (
            patient_info.get("NationalID")
            or patient_info.get("PatientID")
            or patient_info.get("patient_id")
            or patient_info.get("patientId")
            or task.patient_id  # Use task's patient_id as fallback
            or "-"
        )

        physician = patient_data.get("referrerPhysician", {}) if isinstance(patient_data, dict) else {}
        physician_name = (
            physician.get("FullName")
            or physician.get("Name")
            or physician.get("full_name")
            or "-"
        )

        reception_status = (
            patient_data.get("workflowStatus")
            or patient_data.get("status")
            or patient_data.get("workflow_status")
            or "-"
        )

        # Extract additional patient information
        patient_age = patient_info.get("Age", "-")
        patient_gender = patient_info.get("Gender", "-")
        patient_birth_date = patient_info.get("BD", "-")  # Birth date
        patient_tel = patient_info.get("Tel", "-")

        logger.info(f"✅ [RECEPTION] Extracted data from server:")
        logger.info(f"✅ [RECEPTION]   Full Name: {full_display_name}")
        logger.info(f"✅ [RECEPTION]   Identifier: {patient_identifier}")
        logger.info(f"✅ [RECEPTION]   Physician: {physician_name}")
        logger.info(f"✅ [RECEPTION]   Status: {reception_status}")
        logger.info(f"✅ [RECEPTION]   Age: {patient_age}, Gender: {patient_gender}")

        # Update all patient information fields - with widget existence checks
        logger.info(f"📋 [RECEPTION] Updating UI widgets with reception data")
        
        if hasattr(self, 'patient_name_label') and self.patient_name_label:
            self.patient_name_label.setText(f"Name: {full_display_name}")
            logger.info(f"✅ [RECEPTION] Updated patient_name_label: {full_display_name}")
        
        if hasattr(self, 'patient_identifier_label') and self.patient_identifier_label:
            self.patient_identifier_label.setText(f"Identifier: {patient_identifier}")
            logger.info(f"✅ [RECEPTION] Updated patient_identifier_label: {patient_identifier}")
        
        if hasattr(self, 'requesting_physician_label') and self.requesting_physician_label:
            self.requesting_physician_label.setText(f"Requesting Physician: {physician_name}")
            logger.info(f"✅ [RECEPTION] Updated requesting_physician_label: {physician_name}")
        
        if hasattr(self, 'reception_status_label') and self.reception_status_label:
            self.reception_status_label.setText(f"Reception Status: {reception_status}")
            logger.info(f"✅ [RECEPTION] Updated reception_status_label: {reception_status}")

        # Update additional fields if they exist
        if hasattr(self, 'age_label') and self.age_label:
            self.age_label.setText(f"Age: {patient_age}")
            logger.info(f"✅ [RECEPTION] Updated age_label: {patient_age}")
        
        if hasattr(self, 'gender_label') and self.gender_label:
            self.gender_label.setText(f"Gender: {patient_gender}")
            logger.info(f"✅ [RECEPTION] Updated gender_label: {patient_gender}")
        
        if hasattr(self, 'birth_date_label') and self.birth_date_label:
            self.birth_date_label.setText(f"Birth Date: {patient_birth_date}")
            logger.info(f"✅ [RECEPTION] Updated birth_date_label: {patient_birth_date}")
        
        if hasattr(self, 'tel_label') and self.tel_label:
            self.tel_label.setText(f"Time: {patient_tel}")  # Changed from Phone to Time
            logger.info(f"✅ [RECEPTION] Updated tel_label: {patient_tel}")
        
        if hasattr(self, 'body_part_label') and self.body_part_label:
            # Try to get body part from the patient data or task
            body_part = patient_info.get("BodyPart", patient_info.get("body_part", "-"))
            if body_part == "-":
                # Get from task if available
                if task:
                    if hasattr(self, '_additional_task_info') and self._additional_task_info and task.study_uid in self._additional_task_info:
                        body_part = self._additional_task_info[task.study_uid].get('body_part', '-')
                    elif hasattr(task, 'body_part'):
                        body_part = getattr(task, 'body_part', '-')
            self.body_part_label.setText(f"Body Part: {body_part}")
            logger.info(f"📋 [RECEPTION] ✅ Updated body_part_label: {body_part}")

        # Update modality if available in reception data
        if hasattr(self, 'modality_label') and self.modality_label:
            # Try to get modality from the patient data or task
            modality = patient_info.get("Modality", patient_info.get("modality", "-"))
            if modality == "-":
                # Get from task if available
                if task:
                    if hasattr(self, '_additional_task_info') and self._additional_task_info and task.study_uid in self._additional_task_info:
                        modality = self._additional_task_info[task.study_uid].get('modality', '-')
                    elif hasattr(task, 'modality'):
                        modality = getattr(task, 'modality', '-')
            self.modality_label.setText(f"Modality: {modality}")
            logger.info(f"📋 [RECEPTION] ✅ Updated modality_label: {modality}")

        logger.info(f"📋 [RECEPTION] ✅ Reception data applied successfully to details panel")
