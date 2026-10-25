#!/usr/bin/env python3
"""Unified local web app for fundamentals, scoring configs, rankings and baskets."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


APP_FILE = "stock_platform.html"
ECB_DAILY_RATES_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
FX_CACHE_SECONDS = 6 * 60 * 60

MARKETS = {"borsa", "xetra", "lse", "nyse", "nasdaq", "all"}
OUTPUT_FORMATS = {"csv", "jsonl", "json"}
FORMAT_SUFFIX = {"csv": ".csv", "jsonl": ".jsonl", "json": ".json"}
MAX_LOG_LINES = 900
OUTPUT_ROOT = Path("outputs")
FUNDAMENTALS_OUTPUT_DIR = OUTPUT_ROOT / "fundamentals"
FITNESS_OUTPUT_DIR = OUTPUT_ROOT / "fitness"
CONFIG_DIR = Path("config")
CLEANUP_DIRS = {
    "fundamentals": FUNDAMENTALS_OUTPUT_DIR,
    "fitness": FITNESS_OUTPUT_DIR,
}
CLEANUP_SUFFIXES = {".csv", ".json", ".jsonl", ".partial", ".tmp"}
MAX_DIR_SUGGESTIONS = 220


def utc_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def bool_from_payload(payload: dict[str, Any], key: str) -> bool:
    return bool(payload.get(key))


def bool_from_query(params: dict[str, list[str]], key: str, default: bool = False) -> bool:
    values = params.get(key)
    if not values:
        return default
    value = str(values[0]).strip().lower()
    return value in {"1", "true", "yes", "on", "si", "sì"}


def positive_int(value: Any, default: int, minimum: int = 1, maximum: int = 64) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{value!r} non e un intero valido") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{number} fuori range ({minimum}-{maximum})")
    return number


def non_negative_int(value: Any, default: int, maximum: int = 20) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{value!r} non e un intero valido") from exc
    if number < 0 or number > maximum:
        raise ValueError(f"{number} fuori range (0-{maximum})")
    return number


def non_negative_float(value: Any, default: float, maximum: float = 600.0) -> float:
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{value!r} non e un numero valido") from exc
    if number < 0 or number > maximum:
        raise ValueError(f"{number} fuori range (0-{maximum})")
    return number


def command_display(command: list[str]) -> str:
    parts = []
    for item in command:
        if re.search(r"\s", item):
            parts.append(f'"{item}"')
        else:
            parts.append(item)
    return " ".join(parts)


def safe_path(
    root: Path,
    relative_path: str,
    *,
    allowed_suffixes: set[str] | None = None,
    must_exist: bool = False,
    allow_dir: bool = False,
) -> Path | None:
    if not relative_path or "\x00" in relative_path:
        return None

    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.drive:
        return None
    if any(part in {"", ".", ".."} or part.startswith(".") for part in candidate.parts):
        return None

    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None

    if must_exist and not resolved.exists():
        return None
    if allow_dir and resolved.is_dir():
        return resolved
    if allowed_suffixes is not None and resolved.suffix.lower() not in allowed_suffixes:
        return None
    return resolved


def safe_dir_path(
    root: Path,
    relative_path: Any,
    default_relative_dir: Path,
    *,
    create: bool = False,
) -> Path:
    text = str(relative_path or "").strip().replace("\\", "/")
    if text.startswith("/") and not text.startswith("//"):
        text = text.lstrip("/")
    text = text or default_relative_dir.as_posix()
    if "\x00" in text:
        raise ValueError("Cartella non valida")

    candidate = Path(text)
    if candidate.is_absolute() or candidate.drive:
        raise ValueError("Cartella non valida")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in candidate.parts):
        raise ValueError("Cartella non valida")

    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("Cartella fuori workspace") from exc

    if create:
        resolved.mkdir(parents=True, exist_ok=True)
    elif not resolved.is_dir():
        raise ValueError("Cartella non trovata")
    return resolved


def safe_output_path(root: Path, output_text: str, output_dir: Path, allowed_suffixes: set[str]) -> Path | None:
    text = str(output_text or "").strip()
    if not text:
        return None

    candidate = Path(text)
    if not candidate.is_absolute() and not candidate.drive and len(candidate.parts) == 1:
        text = f"{to_relative(root, output_dir)}/{text}"

    path = safe_path(root, text, allowed_suffixes=allowed_suffixes)
    if path is None or not is_relative_to_path(path, output_dir):
        return None
    return path


def to_relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def should_skip_path(root: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part.startswith(".") or part == "__pycache__" for part in parts)


def file_info(root: Path, path: Path) -> dict[str, Any] | None:
    try:
        stat = path.stat()
        relative_path = to_relative(root, path)
    except OSError:
        return None
    return {
        "path": relative_path,
        "name": path.name,
        "size": stat.st_size,
        "modified": int(stat.st_mtime),
    }


def ensure_output_dirs(root: Path) -> None:
    for relative_dir in CLEANUP_DIRS.values():
        (root / relative_dir).mkdir(parents=True, exist_ok=True)


def list_workspace_dirs(root: Path, max_depth: int = 3) -> list[dict[str, Any]]:
    suggestions: dict[str, dict[str, Any]] = {}
    preferred = [FUNDAMENTALS_OUTPUT_DIR, FITNESS_OUTPUT_DIR, CONFIG_DIR, Path("data"), Path("runs")]

    def add_dir(path: Path) -> None:
        try:
            relative = to_relative(root, path)
        except (OSError, ValueError):
            return
        if relative in suggestions or relative in {"", "."}:
            return
        suggestions[relative] = {
            "path": relative,
            "name": path.name,
        }

    for relative_dir in preferred:
        path = root / relative_dir
        if path.exists() and path.is_dir() and not should_skip_path(root, path):
            add_dir(path)

    for path in sorted(root.rglob("*")):
        if len(suggestions) >= MAX_DIR_SUGGESTIONS:
            break
        if not path.is_dir() or should_skip_path(root, path):
            continue
        try:
            depth = len(path.relative_to(root).parts)
        except ValueError:
            continue
        if depth > max_depth:
            continue
        add_dir(path)

    return sorted(suggestions.values(), key=lambda item: item["path"].lower())


def safe_browse_dir(root: Path, relative_path: Any = "") -> Path:
    text = str(relative_path or "").strip().replace("\\", "/")
    if text.startswith("/") and not text.startswith("//"):
        text = text.lstrip("/")

    if not text:
        return root.resolve()

    return safe_dir_path(root, text, Path("."), create=False)


def list_child_dirs(root: Path, folder: Path) -> list[dict[str, Any]]:
    dirs: list[dict[str, Any]] = []
    try:
        children = sorted(folder.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return dirs

    for path in children:
        if not path.is_dir() or should_skip_path(root, path):
            continue
        dirs.append(
            {
                "path": to_relative(root, path),
                "name": path.name,
            }
        )
    return dirs


def is_relative_to_path(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def list_csv_files_in_dir(root: Path, folder: Path) -> list[dict[str, Any]]:
    if not folder.exists():
        return []

    files: list[dict[str, Any]] = []
    for path in sorted(folder.rglob("*.csv")):
        if not path.is_file() or should_skip_path(root, path):
            continue
        info = file_info(root, path)
        if info:
            files.append(info)
    return sorted(files, key=lambda item: item["modified"], reverse=True)


def categorized_csv_files(root: Path, fundamentals_dir: Path, fitness_dir: Path) -> dict[str, list[dict[str, Any]]]:
    fundamentals = list_csv_files_in_dir(root, fundamentals_dir)
    fitness = list_csv_files_in_dir(root, fitness_dir)
    merged = {file["path"]: file for file in [*fundamentals, *fitness]}
    files = sorted(merged.values(), key=lambda item: item["modified"], reverse=True)
    return {
        "csvFiles": files,
        "fundamentalsCsv": fundamentals,
        "fitnessCsv": fitness,
        "otherCsv": [],
    }


def output_folder_summaries(root: Path, fundamentals_dir: Path | None = None, fitness_dir: Path | None = None) -> list[dict[str, Any]]:
    summaries = []
    folders = {
        "fundamentals": fundamentals_dir or safe_dir_path(root, None, FUNDAMENTALS_OUTPUT_DIR, create=True),
        "fitness": fitness_dir or safe_dir_path(root, None, FITNESS_OUTPUT_DIR, create=True),
    }
    for category, folder in folders.items():
        folder.mkdir(parents=True, exist_ok=True)
        files = [path for path in folder.rglob("*") if path.is_file() and not should_skip_path(root, path)]
        total_size = 0
        newest = 0
        for path in files:
            try:
                stat = path.stat()
            except OSError:
                continue
            total_size += stat.st_size
            newest = max(newest, int(stat.st_mtime))
        summaries.append(
            {
                "category": category,
                "path": to_relative(root, folder),
                "fileCount": len(files),
                "size": total_size,
                "modified": newest,
            }
        )
    return summaries


def cleanup_output_folder(
    root: Path,
    category: str,
    older_than_days: int,
    dry_run: bool,
    relative_dir: Any = None,
) -> dict[str, Any]:
    normalized_category = "fitness" if category == "ranking" else category
    if normalized_category not in CLEANUP_DIRS:
        raise ValueError("Categoria cleanup non valida")
    if older_than_days < 0 or older_than_days > 3650:
        raise ValueError("Giorni cleanup fuori range")

    folder = safe_dir_path(root, relative_dir, CLEANUP_DIRS[normalized_category], create=True)
    cutoff = time.time() - (older_than_days * 24 * 60 * 60)
    selected: list[dict[str, Any]] = []
    total_size = 0
    deleted_count = 0

    for path in sorted(folder.rglob("*")):
        if not path.is_file() or should_skip_path(root, path):
            continue
        if path.suffix.lower() not in CLEANUP_SUFFIXES:
            continue
        resolved = path.resolve()
        if not is_relative_to_path(resolved, folder):
            continue
        try:
            stat = resolved.stat()
        except OSError:
            continue
        if stat.st_mtime > cutoff:
            continue

        info = {
            "path": to_relative(root, resolved),
            "name": resolved.name,
            "size": stat.st_size,
            "modified": int(stat.st_mtime),
        }
        selected.append(info)
        total_size += stat.st_size

        if not dry_run:
            try:
                resolved.unlink()
                deleted_count += 1
            except OSError as exc:
                info["error"] = str(exc)

    return {
        "category": normalized_category,
        "folder": to_relative(root, folder),
        "olderThanDays": older_than_days,
        "dryRun": dry_run,
        "count": len(selected),
        "deleted": deleted_count if not dry_run else 0,
        "size": total_size,
        "files": selected[:100],
        "truncated": len(selected) > 100,
    }


def list_config_files(root: Path, config_root: Path, include_subdirs: bool = False) -> list[dict[str, Any]]:
    if not config_root.exists():
        return []
    files: list[dict[str, Any]] = []
    iterator = config_root.rglob("*.json") if include_subdirs else config_root.glob("*.json")
    for path in sorted(iterator):
        if should_skip_path(root, path):
            continue
        info = file_info(root, path)
        if info:
            files.append(info)
    return files


def list_config_dirs(root: Path, config_root: Path, include_subdirs: bool = False) -> list[dict[str, Any]]:
    if not config_root.exists():
        return []
    dirs: list[dict[str, Any]] = []
    candidates = [config_root, *config_root.rglob("*")] if include_subdirs else [config_root]
    for path in sorted(candidates):
        if not path.is_dir() or should_skip_path(root, path):
            continue
        try:
            json_count = len(list(path.glob("*.json")))
        except OSError:
            json_count = 0
        dirs.append({"path": to_relative(root, path), "name": path.name, "jsonCount": json_count})
    return dirs


def fetch_ecb_fx_rates() -> dict[str, Any]:
    request = urllib.request.Request(
        ECB_DAILY_RATES_URL,
        headers={"User-Agent": "stock-platform/1.0"},
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


class Job:
    def __init__(self, job_id: str, kind: str, label: str, command: list[str], output: str | None) -> None:
        self.id = job_id
        self.kind = kind
        self.label = label
        self.command = command
        self.command_text = command_display(command)
        self.output = output
        self.status = "queued"
        self.progress = 0
        self.exit_code: int | None = None
        self.created_at = iso_now()
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.updated_at = self.created_at
        self.logs: deque[str] = deque(maxlen=MAX_LOG_LINES)
        self.process: subprocess.Popen[str] | None = None
        self.cancel_requested = False
        self.error: str | None = None

    def add_log(self, line: str) -> None:
        if line:
            self.logs.append(line)
        self.updated_at = iso_now()

    def to_dict(self, include_logs: bool = True) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "progress": self.progress,
            "exitCode": self.exit_code,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "updatedAt": self.updated_at,
            "output": self.output,
            "command": self.command_text,
            "error": self.error,
        }
        if include_logs:
            payload["logs"] = list(self.logs)
        return payload


class JobManager:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}

    def snapshot(self, include_logs: bool = False) -> list[dict[str, Any]]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [job.to_dict(include_logs=include_logs) for job in jobs]

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.to_dict(include_logs=True) if job else None

    def start_from_payload(self, payload: dict[str, Any]) -> Job:
        kind = str(payload.get("type", "")).strip()
        if kind == "fundamentals":
            job = self._build_fundamentals_job(payload)
        elif kind == "fitness":
            job = self._build_fitness_job(payload)
        else:
            raise ValueError("Tipo job non supportato")

        with self.lock:
            self.jobs[job.id] = job

        thread = threading.Thread(target=self._run_job, args=(job.id,), daemon=True)
        thread.start()
        return job

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            job.cancel_requested = True
            process = job.process
            if job.status in {"queued", "running"}:
                job.status = "cancelling"
                job.add_log("Cancellazione richiesta.")

        if process and process.poll() is None:
            process.terminate()
        return self.get(job_id)

    def _build_fundamentals_job(self, payload: dict[str, Any]) -> Job:
        market = str(payload.get("market", "all")).strip().lower()
        if market not in MARKETS:
            raise ValueError("Mercato non valido")

        output_format = str(payload.get("format", "csv")).strip().lower()
        if output_format not in OUTPUT_FORMATS:
            raise ValueError("Formato output non valido")

        limit = payload.get("limit")
        workers = positive_int(payload.get("workers"), default=4, minimum=1, maximum=16)
        retries = non_negative_int(payload.get("retries"), default=1, maximum=10)
        retry_sleep = non_negative_float(payload.get("retrySleep"), default=2.0, maximum=120.0)
        fundamentals_dir = safe_dir_path(
            self.root_dir,
            payload.get("fundamentalsDir"),
            FUNDAMENTALS_OUTPUT_DIR,
            create=True,
        )

        suffix = FORMAT_SUFFIX[output_format]
        output_text = str(payload.get("output") or "").strip()
        if not output_text:
            output_dir = to_relative(self.root_dir, fundamentals_dir)
            output_text = f"{output_dir}/fundamentals_{market}_{utc_stamp()}{suffix}"
        output_path = safe_output_path(self.root_dir, output_text, fundamentals_dir, {suffix})
        if output_path is None:
            raise ValueError("Percorso output non valido per la cartella fondamentali")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_relative = to_relative(self.root_dir, output_path)

        command = [
            sys.executable,
            str(self.root_dir / "market_fundamentals.py"),
            "--market",
            market,
            "--format",
            output_format,
            "--workers",
            str(workers),
            "--retries",
            str(retries),
            "--retry-sleep",
            str(retry_sleep),
            "--output",
            output_relative,
        ]
        if limit not in (None, ""):
            limit_int = positive_int(limit, default=0, minimum=1, maximum=50000)
            command.extend(["--limit", str(limit_int)])

        flag_map = {
            "includeEtfs": "--include-etfs",
            "includeNonCommon": "--include-non-common",
            "includeBorsaGem": "--include-borsa-gem",
            "includeNonEquity": "--include-non-equity",
            "includeSectorless": "--include-sectorless",
            "includeIsin": "--include-isin",
            "deepFundamentals": "--deep-fundamentals",
            "listOnly": "--list-only",
        }
        for payload_key, cli_flag in flag_map.items():
            if bool_from_payload(payload, payload_key):
                command.append(cli_flag)

        label = f"Fondamentali {market.upper()} -> {output_relative}"
        return Job(uuid.uuid4().hex[:12], "fundamentals", label, command, output_relative)

    def _build_fitness_job(self, payload: dict[str, Any]) -> Job:
        fundamentals_dir = safe_dir_path(
            self.root_dir,
            payload.get("fundamentalsDir"),
            FUNDAMENTALS_OUTPUT_DIR,
            create=True,
        )
        input_text = str(payload.get("input") or "").strip()
        input_path = safe_path(self.root_dir, input_text, allowed_suffixes={".csv"}, must_exist=True)
        if input_path is None or not is_relative_to_path(input_path, fundamentals_dir):
            raise ValueError("CSV input non valido")

        config_dir = safe_dir_path(
            self.root_dir,
            payload.get("configDir"),
            CONFIG_DIR,
            create=False,
        )
        config_include_subdirs = bool(payload.get("configIncludeSubdirs", False))
        config_text = str(payload.get("config") or to_relative(self.root_dir, config_dir)).strip()
        config_path = safe_path(
            self.root_dir,
            config_text,
            allowed_suffixes={".json"},
            must_exist=True,
            allow_dir=True,
        )
        if config_path is None or not is_relative_to_path(config_path, config_dir):
            raise ValueError("Config scoring non valida")
        if not config_include_subdirs and config_path != config_dir and config_path.parent.resolve() != config_dir.resolve():
            raise ValueError("Config scoring fuori dalla root config selezionata")

        fitness_dir = safe_dir_path(
            self.root_dir,
            payload.get("rankingDir"),
            FITNESS_OUTPUT_DIR,
            create=True,
        )
        output_text = str(payload.get("output") or "").strip()
        if not output_text:
            stem = input_path.stem
            output_dir = to_relative(self.root_dir, fitness_dir)
            output_text = f"{output_dir}/{stem}_fitness_{utc_stamp()}.csv"
        output_path = safe_output_path(self.root_dir, output_text, fitness_dir, {".csv"})
        if output_path is None:
            raise ValueError("Percorso output non valido per la cartella ranking")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        input_relative = to_relative(self.root_dir, input_path)
        config_relative = to_relative(self.root_dir, config_path)
        output_relative = to_relative(self.root_dir, output_path)
        command = [
            sys.executable,
            str(self.root_dir / "fitness_score.py"),
            "--input",
            input_relative,
            "--config",
            config_relative,
            "--output",
            output_relative,
        ]
        label = f"Fitness score -> {output_relative}"
        return Job(uuid.uuid4().hex[:12], "fitness", label, command, output_relative)

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            job.started_at = iso_now()
            job.progress = max(job.progress, 2)
            job.add_log(f"Comando: {job.command_text}")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        try:
            process = subprocess.Popen(
                job.command,
                cwd=self.root_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            with self.lock:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = iso_now()
                job.progress = 100
                job.add_log(f"Errore avvio processo: {exc}")
            return

        with self.lock:
            job.process = process

        if process.stdout:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                with self.lock:
                    job.add_log(line)
                    job.progress = max(job.progress, infer_progress(job.kind, line, job.progress))

        exit_code = process.wait()
        with self.lock:
            job.exit_code = exit_code
            job.finished_at = iso_now()
            if job.cancel_requested:
                job.status = "cancelled"
                job.progress = 100
                job.add_log("Job cancellato.")
            elif exit_code == 0:
                job.status = "completed"
                job.progress = 100
                job.add_log("Job completato.")
            else:
                job.status = "failed"
                job.progress = 100
                job.error = f"Processo terminato con codice {exit_code}"
                job.add_log(job.error)


def infer_progress(kind: str, line: str, current: int) -> int:
    if "Export completato" in line or "Job completato" in line:
        return 100
    if "Scrivo " in line:
        return 96
    if "Fondamentali completati" in line:
        return 95
    progress_match = re.search(r"\((\d{1,3})%\)", line)
    if progress_match:
        return min(95, max(current, int(progress_match.group(1))))
    if "Scarico fondamentali" in line:
        return max(current, 15)
    if "Lista " in line or "Liste aggregate" in line:
        return max(current, 10)
    if kind == "fitness" and "Comando:" not in line:
        return max(current, 45)
    return current


class StockPlatformHandler(BaseHTTPRequestHandler):
    server: "StockPlatformServer"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        route = parsed_url.path

        if route in {"/", f"/{APP_FILE}"}:
            self.send_file(self.server.app_dir / APP_FILE)
            return

        if route == "/api/files":
            try:
                self.send_files(parse_qs(parsed_url.query))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/directories":
            try:
                self.send_directories(parse_qs(parsed_url.query))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/csv":
            params = parse_qs(parsed_url.query)
            self.send_csv(params.get("path", [""])[0], params.get("rankingDir", [""])[0])
            return

        if route == "/api/configs":
            try:
                self.send_configs(parse_qs(parsed_url.query))
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/config":
            params = parse_qs(parsed_url.query)
            self.send_config(
                params.get("path", [""])[0],
                params.get("configDir", [""])[0],
                bool_from_query(params, "configIncludeSubdirs"),
            )
            return

        if route == "/api/jobs":
            self.send_json({"jobs": self.server.jobs.snapshot(include_logs=False)})
            return

        if route.startswith("/api/jobs/"):
            job_id = route.rsplit("/", 1)[-1]
            job = self.server.jobs.get(job_id)
            if not job:
                self.send_json({"error": "Job non trovato"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"job": job})
            return

        if route == "/api/fx":
            self.send_fx_rates()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Risorsa non trovata")

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        if parsed_url.path == "/api/jobs":
            try:
                payload = self.read_json_body()
                job = self.server.jobs.start_from_payload(payload)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except json.JSONDecodeError as exc:
                self.send_json({"error": f"JSON non valido: {exc}"}, HTTPStatus.BAD_REQUEST)
                return
            except OSError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self.send_json({"job": job.to_dict(include_logs=True)}, HTTPStatus.CREATED)
            return

        if parsed_url.path == "/api/cleanup":
            try:
                payload = self.read_json_body()
                category = str(payload.get("category") or "").strip()
                older_than_days = non_negative_int(payload.get("olderThanDays"), default=30, maximum=3650)
                dry_run = bool(payload.get("dryRun", True))
                folder = payload.get("folder")
                result = cleanup_output_folder(self.server.root_dir, category, older_than_days, dry_run, folder)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except json.JSONDecodeError as exc:
                self.send_json({"error": f"JSON non valido: {exc}"}, HTTPStatus.BAD_REQUEST)
                return
            except OSError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self.send_json({"cleanup": result})
            return

        if parsed_url.path != "/api/jobs":
            self.send_error(HTTPStatus.NOT_FOUND, "Risorsa non trovata")
            return

    def do_DELETE(self) -> None:
        parsed_url = urlparse(self.path)
        route = parsed_url.path
        if not route.startswith("/api/jobs/"):
            self.send_error(HTTPStatus.NOT_FOUND, "Risorsa non trovata")
            return

        job_id = route.rsplit("/", 1)[-1]
        job = self.server.jobs.cancel(job_id)
        if not job:
            self.send_json({"error": "Job non trovato"}, HTTPStatus.NOT_FOUND)
            return
        self.send_json({"job": job})

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("Body JSON mancante o troppo grande")
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Body JSON non valido")
        return payload

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

    def send_files(self, params: dict[str, list[str]] | None = None) -> None:
        params = params or {}
        fundamentals_dir = safe_dir_path(
            self.server.root_dir,
            params.get("fundamentalsDir", [""])[0],
            FUNDAMENTALS_OUTPUT_DIR,
            create=True,
        )
        fitness_dir = safe_dir_path(
            self.server.root_dir,
            params.get("rankingDir", [""])[0],
            FITNESS_OUTPUT_DIR,
            create=True,
        )
        config_dir = safe_dir_path(
            self.server.root_dir,
            params.get("configDir", [""])[0],
            CONFIG_DIR,
            create=False,
        )
        config_include_subdirs = bool_from_query(params, "configIncludeSubdirs")
        csv_payload = categorized_csv_files(self.server.root_dir, fundamentals_dir, fitness_dir)
        self.send_json(
            {
                "rootDir": str(self.server.root_dir),
                "fundamentalsDir": to_relative(self.server.root_dir, fundamentals_dir),
                "rankingDir": to_relative(self.server.root_dir, fitness_dir),
                "configDir": to_relative(self.server.root_dir, config_dir),
                "configIncludeSubdirs": config_include_subdirs,
                **csv_payload,
                "configFiles": list_config_files(self.server.root_dir, config_dir, config_include_subdirs),
                "configDirs": list_config_dirs(self.server.root_dir, config_dir, config_include_subdirs),
                "directorySuggestions": list_workspace_dirs(self.server.root_dir),
                "outputFolders": output_folder_summaries(self.server.root_dir, fundamentals_dir, fitness_dir),
                "scripts": {
                    "fundamentals": (self.server.root_dir / "market_fundamentals.py").exists(),
                    "fitness": (self.server.root_dir / "fitness_score.py").exists(),
                },
            }
        )

    def send_directories(self, params: dict[str, list[str]] | None = None) -> None:
        params = params or {}
        folder = safe_browse_dir(self.server.root_dir, params.get("path", [""])[0])
        root = self.server.root_dir.resolve()
        relative = "" if folder == root else to_relative(self.server.root_dir, folder)
        parent = None
        if folder != root:
            parent_path = folder.parent.resolve()
            parent = "" if parent_path == root else to_relative(self.server.root_dir, parent_path)
        self.send_json(
            {
                "rootDir": str(self.server.root_dir),
                "path": relative,
                "parent": parent,
                "dirs": list_child_dirs(self.server.root_dir, folder),
            }
        )

    def send_configs(self, params: dict[str, list[str]] | None = None) -> None:
        params = params or {}
        config_dir = safe_dir_path(
            self.server.root_dir,
            params.get("configDir", [""])[0],
            CONFIG_DIR,
            create=False,
        )
        config_include_subdirs = bool_from_query(params, "configIncludeSubdirs")
        self.send_json(
            {
                "rootDir": str(self.server.root_dir),
                "configDir": to_relative(self.server.root_dir, config_dir),
                "configIncludeSubdirs": config_include_subdirs,
                "files": list_config_files(self.server.root_dir, config_dir, config_include_subdirs),
                "dirs": list_config_dirs(self.server.root_dir, config_dir, config_include_subdirs),
                "directorySuggestions": list_workspace_dirs(self.server.root_dir),
            }
        )

    def send_csv(self, relative_path: str, ranking_dir: Any = None) -> None:
        path = safe_path(self.server.root_dir, relative_path, allowed_suffixes={".csv"}, must_exist=True)
        if path is None:
            self.send_json({"error": "Percorso CSV non valido"}, HTTPStatus.BAD_REQUEST)
            return
        if ranking_dir:
            try:
                allowed_dir = safe_dir_path(self.server.root_dir, ranking_dir, FITNESS_OUTPUT_DIR, create=True)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if not is_relative_to_path(path, allowed_dir):
                self.send_json({"error": "CSV fuori dalla cartella ranking selezionata"}, HTTPStatus.BAD_REQUEST)
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

    def send_config(self, relative_path: str, config_dir_text: Any = None, include_subdirs: bool = False) -> None:
        path = safe_path(self.server.root_dir, relative_path, allowed_suffixes={".json"}, must_exist=True)
        if path is None:
            self.send_json({"error": "Percorso JSON non valido"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            config_root = safe_dir_path(self.server.root_dir, config_dir_text, CONFIG_DIR, create=False)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        try:
            path.resolve().relative_to(config_root)
        except ValueError:
            self.send_json({"error": "Il JSON deve stare nella cartella config selezionata"}, HTTPStatus.BAD_REQUEST)
            return
        if not include_subdirs and path.parent.resolve() != config_root.resolve():
            self.send_json({"error": "Il JSON deve stare nella root config selezionata"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            self.send_json({"error": f"JSON non valido: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        except OSError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.send_json({"path": to_relative(self.server.root_dir, path), "payload": payload})

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


class StockPlatformServer(ThreadingHTTPServer):
    allow_reuse_address = True

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
        ensure_output_dirs(root_dir)
        self.jobs = JobManager(root_dir)
        self.fx_cache: dict[str, Any] | None = None
        self.fx_cache_at = 0.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Avvia la piattaforma locale unificata per fondamentali, scoring e basket.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host su cui esporre la UI. Default: 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8767,
        help="Porta della UI. Usa 0 per far scegliere una porta libera al sistema.",
    )
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=Path("."),
        help="Cartella progetto in cui trovare script, config e CSV. Default: cartella corrente.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    app_dir = Path(__file__).resolve().parent
    root_dir = args.root_dir.resolve()

    server = StockPlatformServer(
        (args.host, args.port),
        StockPlatformHandler,
        app_dir=app_dir,
        root_dir=root_dir,
    )
    host, port = server.server_address[:2]
    print(f"Stock Platform: http://{host}:{port}/")
    print(f"Root dir: {root_dir}")
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
