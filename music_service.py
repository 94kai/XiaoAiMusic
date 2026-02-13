import logging
import mimetypes
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import unquote
from urllib.parse import urlparse


logger = logging.getLogger(__name__)


def guess_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


class LocalMusicHttpServer:
    def __init__(self, host: str, port: int, base_url: str):
        self.host = host
        self.port = port
        self.base_url = base_url.rstrip("/")
        self._allowed_files: set[str] = set()
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer((self.host, self.port), self._build_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _build_handler(self):
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                path = unquote(parsed.path)

                if path.startswith("/file/"):
                    encoded = path.split("/", 3)[2] if len(path.split("/", 3)) >= 3 else ""
                    server_ref._serve_file(self, encoded)
                    return

                self.send_response(404)
                self.end_headers()

            def do_HEAD(self):
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                if path.startswith("/file/"):
                    encoded = path.split("/", 3)[2] if len(path.split("/", 3)) >= 3 else ""
                    server_ref._serve_file(self, encoded, head_only=True)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, fmt, *args):
                return

        return Handler

    def _encode_path(self, path: str) -> str:
        return path.encode("utf-8").hex()

    def _decode_path(self, encoded: str) -> str:
        return bytes.fromhex(encoded).decode("utf-8")

    def _serve_file(self, handler: BaseHTTPRequestHandler, encoded: str, head_only: bool = False):
        try:
            file_path = self._decode_path(encoded)
        except Exception:
            handler.send_response(400)
            handler.end_headers()
            return

        with self._lock:
            is_allowed = file_path in self._allowed_files
        if not is_allowed:
            handler.send_response(403)
            handler.end_headers()
            return

        if not os.path.isfile(file_path):
            handler.send_response(404)
            handler.end_headers()
            return

        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        file_size = os.path.getsize(file_path)
        range_header = handler.headers.get("Range")

        start = 0
        end = file_size - 1
        status = 200

        if range_header:
            parsed = self._parse_range_header(range_header, file_size)
            if parsed is None:
                handler.send_response(416)
                handler.send_header("Content-Range", f"bytes */{file_size}")
                handler.end_headers()
                return
            start, end = parsed
            status = 206

        content_length = end - start + 1
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", str(content_length))
        if status == 206:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        handler.end_headers()

        if head_only:
            return

        with open(file_path, "rb") as file_obj:
            file_obj.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk = file_obj.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                try:
                    handler.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)

    def _parse_range_header(self, range_header: str, file_size: int) -> tuple[int, int] | None:
        value = range_header.strip().lower()
        if not value.startswith("bytes="):
            return None

        spec = value.split("=", 1)[1].split(",", 1)[0].strip()
        if "-" not in spec:
            return None
        start_text, end_text = spec.split("-", 1)

        try:
            if start_text == "":
                suffix_len = int(end_text)
                if suffix_len <= 0:
                    return None
                start = max(file_size - suffix_len, 0)
                end = file_size - 1
            else:
                start = int(start_text)
                end = file_size - 1 if end_text == "" else int(end_text)
                if start < 0 or end < start:
                    return None
                if start >= file_size:
                    return None
                end = min(end, file_size - 1)
            return start, end
        except Exception:
            return None

    def start(self):
        logger.info(
            "HTTP 服务启动: host=%s port=%d base_url=%s",
            self.host,
            self.port,
            self.base_url,
        )
        self._thread.start()

    def stop(self):
        logger.info("HTTP 服务停止")
        self._server.shutdown()
        self._server.server_close()

    def create_file_url(self, file_path: str) -> str:
        file_path = os.path.abspath(file_path)
        with self._lock:
            self._allowed_files.add(file_path)
        encoded = self._encode_path(file_path)
        filename = os.path.basename(file_path)
        return f"{self.base_url}/file/{encoded}/{filename}"


def build_music_server(http_config: dict) -> LocalMusicHttpServer:
    host = str(http_config.get("host", "0.0.0.0"))
    port = int(http_config.get("port", 18080))
    base_url = str(http_config.get("public_base_url") or "").strip()

    if not base_url:
        device_ip = str(http_config.get("device_ip") or "").strip()
        if device_ip:
            base_url = f"http://{device_ip}:{port}"

    if not base_url:
        base_url = f"http://{guess_local_ip()}:{port}"

    return LocalMusicHttpServer(host=host, port=port, base_url=base_url)
