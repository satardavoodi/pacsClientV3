#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Migration script for Report Status feature

This script:
- Adds reportStatus and reportStatusHistory columns to studies table
- Sets default 'pending' status for existing studies
- Creates necessary indexes
- Validates the migration
"""

import sys
import os
import json
from pathlib import Path

# Add project root to path to import PacsClient modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database.core import get_db_connection, ensure_report_status_schema
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def migrate_report_status():
    """
    Main migration function
    """
    logger.info("🚀 Starting Report Status migration...")
    
    try:
        # Ensure schema exists
        logger.info("📋 Ensuring report status schema...")
        ensure_report_status_schema()
        
        # Validate migration
        logger.info("✅ Validating migration...")
        with get_db_connection() as conn:
            cur = conn.cursor()

            # Check if columns exist
            cur.execute("PRAGMA table_info(studies)")
            columns = [row[1] for row in cur.fetchall()]

            required_columns = ['reportStatus', 'reportStatusHistory', 'reportStatusUpdatedAt']
            missing_columns = [col for col in required_columns if col not in columns]

            if missing_columns:
                logger.error(f"❌ Migration failed: Missing columns: {missing_columns}")
                return False

            logger.info("✅ All required columns exist")

            # Check indexes
            cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_studies_report%'")
            indexes = [row[0] for row in cur.fetchall()]
            logger.info(f"📊 Created indexes: {indexes}")

            # Get statistics
            cur.execute("SELECT COUNT(*) FROM studies")
            total_studies = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM studies WHERE reportStatus IS NULL")
            null_status = cur.fetchone()[0]

            cur.execute("SELECT reportStatus, COUNT(*) FROM studies GROUP BY reportStatus")
            status_counts = dict(cur.fetchall())

            logger.info("📊 Migration Statistics:")
            logger.info(f"   Total studies: {total_studies}")
            logger.info(f"   Studies with null status: {null_status}")
            logger.info(f"   Status distribution:")
            for status, count in status_counts.items():
                logger.info(f"      {status}: {count}")

            # Update any remaining null statuses
            if null_status > 0:
                logger.info(f"🔄 Updating {null_status} studies with null status to 'pending'...")
                cur.execute("UPDATE studies SET reportStatus = 'pending' WHERE reportStatus IS NULL")
                conn.commit()
                logger.info("✅ Updated null statuses")
        
        logger.info("✅ Migration completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Migration failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = migrate_report_status()
    sys.exit(0 if success else 1)

