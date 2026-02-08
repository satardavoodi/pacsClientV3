"""
QUICK REFERENCE: Unified Viewer Controller Usage

This guide shows how to properly update viewers to prevent flickering.
"""

# ══════════════════════════════════════════════════════════════════════════════
# ✅ CORRECT USAGE PATTERNS
# ══════════════════════════════════════════════════════════════════════════════

# Pattern 1: Initialize viewers with loading state
# ─────────────────────────────────────────────────
# Use this when creating the viewer layout
self.viewer_controller.initialize_viewers_with_loading_state(layout=(1, 2))
# Result: 2 viewers showing "Loading medical images..."


# Pattern 2: Display first series when ready
# ─────────────────────────────────────────────────
# Use this when a series finishes downloading/loading
self.viewer_controller.display_first_series_when_ready(series_number="1")
# Result: Series "1" displayed in ALL viewers


# Pattern 3: Display specific series in specific viewers
# ─────────────────────────────────────────────────
# Use this when user clicks a thumbnail to switch series
self.viewer_controller.display_series_in_viewers(
    series_number="2",
    viewer_indices=[0],  # Only update viewer 0
    force_update=False   # Skip if already displayed
)


# Pattern 4: Check if series is already displayed
# ─────────────────────────────────────────────────
# Prevents redundant updates
if not self.viewer_controller.is_series_already_displayed("1", viewer_index=0):
    self.viewer_controller.display_series_in_viewers("1", viewer_indices=[0])


# Pattern 5: Check if viewers are ready
# ─────────────────────────────────────────────────
if self.viewer_controller.are_viewers_initialized():
    self.viewer_controller.display_series_in_viewers("1")
else:
    # Viewers will be created later, series will be displayed automatically
    pass


# ══════════════════════════════════════════════════════════════════════════════
# ❌ FORBIDDEN PATTERNS (Cause Flickering)
# ══════════════════════════════════════════════════════════════════════════════

# DON'T: Direct viewer update
vtk_widget.start_process_series(data, metadata)  # ❌ FORBIDDEN

# DON'T: Direct display calls
self._display_first_series_in_viewer()  # ❌ FORBIDDEN

# DON'T: Loop through viewers directly
for viewer in self.lst_nodes_viewer:
    viewer.vtk_widget.start_process_series(...)  # ❌ FORBIDDEN


# ══════════════════════════════════════════════════════════════════════════════
# 🔄 MIGRATION GUIDE
# ══════════════════════════════════════════════════════════════════════════════

# Old Code (Flickering):
# ─────────────────────────
def load_series_old():
    # Load data
    vtk_data, metadata = load_series_data(series_number)
    
    # Direct update (BAD)
    vtk_widget.start_process_series(vtk_data, metadata)

# New Code (Flicker-Free):
# ─────────────────────────
def load_series_new():
    # Load data (same as before)
    success = self._load_single_series_on_demand(series_number)
    
    # Delegate to controller (GOOD)
    if success:
        self.viewer_controller.display_first_series_when_ready(str(series_number))


# ══════════════════════════════════════════════════════════════════════════════
# 🎯 COMMON SCENARIOS
# ══════════════════════════════════════════════════════════════════════════════

# Scenario A: Patient opens with existing data
# ─────────────────────────────────────────────────
def open_patient_with_data():
    # 1. Load series data into lst_thumbnails_data
    self._load_single_series_on_demand(1)
    
    # 2. Create viewers in loading state
    self.viewer_controller.initialize_viewers_with_loading_state((1, 2))
    
    # 3. Display first series
    self.viewer_controller.display_first_series_when_ready("1")


# Scenario B: Patient opens, series downloading progressively
# ─────────────────────────────────────────────────
def open_patient_progressive():
    # 1. Create viewers immediately (before data arrives)
    self.viewer_controller.initialize_viewers_with_loading_state((1, 2))
    # Viewers show: "Loading medical images..."
    
    # 2. When first series downloads (called by download manager)
    def on_series_downloaded(series_number):
        # Load the data
        success = self._load_single_series_on_demand(int(series_number))
        
        # Display when ready
        if success:
            self.viewer_controller.display_first_series_when_ready(series_number)


# Scenario C: User clicks thumbnail to switch series
# ─────────────────────────────────────────────────
def on_thumbnail_clicked(series_number):
    # Get currently selected viewer index
    selected_viewer_idx = self.get_selected_viewer_index()
    
    # Update only the selected viewer
    self.viewer_controller.display_series_in_viewers(
        series_number=series_number,
        viewer_indices=[selected_viewer_idx]
    )


# Scenario D: Display same series in all viewers
# ─────────────────────────────────────────────────
def show_series_in_all_viewers(series_number):
    # Don't specify viewer_indices - updates all viewers
    self.viewer_controller.display_series_in_viewers(series_number)


# ══════════════════════════════════════════════════════════════════════════════
# 🐛 DEBUGGING TIPS
# ══════════════════════════════════════════════════════════════════════════════

# Enable controller logging:
import logging
logging.getLogger("PacsClient.pacs.patient_tab.ui.patient_ui.viewer_state_controller").setLevel(logging.DEBUG)

# Check current viewer state:
print(f"Viewer 0 shows: {self.viewer_controller.get_current_series_in_viewer(0)}")
print(f"Viewers initialized: {self.viewer_controller.are_viewers_initialized()}")

# Check if update is needed:
already_shown = self.viewer_controller.is_series_already_displayed("1", viewer_index=0)
print(f"Series '1' already in viewer 0: {already_shown}")


# ══════════════════════════════════════════════════════════════════════════════
# 📋 CHECKLIST FOR NEW CODE
# ══════════════════════════════════════════════════════════════════════════════

"""
Before writing code that updates viewers, ask:

1. □ Am I calling vtk_widget.start_process_series() directly?
   → If YES, change to use viewer_controller instead

2. □ Am I in a loop updating multiple viewers?
   → If YES, collect indices and make ONE controller call

3. □ Am I checking if the series is already displayed?
   → If NO, add is_series_already_displayed() check

4. □ Am I creating viewers?
   → If YES, use initialize_viewers_with_loading_state()

5. □ Does my function have "load" or "display" in the name?
   → If YES, ensure it routes through the controller

6. □ Am I handling progressive downloads?
   → If YES, use display_first_series_when_ready()
"""

# ══════════════════════════════════════════════════════════════════════════════
# 🎓 BEST PRACTICES
# ══════════════════════════════════════════════════════════════════════════════

# 1. Separation of Concerns
# ─────────────────────────
# Load data ≠ Display data
# Always split into two steps:

# Step 1: Load/prepare data
success = self._load_single_series_on_demand(series_number)

# Step 2: Display via controller
if success:
    self.viewer_controller.display_first_series_when_ready(series_number)


# 2. State Before Action
# ─────────────────────────
# Always check state before acting:

if self.viewer_controller.are_viewers_initialized():
    # Viewers exist, can display immediately
    self.viewer_controller.display_series_in_viewers(series_number)
else:
    # Viewers don't exist yet, controller will display when ready
    # (pending series mechanism handles this automatically)
    pass


# 3. Minimal Updates
# ─────────────────────────
# Only update what changed:

# BAD: Update all viewers even if only one changed
for i in range(len(self.lst_nodes_viewer)):
    self.viewer_controller.display_series_in_viewers(series_number, viewer_indices=[i])

# GOOD: Update only the changed viewer
self.viewer_controller.display_series_in_viewers(
    series_number,
    viewer_indices=[selected_index]
)


# 4. Trust the Controller
# ─────────────────────────
# The controller handles:
# - Thread safety
# - Redundancy prevention
# - State tracking
# - Race condition prevention
#
# You don't need to:
# - Add your own locks
# - Check if already displayed (controller does this)
# - Manage viewer state manually


# ══════════════════════════════════════════════════════════════════════════════
# 🚨 WARNING SIGNS (Code Smell)
# ══════════════════════════════════════════════════════════════════════════════

"""
If you see these patterns, refactor immediately:

1. Multiple functions calling start_process_series()
   → Consolidate to use controller

2. Same series being loaded multiple times
   → Add state checking via controller

3. Flickering or double-loading in UI
   → Check for direct viewer updates bypassing controller

4. Race conditions or crashes during loading
   → Ensure all updates go through controller's lock

5. Inconsistent viewer state
   → Use controller's state tracking instead of manual flags
"""
