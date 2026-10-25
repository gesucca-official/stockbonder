#!/usr/bin/env python3
"""Local web viewer for CSV output files."""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_FILE = "csv_output_viewer.html"
ECB_DAILY_RATES_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
FX_CACHE_SECONDS = 6 * 60 * 60


class CsvOutputViewerHandler(BaseHTTPRequestHandler):
    server: "CsvOutputViewerServer"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        route = parsed_url.path

        if route in {"/", f"/{APP_FILE}"}:
            self.send_file(self.server.app_dir / APP_FILE)
            return

        if route == "/api/files":
            self.send_csv_files()
            return

        if route == "/api/csv":
            params = parse_qs(parsed_url.query)
            self.send_csv(params.get("path", [""])[0])
            return

        if route == "/api/fx":
            self.send_fx_rates()
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

    def send_csv_files(self) -> None:
        files = []
        for path in sorted(self.server.root_dir.rglob("*.csv")):
            if any(part.startswith(".") for part in path.relative_to(self.server.root_dir).parts):
                continue
            try:
                stat = path.stat()
                relative_path = path.relative_to(self.server.root_dir).as_posix()
            except OSError:
                continue
            files.append(
                {
                    "path": relative_path,
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": int(stat.st_mtime),
                }
            )

        self.send_json(
            {
                "rootDir": str(self.server.root_dir),
                "files": files,
            }
        )

    def send_csv(self, relative_path: str) -> None:
        path = self.resolve_csv_path(relative_path)
        if path is None:
            self.send_json({"error": "Percorso CSV non valido"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self.send_json({"error": "CSV non trovato"}, HTTPStatus.NOT_FOUND)
            return
        except OSError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_fx_rates(self) -> None:
        now = time.time()
        if self.server.fx_cache and now - self.server.fx_cache_at < FX_CACHE_SECONDS:
            self.send_json(self.server.fx_cache)
            return

        try:
            payload = fetch_ecb_fx_rates()
        except (OSError, urllib.error.URLError, ET.ParseError, ValueError) as exc:
            if self.server.fx_cache:
                cached = dict(self.server.fx_cache)
                cached["stale"] = True
                cached["error"] = str(exc)
                self.send_json(cached)
                return
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return

        self.server.fx_cache = payload
        self.server.fx_cache_at = now
        self.send_json(payload)

    def resolve_csv_path(self, relative_path: str) -> Path | None:
        if not relative_path or "\x00" in relative_path:
            return None

        candidate = Path(relative_path)
        if candidate.is_absolute() or candidate.suffix.lower() != ".csv":
            return None

        root = self.server.root_dir
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            return None

        return resolved


class CsvOutputViewerServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        app_dir: Path,
        root_dir: Path,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.app_dir = app_dir
        self.root_dir = root_dir
        self.fx_cache: dict[str, object] | None = None
        self.fx_cache_at = 0.0


def fetch_ecb_fx_rates() -> dict[str, object]:
    request = urllib.request.Request(
        ECB_DAILY_RATES_URL,
        headers={"User-Agent": "csv-output-viewer/1.0"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        body = response.read()

    root = ET.fromstring(body)
    rates: dict[str, float] = {"EUR": 1.0}
    rate_date = ""

    for cube in root.iter():
        currency = cube.attrib.get("currency")
        rate = cube.attrib.get("rate")
        if currency and rate:
            rates[currency.upper()] = float(rate)
        if cube.attrib.get("time"):
            rate_date = cube.attrib["time"]

    if len(rates) <= 1:
        raise ValueError("Nessun cambio trovato nella risposta ECB")

    return {
        "base": "EUR",
        "date": rate_date,
        "rates": rates,
        "source": ECB_DAILY_RATES_URL,
        "stale": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Avvia una UI locale per consultare e filtrare file CSV.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host su cui esporre la UI. Default: 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8766,
        help="Porta della UI. Usa 0 per far scegliere una porta libera al sistema.",
    )
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=Path("."),
        help="Cartella in cui cercare i CSV. Default: cartella corrente.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    app_dir = Path(__file__).resolve().parent
    root_dir = args.root_dir.resolve()

    server = CsvOutputViewerServer(
        (args.host, args.port),
        CsvOutputViewerHandler,
        app_dir=app_dir,
        root_dir=root_dir,
    )
    host, port = server.server_address[:2]
    print(f"StockMix Lab: http://{host}:{port}/")
    print(f"CSV root: {root_dir}")
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
