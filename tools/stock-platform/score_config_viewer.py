#!/usr/bin/env python3
"""Local web viewer for fitness score JSON configuration files."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_FILE = "score_config_viewer.html"


class ScoreConfigViewerHandler(BaseHTTPRequestHandler):
    server: "ScoreConfigViewerServer"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        route = parsed_url.path

        if route in {"/", f"/{APP_FILE}"}:
            self.send_file(self.server.app_dir / APP_FILE)
            return

        if route == "/api/configs":
            self.send_configs()
            return

        if route == "/api/config":
            params = parse_qs(parsed_url.query)
            self.send_config(params.get("name", [""])[0])
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Risorsa non trovata")

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File non trovato")
            return

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_configs(self) -> None:
        config_dir = self.server.config_dir
        files = []
        if config_dir.exists() and config_dir.is_dir():
            for path in sorted(config_dir.glob("*.json")):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files.append(
                    {
                        "name": path.name,
                        "size": stat.st_size,
                        "modified": int(stat.st_mtime),
                    }
                )

        self.send_json(
            {
                "configDir": str(config_dir),
                "files": files,
            }
        )

    def send_config(self, name: str) -> None:
        clean_name = Path(name).name
        if not clean_name or clean_name != name or not clean_name.endswith(".json"):
            self.send_json({"error": "Nome configurazione non valido"}, HTTPStatus.BAD_REQUEST)
            return

        path = self.server.config_dir / clean_name
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            self.send_json({"error": "Configurazione non trovata"}, HTTPStatus.NOT_FOUND)
            return
        except json.JSONDecodeError as exc:
            self.send_json({"error": f"JSON non valido: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        except OSError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_json({"name": clean_name, "payload": payload})


class ScoreConfigViewerServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        app_dir: Path,
        config_dir: Path,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.app_dir = app_dir
        self.config_dir = config_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Avvia una UI locale per visualizzare le regole JSON di fitness score.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host su cui esporre la UI. Default: 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Porta della UI. Usa 0 per far scegliere una porta libera al sistema.",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path("config"),
        help="Cartella con i JSON di scoring. Default: config.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    app_dir = Path(__file__).resolve().parent
    config_dir = args.config_dir.resolve()

    server = ScoreConfigViewerServer(
        (args.host, args.port),
        ScoreConfigViewerHandler,
        app_dir=app_dir,
        config_dir=config_dir,
    )
    host, port = server.server_address[:2]
    print(f"Score config viewer: http://{host}:{port}/")
    print(f"Config dir: {config_dir}")
    print("Premi Ctrl+C per chiudere.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nChiusura server.")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
