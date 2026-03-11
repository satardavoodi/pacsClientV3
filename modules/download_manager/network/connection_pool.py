"""
Connection Pool - Reusable socket connections for parallel downloads

Manages pool of socket connections to avoid connection overhead.
"""

import logging
import queue
import threading
from typing import Optional

from .socket_client import SocketDicomClient

logger = logging.getLogger(__name__)


class ConnectionPool:
    """
    Connection pool for socket clients
    
    Features:
    - Reusable connections
    - Thread-safe operations
    - Automatic cleanup
    - Health checking
    """
    
    def __init__(
        self,
        host: str,
        port: int,
        pool_size: int = 4,
        token_manager = None
    ):
        """
        Initialize connection pool
        
        Args:
            host: Server host
            port: Server port
            pool_size: Number of connections in pool
            token_manager: Token manager for authentication
        """
        self.host = host
        self.port = port
        self.pool_size = pool_size
        self.token_manager = token_manager
        
        self.connections = queue.Queue(maxsize=pool_size)
        self.lock = threading.Lock()
        
        # Initialize pool
        self._initialize_pool()
        
        logger.info(f"✅ ConnectionPool initialized (size: {pool_size})")
    
    def _initialize_pool(self) -> None:
        """Initialize connection pool"""
        for _ in range(self.pool_size):
            client = SocketDicomClient(
                host=self.host,
                port=self.port,
                token_manager=self.token_manager
            )
            self.connections.put(client)
    
    def get_connection(self, timeout: float = 30.0) -> Optional[SocketDicomClient]:
        """
        Get connection from pool
        
        Args:
            timeout: Timeout for getting connection
            
        Returns:
            SocketDicomClient or None if timeout
        """
        try:
            client = self.connections.get(timeout=timeout)
            
            # Ensure connected
            if not client.connected and not client.connect():
                # Connection failed - try to create new one
                client = SocketDicomClient(
                    host=self.host,
                    port=self.port,
                    token_manager=self.token_manager
                )
                if not client.connect():
                    # Put back in pool and return None
                    self.connections.put(client)
                    return None
            
            return client
        
        except queue.Empty:
            logger.warning("⚠️ Connection pool timeout - no available connections")
            return None
    
    def return_connection(self, client: SocketDicomClient) -> None:
        """
        Return connection to pool
        
        Args:
            client: Client to return
        """
        try:
            self.connections.put_nowait(client)
        except queue.Full:
            # Pool is full - close this connection
            client.disconnect()
            logger.debug("Pool full - closed excess connection")
    
    def close_all(self) -> None:
        """Close all connections in pool"""
        with self.lock:
            while not self.connections.empty():
                try:
                    client = self.connections.get_nowait()
                    client.disconnect()
                except queue.Empty:
                    break
            
            logger.info("🔌 All connections closed")
    
    def __del__(self):
        """Destructor - ensure cleanup"""
        try:
            self.close_all()
        except:
            pass
