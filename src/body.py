from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


class Body:
    """Gestiona el espacio de archivos físico del agente (directorio /body).
    Garantiza la contención de rutas y la manipulación segura de archivos.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def safe_path(self, relative_path: str) -> Path:
        """Resuelve una ruta relativa y asegura que permanezca estrictamente dentro de root."""
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("path must be a non-empty string")
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError("path outside body")
        return candidate

    def write(self, path: str, content: str = "") -> dict[str, Any]:
        """Crea o sobrescribe un archivo dentro del cuerpo."""
        target = self.safe_path(path)
        existed = target.exists()
        if existed and target.is_dir():
            raise IsADirectoryError(f"No se puede sobrescribir el directorio '{path}' con WRITE.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        target.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "action": "WRITE",
            "path": path,
            "created": not existed,
            "bytes_written": len(content.encode("utf-8")),
        }

    def read(self, path: str) -> dict[str, Any]:
        """Lee el contenido textual de un archivo dentro del cuerpo."""
        target = self.safe_path(path)
        if not target.exists():
            raise FileNotFoundError(f"El archivo '{path}' no existe.")
        if target.is_dir():
            raise IsADirectoryError(f"'{path}' es un directorio. Usa LIST para inspeccionarlo.")
        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "success": True,
            "action": "READ",
            "path": path,
            "content": content,
            "size_bytes": len(content.encode("utf-8")),
        }

    def delete(self, path: str) -> dict[str, Any]:
        """Elimina un archivo o directorio completo dentro del cuerpo."""
        target = self.safe_path(path)
        if not target.exists():
            raise FileNotFoundError(f"No se puede eliminar '{path}': no existe.")
        if target == self.root:
            raise PermissionError("No está permitido eliminar la raíz del cuerpo.")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"success": True, "action": "DELETE", "path": path}

    def list(self, path: str = ".") -> dict[str, Any]:
        """Inspecciona activamente el contenido de un directorio específico."""
        target = self.safe_path(path)
        if not target.exists():
            raise FileNotFoundError(f"El directorio '{path}' no existe.")
        if not target.is_dir():
            raise NotADirectoryError(f"'{path}' es un archivo, no un directorio.")

        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            entry_type = "directory" if item.is_dir() else "file"
            entry_data: dict[str, Any] = {
                "name": item.name,
                "type": entry_type,
            }
            if item.is_file():
                entry_data["size_bytes"] = item.stat().st_size
            entries.append(entry_data)

        rel_path = "." if target == self.root else str(target.relative_to(self.root))
        return {
            "success": True,
            "action": "LIST",
            "path": rel_path,
            "entries": entries,
            "total_items": len(entries),
        }

    def shallow_tree(self) -> list[dict[str, Any]]:
        """Devuelve únicamente el primer nivel del cuerpo (profundidad 1).
        Mantiene el coste de tokens constante O(1) independientemente del número
        de archivos que el agente acumule en subdirectorios.
        """
        entries = []
        for item in sorted(self.root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            rel = str(item.relative_to(self.root))
            entry: dict[str, Any] = {
                "path": rel,
                "type": "directory" if item.is_dir() else "file",
            }
            if item.is_file():
                entry["size_bytes"] = item.stat().st_size
            entries.append(entry)
        return entries

    def tree(self) -> list[dict[str, Any]]:
        """Árbol recursivo completo. Reservado para volcados externos y diagnósticos."""
        result = []
        for p in sorted(self.root.rglob("*")):
            rel = str(p.relative_to(self.root))
            if p.is_dir():
                result.append({"path": rel, "type": "directory"})
            else:
                result.append({
                    "path": rel,
                    "type": "file",
                    "size_bytes": p.stat().st_size,
                })
        return result

    def dump_text(self, output_path: Path) -> None:
        """Genera un volcado textual plano de todo el cuerpo para auditoría externa."""
        chunks: list[str] = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if p.is_dir():
                chunks.append(f"\n===== DIRECTORY: {rel} =====\n")
                continue
            chunks.append(f"\n===== FILE: {rel} =====\n")
            try:
                data = p.read_bytes()
                if b"\x00" in data:
                    chunks.append("[BINARY FILE OMITTED]\n")
                else:
                    chunks.append(data.decode("utf-8", errors="replace"))
                    chunks.append("\n")
            except Exception as exc:
                chunks.append(f"[READ ERROR: {type(exc).__name__}: {exc}]\n")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("".join(chunks), encoding="utf-8")

    def json_tree(self) -> str:
        """Devuelve la estructura recursiva completa en formato JSON formateado."""
        return json.dumps(self.tree(), ensure_ascii=False, indent=2)