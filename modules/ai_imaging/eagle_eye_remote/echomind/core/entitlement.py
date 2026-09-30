from .api_manager import Manage


def company_entitled():
    return Manage.instance().is_validated()
