from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from body import Body
from config import EXEC_CPU, EXEC_IMAGE, EXEC_MEMORY, EXEC_TIMEOUT_S


class Executor:
    """Ejecutor Universal Multi-Lenguaje (Python, Bash, Node.js, Binarios) en Docker.

    Inspecciona Shebangs (#!), extensiones y otorga permisos chmod +x automáticamente.
    Monta /body en lectura/escritura y mantiene la red habilitada.
    """

    def __init__(self, body: Body):
        self.body = body
        if not shutil.which("docker"):
            raise RuntimeError(
                "Docker es requerido para EXECUTE. Inicia Docker Desktop antes del experimento."
            )

    def execute(self, path: str, args: list[str]) -> dict[str, Any]:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")

        clean_args = list(args) if isinstance(args, list) else []
        if not all(isinstance(x, str) for x in clean_args):
            raise TypeError("args must be a list of strings")

        # Tolerancia: si pasa el intérprete en 'path' y el archivo en 'args'
        norm_path = path.strip().lower()
        if norm_path in ("python", "python3", "bash", "sh", "/bin/bash", "/bin/sh", "/usr/bin/python"):
            if clean_args:
                path = clean_args.pop(0)
            else:
                raise ValueError(f"Se especificó '{norm_path}' como ruta pero args está vacío.")

        path = path.lstrip("/")
        target = self.body.safe_path(path)
        if not target.exists() or target.is_dir():
            raise FileNotFoundError(path)

        # Habilitar permisos de ejecución (chmod +x / 0o755)
        try:
            target.chmod(target.stat().st_mode | 0o755)
        except Exception:
            pass

        rel_target = target.relative_to(self.body.root).as_posix()
        container_target = f"/body/{rel_target}"

        # Detección inteligente por Shebang
        shebang_interpreter: str | None = None
        try:
            with target.open("r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline().strip()
                if first_line.startswith("#!"):
                    shebang_interpreter = first_line[2:].strip()
        except Exception:
            pass

        exec_prefix: list[str] = []
        suffix = target.suffix.lower()

        if shebang_interpreter:
            parts = shebang_interpreter.split()
            if parts:
                base_bin = Path(parts[-1]).name
                if base_bin in ("python", "python3", "env"):
                    if any("python" in p for p in parts):
                        exec_prefix = ["python3"]
                    elif "bash" in parts:
                        exec_prefix = ["bash"]
                    elif "sh" in parts:
                        exec_prefix = ["sh"]
                    elif "node" in parts:
                        exec_prefix = ["node"]
                    else:
                        exec_prefix = [parts[-1]] + parts[1:]
                else:
                    exec_prefix = [base_bin] + parts[1:]
        else:
            # Fallback por extensión
            if suffix in (".sh", ".bash"):
                exec_prefix = ["bash"]
            elif suffix in (".py", ".pyw"):
                exec_prefix = ["python3"]
            elif suffix in (".js",):
                exec_prefix = ["node"]
            else:
                exec_prefix = []

        command = [
            "docker", "run", "--rm",
            "--init",
            "--network", "bridge",
            "--cpus", EXEC_CPU,
            "--memory", EXEC_MEMORY,
            "--pids-limit", "128",
            "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
            "-v", f"{self.body.root}:/body:rw",
            "-w", "/body",
            EXEC_IMAGE,
        ] + exec_prefix + [container_target, *clean_args]

        try:
            completed = subprocess.run(
                command,
                cwd=str(self.body.root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=EXEC_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "action": "EXECUTE",
                "error": "TimeoutExpired",
                "stdout": self._tail(exc.stdout),
                "stderr": self._tail(exc.stderr),
            }
        except Exception as exc:
            return {
                "success": False,
                "action": "EXECUTE",
                "error": type(exc).__name__,
                "message": str(exc),
            }

        return {
            "success": completed.returncode == 0,
            "action": "EXECUTE",
            "path": path,
            "returncode": completed.returncode,
            "stdout": self._tail(completed.stdout),
            "stderr": self._tail(completed.stderr),
        }

    @staticmethod
    def _tail(value: Any, limit: int = 20000) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return str(value)[-limit:]