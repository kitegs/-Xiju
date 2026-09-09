"""Restricted executor for the rare cases that truly require generated code.

It is intentionally not exposed as an API endpoint in the first milestone.
The product must first collect user approval and a structured execution plan.
"""
from __future__ import annotations

import asyncio
import subprocess
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .config import SANDBOX_ENABLED, SANDBOX_IMAGE


@dataclass(frozen=True)
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int


class SandboxUnavailable(RuntimeError):
    pass


def run_generated_python(code: str, dataset_path: Path, timeout_seconds: int = 20) -> SandboxResult:
    """Run code only inside a non-networked, read-only, resource-limited container.

    No caller should use this for normal profiling, aggregation, charting or cleaning:
    those operations belong to deterministic host-side tools. The caller must validate
    a user-approved task plan before reaching this function.
    """
    if not SANDBOX_ENABLED or not SANDBOX_IMAGE:
        raise SandboxUnavailable("Sandbox is not configured")
    source = dataset_path.resolve()
    if not source.is_file():
        raise ValueError("Dataset file is required")
    with tempfile.TemporaryDirectory(prefix="aibi-sandbox-") as temp_dir:
        mounted_data = Path(temp_dir).resolve()
        shutil.copy2(source, mounted_data / f"dataset{source.suffix.lower()}")
        command = [
            "docker", "run", "--rm", "-i", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "128", "--memory", "512m", "--cpus", "1.0",
            "--user", "10001:10001", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,src={mounted_data},dst=/data,readonly",
            SANDBOX_IMAGE, "python", "-I", "-",
        ]
        try:
            completed = subprocess.run(
                command, input=code, text=True, capture_output=True, timeout=timeout_seconds,
                check=False, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Sandbox execution exceeded its time limit") from exc
    # Keep generated output bounded before it can enter an agent context or a report.
    return SandboxResult(stdout=completed.stdout[:1_000_000], stderr=completed.stderr[:100_000], exit_code=completed.returncode)


async def run_generated_python_async(code: str, dataset_path: Path, timeout_seconds: int = 20) -> SandboxResult:
    """Async variant whose Docker process is stopped when the owning Run is cancelled."""
    if not SANDBOX_ENABLED or not SANDBOX_IMAGE:
        raise SandboxUnavailable("Sandbox is not configured")
    source = dataset_path.resolve()
    if not source.is_file():
        raise ValueError("Dataset file is required")
    container_name = f"aibi-sandbox-{uuid4().hex[:16]}"
    with tempfile.TemporaryDirectory(prefix="aibi-sandbox-") as temp_dir:
        mounted_data = Path(temp_dir).resolve()
        shutil.copy2(source, mounted_data / f"dataset{source.suffix.lower()}")
        command = [
            "docker", "run", "--rm", "--name", container_name, "-i", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "128", "--memory", "512m", "--cpus", "1.0",
            "--user", "10001:10001", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,src={mounted_data},dst=/data,readonly",
            SANDBOX_IMAGE, "python", "-I", "-",
        ]
        process = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(code.encode("utf-8")), timeout_seconds)
        except (asyncio.CancelledError, TimeoutError) as exc:
            cleanup = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await cleanup.wait()
            if process.returncode is None:
                process.kill()
                await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise TimeoutError("Sandbox execution exceeded its time limit") from exc
    return SandboxResult(
        stdout=stdout.decode("utf-8", "replace")[:1_000_000],
        stderr=stderr.decode("utf-8", "replace")[:100_000], exit_code=process.returncode or 0,
    )
