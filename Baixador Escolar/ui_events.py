"""Filas de UI que preservam eventos funcionais e agrupam telemetria."""

from collections import deque
from collections.abc import Callable
from queue import Empty
from threading import Lock
from typing import Generic, TypeVar


T = TypeVar("T")


class CoalescingQueue(Generic[T]):
    """Agrupa progresso consecutivo da mesma operação, sem cruzar fases/términos.

    A chave None identifica um evento estrutural. Outras chaves identificam
    amostras substituíveis da mesma geração. O produtor nunca aguarda a UI.
    """

    def __init__(self, progress_key: Callable[[T], object | None]) -> None:
        self._progress_key = progress_key
        self._events: deque[T] = deque()
        self._pending: tuple[object, T] | None = None
        self._lock = Lock()

    def put(self, event: T) -> None:
        key = self._progress_key(event)
        with self._lock:
            if key is None or (self._pending is not None and key != self._pending[0]):
                if self._pending is not None:
                    self._events.append(self._pending[1])
                    self._pending = None
            if key is None:
                self._events.append(event)
            else:
                self._pending = (key, event)

    def get_nowait(self) -> T:
        with self._lock:
            if self._events:
                return self._events.popleft()
            if self._pending is not None:
                event = self._pending[1]
                self._pending = None
                return event
        raise Empty

    def qsize(self) -> int:
        with self._lock:
            return len(self._events) + int(self._pending is not None)

    def empty(self) -> bool:
        return self.qsize() == 0
