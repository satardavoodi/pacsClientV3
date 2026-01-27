"""
Reception Data Service Module

This module provides functionality to fetch and manage patient reception data from the API.
It handles HTTP requests to retrieve patient information based on reception ID.
"""

import requests
from typing import Dict, Optional, Any
from PySide6.QtCore import QObject, Signal, QThread


class ReceptionDataFetchWorker(QThread):
    """
    Worker thread for fetching reception data from API without blocking the UI.
    
    Signals:
        finished: Emitted when data fetch is successful with the response data
        error: Emitted when an error occurs with error message
    """
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, patient_id: str, base_url: str = "http://81.16.117.196:8080"):
        """
        Initialize the worker.
        
        Args:
            patient_id: The patient ID to fetch data for
            base_url: Base URL of the API server
        """
        super().__init__()
        self.patient_id = patient_id
        self.base_url = base_url
        self.canceled = False
    
    def run(self):
        """Execute the API request in background."""
        try:
            # Construct URL with query parameter  
            # Try to determine if patient_id is a reception ID (numeric) or National Code
            url = f"{self.base_url}/api/pacs/patients"
            
            # If patient_id looks like a number and length < 10, assume it's receptionId
            # Otherwise use nationalCode
            if self.patient_id and self.patient_id.isdigit() and len(self.patient_id) < 10:
                params = {"receptionId": self.patient_id}
                print(f"[ReceptionDataService] Using receptionId: {self.patient_id}")
            else:
                params = {"nationalCode": self.patient_id}
                print(f"[ReceptionDataService] Using nationalCode: {self.patient_id}")
            
            print(f"[ReceptionDataService] Fetching data from: {url}")
            print(f"[ReceptionDataService] Parameters: {params}")
            
            # Make GET request (the API uses GET with query params, not POST)
            response = requests.get(url, params=params, timeout=30)
            
            print(f"[ReceptionDataService] Response status: {response.status_code}")
            print(f"[ReceptionDataService] Response text: {response.text[:500]}")
            
            # Check if request was successful
            response.raise_for_status()
            
            # Parse JSON response
            data = response.json()
            
            # Emit success signal with data
            if not self.canceled:
                self.finished.emit(data)
                
        except requests.exceptions.Timeout:
            if not self.canceled:
                self.error.emit("Request timeout. Please check your connection.")
        except requests.exceptions.ConnectionError:
            if not self.canceled:
                self.error.emit("Connection error. Please check server availability.")
        except requests.exceptions.HTTPError as e:
            if not self.canceled:
                self.error.emit(f"HTTP Error: {e.response.status_code}")
        except Exception as e:
            if not self.canceled:
                self.error.emit(f"Unexpected error: {str(e)}")
    
    def cancel(self):
        """Cancel the ongoing request."""
        self.canceled = True


class ReceptionDataService(QObject):
    """
    Service class for managing reception data API calls.
    
    Signals:
        data_received: Emitted when data is successfully received
        error_occurred: Emitted when an error occurs
    """
    data_received = Signal(dict)
    error_occurred = Signal(str)
    
    def __init__(self, base_url: str = "http://81.16.117.196:8080"):
        """
        Initialize the service.
        
        Args:
            base_url: Base URL of the API server
        """
        print(f"[ReceptionDataService] __init__ called with base_url: {base_url}")
        super().__init__()
        self.base_url = base_url
        self.current_worker = None
        print("[ReceptionDataService] __init__ completed")
    
    def fetch_patient_data(self, patient_id: str):
        """
        Fetch patient data by patient ID asynchronously.
        
        Args:
            patient_id: The patient ID to fetch data for
        """
        print(f"[ReceptionDataService] Starting fetch for patient ID: {patient_id}")
        
        # Cancel any ongoing request
        if self.current_worker and self.current_worker.isRunning():
            print("[ReceptionDataService] Canceling previous request")
            self.current_worker.cancel()
            self.current_worker.wait()
        
        # Create and start new worker
        self.current_worker = ReceptionDataFetchWorker(patient_id, self.base_url)
        self.current_worker.finished.connect(self._on_data_received)
        self.current_worker.error.connect(self._on_error)
        self.current_worker.start()
    
    def _on_data_received(self, data: dict):
        """
        Handle successful data reception.
        
        Args:
            data: The received data from API
        """
        print(f"[ReceptionDataService] Data received successfully")
        print(f"[ReceptionDataService] Data keys: {data.keys() if data else 'None'}")
        self.data_received.emit(data)
    
    def _on_error(self, error_message: str):
        """
        Handle error occurrence.
        
        Args:
            error_message: The error message
        """
        print(f"[ReceptionDataService] Error occurred: {error_message}")
        self.error_occurred.emit(error_message)
    
    def cancel_request(self):
        """Cancel any ongoing request."""
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.cancel()
            self.current_worker.wait()

