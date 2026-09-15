from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

from config import (
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_PRESENCE_PENALTY,
    LLM_REPETITION_PENALTY,
    LLM_TEMPERATURE,
    REQUEST_TIMEOUT_S,
)

ALLOWED_ACTIONS = {"WRITE", "READ", "DELETE", "LIST", "EXECUTE"}


def _clean_special_tokens(text: str) -> str:
    cleaned = re.sub(r"<\|[^|>]+(?:\|>)?", "", text)
    return cleaned.strip()


def _detect_loop_ngrams(text: str) -> bool:
    """Detecta bucles repetitivos en el razonamiento de streaming."""
    for w in (120, 240):
        if len(text) >= w * 2:
            target = text[-w:].strip()
            history = text[-(w * 15) : -w]
            if target in history:
                return True
    return False


def _extract_actions_from_obj(obj: Any) -> list[dict[str, Any]]:
    """Extrae acciones válidas soportando {"actions": [...]} o {"action": ...}."""
    actions: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        if "actions" in obj and isinstance(obj["actions"], list):
            for item in obj["actions"]:
                if isinstance(item, dict) and item.get("action") in ALLOWED_ACTIONS:
                    actions.append(item)
        elif obj.get("action") in ALLOWED_ACTIONS:
            actions.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item.get("action") in ALLOWED_ACTIONS:
                actions.append(item)
    return actions


def _find_json_actions(text: str) -> list[dict[str, Any]]:
    """Encuentra y analiza bloques JSON válidos en el texto."""
    results: list[dict[str, Any]] = []
    pos = 0
    length = len(text)

    while pos < length:
        start = text.find("{", pos)
        if start == -1:
            break

        depth = 0
        in_string = False
        escape = False
        end = -1

        for i in range(start, length):
            char = text[i]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break

        if end != -1:
            snippet = text[start : end + 1]
            obj = None
            try:
                obj = json.loads(snippet, strict=False)
            except Exception:
                fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', snippet)
                try:
                    obj = json.loads(fixed, strict=False)
                except Exception:
                    pass

            if obj:
                extracted = _extract_actions_from_obj(obj)
                if extracted:
                    results.extend(extracted)
            pos = end + 1
        else:
            pos = start + 1

    return results


def _rescue_conversational_action(text: str) -> list[dict[str, Any]]:
    """Rescata intenciones expresadas en lenguaje natural si falla el JSON."""
    rescued: list[dict[str, Any]] = []

    # Patrón: EXECUTE("script.sh", ["arg1"])
    exec_calls = re.findall(r'EXECUTE\(\s*["\']([^"\']+)["\'](?:\s*,\s*(\[[^\]]*\]))?\s*\)', text)
    if exec_calls:
        target_path, raw_args = exec_calls[-1]
        args_list: list[str] = []
        if raw_args:
            try:
                args_list = json.loads(raw_args, strict=False)
            except Exception:
                args_list = re.findall(r'["\']([^"\']+)["\']', raw_args)
        rescued.append({
            "action": "EXECUTE",
            "path": target_path.strip(),
            "args": args_list,
        })
        return rescued

    # Patrón: Path: `archivo.py` ... Content: `código`
    path_matches = list(re.finditer(r"Path:\s*`?([a-zA-Z0-9_\-\./ ]+\.[a-zA-Z0-9]+)`?", text, re.IGNORECASE))
    if path_matches:
        last_path_m = path_matches[-1]
        path = last_path_m.group(1).strip()
        sub = text[last_path_m.end() :]
        c_match = re.search(r"Content:\s*`+([\s\S]*?)`+", sub, re.IGNORECASE)
        if c_match:
            content = c_match.group(1).strip().replace("\\n", "\n").replace('\\"', '"')
            rescued.append({"action": "WRITE", "path": path, "content": content})
            return rescued

    # Patrón: Action: READ "ruta"
    read_matches = re.findall(r"Action:\s*READ\s+[`\"']?([a-zA-Z0-9_\-\./]+)[`\"']?", text, re.IGNORECASE)
    if read_matches:
        rescued.append({"action": "READ", "path": read_matches[-1].strip()})
        return rescued

    return rescued


def parse_actions(content: str, reasoning: str = "") -> list[dict[str, Any]]:
    """Extrae la lista de acciones priorizando content con fallback exhaustivo en reasoning."""
    clean_content = _clean_special_tokens(content).strip()
    clean_reasoning = _clean_special_tokens(reasoning).strip()

    # 1. Analizar respuesta formal (content)
    if clean_content:
        # Markdown ```json ... ```
        m = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
        for block in reversed(m):
            actions = _find_json_actions(block)
            if actions:
                return actions

        actions = _find_json_actions(clean_content)
        if actions:
            return actions

        rescued = _rescue_conversational_action(clean_content)
        if rescued:
            return rescued

    # 2. Fallback: Analizar en pensamiento (reasoning)
    if clean_reasoning:
        m = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_reasoning)
        for block in reversed(m):
            actions = _find_json_actions(block)
            filtered = [a for a in actions if a.get("path") not in ("<ruta>", "ruta")]
            if filtered:
                return filtered

        actions = _find_json_actions(clean_reasoning)
        filtered = [a for a in actions if a.get("path") not in ("<ruta>", "ruta")]
        if filtered:
            return filtered

        rescued = _rescue_conversational_action(clean_reasoning)
        filtered = [a for a in rescued if a.get("path") not in ("<ruta>", "ruta")]
        if filtered:
            return filtered

    snippet_c = (clean_content[:200] + "...") if len(clean_content) > 200 else clean_content
    snippet_r = (clean_reasoning[-300:] + "...") if len(clean_reasoning) > 300 else clean_reasoning
    raise ValueError(
        f"No se encontró ninguna acción JSON válida.\n"
        f"Contenido: {snippet_c!r}\n"
        f"Razonamiento final: {snippet_r!r}"
    )


class LLMClient:
    """Cliente HTTP con Streaming, soporte CoT y auto-rescate de acciones."""

    def __init__(self, model_name: str | None = None) -> None:
        self.url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
        self.model = model_name or LLM_MODEL

    def chat(
        self,
        system_text: str,
        user_text: str,
    ) -> tuple[str, str, dict[str, Any]]:

        payload = {
            "model": self.model,
            "temperature": LLM_TEMPERATURE,
            "presence_penalty": LLM_PRESENCE_PENALTY,
            "repetition_penalty": LLM_REPETITION_PENALTY,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
        }

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        reasoning_chunks: list[str] = []
        content_chunks: list[str] = []
        usage: dict[str, Any] = {}

        is_thinking = False
        has_content = False

        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            while True:
                raw_line = response.readline()
                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except Exception:
                    continue

                if "usage" in chunk and chunk["usage"]:
                    usage = chunk["usage"]

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})

                # 1. Fragmentos de pensamiento (CoT)
                r_text = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if r_text:
                    if not is_thinking:
                        print("\n🧠 [Pensamiento]:\n", end="", flush=True)
                        is_thinking = True
                    print(r_text, end="", flush=True)
                    reasoning_chunks.append(r_text)

                    current_thought = "".join(reasoning_chunks)
                    if len(reasoning_chunks) % 5 == 0 and _detect_loop_ngrams(current_thought):
                        print("\n⚡ [Detector Anti-Bucle]: Ciclo repetitivo detectado. Procediendo a acción...", flush=True)
                        break

                # 2. Fragmentos de contenido / acción final
                c_text = delta.get("content") or ""
                if c_text:
                    if is_thinking and not has_content:
                        print("\n\n💡 [Acción]:\n", end="", flush=True)
                        is_thinking = False
                    elif not has_content and not is_thinking:
                        print("\n💡 [Acción]:\n", end="", flush=True)
                    has_content = True
                    print(c_text, end="", flush=True)
                    content_chunks.append(c_text)

        print("", flush=True)

        full_content = "".join(content_chunks).strip()
        full_reasoning = "".join(reasoning_chunks).strip()

        # Normalizar tags <think>
        if "<think>" in full_content and "</think>" in full_content:
            parts = full_content.split("</think>", 1)
            thought = parts[0].replace("<think>", "").strip()
            answer = parts[1].strip()
            if not full_reasoning:
                full_reasoning = thought
            full_content = answer
        elif "<think>" in full_content and not full_reasoning:
            full_reasoning = full_content.replace("<think>", "").strip()
            full_content = ""

        # Auto-rescate si se cortó por detector anti-bucle
        if not full_content and full_reasoning:
            try:
                rescued_actions = parse_actions("", full_reasoning)
                full_content = json.dumps({"actions": rescued_actions})
                print(f"⚡ [Auto-Rescate]: {len(rescued_actions)} acción(es) recuperada(s) del razonamiento.", flush=True)
            except Exception:
                pass

        return full_content, full_reasoning, usage