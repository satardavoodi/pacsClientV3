"""
Tab lifecycle, theme, cleanup, tools, filters, priority queue.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""

import copy
import gc
import logging
import logging as _logging
import time
import traceback
import vtk
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
from PacsClient.pacs.patient_tab.utils import NodeViewer
logger = logging.getLogger(__name__)

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))

import os as _os

# Patient-close GUI-freeze fix (2026-06-27): exit_patient_widget ran a SYNCHRONOUS full
# gc.collect() on the GUI thread, walking the whole heap (hundreds of MB of volumes + VTK
# wrappers) → up to ~3.7s freeze on EVERY patient close (stall trace pinned this site). The
# collect must STAY on the GUI thread (VTK render windows can only be destroyed there), so we
# DEFER it to the idle event loop and COALESCE a burst of closes into ONE sweep: the close
# returns instantly; cycle collection happens a moment later when idle. Kill switch
# AIPACS_DEFER_CLOSE_GC=0 restores the synchronous in-close collect.
_DEFER_CLOSE_GC = (_os.getenv("AIPACS_DEFER_CLOSE_GC", "1") or "1").strip() != "0"
_CLOSE_GC_PENDING = [False]

# ── A0: make the close path visible (2026-08-23) ──────────────────────────────
# An end-user workstation hung for 17s on 2026-08-23 00:47 (Windows Application
# Hang 1002, AIPacs.exe 3.6.2.0, pid 24696) immediately after a patient-tab
# close, and left NOTHING in our logs. Two structural reasons:
#
#   1. The close path logs nothing of its own at INFO — every ``print()`` in this
#      module is redirected to ``logger.debug`` (see above), so we cannot even
#      tell whether ``exit_patient_widget`` returned.
#   2. The deferred ``gc.collect()`` below is the one UNLOGGED, UNBOUNDED,
#      GIL-HOLDING step on that path. The 2026-06-27 fix moved this collect
#      150 ms later so the close *returns* instantly — it did NOT make the
#      collect shorter, and 150 ms after a close the user is still sitting there.
#      That session's heap was 2 378 MB of VTK wrappers.
#
# So: a breadcrumb BEFORE each step (proves we entered it even if we never come
# back) and a native hang watchdog AROUND it (dumps the stuck stack even though
# the GIL is held — our Python-thread sampler cannot). Observation only.
# Kill switch AIPACS_CLOSE_PATH_TIMING=0 restores the silent legacy behaviour.
import contextlib as _contextlib

_CLOSE_PATH_TIMING = (_os.getenv("AIPACS_CLOSE_PATH_TIMING", "1") or "1").strip() != "0"

try:
    _CLOSE_PATH_WARN_MS = float(_os.getenv("AIPACS_CLOSE_PATH_WARN_MS", "") or 250.0)
except (TypeError, ValueError):
    _CLOSE_PATH_WARN_MS = 250.0

try:
    from PacsClient.utils.native_fault_log import hang_watchdog as _hang_watchdog
except Exception:  # pragma: no cover - the close path must never depend on this
    @_contextlib.contextmanager
    def _hang_watchdog(label, seconds=None):  # type: ignore[misc]
        yield False


@_contextlib.contextmanager
def _close_step(label: str):
    """Breadcrumb + native hang watchdog around one patient-close step.

    The ``start`` line is the point: if the process dies inside the step there is
    no ``done`` line, and the pair tells us exactly which step swallowed it.
    Never raises, never changes what the step does.
    """
    if not _CLOSE_PATH_TIMING:
        yield
        return
    logger.info("[CLOSE_PATH] %s start", label)
    _t0 = time.perf_counter()
    try:
        with _hang_watchdog(label):
            yield
    finally:
        _elapsed_ms = (time.perf_counter() - _t0) * 1000.0
        _emit = logger.warning if _elapsed_ms >= _CLOSE_PATH_WARN_MS else logger.info
        try:
            _emit("[CLOSE_PATH] %s done ms=%.1f", label, _elapsed_ms)
        except Exception:
            pass


def _run_deferred_close_gc():
    _CLOSE_GC_PENDING[0] = False
    with _close_step("deferred_close_gc"):
        try:
            gc.collect()
        except Exception:
            pass


def _schedule_deferred_close_gc():
    """Coalesced, idle-deferred gc.collect() for patient-close teardown. If a collect is already
    queued (e.g. closing several patients in a row) do nothing — one sweep covers them all. Falls
    back to an immediate collect when there is no Qt event loop (tests)."""
    if _CLOSE_GC_PENDING[0]:
        return
    _CLOSE_GC_PENDING[0] = True
    try:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(150, _run_deferred_close_gc)
    except Exception:
        _run_deferred_close_gc()


class _PWLifecycleMixin:
    """Tab lifecycle, theme, cleanup, tools, filters, priority queue."""

    def add_priority_series_for_display(self, series_number, vtk_image_data, metadata):
        """افزودن سری اولویت‌دار به صف نمایش مستقل"""
        try:
            series_key = str(series_number)
            print(f"🎯 [PRIORITY DISPLAY] Adding series {series_key} to priority display queue")
            
            # ذخیره داده‌ها
            self._priority_series_data[series_key] = {
                'vtk_image_data': vtk_image_data,
                'metadata': metadata,
                'added_time': time.time()
            }
            
            # افزودن به صف (اگر قبلاً نبوده)
            if series_key not in self._priority_series_queue:
                self._priority_series_queue.append(series_key)
                print(f"   ✅ Added to queue. Queue length: {len(self._priority_series_queue)}")
            
            # تلاش برای نمایش فوری
            self._try_display_priority_series(series_key)
            
        except Exception as e:
            print(f"❌ Error adding priority series to display queue: {e}")
            import traceback
            traceback.print_exc()

    def _try_display_priority_series(self, series_key):
        """تلاش برای نمایش فوری سری اولویت‌دار"""
        try:
            if series_key not in self._priority_series_data:
                print(f"⚠️ Series {series_key} not in priority data")
                return False

            # بررسی وجود ویوورها
            if not hasattr(self, 'lst_nodes_viewer') or not self.lst_nodes_viewer:
                print(f"⚠️ No viewers available for series {series_key}, will try later")
                return False

            data = self._priority_series_data[series_key]
            vtk_image_data = data['vtk_image_data']
            metadata = data['metadata']

            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []
                print(f"⚠️ lst_thumbnails_data not initialized")
                return False

            # پیدا کردن ایندکس سری در lst_thumbnails_data
            series_idx = -1
            for i in range(len(self.lst_thumbnails_data)):
                if str(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == series_key:
                    series_idx = i
                    break

            if series_idx == -1:
                print(f"⚠️ Series {series_key} not found in thumbnails data")
                return False

            print(f"🎬 [PRIORITY DISPLAY] Attempting immediate display of series {series_key}")

            # استفاده از اولین ویوور
            viewer = self.lst_nodes_viewer[0]

            # If this is the first displayed series (or any viewer is empty), fill all viewers
            if (not self._first_series_displayed) or self._any_viewer_empty():
                print(f"   🔄 Filling all viewers for first series {series_key}")
                if self._display_first_series_in_all_viewers(series_key):
                    self._mark_first_series_displayed()
                    # Set main viewer to first
                    self.set_viewer_to_main_viewer(viewer)
                    # Remove from queue/data
                    if series_key in self._priority_series_queue:
                        self._priority_series_queue.remove(series_key)
                    if series_key in self._priority_series_data:
                        del self._priority_series_data[series_key]
                    print(f"🎉 [PRIORITY DISPLAY] Series {series_key} displayed in all viewers!")
                    return True

            # روش اصلی: استفاده از switch_series
            if hasattr(viewer, 'switch_series'):
                print(f"   🔄 Using switch_series for series {series_key}")
                flag_switch = viewer.switch_series(
                    vtk_image_data,
                    metadata,
                    series_idx,
                    metadata_fixed=self.metadata_fixed
                )

                if flag_switch:
                    print(f"   ✅ switch_series succeeded for series {series_key}")

                    # تنظیم به عنوان ویوور اصلی
                    self.set_viewer_to_main_viewer(viewer)

                    # تنظیم اسلایدر
                    if hasattr(viewer, 'slider') and viewer.slider:
                        self.reset_slider(viewer.vtk_widget, viewer.slider)

                    # حذف از صف و دیکشنری
                    if series_key in self._priority_series_queue:
                        self._priority_series_queue.remove(series_key)
                    if series_key in self._priority_series_data:
                        del self._priority_series_data[series_key]

                    # رندر فوری
                    if hasattr(viewer.vtk_widget, 'GetRenderWindow'):
                        viewer.vtk_widget.GetRenderWindow().Render()

                    print(f"🎉 [PRIORITY DISPLAY] Series {series_key} displayed successfully!")
                    return True
                else:
                    print(f"   ❌ switch_series failed for series {series_key}")
                    return False

            return False

        except Exception as e:
            print(f"❌ Error in priority display attempt: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _process_priority_series_queue(self):
        """پردازش دوره‌ای صف سری‌های اولویت‌دار"""
        try:
            if not self._priority_series_queue or not self.isVisible():
                return

            # کپی از صف برای جلوگیری از تغییر در حین پردازش
            queue_copy = self._priority_series_queue.copy()

            for series_key in queue_copy:
                # بررسی timeout (بیش از 30 ثانیه نمانده باشد)
                if series_key in self._priority_series_data:
                    added_time = self._priority_series_data[series_key]['added_time']
                    if time.time() - added_time > 30:  # 30 ثانیه
                        print(f"⚠️ Removing stale priority series {series_key} from queue")
                        self._priority_series_queue.remove(series_key)
                        del self._priority_series_data[series_key]
                        continue

                # تلاش برای نمایش
                if self._try_display_priority_series(series_key):
                    break  # فقط یک سری در هر چرخه نمایش بده

        except Exception as e:
            print(f"⚠️ Error processing priority queue: {e}")

    def exit_patient_widget(self):
        """تمام resources را با سرعت تمیز کن

        Thin wrapper (A0, 2026-08-23): the whole synchronous teardown — viewer
        cleanup, ``release_mpr_children``, VTK widget destruction, thumbnail
        release — runs on the GUI thread and logged nothing at INFO, so a block
        anywhere inside it was indistinguishable from the app simply stopping.
        The body is unchanged; it just runs inside a breadcrumb + hang watchdog.
        """
        with _close_step("exit_patient_widget"):
            self._exit_patient_widget_impl()

    def _exit_patient_widget_impl(self):
        try:
            print("🔴 exit_patient_widget: Starting cleanup...")
            
            # Clean up any loading overlays
            try:
                self._hide_eagle_eye_loading_ui()
            except Exception:
                pass
            
            # Ensure home loading overlay is hidden if this widget is closed early
            try:
                from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
                home_widget = get_home_widget()
                if home_widget is not None:
                    home_widget._hide_double_click_loading()

                    # Remove this widget from home widget's cache if it exists
                    if hasattr(home_widget, 'dict_tabs_widget') and self.study_uid:
                        if self.study_uid in home_widget.dict_tabs_widget:
                            del home_widget.dict_tabs_widget[self.study_uid]
                            print(f"✅ Removed study {self.study_uid} from home widget cache")
                        else:
                            print(f"⚠️ Study {self.study_uid} not found in home widget cache")
                    else:
                        print(f"⚠️ Home widget doesn't have dict_tabs_widget or study_uid is None")
                        
                    # Remove this study from the opening studies set to allow reopening
                    if hasattr(home_widget, 'remove_from_opening_studies') and self.study_uid:
                        home_widget.remove_from_opening_studies(self.study_uid)
            except Exception as e:
                print(f"⚠️ Error removing widget from home cache: {e}")
                import traceback
                traceback.print_exc()

            # Cancel all background tasks first to prevent new tasks from being created
            if hasattr(self, '_background_tasks'):
                for task in list(self._background_tasks):
                    try:
                        if not task.done():
                            task.cancel()
                            # Wait briefly for task to finish cancellation
                            try:
                                if hasattr(task, 'exception'):
                                    task.exception()  # Consume any exceptions from cancellation
                            except:
                                pass
                    except:
                        pass
                self._background_tasks.clear()

            # Cancel the series worker task if it exists
            if hasattr(self, '_series_worker_task') and self._series_worker_task:
                try:
                    if not self._series_worker_task.done():
                        self._series_worker_task.cancel()
                except:
                    pass

            # Cancel any active load task
            if hasattr(self, '_active_load_task') and self._active_load_task:
                try:
                    if not self._active_load_task.done():
                        self._active_load_task.cancel()
                except:
                    pass

            # Clean up viewers
            self.cleanup_all_viewers()

            # Force clear all viewer/controller caches on tab close.
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                # S5b: cancel any in-flight async series applies FIRST, so a queued UI-thread apply
                # finds its token cancelled and bails before touching a viewer we're tearing down
                # (the D1 use-after-free class). No-op when AIPACS_VIEWER_UNIFIED_TEARDOWN is off.
                try:
                    if hasattr(self.viewer_controller, 'cancel_inflight_loads'):
                        self.viewer_controller.cancel_inflight_loads()
                except Exception:
                    pass
                try:
                    self.viewer_controller.clear_all_caches_for_close()
                except Exception:
                    pass

            # Clean up viewer controller
            if hasattr(self, 'viewer_controller'):
                # Clean up viewer nodes efficiently
                if hasattr(self.viewer_controller, 'lst_nodes_viewer'):
                    for node in list(self.viewer_controller.lst_nodes_viewer):  # Use list() to avoid modification during iteration
                        try:
                            node: NodeViewer
                            vtk_widget: VTKWidget = getattr(node, 'vtk_widget', None)
                            if vtk_widget is not None:
                                # 2026-08-19: release an OPEN MPR viewer first.
                                # This loop cleans the HOST viewer and then nulls
                                # node.vtk_widget, but an MPR viewer hangs off the
                                # host as `_zeta_mpr_widget` and was never reached
                                # — so closing a patient tab with MPR open orphaned
                                # its full volume, 4 render windows and GPU texture.
                                # Observed live: MPR opened 12:57, close_patient at
                                # 15:35, no cleanup() logged in between.
                                # Must run BEFORE the host teardown, while the GL
                                # context is still valid.
                                try:
                                    from modules.mpr.zeta_mpr.mpr_viewer._mpr_lifecycle import (
                                        release_mpr_children,
                                    )
                                    release_mpr_children(vtk_widget, reason="close_patient")
                                except Exception:
                                    pass
                                try:
                                    if hasattr(vtk_widget, 'cleanup_image_viewer'):
                                        vtk_widget.cleanup_image_viewer()  # Advanced viewer (VTKWidget)
                                    elif hasattr(vtk_widget, 'cleanup'):
                                        vtk_widget.cleanup()  # FAST viewer (QtFastContainer)
                                except:
                                    pass

                            # Safe cleanup: keep attributes but null them out to avoid AttributeError races
                            for attr in ('vtk_widget', 'widget', 'slider'):
                                try:
                                    if hasattr(node, attr):
                                        setattr(node, attr, None)
                                except:
                                    pass
                        except Exception as e:
                            self.logger.debug(f"Error cleaning up viewer node: {e}")

            # Check if lst_thumbnails_data exists before trying to access it
            if hasattr(self, 'lst_thumbnails_data') and self.lst_thumbnails_data:
                # Use slice assignment for faster clearing
                for i in range(len(self.lst_thumbnails_data)):
                    try:
                        item = self.lst_thumbnails_data[i]
                        if not item:
                            continue

                        # Release VTK data
                        if 'vtk_image_data' in item:
                            vtk_data = item['vtk_image_data']
                            if vtk_data and hasattr(vtk_data, 'GetPointData'):
                                try:
                                    vtk_data.GetPointData().SetScalars(None)
                                except:
                                    pass

                        # Clear metadata
                        try:
                            item.clear()
                        except:
                            pass
                    except Exception as e:
                        self.logger.debug(f"Error cleaning item {i}: {e}")

                self.lst_thumbnails_data.clear()

            # Clean up node viewer list
            if hasattr(self, 'lst_nodes_viewer'):
                self.lst_nodes_viewer.clear()

            # Clean up series names
            if hasattr(self, 'lst_series_name'):
                self.lst_series_name.clear()

            # Stop timers efficiently
            for timer_attr in ['_priority_display_timer', '_pipeline_task']:
                if hasattr(self, timer_attr):
                    timer = getattr(self, timer_attr)
                    if timer:
                        try:
                            if hasattr(timer, 'stop'):
                                timer.stop()
                        except:
                            pass

            # Belt-and-suspenders: stop the per-tab viewer-controller timers on
            # teardown.  A queued tick — especially `_dl_watchdog_timer`, which
            # calls `change_series_on_viewer` via `_maybe_resume_awaiting_from_disk`
            # — could otherwise fire into a half-deleted widget after the nodes are
            # cleared, a use-after-free window on patient switch / tab close (only
            # `_progressive_grow_timer` was being stopped here).  `stop()` is
            # idempotent and never raises; `getattr(..., None)` skips timers that
            # were never created.
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                for _tname in ('_progressive_grow_timer', '_dl_watchdog_timer', '_warmup_result_timer'):
                    try:
                        _t = getattr(self.viewer_controller, _tname, None)
                        if _t is not None and hasattr(_t, 'stop'):
                            _t.stop()
                    except Exception:
                        pass

            # Force garbage collection for VTK objects — DEFERRED + coalesced (2026-06-27) so the
            # close returns instantly instead of freezing the GUI thread ~3.7s on the heap walk.
            # The collect still runs on the GUI thread (VTK render windows destroy only there),
            # just on the next idle turn, and a burst of closes collapses to a single sweep.
            if _DEFER_CLOSE_GC:
                _schedule_deferred_close_gc()
            else:
                gc.collect()

            print("✅ [EXIT] PatientWidget cleaned up successfully")
        except Exception as e:
            self.logger.error(f"Error in exit_patient_widget: {e}")
            import traceback
            traceback.print_exc()

    def closeEvent(self, event):
        """Handle widget close event"""
        try:
            if getattr(self, '_pw_close_handled', False):
                # closeEvent already ran once. It can be re-entered via the
                # tab manager's close path (close_patient_tab calls
                # widget.close()); make it idempotent so the teardown below
                # is not repeated.
                event.accept()
                return
            self._pw_close_handled = True

            # Disconnect from the app-lifetime ThemeManager so this closed tab does
            # not leave a live receiver on the singleton (per-tab memory retention).
            try:
                _tm = getattr(self, '_app_theme_manager', None)
                if _tm is not None:
                    _tm.themeChanged.disconnect(self._on_app_theme_changed)
            except (TypeError, RuntimeError):
                pass

            try:
                self.on_tab_deactivated()
            except Exception:
                pass

            # Cancel all background tasks before cleanup
            if hasattr(self, '_background_tasks'):
                for task in list(self._background_tasks):
                    try:
                        if not task.done():
                            task.cancel()
                            # Wait briefly for task to finish cancellation
                            try:
                                if hasattr(task, 'exception'):
                                    task.exception()  # Consume any exceptions from cancellation
                            except:
                                pass
                    except:
                        pass
                self._background_tasks.clear()

            # Cancel the series worker task if it exists
            if hasattr(self, '_series_worker_task') and self._series_worker_task:
                try:
                    if not self._series_worker_task.done():
                        self._series_worker_task.cancel()
                except:
                    pass

            # Clean up resources
            self.exit_patient_widget()

            # If we have a tab manager, notify it that this tab is being closed
            if hasattr(self, 'tab_manager') and self.tab_manager:
                try:
                    # Remove this tab from the custom tab manager
                    tab_index = self.tab_manager.find_tab_by_study_uid(self.study_uid)
                    if tab_index is not None and tab_index != -1:
                        print(f"Removing tab at index {tab_index} for study {self.study_uid}")
                        # Call the tab manager's close method to properly remove the tab
                        self.tab_manager.close_patient_tab(tab_index)
                except Exception as e:
                    print(f"Warning: Error interacting with tab manager: {e}")
                    
                    # Fallback: try to remove from tab manager's study_uid mapping directly
                    try:
                        if (hasattr(self.tab_manager, 'study_uid_to_tab') and 
                            self.study_uid in self.tab_manager.study_uid_to_tab):
                            del self.tab_manager.study_uid_to_tab[self.study_uid]
                            print(f"Fallback: Removed study {self.study_uid} from tab manager mapping")
                    except Exception as fallback_e:
                        print(f"Fallback removal also failed: {fallback_e}")

            # Release this widget's reference to the event loop.
            # IMPORTANT: self._event_loop holds the *single* qasync QEventLoop
            # that drives the ENTIRE application (created once in main.py as
            # `loop = QEventLoop(app)` and run via `loop.run_forever()`).
            # Calling .stop() on it terminates the whole application — that is
            # what previously made AI-PACS exit completely when a single
            # patient tab was closed, or when "Sync and Close" finished.
            # Closing one patient tab must only drop this widget's reference;
            # the shared loop must keep running for the rest of the app.
            # Background tasks for this widget were already cancelled above.
            if hasattr(self, '_event_loop') and self._event_loop:
                self._event_loop = None

            # Accept the close event
            event.accept()
        except Exception as e:
            self.logger.error(f"Error in closeEvent: {e}")
            event.accept()

    def _on_advanced_tool_applied(self, tool_name: str, result):
        """
        Handle results produced by advanced tools (volume, surface, mask, etc.)
        """
        print(f"[PatientWidget] Advanced tool applied: {tool_name}")

        widget = self.selected_widget
        viewer = getattr(widget, "image_viewer", None)

        if viewer is None:
            print("[PatientWidget] No active image viewer")
            return

        renderer = getattr(viewer, "renderer", None)

        def render_scene():
            renderer.ResetCamera()
            renderer.GetRenderWindow().Render()

        try:
            # =========================
            # Volume result
            # =========================
            if isinstance(result, vtk.vtkVolume) and renderer:
                renderer.AddVolume(result)
                render_scene()
                return

            # =========================
            # Single surface actor
            # =========================
            if isinstance(result, vtk.vtkActor) and renderer:
                renderer.AddActor(result)
                render_scene()
                return

            # =========================
            # Multiple actors / volumes
            # =========================
            if isinstance(result, dict) and renderer:
                for obj in result.values():
                    if isinstance(obj, vtk.vtkActor):
                        renderer.AddActor(obj)
                    elif isinstance(obj, vtk.vtkVolume):
                        renderer.AddVolume(obj)
                render_scene()
                return

            # =========================
            # Mask / image data
            # =========================
            if isinstance(result, vtk.vtkImageData):
                self.add_mask_to_viewer(viewer, result, tool_name)
                return

            print(f"[PatientWidget] Unsupported result type: {type(result)}")

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Failed to apply advanced tool result ({tool_name})",
                exc_info=True,
            )

    def add_mask_to_viewer(self, viewer, mask: vtk.vtkImageData, tool_name: str):
        """
        Add a binary mask to either a 2D or 3D viewer automatically.

        - 2D viewer  → RGBA overlay using vtkImageActor
        - 3D viewer  → Surface rendering using FlyingEdges / Marching Cubes

        Viewer type is inferred from its capabilities.
        """

        TOOL_COLORS = {
            "lung":    (1.0, 0.0, 0.0),
            "airway":  (0.0, 1.0, 0.0),
            "vessel":  (0.0, 0.0, 1.0),
            "bone":    (1.0, 1.0, 0.0),
            "default": (1.0, 0.0, 1.0),
        }

        def resolve_color(name: str):
            name = name.lower()
            return next(
                (color for key, color in TOOL_COLORS.items() if key in name),
                TOOL_COLORS["default"],
            )

        try:
            color = resolve_color(tool_name)

            # =========================
            # 2D VIEWER (Image Overlay)
            # =========================
            if hasattr(viewer, "GetRenderer") and hasattr(viewer, "GetSlice"):
                lut = vtk.vtkLookupTable()
                lut.SetNumberOfTableValues(2)
                lut.SetRange(0, 1)
                lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)
                lut.SetTableValue(1, *color, 0.3)
                lut.Build()

                mapper = vtk.vtkImageMapToColors()
                mapper.SetInputData(mask)
                mapper.SetLookupTable(lut)
                mapper.SetOutputFormatToRGBA()
                mapper.Update()

                actor = vtk.vtkImageActor()
                actor.GetMapper().SetInputConnection(mapper.GetOutputPort())

                z = viewer.GetSlice()
                dims = mask.GetDimensions()
                actor.SetDisplayExtent(0, dims[0] - 1, 0, dims[1] - 1, z, z)

                renderer = viewer.GetRenderer()
                renderer.AddActor(actor)

                if not hasattr(self.selected_widget, "_mask_actors"):
                    self.selected_widget._mask_actors = []
                self.selected_widget._mask_actors.append(actor)

                viewer.Render()
                return

            # =========================
            # 3D VIEWER (Surface)
            # =========================
            if hasattr(viewer, "renderer"):
                surface = vtk.vtkFlyingEdges3D()
                surface.SetInputData(mask)
                surface.SetValue(0, 0.5)
                surface.Update()

                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(surface.GetOutputPort())

                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor(*color)
                actor.GetProperty().SetOpacity(0.5)

                viewer.renderer.AddActor(actor)
                viewer.renderer.ResetCamera()
                viewer.renderer.GetRenderWindow().Render()
                return

            raise RuntimeError("Viewer type not supported")

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Failed to add mask ({tool_name}) to viewer", exc_info=True
            )

    def _on_app_theme_changed(self, theme: dict) -> None:
        """Handle application theme changes and retint all UI elements."""
        try:
            self._app_theme = theme or self._app_theme_manager.current_theme() if self._app_theme_manager else {}
            _pw_retint_widget_tree(self, self._app_theme)
        except Exception as e:
            logger.warning(f"Error retinting PatientWidget on theme change: {e}")

    def apply_filters_to_all_series_of_modality(self, modality: str, filter_params: dict):
        """
        Apply the same filters to all series of the same modality.
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []

            logger.info(f"[PatientWidget] Starting to apply filters to all {modality} series...")
            logger.info(f"Filter parameters: {filter_params}")

            # Find all series of the same modality
            series_to_update = []
            metadata_to_update = []
            indices_to_update = []

            for i, thumbnail_data in enumerate(self.lst_thumbnails_data):
                series_modality = thumbnail_data['metadata']['series'].get('modality', '').upper()
                if series_modality == modality:
                    series_to_update.append(thumbnail_data['vtk_image_data'])
                    metadata_to_update.append(thumbnail_data['metadata'])
                    indices_to_update.append(i)

            if not series_to_update:
                logger.warning(f"[PatientWidget] No {modality} series found to update")
                return

            logger.info(f"[PatientWidget] Found {len(series_to_update)} {modality} series to update")

            # Apply filters to all series of the same modality
            from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters_to_multiple_series
            logger.info(f"[PatientWidget] About to apply filters to {len(series_to_update)} series")
            updated_series = apply_filters_to_multiple_series(
                series_to_update,
                metadata_to_update,
                filter_params.get("filter_type", "smoothing"),
                filter_params.get("params", {})
            )
            logger.info(f"[PatientWidget] Filters applied successfully to {len(updated_series)} series")

            # Update the stored image data
            for idx, updated_data in zip(indices_to_update, updated_series):
                self.lst_thumbnails_data[idx]['vtk_image_data'] = updated_data
                logger.info(f"[PatientWidget] Updated series at index {idx} with filtered data")

            logger.info(f"[PatientWidget] Successfully updated {len(series_to_update)} {modality} series")

            # If the current viewer is showing a series of this modality, update it
            if (self.selected_widget and
                hasattr(self.selected_widget, 'image_viewer') and
                hasattr(self.selected_widget.image_viewer, 'metadata')):
                current_modality = self.selected_widget.image_viewer.metadata['series'].get('modality', '').upper()
                if current_modality == modality:
                    logger.info(f"[PatientWidget] Current viewer is showing {current_modality} series, updating...")
                    # Refresh the current view
                    # Find the current series index by matching the metadata
                    current_series_number = self.selected_widget.image_viewer.metadata['series'].get('series_number')
                    current_series_idx = -1
                    for i, thumbnail_data in enumerate(self.lst_thumbnails_data):
                        if thumbnail_data['metadata']['series'].get('series_number') == current_series_number:
                            current_series_idx = i
                            break

                    if current_series_idx != -1:
                        logger.info(f"[PatientWidget] Updating current viewer with filtered data for series {current_series_number}")
                        current_vtk_data = self.lst_thumbnails_data[current_series_idx]['vtk_image_data']
                        # Check if the viewer has the display_image method before calling it
                        if hasattr(self.selected_widget.image_viewer, 'display_image'):
                            self.selected_widget.image_viewer.display_image(current_vtk_data,
                                                                          self.lst_thumbnails_data[current_series_idx]['metadata'])
                        else:
                            # Alternative method for viewers that don't have display_image
                            # This might be a VTK widget that needs to be updated differently
                            logger.warning(f"[PatientWidget] Viewer doesn't have display_image method, trying alternative update")
                            # Update the viewer's image data directly if possible
                            if hasattr(self.selected_widget.image_viewer, 'reset_image_viewer'):
                                self.selected_widget.image_viewer.reset_image_viewer(
                                    current_vtk_data,
                                    self.lst_thumbnails_data[current_series_idx]['metadata']
                                )
                            else:
                                # If neither method is available, try to update through the VTK widget
                                logger.warning(f"[PatientWidget] Neither display_image nor reset_image_viewer available, trying direct update")
                                # Update the VTK widget's image data directly
                                if hasattr(self.selected_widget, 'start_process_series'):
                                    # Restart the series processing with the new data
                                    self.selected_widget.start_process_series(
                                        current_vtk_data,
                                        self.lst_thumbnails_data[current_series_idx]['metadata'],
                                        self.lst_thumbnails_data[current_series_idx]['metadata']['series']['series_number'],
                                        self.selected_widget.id_vtk_widget,
                                        self.metadata_fixed
                                    )

                        logger.info(f"[PatientWidget] Updated current viewer with filtered data")
                    else:
                        logger.warning(f"[PatientWidget] Could not find current series index for series number {current_series_number}")

        except Exception as e:
            logger.error(f"[PatientWidget] Error applying filters to all {modality} series: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def handle_tool_applied(self, tool_name: str, result):
        """
        Handle results from advanced tools including filters
        """
        try:
            print(f"[PatientWidget] Tool applied: {tool_name}")

            if tool_name == "filters_applied_to_modality":
                # Handle filter application to all series of a modality
                modality = result.get("modality", "")
                filter_params = result.get("filter_params", {})

                if modality:
                    self.apply_filters_to_all_series_of_modality(modality, filter_params)
            else:
                # Handle other tools (original functionality)
                self._on_advanced_tool_applied(tool_name, result)

        except Exception as e:
            print(f"[PatientWidget] Error handling tool applied: {e}", exc_info=True)

    def set_tab_manager(self, tab_manager):
        self.tab_manager = tab_manager

    def on_tab_activated(self):
        """Called when this patient tab becomes active in the main tab widget."""
        if self._is_active_patient_tab:
            return
        self._is_active_patient_tab = True
        try:
            print(f"✅ [PatientWidget] on_tab_activated study={self.study_uid}")
        except Exception:
            pass
        try:
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                self.viewer_controller.on_tab_activated()
        except Exception:
            pass
        # A series that finished downloading while this tab was inactive still
        # showed the loading overlay on return. Re-sync thumbnail completion
        # state shortly after activation (deferred so it never blocks the switch).
        try:
            from PySide6.QtCore import QTimer as _QTimer
            if hasattr(self, 'resync_thumbnail_download_states'):
                _QTimer.singleShot(150, self.resync_thumbnail_download_states)
        except Exception:
            pass

    def on_tab_deactivated(self):
        """Called when this patient tab is no longer the active tab."""
        if not self._is_active_patient_tab:
            return
        self._is_active_patient_tab = False
        try:
            print(f"🛑 [PatientWidget] on_tab_deactivated study={self.study_uid}")
        except Exception:
            pass
        try:
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                self.viewer_controller.on_tab_deactivated()
        except Exception:
            pass

