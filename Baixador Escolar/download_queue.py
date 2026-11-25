"""Motor FIFO independente de Tk, com posse exclusiva de um DownloadService.

O serviço fornecido deve estar ocioso, com stream vazio, e não pode ser usado
por outro consumidor (inclusive a UI atual). Só o coordenador chama start/cancel
ou consome events. Atualizações podem usar a reserva pública do mesmo serviço.

Snapshots são a API de observação: não há fila de notificações nem histórico
crescente. Términos ficam retidos até remove(); o limite inclui esses itens.
DownloadBusyError suspende o despacho até retry() explícito, preservando FIFO.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from queue import Empty
from threading import Condition, Event, Thread, current_thread
from uuid import uuid4

from constants import CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO, VIDEO_QUALITIES
from downloader import (
    DownloadBusyError,
    DownloadEvent,
    DownloadEventBuffer,
    DownloadEventKind,
    DownloadPhase,
    DownloadProgress,
    DownloadRequest,
    DownloadResult,
    DownloadService,
    DownloadServiceError,
    _redact_sensitive_text,
)
from mp3_quality import Mp3Quality
from utils import is_valid_url


class QueueState(StrEnum):
    WAITING = "waiting"
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


_TERMINAL = frozenset({QueueState.COMPLETED, QueueState.CANCELLED, QueueState.ERROR})
_POLL_SECONDS = 0.05
_EVENT_BATCH = 128


class _QueueEventBuffer(DownloadEventBuffer):
    """Última fase e progresso; todos os términos são preservados.

    Só o stream sob posse da fila usa este buffer. O serviço publica exatamente
    um término por operação. Antes do próximo start, a fila aguarda a liberação
    e esvazia o stream: no máximo duas amostras e um término ficam pendentes.
    A ordem relativa das amostras restantes e do término é preservada.
    """

    def put(self, event: DownloadEvent) -> None:
        with self._lock:
            if event.kind in {DownloadEventKind.PHASE, DownloadEventKind.PROGRESS}:
                self._events = deque(
                    previous for previous in self._events if previous.kind != event.kind
                )
            self._events.append(event)


@dataclass(frozen=True)
class QueueItem:
    """Snapshot; dados pessoais só aparecem quando acessados explicitamente."""

    id: str
    request: DownloadRequest = field(repr=False)
    state: QueueState = QueueState.WAITING
    progress: DownloadProgress | None = None
    result: DownloadResult | None = field(default=None, repr=False)
    error: str | None = None
    cancel_requested: bool = False


class DownloadQueueError(ValueError):
    """Rejeição controlada com mensagem pública, sem ecoar a entrada."""


def _validate_request(request: DownloadRequest) -> None:
    # Validação estrutural apenas. Ferramentas, pasta, permissões e comandos
    # continuam sendo validados pelo serviço no instante da execução.
    if (
        not isinstance(request, DownloadRequest)
        or not isinstance(request.url, str)
        or len(request.url) > 16_384
        or not is_valid_url(request.url)
        or not isinstance(request.content_type, str)
        or request.content_type not in {CONTENT_TYPE_AUDIO, CONTENT_TYPE_VIDEO}
        or not isinstance(request.quality, str)
        or len(request.quality) > 100
        or (
            request.content_type == CONTENT_TYPE_VIDEO
            and request.quality not in VIDEO_QUALITIES
        )
        or not isinstance(request.mp3_quality, Mp3Quality)
        or (
            request.destination_dir is not None
            and (
                not isinstance(request.destination_dir, Path)
                or not request.destination_dir.is_absolute()
                or len(str(request.destination_dir)) > 32_768
            )
        )
    ):
        raise DownloadQueueError("Solicitação de download inválida.")


class DownloadQueue:
    """Uma thread coordenadora e, no máximo, uma operação do serviço.

    A seleção sob o lock é o ponto de início de PREPARING. start() pode fazer
    I/O; cancel/shutdown registram a intenção sem esperar essa preparação. O
    cancelamento é enviado assim que start() retorna, antes de outro despacho.
    shutdown(timeout) retorna False se a liberação ainda não foi confirmada;
    nesse caso o coordenador continua responsável pela operação e pode-se
    aguardar novamente. Nunca se deve abandonar a instância nesse estado.
    """

    def __init__(self, service: DownloadService, *, max_items: int = 100) -> None:
        if type(max_items) is not int or not 1 <= max_items <= 100:
            raise DownloadQueueError("O limite da fila deve estar entre 1 e 100.")
        if service.is_running or not service.events.empty():
            raise DownloadQueueError("O serviço deve estar ocioso e sem eventos.")
        self._service = service
        # Transferência explícita de posse; nunca conectar à instância da UI.
        original_events = service.events
        service.events = _QueueEventBuffer()
        self._max_items = max_items
        self._items: dict[str, QueueItem] = {}
        self._pending: deque[str] = deque()
        self._active: str | None = None
        self._blocked = False
        self._closing = False
        self._shutdown_revision = 0
        self._closed = Event()
        self._control_error: str | None = None
        self._condition = Condition()
        self._worker = Thread(target=self._run, name="download-queue", daemon=True)
        try:
            self._worker.start()
        except Exception:
            service.events = original_events
            raise DownloadQueueError(
                "Não foi possível iniciar o motor da fila."
            ) from None

    def add(self, request: DownloadRequest) -> str:
        """Registra um item; preserva o request imutável e retorna UUID estável."""
        _validate_request(request)
        with self._condition:
            if self._closing:
                raise DownloadQueueError("A fila está encerrando.")
            if len(self._items) >= self._max_items:
                raise DownloadQueueError("A fila atingiu o limite de itens.")
            item_id = uuid4().hex
            self._items[item_id] = QueueItem(item_id, request)
            self._pending.append(item_id)
            self._condition.notify_all()
            return item_id

    def get(self, item_id: str) -> QueueItem:
        """Obtém snapshot imutável; identificadores desconhecidos geram KeyError."""
        with self._condition:
            return self._items[item_id]

    def items(self) -> tuple[QueueItem, ...]:
        """Consulta todos os itens na ordem de inclusão, inclusive os terminais."""
        with self._condition:
            return tuple(self._items.values())

    @property
    def blocked(self) -> bool:
        """O serviço recusou um início por estar ocupado; aguarda retry()."""
        with self._condition:
            return self._blocked

    def retry(self) -> bool:
        """Autoriza uma nova tentativa após ocupação; não reinicia itens falhos."""
        with self._condition:
            if self._closing or not self._blocked:
                return False
            self._blocked = False
            self._condition.notify_all()
            return True

    def retry_item(self, item_id: str) -> None:
        """Repõe uma tentativa encerrada no fim da fila com o mesmo pedido."""
        with self._condition:
            item = self._items[item_id]
            if self._closing:
                raise DownloadQueueError("A fila está encerrando.")
            if item.state not in {QueueState.ERROR, QueueState.CANCELLED}:
                raise DownloadQueueError("Este item não pode ser repetido.")
            if self._active == item_id:
                raise DownloadQueueError(
                    "Aguarde a liberação dos recursos deste download."
                )
            del self._items[item_id]
            self._items[item_id] = QueueItem(item_id, item.request)
            self._pending.append(item_id)
            self._condition.notify_all()

    def cancel(self, item_id: str) -> bool:
        """Cancela espera ou registra intenção; ativo só termina por confirmação."""
        with self._condition:
            item = self._items[item_id]
            if item.state in _TERMINAL or item.cancel_requested:
                return False
            if self._active != item_id:
                self._pending.remove(item_id)
                self._items[item_id] = replace(
                    item, state=QueueState.CANCELLED, cancel_requested=True
                )
            else:
                self._items[item_id] = replace(item, cancel_requested=True)
            self._condition.notify_all()
            return True

    def remove(self, item_id: str) -> None:
        """Libera memória de um término já consumido, após liberação do serviço."""
        with self._condition:
            if self._items[item_id].state not in _TERMINAL or self._active == item_id:
                raise DownloadQueueError("O item ainda está em andamento.")
            del self._items[item_id]

    @property
    def is_closed(self) -> bool:
        return self._closed.is_set() and not self._worker.is_alive()

    @property
    def control_error(self) -> str | None:
        """Última falha de cancelamento/fechamento; não inclui detalhes pessoais."""
        with self._condition:
            return self._control_error

    def shutdown(self, timeout: float = 5.0) -> bool:
        """Impede despachos, cancela esperas e aguarda por tempo limitado.

        False exige manter a instância viva e consultar control_error. Uma nova
        chamada também autoriza repetir cancelamento/close que tenham falhado.
        """
        if not math.isfinite(timeout) or timeout < 0:
            raise DownloadQueueError(
                "O tempo de espera deve ser finito e não negativo."
            )
        with self._condition:
            self._closing = True
            self._shutdown_revision += 1
            for item_id in self._pending:
                self._items[item_id] = replace(
                    self._items[item_id],
                    state=QueueState.CANCELLED,
                    cancel_requested=True,
                )
            self._pending.clear()
            if self._active is not None:
                item = self._items[self._active]
                if item.state not in _TERMINAL:
                    self._items[item.id] = replace(item, cancel_requested=True)
            self._condition.notify_all()
        if current_thread() is not self._worker:
            self._worker.join(timeout)
        return self.is_closed

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._closing or (self._pending and not self._blocked)
                )
                if self._closing:
                    break
                item_id = self._pending.popleft()
                self._active = item_id
                self._items[item_id] = replace(
                    self._items[item_id], state=QueueState.PREPARING
                )
                self._condition.notify_all()
            try:
                self._service.start(self._items[item_id].request)
            except DownloadBusyError:
                with self._condition:
                    item = self._items[item_id]
                    cancelled = self._closing or item.cancel_requested
                    self._items[item_id] = replace(
                        item,
                        state=QueueState.CANCELLED if cancelled else QueueState.WAITING,
                    )
                    if not cancelled:
                        self._pending.appendleft(item_id)
                        self._blocked = True
                    self._active = None
                    self._condition.notify_all()
                continue
            except Exception as error:
                self._set_error(item_id, error)
            self._follow_active(item_id)
            with self._condition:
                self._active = None
                self._condition.notify_all()
        # Não fechar o logger enquanto o serviço ainda puder publicar.
        while True:
            with self._condition:
                revision = self._shutdown_revision
            try:
                self._service.close()
            except Exception:
                self._set_control_error(
                    "Não foi possível confirmar o fechamento do serviço."
                )
                with self._condition:
                    self._condition.wait_for(
                        lambda: self._shutdown_revision != revision
                    )
            else:
                self._closed.set()
                return

    def _set_control_error(self, message: str) -> None:
        with self._condition:
            self._control_error = message
            self._condition.notify_all()

    def _set_error(self, item_id: str, error: object) -> None:
        with self._condition:
            item = self._items[item_id]
            message = (
                error.user_message
                if isinstance(error, DownloadServiceError)
                else "Não foi possível concluir o download."
            )
            safe = _redact_sensitive_text(
                message,
                self._service.base_dir,
                item.request.url,
                item.request.destination_dir,
            )
            self._items[item_id] = replace(
                item, state=QueueState.ERROR, error=safe[:512]
            )
            self._condition.notify_all()

    def _follow_active(self, item_id: str) -> None:
        cancel_sent = False
        cancel_revision = -1
        while True:
            with self._condition:
                item = self._items[item_id]
                should_cancel = item.cancel_requested and (
                    not cancel_sent or cancel_revision != self._shutdown_revision
                )
                revision = self._shutdown_revision
            if should_cancel:
                try:
                    self._service.cancel()
                except Exception:
                    self._set_control_error(
                        "O cancelamento falhou. Tentando encerrar a operação com segurança."
                    )
                    # Fallback existente do serviço, fora da thread solicitante.
                    # Não abandonar a operação se até esse fallback falhar.
                    try:
                        self._service.shutdown(timeout=0)
                    except Exception:
                        self._set_control_error(
                            "Não foi possível confirmar o cancelamento da operação."
                        )
                cancel_sent = True
                cancel_revision = revision
            # Ociosidade deve ser lida ANTES de esvaziar o stream. Se o worker
            # terminar entre as duas leituras, ainda haverá outra rodada de drain.
            released = not self._service.is_running
            drained = 0
            while drained < _EVENT_BATCH:
                try:
                    event = self._service.events.get_nowait()
                except Empty:
                    break
                self._apply_event(item_id, event)
                drained += 1
            if released and self._service.events.empty():
                with self._condition:
                    terminal = self._items[item_id].state in _TERMINAL
                if not terminal:
                    self._set_error(item_id, None)
                return
            with self._condition:
                if drained < _EVENT_BATCH:
                    self._condition.wait_for(
                        lambda: (
                            self._items[item_id].cancel_requested
                            and (
                                not cancel_sent
                                or cancel_revision != self._shutdown_revision
                            )
                        ),
                        timeout=_POLL_SECONDS,
                    )

    def _apply_event(self, item_id: str, event: DownloadEvent) -> None:
        with self._condition:
            item = self._items[item_id]
            if item.state in _TERMINAL:
                return
            if event.kind == DownloadEventKind.ERROR:
                self._set_error(item_id, event.payload)
                return
            if event.kind == DownloadEventKind.COMPLETED:
                if not isinstance(event.payload, DownloadResult):
                    self._set_error(item_id, None)
                    return
                item = replace(item, state=QueueState.COMPLETED, result=event.payload)
            elif event.kind == DownloadEventKind.CANCELLED:
                item = replace(item, state=QueueState.CANCELLED)
            elif event.kind == DownloadEventKind.PROGRESS and isinstance(
                event.payload, DownloadProgress
            ):
                item = replace(
                    item, progress=event.payload, state=QueueState.DOWNLOADING
                )
            elif event.kind == DownloadEventKind.PHASE and isinstance(
                event.payload, DownloadPhase
            ):
                item = replace(item, state=QueueState(event.payload.value))
            self._items[item_id] = item
            self._condition.notify_all()
