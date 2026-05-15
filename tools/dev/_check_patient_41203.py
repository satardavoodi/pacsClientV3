#!/usr/bin/env python
"""Quick script to check for patient 41203 in the database and logs."""
import sqlite3
import os

# Check database
db_path = 'user_data/aipacs.db'
if os.path.exists(db_path):
    print(f"✓ Database found: {db_path}")
    db = sqlite3.connect(db_path)
    cursor = db.cursor()
    
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"\nTables in database: {', '.join(tables)}")
    
    # Search for any mention of 41203 in patient IDs or names
    if 'patients' in tables:
        cursor.execute("SELECT patient_id, patient_name, COUNT(*) FROM patients WHERE patient_id LIKE '%41203%' GROUP BY patient_id")
        results = cursor.fetchall()
        if results:
            print(f"\n✓ Found patient 41203 in database:")
            for row in results:
                print(f"  Patient ID: {row[0]}, Name: {row[1]}, Studies: {row[2]}")
        else:
            print("\n✗ Patient 41203 not found in database")
    
    db.close()
else:
    print(f"✗ Database not found: {db_path}")

# Check logs for retroactive metadata sync indicators
print("\n" + "="*60)
print("Checking viewer_diagnostics.log for retroactive sync patterns:")
log_path = 'user_data/logs/viewer_diagnostics.log'
if os.path.exists(log_path):
    import re
    with open(log_path, 'r') as f:
        content = f.read()
    
    # Search for retroactive patterns
    retro_capped = re.findall(r'\[RETRO_META_SYNC_CAPPED\].*?series=(\d+).*?duration_ms=([\d.]+)', content)
    retro_throttled = re.findall(r'\[RETRO_META_SYNC_THROTTLED\].*?series=(\d+)', content)
    retro_final_flush = re.findall(r'\[RETRO_META_SYNC_FINAL_FLUSH\].*?series=(\d+)', content)
    retroactive_activate = re.findall(r'phase=retroactive_activate\s+series=(\d+).*?grow_overlap_with_drag=(\w+)', content)
    
    print(f"\n[RETRO_META_SYNC_CAPPED] count: {len(retro_capped)}")
    if retro_capped:
        print(f"  Sample: series={retro_capped[0][0]}, duration_ms={retro_capped[0][1]}")
    
    print(f"\n[RETRO_META_SYNC_THROTTLED] count: {len(retro_throttled)}")
    
    print(f"\n[RETRO_META_SYNC_FINAL_FLUSH] count: {len(retro_final_flush)}")
    
    print(f"\nRetroactive activations (phase=retroactive_activate): {len(retroactive_activate)}")
    if retroactive_activate:
        for series, overlap in retroactive_activate[:5]:
            print(f"  Series {series}, grow_overlap_with_drag={overlap}")
    
    # Look for series 202 patterns
    print("\n" + "="*60)
    print("Checking for series 202 (problematic case):")
    series_202_pattern = r'series=202.*?(?=\n)'
    series_202_lines = re.findall(series_202_pattern, content)
    if series_202_lines:
        print(f"Found {len(series_202_lines)} lines mentioning series 202")
        # Check if new tags are present for series 202
        if 'RETRO_META_SYNC_CAPPED.*series=202' in content:
            print("✓ New [RETRO_META_SYNC_CAPPED] tag present for series 202")
        else:
            print("✗ [RETRO_META_SYNC_CAPPED] NOT found for series 202 yet")
        
        # Check for old pattern (post_grow_signal_ms=5.925)
        series_202_old = re.findall(r'phase=deferred_meta_sync.*?series=202.*?post_grow_signal_ms=([\d.]+)', content)
        if series_202_old:
            print(f"Found old pattern: phase=deferred_meta_sync with post_grow_signal_ms={series_202_old[0]}")
else:
    print(f"✗ Log file not found: {log_path}")
