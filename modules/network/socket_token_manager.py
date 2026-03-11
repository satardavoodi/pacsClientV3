# -*- coding: utf-8 -*-
"""
Socket Token Manager
مدیریت توکن احراز هویت برای Socket Server

این ماژول یک singleton manager برای ذخیره و مدیریت token احراز هویت است
که باید در تمام request های socket ارسال شود.
"""

import threading
from typing import Optional, Dict, Any


class SocketTokenManager:
    """
    Singleton manager for socket authentication token
    
    این کلاس token را ذخیره می‌کند و به تمام socket client ها دسترسی می‌دهد
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        
        self._token: Optional[str] = None
        self._user: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self._initialized = True
    
    @classmethod
    def instance(cls) -> "SocketTokenManager":
        """Get the singleton instance"""
        return cls()
    
    def set_token(self, token: str, user: Optional[Dict[str, Any]] = None) -> None:
        """
        ذخیره token و اطلاعات کاربر
        
        Args:
            token: JWT token از سرور
            user: اطلاعات کاربر (اختیاری)
        """
        with self._lock:
            self._token = token
            self._user = user
    
    def get_token(self) -> Optional[str]:
        """
        دریافت token فعلی
        
        Returns:
            Token string یا None اگر token وجود نداشته باشد
        """
        with self._lock:
            return self._token
    
    def get_user(self) -> Optional[Dict[str, Any]]:
        """
        دریافت اطلاعات کاربر
        
        Returns:
            Dictionary با اطلاعات کاربر یا None
        """
        with self._lock:
            return self._user
    
    def clear_token(self) -> None:
        """پاک کردن token و اطلاعات کاربر"""
        with self._lock:
            self._token = None
            self._user = None
    
    def has_token(self) -> bool:
        """
        بررسی وجود token
        
        Returns:
            True اگر token وجود داشته باشد
        """
        with self._lock:
            return self._token is not None
    
    def add_token_to_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        اضافه کردن token به request
        
        طبق راهنمای سرور، token باید در سطح request اضافه شود:
        {
            "endpoint": "...",
            "token": "...",
            "params": {...}
        }
        
        Args:
            request: Request dictionary که باید token به آن اضافه شود
            
        Returns:
            Request dictionary با token اضافه شده
        """
        token = self.get_token()
        if token:
            # اضافه کردن token در سطح request (توصیه شده در راهنما)
            request["token"] = token
        return request


# Global accessor function
def get_socket_token_manager() -> SocketTokenManager:
    """Get the global socket token manager instance"""
    return SocketTokenManager.instance()

