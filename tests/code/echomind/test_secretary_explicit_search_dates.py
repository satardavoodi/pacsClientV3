from modules.EchoMind.secretary.executor import SecretaryExecutor


def test_server_explicit_date_range_reaches_search():
    class Home:
        def is_available(self): return True
        def get_active_source(self): return "server"
        def search(self, source, criteria): self.criteria = criteria
        def list_rows(self): return []
    home = Home()
    executor = SecretaryExecutor(home)
    result = executor._list_patients({"action": "list_patients", "entities": {
        "date_from": "20261001", "date_to": "20261001", "modality": "MR"}}, {})
    assert result["ok"]
    assert home.criteria == {"date_from": "20261001", "date_to": "20261001", "modality": "MR"}


def test_invalid_explicit_date_does_not_broaden_search():
    class Home:
        def is_available(self): return True
        def get_active_source(self): return "server"
        def search(self, **kwargs): raise AssertionError("must not search")
    result = SecretaryExecutor(Home())._list_patients({"entities": {"date_from": "20261301", "date_to": "20261001"}}, {})
    assert not result["ok"] and result["error_code"] == "INVALID_DATE_RANGE"
