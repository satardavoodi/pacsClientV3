"""
Series Utilities for PACS Client

This module provides utility functions for working with series information,
including database operations, filtering, and statistics.
"""

from typing import List, Dict, Optional, Any
import sys
import logging
from PacsClient.utils.db_manager import (
    insert_series, find_series_pk, get_series_by_study_pk, 
    find_study_pk_with_study_uid, find_patient_pk, insert_patient, insert_study
)

logger = logging.getLogger(__name__)


def _emit_cli(message: str):
    """Emit user-facing console text without direct print calls."""
    sys.stdout.write(f"{message}\n")


def extract_series_info_from_grpc_response(grpc_response) -> Dict[str, Any]:
    """
    Extract series information from gRPC response
    
    Args:
        grpc_response: Response from gRPC GetStudyThumbnails call
        
    Returns:
        dict: Structured series information
    """
    try:
        study_info = {
            'study_uid': grpc_response.study_instance_uid,
            'patient_id': grpc_response.patient_id,
            'patient_name': grpc_response.patient_name,
            'study_date': grpc_response.study_date,
            'study_description': grpc_response.study_description,
            'count_of_series': grpc_response.count_of_series,
            'thumbnails_available': grpc_response.thumbnails_available,
            'series': []
        }
        
        # Extract series information
        for series in grpc_response.series_thumbnails:
            series_info = {
                'series_uid': series.series_uid,
                'series_number': series.series_number,
                'series_description': series.series_description,
                'modality': series.modality,
                'image_count': series.image_count,
                'protocol_name': getattr(series, 'protocol_name', ''),
                'body_part_examined': getattr(series, 'body_part_examined', ''),
                'manufacturer': getattr(series, 'manufacturer', ''),
                'institution_name': getattr(series, 'institution_name', ''),
                'thumbnail_path': getattr(series, 'thumbnail_path', ''),
                'thumbnail_data': getattr(series, 'thumbnail_data', b'')
            }
            study_info['series'].append(series_info)
        
        return study_info
        
    except Exception as e:
        logger.warning("Error extracting series info: %s", e)
        return None


def save_series_to_database(study_uid: str, series_list: List[Dict]) -> bool:
    """
    Save series information to database
    
    Args:
        study_uid: Study Instance UID
        series_list: List of series dictionaries
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get study_pk from database
        study_pk = find_study_pk_with_study_uid(study_uid)
        if not study_pk:
            logger.warning("Study not found in database: %s", study_uid)
            return False
        
        saved_count = 0
        for series_data in series_list:
            try:
                # Extract series information
                series_uid = series_data.get('series_uid', '')
                series_number = series_data.get('series_number', '')
                series_description = series_data.get('series_description', '')
                modality = series_data.get('modality', '')
                image_count = series_data.get('image_count', 0)
                thumbnail_path = series_data.get('thumbnail_path', '')
                
                # Check if series already exists
                existing_series_pk = find_series_pk(series_uid)
                if existing_series_pk:
                    logger.debug("Series already exists: %s", series_uid)
                    continue
                
                # Save series to database
                series_pk = insert_series(
                    series_uid=series_uid,
                    study_fk=study_pk,
                    series_name=f"Series {series_number}",
                    series_number=series_number,
                    series_description=series_description,
                    main_thumbnail=True if thumbnail_path else False,
                    thumbnail_path=thumbnail_path,
                    series_path=None  # Will be set when DICOM files are downloaded
                )
                
                logger.debug("Saved series %s: %s (%s)", series_number, series_description, modality)
                saved_count += 1
                
            except Exception as e:
                logger.warning(
                    "Error saving series %s: %s",
                    series_data.get('series_number', 'Unknown'),
                    e,
                )
                continue
        
        logger.info("Successfully saved %d series to database", saved_count)
        return saved_count > 0
        
    except Exception as e:
        logger.warning("Error in save_series_to_database: %s", e)
        return False


def filter_series_by_modality(series_list: List[Dict], modality: str) -> List[Dict]:
    """
    Filter series by modality
    
    Args:
        series_list: List of series dictionaries
        modality: Modality to filter by (e.g., 'CT', 'MR', 'US')
        
    Returns:
        List[Dict]: Filtered series list
    """
    return [s for s in series_list if s.get('modality', '').upper() == modality.upper()]


def filter_series_by_keyword(series_list: List[Dict], keyword: str) -> List[Dict]:
    """
    Filter series by keyword in description
    
    Args:
        series_list: List of series dictionaries
        keyword: Keyword to search for
        
    Returns:
        List[Dict]: Filtered series list
    """
    keyword_lower = keyword.lower()
    return [s for s in series_list if keyword_lower in s.get('series_description', '').lower()]


def get_series_statistics(series_list: List[Dict]) -> Dict[str, Any]:
    """
    Get statistics about series list
    
    Args:
        series_list: List of series dictionaries
        
    Returns:
        dict: Statistics about the series
    """
    if not series_list:
        return {
            'total_series': 0,
            'total_images': 0,
            'modalities': {},
            'average_images_per_series': 0
        }
    
    total_series = len(series_list)
    total_images = sum(s.get('image_count', 0) for s in series_list)
    
    # Count modalities
    modalities = {}
    for series in series_list:
        modality = series.get('modality', 'Unknown')
        modalities[modality] = modalities.get(modality, 0) + 1
    
    # Calculate average
    average_images = total_images / total_series if total_series > 0 else 0
    
    return {
        'total_series': total_series,
        'total_images': total_images,
        'modalities': modalities,
        'average_images_per_series': round(average_images, 2)
    }


def get_series_from_database(study_uid: str) -> Optional[List[Dict]]:
    """
    Get series information from database
    
    Args:
        study_uid: Study Instance UID
        
    Returns:
        List[Dict]: Series information from database or None if not found
    """
    try:
        study_pk = find_study_pk_with_study_uid(study_uid)
        if not study_pk:
            return None
        
        series_list = get_series_by_study_pk(study_pk)
        return series_list
        
    except Exception as e:
        logger.warning("Error getting series from database: %s", e)
        return None


def compare_series_lists(server_series: List[Dict], db_series: List[Dict]) -> Dict[str, Any]:
    """
    Compare series lists from server and database
    
    Args:
        server_series: Series list from server
        db_series: Series list from database
        
    Returns:
        dict: Comparison results
    """
    server_uids = {s.get('series_uid') for s in server_series}
    db_uids = {s.get('series_uid') for s in db_series}
    
    only_in_server = server_uids - db_uids
    only_in_db = db_uids - server_uids
    in_both = server_uids & db_uids
    
    return {
        'server_count': len(server_series),
        'db_count': len(db_series),
        'only_in_server': len(only_in_server),
        'only_in_db': len(only_in_db),
        'in_both': len(in_both),
        'missing_in_db': list(only_in_server),
        'extra_in_db': list(only_in_db)
    }


def print_series_summary(series_list: List[Dict], title: str = "Series Summary", *, use_logger: bool = False):
    """
    Print a formatted summary of series information
    
    Args:
        series_list: List of series dictionaries
        title: Title for the summary
        use_logger: If True, emit summary via logger.info instead of console print
    """
    emit = logger.info if use_logger else _emit_cli

    emit(f"\n{title}")
    emit("=" * len(title))
    
    if not series_list:
        emit("No series found")
        return
    
    stats = get_series_statistics(series_list)
    
    emit(f"📊 Total Series: {stats['total_series']}")
    emit(f"🖼️ Total Images: {stats['total_images']}")
    emit(f"📈 Average Images per Series: {stats['average_images_per_series']}")
    
    emit(f"\n🔬 Modalities:")
    for modality, count in stats['modalities'].items():
        emit(f"   {modality}: {count} series")
    
    emit(f"\n📋 Series Details:")
    for i, series in enumerate(series_list, 1):
        emit(f"   {i}. Series {series.get('series_number', 'N/A')}:")
        emit(f"      📝 Description: {series.get('series_description', 'N/A')}")
        emit(f"      🔬 Modality: {series.get('modality', 'N/A')}")
        emit(f"      🖼️ Images: {series.get('image_count', 0)}")
        emit(f"      🆔 UID: {series.get('series_uid', 'N/A')[:20]}...")


# Example usage functions
def example_usage():
    """
    Example usage of series utilities
    """
    _emit_cli("🚀 Series Utilities Example")
    _emit_cli("=" * 30)
    
    # Example series data (simulated gRPC response)
    example_series = [
        {
            'series_uid': '1.2.3.4.5.6.7.8.9.1',
            'series_number': '1',
            'series_description': 'Axial T1',
            'modality': 'MR',
            'image_count': 20,
            'protocol_name': 'Brain T1',
            'body_part_examined': 'BRAIN'
        },
        {
            'series_uid': '1.2.3.4.5.6.7.8.9.2',
            'series_number': '2',
            'series_description': 'Axial T2',
            'modality': 'MR',
            'image_count': 20,
            'protocol_name': 'Brain T2',
            'body_part_examined': 'BRAIN'
        },
        {
            'series_uid': '1.2.3.4.5.6.7.8.9.3',
            'series_number': '3',
            'series_description': 'Chest CT',
            'modality': 'CT',
            'image_count': 50,
            'protocol_name': 'Chest Routine',
            'body_part_examined': 'CHEST'
        }
    ]
    
    # Print summary
    print_series_summary(example_series, "Example Series Data")
    
    # Filter examples
    _emit_cli(f"\n🔍 Filter Examples:")
    
    mr_series = filter_series_by_modality(example_series, 'MR')
    _emit_cli(f"   MR Series: {len(mr_series)}")
    
    ct_series = filter_series_by_modality(example_series, 'CT')
    _emit_cli(f"   CT Series: {len(ct_series)}")
    
    axial_series = filter_series_by_keyword(example_series, 'axial')
    _emit_cli(f"   Axial Series: {len(axial_series)}")
    
    # Statistics
    stats = get_series_statistics(example_series)
    _emit_cli(f"\n📊 Statistics:")
    _emit_cli(f"   Total Series: {stats['total_series']}")
    _emit_cli(f"   Total Images: {stats['total_images']}")
    _emit_cli(f"   Average Images: {stats['average_images_per_series']}")


if __name__ == "__main__":
    example_usage()
