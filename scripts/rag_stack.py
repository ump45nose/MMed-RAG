#!/usr/bin/env python3
"""RAG demo stack orchestrator for local Milvus deployments."""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "docker-compose.dev.yml"
MILVUS_COMPOSE = ROOT / "docker-compose.override.milvus.yml"
PROFILE_COMPOSE_TEMPLATE = "docker-compose.override.{profile}.yml"
ENV_TEMPLATE = ".env.{profile}"
DEFAULT_ENV = ROOT / ".env"
BACKEND_STACK_SERVICES = ["db", "minio", "etcd", "milvus", "backend"]


def run_command(args: Sequence[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run one command from the repository root and stream useful output."""
    print("+ " + " ".join(args), flush=True)
    return subprocess.run(
        list(args),
        cwd=ROOT,
        env=env,
        text=True,
        check=check,
    )


def command_output(args: Sequence[str], *, check: bool = True) -> str:
    """Run one command and return stripped stdout for health probes."""
    completed = subprocess.run(
        list(args),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )
    return completed.stdout.strip()


def has_nvidia_gpu() -> bool:
    """Detect whether the current machine exposes an NVIDIA GPU to the host."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def select_profile(explicit: str | None = None) -> str:
    """Choose office/home profile from explicit CLI, hostname hints, or GPU presence."""
    if explicit:
        return explicit

    hostname = socket.gethostname().lower()
    office_markers = ("office", "corp", "work", "公司", "workstation")
    home_markers = ("home", "gaming", "desktop", "laptop")
    if any(marker in hostname for marker in office_markers):
        return "office"
    if any(marker in hostname for marker in home_markers):
        return "home"

    # 有 GPU 的机器默认按 home/本地模型环境处理；否则按 office 的 API 环境处理。
    return "home" if has_nvidia_gpu() else "office"


def selected_files(profile: str) -> tuple[Path, list[Path]]:
    """Resolve env and compose files for the selected deployment profile."""
    profile_env = ROOT / ENV_TEMPLATE.format(profile=profile)
    env_file = profile_env if profile_env.exists() else DEFAULT_ENV
    profile_compose = ROOT / PROFILE_COMPOSE_TEMPLATE.format(profile=profile)
    compose_files = [BASE_COMPOSE, MILVUS_COMPOSE]
    if profile_compose.exists():
        compose_files.append(profile_compose)
    return env_file, compose_files


def compose_args(profile: str) -> list[str]:
    """Build docker compose arguments using base, Milvus, and profile override files."""
    env_file, compose_files = selected_files(profile)
    args = ["docker", "compose", "--env-file", str(env_file)]
    for compose_file in compose_files:
        args.extend(["-f", str(compose_file)])
    return args


def wait_until(name: str, probe, *, timeout: int = 180, interval: float = 3.0) -> None:
    """Poll one readiness probe until it succeeds or times out."""
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            if probe():
                print(f"{name} ready", flush=True)
                return
        except Exception as exc:  # noqa: BLE001 - probe errors are reported in timeout message.
            last_error = str(exc)
        time.sleep(interval)
    raise TimeoutError(f"{name} not ready after {timeout}s. Last error: {last_error}")


def service_container_id(profile: str, service: str) -> str:
    """Return the current container id for one compose service."""
    return command_output([*compose_args(profile), "ps", "-q", service])


def wait_database(profile: str) -> None:
    """Wait for the repository database service; MySQL is primary, Postgres is supported for overrides."""
    env_values = load_env_file(selected_files(profile)[0])
    if env_values.get("POSTGRES_HOST"):
        wait_postgres(profile)
        return
    wait_mysql(profile)


def wait_mysql(profile: str) -> None:
    """Wait until MySQL accepts authenticated ping inside the db container."""
    def probe() -> bool:
        run_command(
            [
                *compose_args(profile),
                "exec",
                "-T",
                "db",
                "mysqladmin",
                "ping",
                "-h",
                "localhost",
                "-u",
                "ragwebui",
                "--password=ragwebui",
            ],
            check=True,
        )
        return True

    wait_until("MySQL", probe, timeout=240)


def wait_postgres(profile: str) -> None:
    """Wait until a Postgres service is ready when a profile swaps the database."""
    def probe() -> bool:
        run_command([*compose_args(profile), "exec", "-T", "postgres", "pg_isready"], check=True)
        return True

    wait_until("Postgres", probe, timeout=240)


def wait_milvus() -> None:
    """Wait until Milvus standalone reports healthy on the host health endpoint."""
    def probe() -> bool:
        with urllib.request.urlopen("http://localhost:9091/healthz", timeout=5) as response:
            return response.status == 200

    wait_until("Milvus", probe, timeout=300)


def wait_backend() -> None:
    """Wait until backend /api/health returns healthy JSON."""
    def probe() -> bool:
        with urllib.request.urlopen("http://localhost:8000/api/health", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("status") == "healthy"

    wait_until("Backend", probe, timeout=240)


def run_alembic(profile: str) -> None:
    """Run Alembic migration after containers are healthy to keep schema deterministic."""
    run_command([*compose_args(profile), "exec", "-T", "backend", "alembic", "upgrade", "head"])


def seed_if_needed(profile: str) -> None:
    """Seed demo metadata only when the KB database is empty and the JSONL dataset exists."""
    dataset = ROOT / "backend" / "evaluation" / "datasets" / "interview_demo.jsonl"
    if not dataset.exists():
        print(f"seed skipped: dataset not found: {dataset}", flush=True)
        return

    code = r'''
from pathlib import Path
from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeBase

db = SessionLocal()
try:
    kb_count = db.query(KnowledgeBase).count()
    dataset = Path("evaluation/datasets/interview_demo.jsonl")
    rows = [line for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if kb_count:
        print(f"seed skipped: knowledge_bases={kb_count}, dataset_rows={len(rows)}")
    else:
        print(
            "seed notice: interview_demo.jsonl is available "
            f"with {len(rows)} rows; create/upload source DOCX before vector seeding."
        )
finally:
    db.close()
'''
    run_command([*compose_args(profile), "exec", "-T", "backend", "python", "-c", code])


def load_env_file(path: Path) -> dict[str, str]:
    """Load simple KEY=VALUE pairs from a dotenv file without expanding secrets."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def up(args: argparse.Namespace) -> None:
    """Bring up Milvus stack, wait for health, migrate, and optionally seed."""
    profile = select_profile(args.profile)
    env_file, compose_files = selected_files(profile)
    print(f"profile={profile} host={socket.gethostname()} os={platform.system()} gpu={has_nvidia_gpu()}")
    print(f"env_file={env_file}")
    print("compose_files=" + ", ".join(str(item) for item in compose_files))

    # 默认只启动后端依赖，避免前端镜像构建受 npm 网络影响；--full 才启动 nginx/frontend。
    services = [] if args.full else BACKEND_STACK_SERVICES
    run_command([*compose_args(profile), "up", "-d", "--build", *services])
    wait_database(profile)
    wait_milvus()
    wait_backend()
    run_alembic(profile)
    if args.seed:
        seed_if_needed(profile)


def down(args: argparse.Namespace) -> None:
    """Stop the selected compose stack, optionally removing named volumes."""
    profile = select_profile(args.profile)
    command = [*compose_args(profile), "down"]
    if args.volumes:
        command.append("-v")
    run_command(command)


def reset(args: argparse.Namespace) -> None:
    """Destroy volumes and recreate a fresh Milvus stack for environment alignment."""
    profile = select_profile(args.profile)
    run_command([*compose_args(profile), "down", "-v"])
    args.profile = profile
    up(args)


def seed(args: argparse.Namespace) -> None:
    """Run optional seed logic against an already running backend."""
    profile = select_profile(args.profile)
    seed_if_needed(profile)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    """Parse CLI commands for stack lifecycle operations."""
    parser = argparse.ArgumentParser(description="One-click Milvus RAG stack orchestration.")
    parser.add_argument("--profile", choices=["office", "home"], help="Override auto profile selection.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    up_parser = subparsers.add_parser("up", help="Start stack and wait for health.")
    up_parser.add_argument("--seed", action="store_true", help="Seed demo dataset metadata when empty.")
    up_parser.add_argument("--full", action="store_true", help="Also start frontend and nginx services.")

    down_parser = subparsers.add_parser("down", help="Stop stack.")
    down_parser.add_argument("-v", "--volumes", action="store_true", help="Remove named volumes.")

    reset_parser = subparsers.add_parser("reset", help="Run down -v, then up.")
    reset_parser.add_argument("--seed", action="store_true", help="Seed after reset.")
    reset_parser.add_argument("--full", action="store_true", help="Also start frontend and nginx services.")

    subparsers.add_parser("seed", help="Run seed logic only.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    """Dispatch the selected orchestration command."""
    args = parse_args(argv or sys.argv[1:])
    actions = {
        "up": up,
        "down": down,
        "reset": reset,
        "seed": seed,
    }
    actions[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
