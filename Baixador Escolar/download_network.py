"""Local outbound HTTP policy for the requests made through yt-dlp's proxy."""

from __future__ import annotations

from base64 import b64encode
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import re
import secrets
import select
import socket
import threading
from urllib.parse import urlunsplit

from utils import split_media_url

_PORTS = {80, 443}
_SPECIAL_V6 = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
    ipaddress.ip_network("2001::/32"),
    ipaddress.ip_network("2002::/16"),
)
_HOP_HEADERS = {
    "connection",
    "proxy-connection",
    "proxy-authenticate",
    "proxy-authorization",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "expect",
}
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", re.ASCII)
_CHUNK = 64 * 1024
_TIMEOUT = 18


class DestinationBlocked(ValueError):
    pass


def _public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return _public_address(str(address.ipv4_mapped))
        if any(address in network for network in _SPECIAL_V6):
            return False
    return address.is_global and not address.is_multicast and not address.is_reserved


def _check_endpoint(host: str, port: int) -> None:
    if port not in _PORTS:
        raise DestinationBlocked
    name = host.lower().removesuffix(".")
    if (
        "." not in name
        and ":" not in name
        or name.endswith((".localhost", ".local", ".internal", ".home.arpa"))
    ):
        raise DestinationBlocked
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return
    if not _public_address(name):
        raise DestinationBlocked


def check_media_destination(url: str) -> None:
    parsed = split_media_url(url)
    _check_endpoint(
        parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    )


def _public_endpoints(host: str, port: int):
    _check_endpoint(host, port)
    endpoints = socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    if not endpoints or any(
        family not in (socket.AF_INET, socket.AF_INET6)
        or not _public_address(target[0])
        for family, _, _, _, target in endpoints
    ):
        raise DestinationBlocked
    return endpoints


def _forward_headers(headers):
    linked = {
        name.strip().lower()
        for value in headers.get_all("Connection", [])
        for name in value.split(",")
    }
    for name, value in headers.items():
        if name.lower() not in (_HOP_HEADERS | linked):
            if not _HEADER_NAME.fullmatch(name) or "\r" in value or "\n" in value:
                raise ValueError("Invalid HTTP header")
            yield name, value


class _PolicyRequest(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(_TIMEOUT)

    def log_message(self, *_args):
        pass

    def _authorize(self):
        supplied = self.headers.get("Proxy-Authorization", "")
        if secrets.compare_digest(
            supplied.encode("latin-1"), self.server.authorization
        ):
            return True
        self.send_response_only(407)
        self.send_header("Proxy-Authenticate", 'Basic realm="EduDownloader"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _connect(self, host, port):
        for family, socktype, proto, _, address in _public_endpoints(host, port):
            if self.server.stopping.is_set():
                break
            candidate = socket.socket(family, socktype, proto)
            candidate.settimeout(_TIMEOUT)
            try:
                # Conecta ao endereço verificado, sem segunda resolução DNS.
                candidate.connect(address)
                return candidate
            except OSError:
                candidate.close()
        raise OSError("Connection unavailable")

    def _deny(self, status):
        try:
            self.send_response_only(status)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except OSError:
            pass

    def do_CONNECT(self):
        if not self._authorize():
            return
        established = False
        try:
            parsed = split_media_url("https://" + self.path)
            if parsed.path or parsed.query or parsed.fragment or parsed.port is None:
                raise DestinationBlocked
            with self._connect(parsed.hostname, parsed.port) as upstream:
                self.send_response_only(200, "Connection Established")
                self.end_headers()
                established = True
                sockets = {self.connection: upstream, upstream: self.connection}
                while not self.server.stopping.is_set():
                    ready, _, _ = select.select(list(sockets), [], [], 0.25)
                    for source in ready:
                        data = source.recv(_CHUNK)
                        if not data:
                            return
                        sockets[source].sendall(data)
        except ValueError:
            if not established:
                self.server.blocked.set()
                self._deny(403)
        except OSError:
            if not established:
                self._deny(502)

    def _forward_http(self):
        if not self._authorize():
            return
        headers_sent = False
        try:
            parsed = split_media_url(self.path)
            if parsed.scheme != "http" or parsed.fragment:
                raise DestinationBlocked
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) > 1:
                raise ValueError("Ambiguous HTTP body")
            size = int(lengths[0]) if lengths else 0
            if not 0 <= size <= 8 * 1024 * 1024:
                raise ValueError("Request body too large")
            body = self.rfile.read(size) if size else None
            if size and len(body) != size:
                raise ValueError("Incomplete HTTP body")
            port = parsed.port or 80
            origin = http.client.HTTPConnection(parsed.hostname, port, timeout=_TIMEOUT)
            with self._connect(parsed.hostname, port) as upstream:
                origin.sock = upstream
                request_path = parsed.path or "/"
                if parsed.query:
                    request_path += "?" + parsed.query
                origin.putrequest(self.command, request_path, skip_accept_encoding=True)
                for name, value in _forward_headers(self.headers):
                    if name.lower() not in {"host", "content-length"}:
                        origin.putheader(name, value)
                if lengths:
                    origin.putheader("Content-Length", str(size))
                origin.putheader("Connection", "close")
                origin.endheaders(body)
                response = origin.getresponse()
                try:
                    self.send_response_only(response.status)
                    for name, value in _forward_headers(response.headers):
                        if not (response.chunked and name.lower() == "content-length"):
                            self.send_header(name, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    headers_sent = True
                    if self.command != "HEAD":
                        while not self.server.stopping.is_set():
                            data = response.read(_CHUNK)
                            if not data:
                                break
                            self.wfile.write(data)
                finally:
                    response.close()
        except ValueError:
            if not headers_sent:
                self.server.blocked.set()
                self._deny(403)
        except (OSError, http.client.HTTPException):
            if not headers_sent:
                self._deny(502)

    do_GET = do_HEAD = do_POST = _forward_http


class _PolicyServer(ThreadingHTTPServer):
    def __init__(self, authorization):
        super().__init__(("127.0.0.1", 0), _PolicyRequest)
        self.authorization = authorization
        self.blocked = threading.Event()
        self.stopping = threading.Event()
        self._capacity = threading.BoundedSemaphore(16)

    def process_request(self, request, address):
        if self._capacity.acquire(blocking=False):
            try:
                super().process_request(request, address)
            except BaseException:
                self._capacity.release()
                raise
        else:
            self.shutdown_request(request)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self._capacity.release()

    def handle_error(self, request, client_address):
        # O endereço de um recurso ou a autorização do proxy nunca vai ao log.
        pass


class DownloadNetwork:
    """Proxy isolado por tarefa, com credencial efêmera apenas em loopback."""

    def __enter__(self):
        token = secrets.token_urlsafe(24)
        self.token = token
        self.server = _PolicyServer(
            b"Basic " + b64encode(f"edu:{token}".encode("ascii"))
        )
        authority = f"edu:{token}@127.0.0.1:{self.server.server_port}"
        self.url = urlunsplit(("http", authority, "", "", ""))
        self.worker = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
            name="download-network-policy",
        )
        try:
            self.worker.start()
        except BaseException:
            self.server.server_close()
            raise
        return self

    def __exit__(self, *_args):
        self.server.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    @property
    def blocked(self):
        return self.server.blocked.is_set()

    def redact(self, details):
        return details.replace(self.token, "<omitido>").replace(
            self.server.authorization[6:].decode("ascii"), "<omitido>"
        )
