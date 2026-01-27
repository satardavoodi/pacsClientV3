"""
On-Demand Series Downloader
دانلودگر سری به صورت درخواستی

Downloads individual series on-demand using socket connection with GetSeriesImages endpoint
"""

import socket
import json
import gzip
import os
from pathlib import Path
from typing import Optional, Callable
from PacsClient.utils.socket_token_manager import get_socket_token_manager


class SeriesDownloader:
    """
    Downloads individual series on-demand using socket connection
    دانلود سری‌های جداگانه به صورت درخواستی با استفاده از socket
    """
    
    def __init__(self, host='localhost', port=50052):
        """
        Initialize socket-based series downloader
        
        Args:
            host: Server hostname
            port: Socket port (default 50052 for socket service)
        """
        self.host = host
        self.port = port
        self.socket = None
    
    def __del__(self):
        """Ensure socket is closed when object is destroyed"""
        self.disconnect()
    
    def connect(self) -> bool:
        """Establish socket connection to server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            return True
            
        except Exception as e:
            return False
    
    def disconnect(self):
        """Close socket connection"""
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
                self.socket = None
            except:
                try:
                    self.socket.close()
                    self.socket = None
                except:
                    pass
    
    def _send_request(self, request_data: dict) -> dict:
        """
        Send request and receive response via socket
        
        Args:
            request_data: Request dictionary
            
        Returns:
            Response dictionary
        """
        try:
            # Convert to JSON and send
            request_json = json.dumps(request_data)
            request_bytes = request_json.encode('utf-8')
            
            # Send length first (4 bytes)
            length = len(request_bytes)
            self.socket.sendall(length.to_bytes(4, byteorder='big'))
            
            # Send data
            self.socket.sendall(request_bytes)
            
            # Receive response length
            length_bytes = self._recv_exactly(4)
            response_length = int.from_bytes(length_bytes, byteorder='big')
            
            # Receive response data
            response_bytes = self._recv_exactly(response_length)
            response_json = response_bytes.decode('utf-8')
            response_data = json.loads(response_json)
            
            return response_data
            
        except Exception as e:
            raise
    
    def _recv_exactly(self, n: int) -> bytes:
        """Receive exactly n bytes from socket"""
        data = b''
        while len(data) < n:
            chunk = self.socket.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Socket connection closed")
            data += chunk
        return data
    
    def download_series(
        self,
        series_uid: str,
        output_dir: str,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
        batch_size: int = 10,
        max_retries: int = 3
    ) -> bool:
        """
        Download a specific series using GetSeriesImages endpoint with batch loading
        and automatic retry on failure.
        
        Args:
            series_uid: Series Instance UID
            output_dir: Directory to save DICOM files
            progress_callback: Optional callback(current, total, percent)
            batch_size: Number of instances per batch (default: 10)
            max_retries: Maximum number of retry attempts per batch (default: 3)
        
        Returns:
            bool: True if successful
        """
        if not self.socket:
            # Try to reconnect
            if not self.connect():
                print(f"❌ Cannot download series - no socket connection")
                return False
        
        try:
            # Create output directory
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
            batch_index = 0
            has_more = True
            total_downloaded = 0
            total_instances = None
            consecutive_failures = 0
            max_consecutive_failures = 5
            
            while has_more:
                # Create request for GetSeriesImages with batch parameters
                request = {
                    "endpoint": "GetSeriesImages",
                    "params": {
                        "series_uid": series_uid,
                        "batch_size": batch_size,
                        "batch_index": batch_index,
                        "metadata_only": False
                    }
                }
                
                # Add token to request
                try:
                    token_manager = get_socket_token_manager()
                    request = token_manager.add_token_to_request(request)
                except Exception as e:
                    print(f"⚠️ Token error: {e}")
                
                # Try to send request with retries
                response = None
                for attempt in range(max_retries):
                    try:
                        response = self._send_request(request)
                        if response:
                            consecutive_failures = 0
                            break
                    except Exception as e:
                        print(f"⚠️ Request attempt {attempt + 1}/{max_retries} failed: {e}")
                        consecutive_failures += 1
                        
                        # Try to reconnect
                        if attempt < max_retries - 1:
                            self.disconnect()
                            import time
                            time.sleep(1)  # Wait before reconnecting
                            if not self.connect():
                                print(f"⚠️ Reconnection failed, will retry...")
                
                if not response:
                    print(f"⚠️ Batch {batch_index} failed after {max_retries} attempts")
                    if consecutive_failures >= max_consecutive_failures:
                        print(f"❌ Too many consecutive failures, aborting download")
                        return total_downloaded > 0  # Return True if we got some data
                    batch_index += 1
                    continue
                
                # Check response status
                if response.get('status') != 'success':
                    error_msg = response.get('message', 'Unknown error')
                    print(f"⚠️ Server error for batch {batch_index}: {error_msg}")
                    batch_index += 1
                    continue
                
                # Get data from response
                data = response.get('data', {})
                instances = data.get('instances', [])
                
                # Get total instances count from first batch
                if total_instances is None:
                    total_instances = data.get('total_instances', len(instances))
                
                if not instances:
                    # No more instances in this batch
                    break
                
                # Process instances in this batch
                import base64
                for instance in instances:
                    try:
                        dicom_data_b64 = instance.get('dicom_data', '')
                        is_compressed = instance.get('is_compressed', False)
                        instance_number = instance.get('instance_number', total_downloaded + 1)
                        
                        try:
                            instance_number = int(instance_number)
                        except (ValueError, TypeError):
                            instance_number = total_downloaded + 1
                        
                        if not dicom_data_b64:
                            continue
                        
                        dicom_data = base64.b64decode(dicom_data_b64)
                        
                        if is_compressed:
                            dicom_data = gzip.decompress(dicom_data)
                        
                        file_name = f"Instance_{instance_number:04d}.dcm"
                        file_path = os.path.join(output_dir, file_name)
                        
                        with open(file_path, 'wb') as f:
                            f.write(dicom_data)
                        
                        total_downloaded += 1
                        
                        # Progress callback
                        percent = (total_downloaded / total_instances) * 100 if total_instances else 0
                        if progress_callback:
                            try:
                                progress_callback(total_downloaded, total_instances, percent)
                            except:
                                pass  # Ignore callback errors
                    
                    except Exception as inst_error:
                        print(f"⚠️ Error processing instance {instance.get('instance_number', '?')}: {inst_error}")
                        continue  # Continue with next instance
                
                # Check if there are more batches
                has_more = data.get('has_more', False)
                
                # SAFETY CHECK: Even if server says no more, continue if we haven't downloaded all
                if not has_more and total_instances and total_downloaded < total_instances:
                    # Check if we're making progress
                    if batch_index > (total_instances // batch_size) + 2:
                        # We've tried too many batches, server probably doesn't have more
                        break
                    has_more = True
                
                # Break if we've downloaded all instances
                if total_instances and total_downloaded >= total_instances:
                    break
                
                batch_index += 1
            
            return total_downloaded > 0  # Success if we downloaded at least one file
            
        except Exception as e:
            print(f"❌ Error downloading series: {e}")
            import traceback
            traceback.print_exc()
            return total_downloaded > 0 if 'total_downloaded' in dir() else False
    
    def download_series_for_study(
        self,
        study_uid: str,
        series_list: list,
        base_output_dir: str,
        progress_callback: Optional[Callable[[str, int, int, float], None]] = None
    ) -> dict:
        """
        Download multiple series for a study
        
        Args:
            study_uid: Study Instance UID
            series_list: List of dicts with 'series_uid' and 'series_number'
            base_output_dir: Base directory for study
            progress_callback: Optional callback(series_uid, current, total, percent)
        
        Returns:
            dict: Results with 'success', 'failed', 'total'
        """
        results = {'success': [], 'failed': [], 'total': len(series_list)}
        
        for idx, series_info in enumerate(series_list):
            series_uid = series_info.get('series_uid')
            series_number = series_info.get('series_number', f'series_{idx+1}')
            
            # Create series directory
            series_dir = os.path.join(base_output_dir, str(series_number))
            
            # Download series with progress callback
            def series_progress(current, total, percent):
                if progress_callback:
                    progress_callback(series_uid, current, total, percent)
            
            success = self.download_series(series_uid, series_dir, series_progress)
            
            if success:
                results['success'].append(series_uid)
            else:
                results['failed'].append(series_uid)
        
        return results


# def test_series_downloader():
#     """Test the series downloader"""
#     downloader = SeriesDownloader(host='81.16.117.196', port=50052)
#
#     if not downloader.connect():
#         return
#
#     # Test with a series
#     series_uid = "1.2.840.113619.2.55.3..."  # Replace with actual UID
#     output_dir = "./test_series"
#
#     def progress(current, total, percent):
#         print(f"Progress: {current}/{total} ({percent:.1f}%)")
#
#     success = downloader.download_series(series_uid, output_dir, progress)
#
#     if success:
#         print("✅ Test successful!")
#     else:
#         print("❌ Test failed!")
#
#     downloader.disconnect()
#
#
# if __name__ == "__main__":
#     test_series_downloader()

