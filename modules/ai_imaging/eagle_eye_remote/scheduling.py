"""Bounded FIFO resource reservations for isolated server inference workers."""
from contextlib import contextmanager
from collections import deque
import threading

from .contracts import MODULES


class Resources:
    def __init__(self, configuration=None):
        configuration = configuration or {}
        self.capacity = dict(configuration.get('capacity', {'jobs': 1}))
        self.profiles = configuration.get('modules', {name: {'jobs': 1} for name in MODULES})
        if (not self.capacity or set(self.capacity) - {'jobs', 'cpu_threads', 'ram_mb'}
                or 'jobs' not in self.capacity
                or any(type(value) is not int or value <= 0 for value in self.capacity.values())
                or not 1 <= self.capacity['jobs'] <= 8
                or set(self.profiles) != set(MODULES)):
            raise ValueError('Configure positive server resource limits and every module budget.')
        for profile in self.profiles.values():
            if (not isinstance(profile, dict) or set(profile) != set(self.capacity)
                    or profile.get('jobs') != 1
                    or any(type(value) is not int or not 0 < value <= self.capacity[key]
                           for key, value in profile.items())):
                raise ValueError('Each module requires a bounded resource profile within server capacity.')
        if self.capacity['jobs'] > 1 and not {'cpu_threads', 'ram_mb'}.issubset(self.capacity):
            raise ValueError('Parallel execution requires explicit CPU and RAM budgets for all modules.')
        self.profiles = {name: dict(profile) for name, profile in self.profiles.items()}
        self.used = {key: 0 for key in self.capacity}
        self.pending = deque()
        self.condition = threading.Condition()

    @contextmanager
    def lease(self, module, cancel):
        cost = self.profiles[module]
        ticket = object()
        acquired = False
        with self.condition:
            self.pending.append(ticket)
            try:
                while True:
                    if cancel.is_set():
                        raise RuntimeError('Analysis cancelled while waiting for server resources.')
                    if self.pending[0] is ticket and all(
                            self.used[key] + cost[key] <= self.capacity[key] for key in cost):
                        self.pending.popleft()
                        for key in cost:
                            self.used[key] += cost[key]
                        acquired = True
                        self.condition.notify_all()
                        break
                    self.condition.wait(.1)
            finally:
                if not acquired:
                    self.pending.remove(ticket)
                    self.condition.notify_all()
        try:
            yield
        finally:
            with self.condition:
                for key in cost:
                    self.used[key] -= cost[key]
                self.condition.notify_all()
