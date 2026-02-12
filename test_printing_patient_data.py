"""
Test script to compare working vs non-working patient data in printing module
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from PacsClient.utils.database import get_connection_database


def inspect_patient(patient_id_or_name: str):
    """Inspect patient data structure"""
    print(f"\n{'='*80}")
    print(f"🔍 Inspecting patient: {patient_id_or_name}")
    print(f"{'='*80}\n")
    
    conn = get_connection_database()
    cur = conn.cursor()
    
    # Find patient
    cur.execute("""
        SELECT patient_pk, patient_id, patient_name
        FROM patients
        WHERE patient_id LIKE ? OR patient_name LIKE ?
    """, (f"%{patient_id_or_name}%", f"%{patient_id_or_name}%"))
    
    patient_row = cur.fetchone()
    if not patient_row:
        print(f"❌ Patient not found: {patient_id_or_name}")
        return
    
    patient_pk, patient_id, patient_name = patient_row
    print(f"✅ Patient found:")
    print(f"   patient_pk: {patient_pk}")
    print(f"   patient_id: {patient_id}")
    print(f"   patient_name: {patient_name}")
    
    # Get studies
    cur.execute("""
        SELECT study_pk, study_uid, study_date, study_time, study_description, 
               modality, study_path
        FROM studies
        WHERE patient_fk = ?
    """, (patient_pk,))
    
    studies = cur.fetchall()
    print(f"\n📊 Studies: {len(studies)}")
    
    for study_row in studies:
        study_pk, study_uid, study_date, study_time, study_desc, modality, study_path = study_row
        print(f"\n   Study #{study_pk}:")
        print(f"      study_uid: {study_uid[:60]}...")
        print(f"      study_date: {study_date}")
        print(f"      study_time: {study_time}")
        print(f"      modality: {modality}")
        print(f"      study_path: {study_path}")
        print(f"      study_path exists: {Path(study_path).exists() if study_path else 'N/A'}")
        
        # Get series for this study
        cur.execute("""
            SELECT series_pk, series_uid, series_number, series_description, 
                   series_path, image_count, modality
            FROM series
            WHERE study_fk = ?
            ORDER BY series_number
        """, (study_pk,))
        
        series_list = cur.fetchall()
        print(f"      Series: {len(series_list)}")
        
        for series_row in series_list:
            series_pk, series_uid, series_num, series_desc, series_path, img_count, series_mod = series_row
            print(f"\n         Series #{series_num} (pk={series_pk}):")
            print(f"            series_uid: {series_uid[:60]}...")
            print(f"            description: {series_desc}")
            print(f"            image_count: {img_count}")
            print(f"            series_path: {series_path}")
            
            if series_path:
                series_dir = Path(series_path)
                print(f"            series_path exists: {series_dir.exists()}")
                if series_dir.exists():
                    dcm_files = list(series_dir.glob("*.dcm"))
                    instance_files = list(series_dir.glob("Instance_*.dcm"))
                    print(f"            *.dcm files on disk: {len(dcm_files)}")
                    print(f"            Instance_*.dcm files: {len(instance_files)}")
            
            # Get instances for this series
            cur.execute("""
                SELECT instance_pk, sop_uid, instance_path, instance_number, 
                       rows, columns, group_id
                FROM instances
                WHERE series_fk = ?
                ORDER BY instance_number
                LIMIT 5
            """, (series_pk,))
            
            instances = cur.fetchall()
            print(f"            Instances in DB: {len(instances)} (showing first 5)")
            
            if instances:
                for inst_row in instances:
                    inst_pk, sop_uid, inst_path, inst_num, rows, cols, group_id = inst_row
                    path_exists = Path(inst_path).exists() if inst_path else False
                    print(f"               Instance #{inst_num}: pk={inst_pk}, path={inst_path[:80] if inst_path else 'NULL'}..., exists={path_exists}, group_id={group_id}")
            else:
                print(f"               ⚠️ No instances in database!")
                
            # Count total instances for this series
            cur.execute("SELECT COUNT(*) FROM instances WHERE series_fk = ?", (series_pk,))
            total_instances = cur.fetchone()[0]
            if total_instances != len(instances):
                print(f"               Total instances in DB: {total_instances}")
    
    conn.close()


def main():
    """Compare working vs non-working patients"""
    print("\n" + "="*80)
    print("🔬 PRINTING MODULE - PATIENT DATA COMPARISON")
    print("="*80)
    
    # Working patient (old download)
    inspect_patient("30411")
    
    # Non-working patient (new download)
    inspect_patient("31158")
    
    print("\n" + "="*80)
    print("✅ Comparison complete")
    print("="*80)


if __name__ == "__main__":
    main()
