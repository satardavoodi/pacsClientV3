from .home_ui import HomePanelWidget
from .right_panel_widget import RightPanelWidget
from .patient_search_widget import PatientSearchWidget
from .patient_table_widget import PatientTableWidget
from .data_access_panel import DataAccessPanelWidget
from .home_db_service import HomeDbService
from .home_tab_service import HomeTabService
from .home_download_service import HomeDownloadService
from .home_search_service import HomeSearchService
from .home_widget_utils import is_widget_alive

try:
    from .secretary_button_widget import SecretaryButtonWidget
except Exception:
    # Optional EchoMind plugin dependency can be intentionally excluded in
    # Nuitka core builds; keep package import-safe for startup.
    SecretaryButtonWidget = None

__all__ = [
    'HomePanelWidget', 'PatientSearchWidget', 'PatientTableWidget',
    'DataAccessPanelWidget',
    'HomeDbService', 'HomeTabService', 'HomeDownloadService',
    'HomeSearchService', 'is_widget_alive',
]

if SecretaryButtonWidget is not None:
    __all__.append('SecretaryButtonWidget')
