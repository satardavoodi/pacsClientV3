#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Generate Missing Thumbnails
"""

import sys
import io
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from PacsClient.components.resumable_dicom_socket_client import ResumableDicomSocketClient

def main():
    """Generate thumbnails for all completed studies that don't have them."""
    print("Starting thumbnail generation for completed studies...")
    
    # Get source directory
    source_path = Path("./source")
    if not source_path.exists():
        print(f"[ERROR] Source directory not found: {source_path}")
        return
    
    # Get all study directories
    study_dirs = [d for d in source_path.iterdir() if d.is_dir()]
    print(f"[INFO] Found {len(study_dirs)} study directories")
    
    # Create client instance for thumbnail generation
    client = ResumableDicomSocketClient()
    
    generated_count = 0
    skipped_count = 0
    
    for study_dir in study_dirs:
        study_uid = study_dir.name
        print(f"\n[PROCESSING] Study: {study_uid}")
        
        # Check if study has DICOM files
        has_dicom = False
        for series_dir in study_dir.iterdir():
            if series_dir.is_dir():
                dcm_files = list(series_dir.glob("*.dcm"))
                if dcm_files:
                    has_dicom = True
                    break
        
        if not has_dicom:
            print(f"[SKIP] No DICOM files found")
            skipped_count += 1
            continue
        
        # Check if thumbnails already exist
        from PacsClient.pacs.patient_tab.utils.utils import THUMBNAIL_PATH
        thumbnails_dir = THUMBNAIL_PATH / study_uid
        
        if thumbnails_dir.exists():
            existing_thumbs = list(thumbnails_dir.glob("*.jpg")) + list(thumbnails_dir.glob("*.png"))
            if existing_thumbs:
                print(f"[SKIP] Already has {len(existing_thumbs)} thumbnails")
                skipped_count += 1
                continue
        
        # Generate thumbnails
        try:
            print(f"[GENERATE] Creating thumbnails...")
            
            # Set logging level to INFO to see what's happening
            import logging
            logging.getLogger('PacsClient.components.resumable_dicom_socket_client').setLevel(logging.INFO)
            
            success = client._generate_thumbnails_for_study(study_uid, study_dir)
            if success:
                generated_count += 1
                print(f"[SUCCESS] Thumbnails generated")
            else:
                print(f"[WARNING] Failed to generate thumbnails (returned False)")
        except Exception as e:
            print(f"[ERROR] Exception during thumbnail generation: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n" + "="*60)
    print(f"[SUMMARY]")
    print(f"   Generated: {generated_count} studies")
    print(f"   Skipped: {skipped_count} studies")
    print(f"   Total processed: {len(study_dirs)} studies")
    print("="*60)

if __name__ == "__main__":
    main()

