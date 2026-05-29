from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    def shutdown(self, wait=False, cancel_futures=True):
        self.calls.append((wait, cancel_futures))


def test_lightweight_pipeline_shutdown_closes_decode_and_frame_executors():
    pipe = Lightweight2DPipeline.__new__(Lightweight2DPipeline)
    close_calls = []
    decode_executor = _FakeExecutor()
    frame_executor = _FakeExecutor()

    pipe.close_series = lambda: close_calls.append("closed")
    pipe._decode_executor = decode_executor
    pipe._frame_executor = frame_executor

    pipe.shutdown()

    assert close_calls == ["closed"]
    assert decode_executor.calls == [(False, True)]
    assert frame_executor.calls == [(False, True)]


def test_lightweight_pipeline_shutdown_tolerates_missing_executor_attributes():
    pipe = Lightweight2DPipeline.__new__(Lightweight2DPipeline)
    close_calls = []
    decode_executor = _FakeExecutor()

    pipe.close_series = lambda: close_calls.append("closed")
    pipe._decode_executor = decode_executor

    pipe.shutdown()

    assert close_calls == ["closed"]
    assert decode_executor.calls == [(False, True)]