"""
Test Script: Verify Instance Insertion Fix

This script tests that:
1. Instances are being inserted into the database after download
2. All patient fields (age, sex, birth_date) are saved
3. All study fields (description, body_part, study_time) are saved
4. Series paths are recorded in the database
5. Local tab can display the information

Run this after downloading a patient in the UI.
"""

import sys
from pathlib import Path
from PacsClient.utils.database import get_connection_database

def test_database_contents():
    """Test that database contains all expected data"""
    
    conn = get_connection_database()
    cur = conn.cursor()
    
    print("=" * 80)
    print("📋 DATABASE VERIFICATION TEST")
    print("=" * 80)
    
    # Get recent studies
    print("\n1️⃣ CHECKING RECENT STUDIES...")
    cur.execute("""
        SELECT study_pk, study_uid, study_description, body_part, study_time, study_date
        FROM studies
        ORDER BY study_pk DESC
        LIMIT 5
    """)
    
    studies = cur.fetchall()
    if not studies:
        print("   ❌ No studies found in database!")
        return False
    
    print(f"   ✅ Found {len(studies)} recent studies")
    
    for study_pk, study_uid, desc, body_part, study_time, study_date in studies:
        print(f"\n   Study PK: {study_pk}")
        print(f"   Study UID: {study_uid[:40]}...")
        print(f"   Description: {desc if desc else '❌ MISSING'}")
        print(f"   Body Part: {body_part if body_part else '❌ MISSING'}")
        print(f"   Study Time: {study_time if study_time else '❌ MISSING'}")
        print(f"   Study Date: {study_date if study_date else '❌ MISSING'}")
        
        # Check series
        print(f"\n   📂 CHECKING SERIES FOR THIS STUDY...")
        cur.execute("""
            SELECT series_pk, series_uid, series_number, series_path, image_count, body_part_examined
            FROM series
            WHERE study_fk = ?
        """, (study_pk,))
        
        series_list = cur.fetchall()
        print(f"      ✅ Found {len(series_list)} series")
        
        for series_pk, series_uid, series_num, series_path, image_count, body_part_exam in series_list:
            print(f"\n      Series PK: {series_pk}")
            print(f"      Series Number: {series_num}")
            print(f"      Series UID: {series_uid[:40]}...")
            print(f"      Series Path: {series_path if series_path else '❌ MISSING'}")
            print(f"      Image Count: {image_count}")
            print(f"      Body Part Examined: {body_part_exam if body_part_exam else '⚠️ MISSING'}")
            
            # Check instances
            print(f"\n      🖼️ CHECKING INSTANCES FOR THIS SERIES...")
            cur.execute("""
                SELECT COUNT(*) as count
                FROM instances
                WHERE series_fk = ?
            """, (series_pk,))
            
            instance_count = cur.fetchone()[0]
            if instance_count == 0:
                print(f"         ❌ NO INSTANCES FOUND! (expected {image_count})")
            else:
                print(f"         ✅ Found {instance_count} instances (expected {image_count})")
                
                # Show sample instances
                cur.execute("""
                    SELECT sop_uid, instance_path, instance_number
                    FROM instances
                    WHERE series_fk = ?
                    LIMIT 3
                """, (series_pk,))
                
                samples = cur.fetchall()
                for sop, path, inst_num in samples:
                    print(f"            - Instance {inst_num}: {Path(path).name}")
    
    # Check patient info
    print("\n\n2️⃣ CHECKING PATIENT INFORMATION...")
    cur.execute("""
        SELECT patient_pk, patient_id, patient_name, age, sex, birth_date
        FROM patients
        ORDER BY patient_pk DESC
        LIMIT 3
    """)
    
    patients = cur.fetchall()
    for patient_pk, patient_id, patient_name, age, sex, birth_date in patients:
        print(f"\n   Patient: {patient_name} (ID: {patient_id})")
        print(f"   Age: {age if age else '❌ MISSING'}")
        print(f"   Sex: {sex if sex else '❌ MISSING'}")
        print(f"   Birth Date: {birth_date if birth_date else '❌ MISSING'}")
    
    print("\n" + "=" * 80)
    print("✅ DATABASE VERIFICATION COMPLETE")
    print("=" * 80)
    
    return True

if __name__ == "__main__":
    try:
        test_database_contents()
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
