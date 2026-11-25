"""Allow a synthetic HTTP server for the duration of a fixture only."""

from contextlib import contextmanager
import socket
from unittest.mock import patch

import download_network
from utils import split_media_url


@contextmanager
def local_media_endpoint(server):
    host, port = server.server_address
    if host != "127.0.0.1" or not port or server.socket.getsockname() != (host, port):
        raise ValueError("A fixture deve ter um servidor ativo em loopback")

    def is_fixture(hostname, requested_port):
        return (hostname, requested_port) == (host, port)

    check_production = download_network.check_media_destination
    resolve_production = download_network._public_endpoints

    def check(url):
        parsed = split_media_url(url)
        if parsed.scheme != "http" or not is_fixture(parsed.hostname, parsed.port):
            check_production(url)

    def resolve(hostname, requested_port):
        if not is_fixture(hostname, requested_port):
            return resolve_production(hostname, requested_port)
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port))
        ]

    with (
        patch("download_network.check_media_destination", side_effect=check),
        patch("download_network._public_endpoints", side_effect=resolve),
    ):
        yield
