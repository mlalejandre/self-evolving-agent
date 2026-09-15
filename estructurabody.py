import os

def export_body(body_dir="body", output_filename="bodyexportado.txt"):
    # Detectar si la carpeta 'body' existe en el directorio actual o si ya estamos dentro de ella
    if not os.path.exists(body_dir):
        if os.path.exists("core") or os.path.exists("tools") or os.path.exists("autoprompt.txt"):
            print("[INFO] Carpeta 'body' no encontrada explícitamente, pero parece que estás dentro de ella. Usando '.'")
            body_dir = "."
        else:
            print(f"[ERROR] No se encuentra la carpeta '{body_dir}' ni la estructura base en el directorio actual.")
            return

    ignore_dirs = {'.git', '__pycache__', '.pytest_cache', '.DS_Store'}
    ignore_files = {output_filename, 'estructurabody.py'}

    output_lines = []
    
    # 1. Generar la cabecera y el Árbol de Directorios
    output_lines.append("=" * 60)
    output_lines.append(f" ÁRBOL DE DIRECTORIOS (Ruta: {os.path.abspath(body_dir)})")
    output_lines.append("=" * 60 + "\n")
    
    for root, dirs, files in os.walk(body_dir):
        # Filtrar directorios ignorados
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        rel_root = os.path.relpath(root, body_dir)
        level = 0 if rel_root == '.' else rel_root.count(os.sep) + 1
        indent = '    ' * level
        folder_name = os.path.basename(root) if rel_root != '.' else os.path.basename(os.path.abspath(body_dir))
        
        output_lines.append(f"{indent}📁 {folder_name}/")
        
        sub_indent = '    ' * (level + 1)
        for file in sorted(files):
            if file in ignore_files:
                continue
            output_lines.append(f"{sub_indent}📄 {file}")
            
    output_lines.append("\n" + "=" * 60)
    output_lines.append(" CONTENIDO DE LOS ARCHIVOS")
    output_lines.append("=" * 60 + "\n")

    # 2. Recorrer y extraer el código/contenido de cada archivo
    for root, dirs, files in os.walk(body_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in sorted(files):
            if file in ignore_files:
                continue
            
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, body_dir)
            
            output_lines.append("-" * 60)
            output_lines.append(f"ARCHIVO: {rel_path}")
            output_lines.append("-" * 60)
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                output_lines.append(content)
            except Exception as e:
                output_lines.append(f"[Error al leer el archivo: {e}]")
            
            output_lines.append("\n")

    # 3. Guardar el resultado en el archivo de texto
    with open(output_filename, 'w', encoding='utf-8') as out:
        out.write("\n".join(output_lines))
        
    print(f"\n[¡ÉXITO!] Estructura y código exportados correctamente a: {output_filename}")

if __name__ == "__main__":
    # Puedes cambiar 'body' por la ruta exacta si tu carpeta se llama distinto
    target_folder = "body" if os.path.exists("body") else "."
    export_body(target_folder)