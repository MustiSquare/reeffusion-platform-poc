from app.services import loading_progress as progress


def test_progress_is_monotonic_and_expires(monkeypatch):
    class Client:
        def __init__(self): self.values = {}
        def setex(self, key, ttl, value):
            assert ttl == 3600
            self.values[key] = value
        def get(self, key): return self.values.get(key)
    monkeypatch.setattr(progress, 'client', Client())
    with progress.operation('test'):
        progress.report(60, 'Decoding', 'running')
        progress.report(80, 'Saving', 'ready')
        progress.report(30, 'Late update', 'ready')
        assert progress.read('test')['percent'] == 80
    assert progress.read('test')['status'] == 'ready'
    assert progress.current.get() is None


def test_progress_outage_does_not_fail_loading(monkeypatch):
    monkeypatch.setattr(progress, 'client', None)
    with progress.operation('test'): progress.report(50, 'Decoding')
    assert progress.read('test')['status'] == 'unavailable'
