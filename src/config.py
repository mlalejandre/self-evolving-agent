from __future__ import annotations

import os
from pathlib import Path

# ============================================================
# RUTAS DEL PROYECTO
# ============================================================

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent

BODY = PROJECT_ROOT / "body"
EXPERIMENT = PROJECT_ROOT / "experiment"
IMMUTABLE_PROMPT = PROJECT_ROOT / "prompt_inmutable.txt"

LOG_DIR = EXPERIMENT / "logs"
SNAPSHOT_DIR = EXPERIMENT / "snapshots"
AUTOPROMPT_HISTORY_DIR = EXPERIMENT / "autoprompt_history"
REASONING_DIR = EXPERIMENT / "reasoning"
BACKUP_DIR = EXPERIMENT / "backups"

# ============================================================
# CONFIGURACIÓN DEL LLM (LOCAL / OMLX / MLX)
# ============================================================

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "peculiar-ragdoll/Nail-Qwen3.6-35B-A3B-MLX")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.6"))

# Penalizaciones anti-repetición
LLM_PRESENCE_PENALTY = float(os.getenv("LLM_PRESENCE_PENALTY", "0.3"))
LLM_REPETITION_PENALTY = float(os.getenv("LLM_REPETITION_PENALTY", "1.1"))

REQUEST_TIMEOUT_S = int(os.getenv("REQUEST_TIMEOUT_S", "600"))
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "100000"))

# ============================================================
# CONFIGURACIÓN DEL SERVIDOR MLX LOCAL
# ============================================================

MLX_HOST = os.getenv("MLX_HOST", os.getenv("OMLX_HOST", "127.0.0.1"))
MLX_PORT = int(os.getenv("MLX_PORT", os.getenv("OMLX_PORT", "8080")))
MLX_AUTOSTART = os.getenv("MLX_AUTOSTART", os.getenv("OMLX_AUTOSTART", "1")).strip() in {"1", "true", "True"}
MLX_HEALTH_TIMEOUT_S = float(os.getenv("MLX_HEALTH_TIMEOUT_S", "120.0"))

DEFAULT_MLX_PYTHON = str(Path.home() / "mlx-env" / "bin" / "python")
MLX_PYTHON_PATH = os.getenv("MLX_PYTHON_PATH", DEFAULT_MLX_PYTHON)
MLX_MODEL = os.getenv("MLX_MODEL", LLM_MODEL)
MLX_MAX_TOKENS = int(os.getenv("MLX_MAX_TOKENS", "8192"))

# ============================================================
# PARÁMETROS DEL BUCLE DEL EXPERIMENTO
# ============================================================

MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "0"))
RECENT_HISTORY = int(os.getenv("RECENT_HISTORY", "5"))

SNAPSHOT_EVERY = int(os.getenv("SNAPSHOT_EVERY", "100"))
AUTOPROMPT_SNAPSHOT_EVERY = int(os.getenv("AUTOPROMPT_SNAPSHOT_EVERY", "100"))
LOG_EVERY = int(os.getenv("LOG_EVERY", "1"))
AUTOBACKUP_EVERY = int(os.getenv("AUTOBACKUP_EVERY", "100"))

# ============================================================
# CONFIGURACIÓN DEL EXECUTOR UNIVERSAL (DOCKER)
# ============================================================

# python:3.11 contiene bash, python, pip y utilidades esenciales
EXEC_IMAGE = os.getenv("EXEC_IMAGE", "python:3.11")
EXEC_CPU = os.getenv("EXEC_CPU", "2.0")
EXEC_MEMORY = os.getenv("EXEC_MEMORY", "2g")
EXEC_TIMEOUT_S = int(os.getenv("EXEC_TIMEOUT_S", "60"))