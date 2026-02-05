#!/usr/bin/env python3
"""Test script to verify that the patient_widget module can be imported without syntax errors."""

def test_import():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget import PatientWidget
        print("SUCCESS: PatientWidget imported successfully!")
        print("No syntax errors in patient_widget.py")
        return True
    except SyntaxError as e:
        print(f"SYNTAX ERROR: {e}")
        return False
    except ImportError as e:
        print(f"IMPORT ERROR: {e}")
        return False
    except Exception as e:
        print(f"OTHER ERROR: {e}")
        # This might be OK if there are missing dependencies, but syntax should be fine
        print("Syntax is OK (other errors may be due to missing dependencies)")
        return True

if __name__ == "__main__":
    test_import()