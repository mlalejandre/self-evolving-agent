# Proyecto Híbrido — Self-Evolving Autonomous Agent

Arquitectura híbrida de evolución autónoma para modelos de lenguaje locales (oMLX / MLX LM).

## Características Principales

1. **Ejecución Multi-Lenguaje Universal**: El agente no está restringido a Python. Puede escribir y ejecutar scripts en **Bash**, **Python**, **Node.js** o ejecutables compilados. El entorno analiza automáticamente el *Shebang* (`#!`) o la extensión del archivo y aplica permisos de ejecución (`chmod +x`).
2. **Soporte Multi-Acción**: El agente puede encadenar múltiples acciones lógicas en un solo turno (por ejemplo, escribir un script y ejecutarlo de inmediato) mediante la clave `"actions": [...]`.
3. **Aislamiento Seguro en Docker**: Cada ejecución se realiza en un contenedor efímero montando únicamente `/body` en modo lectura/escritura y con directorio de trabajo fijado en `/body`.
4. **Sistema de Respaldo del Host**: Generación de backups automáticos comprimidos (`.tar.gz`) en `experiment/backups/` fuera del alcance y la percepción del agente.
5. **Filtro Anti-Bucles y Streaming CoT**: El cliente HTTP lee los fragmentos de razonamiento en tiempo real y corta bucles repetitivos si detecta n-gramas redundantes.
6. **Auto-Rescate de Acciones**: Si el modelo agota la ventana de generación dentro del pensamiento sin emitir el bloque de respuesta final, el sistema rescata la acción formulada en el pensamiento.

## Requisitos

- macOS con Apple Silicon (para servidor MLX) o endpoint compatible con OpenAI API.
- Docker Desktop o daemon compatible (`docker run`).
- Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
Arranque
code
Bash
# Iniciar con servidor MLX automático:
python3 src/main.py

# O con servidor oMLX iniciado previamente:
export MLX_AUTOSTART=0
python3 src/main.py
## ⚠️ Advertencias

Este es un proyecto **experimental**. El agente puede escribir y ejecutar código (Bash, Python, Node.js o binarios) de forma **autónoma y sin supervisión humana en el loop**, dentro de contenedores Docker efímeros con acceso a red.

- El aislamiento depende de la configuración de Docker (`--read-only`, límites de CPU/memoria, `--pids-limit`), pero **no es una sandbox a prueba de escapes**.
- No ejecutes esto en una máquina con datos sensibles o credenciales accesibles desde el entorno.
- No dejes el proceso corriendo indefinidamente sin revisar los backups y logs generados en `experiment/`.
- Úsalo bajo tu propio riesgo.

## ⚠️ Advertencias

Este es un proyecto **experimental**. El agente puede escribir y ejecutar código (Bash, Python, Node.js o binarios) de forma **autónoma y sin supervisión humana en el loop**, dentro de contenedores Docker efímeros con acceso a red.

- El aislamiento depende de la configuración de Docker (--read-only, límites de CPU/memoria, --pids-limit), pero no es una sandbox a prueba de escapes.
- No ejecutes esto en una máquina con datos sensibles o credenciales accesibles desde el entorno.
- No dejes el proceso corriendo indefinidamente sin revisar los backups y logs generados en experiment/.
- Úsalo bajo tu propio riesgo.
