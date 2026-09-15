from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from body import Body
from config import (
    AUTOBACKUP_EVERY,
    AUTOPROMPT_HISTORY_DIR,
    AUTOPROMPT_SNAPSHOT_EVERY,
    BACKUP_DIR,
    BODY,
    EXPERIMENT,
    IMMUTABLE_PROMPT,
    LOG_DIR,
    LOG_EVERY,
    MAX_CONTEXT_TOKENS,
    MAX_ITERATIONS,
    MLX_AUTOSTART,
    MLX_HEALTH_TIMEOUT_S,
    MLX_HOST,
    MLX_MAX_TOKENS,
    MLX_MODEL,
    MLX_PORT,
    MLX_PYTHON_PATH,
    REASONING_DIR,
    RECENT_HISTORY,
    SNAPSHOT_DIR,
    SNAPSHOT_EVERY,
)
from executor import Executor
from llm_client import ALLOWED_ACTIONS, LLMClient, parse_actions

AUTOPROMPT_PATH = "autoprompt.txt"
_mlx_process: subprocess.Popen[str] | None = None


def utc_now() -> str:
    """Retorna la marca de tiempo actual en formato UTC ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    """Calcula el hash SHA-256 de un archivo para verificar integridad inmutable."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Añade un registro JSON persistente a un archivo .jsonl."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def validate_action(action: dict[str, Any]) -> None:
    """Valida estrictamente los tipos y claves obligatorias de una acción."""
    if not isinstance(action, dict):
        raise ValueError("action must be a JSON object")

    operation = action.get("action")
    if operation not in ALLOWED_ACTIONS:
        raise ValueError(f"invalid action: {operation!r}")

    path = action.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")

    if operation == "WRITE" and not isinstance(action.get("content", ""), str):
        raise ValueError("WRITE.content must be a string")

    if operation == "EXECUTE":
        args = action.get("args", [])
        if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise ValueError("EXECUTE.args must be a list of strings")


def perform_action(body: Body, executor: Executor, action: dict[str, Any]) -> dict[str, Any]:
    """Enruta y ejecuta una acción individual sobre el cuerpo o el ejecutor."""
    validate_action(action)
    operation = action["action"]
    path = action["path"]

    if operation == "WRITE":
        return body.write(path, action.get("content", ""))
    if operation == "READ":
        return body.read(path)
    if operation == "DELETE":
        return body.delete(path)
    if operation == "LIST":
        return body.list(path)
    if operation == "EXECUTE":
        return executor.execute(path, action.get("args", []))

    raise AssertionError("unreachable")


def create_host_backup(body: Body, iteration: int) -> None:
    """Crea una copia de seguridad comprimida .tar.gz fuera del cuerpo del agente."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"body_backup_iter_{iteration:05d}.tar.gz"
    try:
        with tarfile.open(target, "w:gz") as tar:
            tar.add(body.root, arcname=f"body_iter_{iteration}")
        print(f"\n📦 [HOST BACKUP] Respaldo comprimido guardado en {target.name}", flush=True)
    except Exception as e:
        print(f"\n⚠️ [HOST BACKUP] Fallo al crear respaldo: {e}", flush=True)


def ensure_initial_state() -> None:
    """Inicializa directorios base y garantiza la existencia del autoprompt inicial."""
    for directory in (
        BODY,
        EXPERIMENT,
        LOG_DIR,
        SNAPSHOT_DIR,
        AUTOPROMPT_HISTORY_DIR,
        REASONING_DIR,
        BACKUP_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    autoprompt = BODY / AUTOPROMPT_PATH
    if not autoprompt.exists():
        autoprompt.write_text(
            "Este es tu autoprompt evolutivo.\n\n"
            "Puedes modificar este archivo cuando consideres que cambiarlo mejora tu capacidad de trabajo.\n"
            "Su contenido se cargará de nuevo en la siguiente iteración.\n",
            encoding="utf-8",
        )


def build_user_context(
    iteration: int,
    body: Body,
    autoprompt: str,
    previous_result: Any,
    history: list[dict[str, Any]],
) -> str:
    """Construye el contexto de observación para el modelo.
    Utiliza body.shallow_tree() para mantener un coste de tokens O(1)
    y forzar la exploración activa con la primitiva LIST.
    """
    compact_history = []
    for h in history[-RECENT_HISTORY:]:
        compact_history.append({
            "iteration": h.get("iteration"),
            "ok": h.get("ok"),
            "actions": h.get("actions"),
            "results": h.get("results"),
        })

    payload = {
        "iteration": iteration,
        "context": {
            "maximum_tokens": MAX_CONTEXT_TOKENS,
            "note": (
                "Your working context is finite. The body persists between iterations. "
                "'body_root' lists only the top-level items of your body. "
                "Use the LIST action to explore the contents of subdirectories."
            ),
        },
        "body_root": body.shallow_tree(),
        "autoprompt": autoprompt,
        "previous_action_result": previous_result,
        "recent_history": compact_history,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def snapshot_body(body: Body, iteration: int) -> None:
    """Copia el cuerpo actual y genera un volcado de texto para auditoría externa."""
    target = SNAPSHOT_DIR / f"iter_{iteration:08d}"
    dump = SNAPSHOT_DIR / f"iter_{iteration:08d}_body_dump.txt"

    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(body.root, target)
    body.dump_text(dump)


def snapshot_autoprompt(iteration: int) -> None:
    """Guarda un registro histórico del autoprompt en la iteración dada."""
    source = BODY / AUTOPROMPT_PATH
    target = AUTOPROMPT_HISTORY_DIR / f"autoprompt_{iteration:08d}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        shutil.copy2(source, target)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Verifica si un puerto TCP local está ocupado."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def is_server_online() -> bool:
    """Comprueba si el servidor MLX está activo y respondiendo."""
    import urllib.request
    url = f"http://{MLX_HOST}:{MLX_PORT}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            return response.status in (200, 401)
    except Exception:
        return False


def get_active_model_name(fallback: str) -> str:
    """Consulta al servidor MLX el nombre exacto del modelo cargado en memoria."""
    import urllib.request
    url = f"http://{MLX_HOST}:{MLX_PORT}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            data = json.loads(response.read().decode("utf-8"))
            models = data.get("data", [])
            if models:
                for m in models:
                    m_id = str(m.get("id", ""))
                    if "nail" in m_id.lower():
                        return m_id
                return str(models[0].get("id", fallback))
    except Exception:
        pass
    return fallback


def wait_for_mlx() -> None:
    """Espera a que el backend de inferencia MLX termine de cargar pesos en RAM unificada."""
    deadline = time.time() + MLX_HEALTH_TIMEOUT_S
    url = f"http://{MLX_HOST}:{MLX_PORT}/v1/models"

    print(f"⏳ Esperando servidor MLX en {url} (máx {int(MLX_HEALTH_TIMEOUT_S)}s)...", flush=True)
    last_print = 0.0

    while time.time() < deadline:
        if _mlx_process is not None and _mlx_process.poll() is not None:
            log_path = EXPERIMENT / "mlx_server.log"
            details = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else "Sin log."
            raise RuntimeError(
                f"\n❌ El proceso MLX terminó con error (código: {_mlx_process.returncode}).\n"
                f"--- Contenido de mlx_server.log ---\n{details[-1500:]}"
            )

        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status in (200, 401):
                    print("✅ Servidor MLX listo y respondiendo.", flush=True)
                    return
        except Exception:
            pass

        now = time.time()
        if now - last_print >= 5.0:
            remaining = int(deadline - now)
            print(f"   Cargando pesos en memoria unificada... ({remaining}s restantes)", flush=True)
            last_print = now
        time.sleep(1)

    raise RuntimeError(f"El endpoint local de MLX no respondió tras {MLX_HEALTH_TIMEOUT_S:.0f}s.")


def start_mlx_if_needed() -> None:
    """Arranca el servidor mlx_lm.server en un subproceso si no está en ejecución."""
    global _mlx_process

    if is_server_online():
        print(f"✅ Servidor MLX detectado y respondiendo en el puerto {MLX_PORT}.", flush=True)
        return

    if is_port_in_use(MLX_PORT, MLX_HOST):
        raise RuntimeError(
            f"❌ El puerto {MLX_PORT} está bloqueado por otro proceso.\n"
            f"   Ejecuta: lsof -ti:{MLX_PORT} | xargs kill -9"
        )

    if not MLX_AUTOSTART:
        wait_for_mlx()
        return

    if _mlx_process is not None:
        return

    python_bin = Path(MLX_PYTHON_PATH)
    if not python_bin.exists():
        fallback = shutil.which("python3")
        if fallback:
            python_bin = Path(fallback)
        else:
            raise RuntimeError(f"No se encontró el ejecutable Python en {MLX_PYTHON_PATH}.")

    log_path = EXPERIMENT / "mlx_server.log"
    log_handle = log_path.open("w", encoding="utf-8")

    cmd = [
        str(python_bin),
        "-m",
        "mlx_lm.server",
        "--model",
        MLX_MODEL,
        "--port",
        str(MLX_PORT),
        "--max-tokens",
        str(MLX_MAX_TOKENS),
    ]

    print(f"⚡ Iniciando servidor MLX en segundo plano...", flush=True)
    print(f"   Modelo:  {MLX_MODEL}")
    print(f"   Comando: {' '.join(cmd)}", flush=True)

    _mlx_process = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )

    wait_for_mlx()


def stop_mlx() -> None:
    """Detiene limpiamente el proceso del servidor MLX si fue iniciado por main.py."""
    global _mlx_process
    if _mlx_process is None:
        return

    print("\nDeteniendo servidor MLX...", flush=True)
    if _mlx_process.poll() is None:
        try:
            os.killpg(_mlx_process.pid, signal.SIGTERM)
            _mlx_process.wait(timeout=10)
        except Exception:
            try:
                _mlx_process.kill()
            except Exception:
                pass
    _mlx_process = None


def body_metrics(body: Body) -> tuple[int, int]:
    """Calcula el número total de archivos y bytes acumulados en todo el cuerpo."""
    files = 0
    total_bytes = 0
    for path in body.root.rglob("*"):
        if path.is_file():
            files += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                pass
    return files, total_bytes


def run() -> None:
    """Bucle principal de autopoiesis y evolución iterativa del agente."""
    ensure_initial_state()
    immutable_prompt = IMMUTABLE_PROMPT.read_text(encoding="utf-8")
    immutable_hash = sha256_file(IMMUTABLE_PROMPT)

    body = Body(BODY)
    executor = Executor(body)

    history: list[dict[str, Any]] = []
    previous_result: Any = None

    # Recuperar el número de iteración si el experimento se reanuda
    log_file = LOG_DIR / "iterations.jsonl"
    iteration = 0
    if log_file.exists():
        try:
            with log_file.open("r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
                if lines:
                    last_record = json.loads(lines[-1])
                    iteration = int(last_record.get("iteration", 0))
        except Exception:
            iteration = 0

    try:
        start_mlx_if_needed()
        active_model = get_active_model_name(MLX_MODEL)
        llm = LLMClient(model_name=active_model)

        print("=" * 72, flush=True)
        print("SISTEMA HÍBRIDO — AGENTE EVOLUTIVO UNIVERSAL (SHALLOW TREE)", flush=True)
        print(f"Directorio Body:     {BODY}", flush=True)
        print(f"Backend LLM:         http://{MLX_HOST}:{MLX_PORT}/v1", flush=True)
        print(f"Modelo Activo:       {active_model}", flush=True)
        print(f"Percepción del Body: Shallow Tree (Profundidad 1, O(1) tokens)", flush=True)
        print("=" * 72, flush=True)

        while True:
            iteration += 1
            if MAX_ITERATIONS and iteration > MAX_ITERATIONS:
                print(f"Límite alcanzado: MAX_ITERATIONS={MAX_ITERATIONS}.", flush=True)
                break

            autoprompt_file = BODY / AUTOPROMPT_PATH
            autoprompt = autoprompt_file.read_text(encoding="utf-8") if autoprompt_file.exists() else ""

            user_context = build_user_context(
                iteration=iteration,
                body=body,
                autoprompt=autoprompt,
                previous_result=previous_result,
                history=history,
            )

            started = time.perf_counter()
            response_text = ""
            reasoning_text = ""
            usage: dict[str, Any] = {}
            actions_to_run: list[dict[str, Any]] = []
            results_list: list[dict[str, Any]] = []
            ok = False

            print(f"\n▶️ [Iteración {iteration:04d}] Consultando {active_model}...", flush=True)

            try:
                response_text, reasoning_text, usage = llm.chat(
                    immutable_prompt,
                    user_context,
                )
                llm_elapsed = time.perf_counter() - started
                print(f"\n📥 Generación completada en {llm_elapsed:.2f}s.", flush=True)

                if reasoning_text:
                    thought_path = REASONING_DIR / f"iter_{iteration:08d}_thought.txt"
                    thought_path.write_text(reasoning_text, encoding="utf-8")

                actions_to_run = parse_actions(response_text, reasoning_text)

                # Ejecutar secuencialmente las acciones emitidas en el turno
                all_succeeded = True
                for idx, act in enumerate(actions_to_run, 1):
                    act_name = act.get("action")
                    act_path = act.get("path")
                    print(f"⚙️  Acción [{idx}/{len(actions_to_run)}]: {act_name} -> '{act_path}'", flush=True)
                    res = perform_action(body, executor, act)
                    results_list.append(res)

                    if not res.get("success", True):
                        all_succeeded = False
                        print(f"   ❌ Fallo en paso {idx}: {res.get('error', res.get('message', 'Error'))}", flush=True)
                        break  # Detiene la cadena para evitar daños en cascada

                ok = all_succeeded

            except Exception as exc:
                err_res = {
                    "success": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
                results_list.append(err_res)
                actions_to_run = [{"action": "PARSE_OR_RUNTIME_ERROR"}]
                ok = False
                print(f"\n⚠️ Error en iteración: {type(exc).__name__}: {exc}", flush=True)

            elapsed = time.perf_counter() - started
            files, total_bytes = body_metrics(body)

            # Compatibilidad estructural de salida
            main_action = actions_to_run[0] if len(actions_to_run) == 1 else actions_to_run
            main_result = results_list[0] if len(results_list) == 1 else results_list

            record = {
                "timestamp": utc_now(),
                "iteration": iteration,
                "ok": ok,
                "actions": actions_to_run,
                "results": results_list,
                "action": main_action,
                "result": main_result,
                "elapsed_seconds": round(elapsed, 4),
                "body_file_count": files,
                "body_size_bytes": total_bytes,
                "usage": usage,
                "response": response_text,
                "reasoning": reasoning_text,
                "immutable_prompt_sha256": immutable_hash,
            }

            history.append(record)
            previous_result = main_result

            if LOG_EVERY and iteration % LOG_EVERY == 0:
                save_jsonl(LOG_DIR / "iterations.jsonl", record)

            if SNAPSHOT_EVERY and iteration % SNAPSHOT_EVERY == 0:
                snapshot_body(body, iteration)

            if AUTOPROMPT_SNAPSHOT_EVERY and iteration % AUTOPROMPT_SNAPSHOT_EVERY == 0:
                snapshot_autoprompt(iteration)

            if AUTOBACKUP_EVERY and iteration % AUTOBACKUP_EVERY == 0:
                create_host_backup(body, iteration)

            print(f"\n📊 Resumen Iteración {iteration:04d}:")
            print(json.dumps({
                "iteration": iteration,
                "ok": ok,
                "actions_executed": len(actions_to_run),
                "body_total_files": files,
                "body_total_bytes": total_bytes,
                "elapsed_seconds": round(elapsed, 2),
            }, indent=2), flush=True)

    finally:
        stop_mlx()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nExperimento detenido por el usuario.", flush=True)
        stop_mlx()
        sys.exit(0)