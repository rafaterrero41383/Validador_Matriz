import pandas as pd
import re

REQUIRED_FIELDS = {"code", "message", "description"}
CONTRACT_SHEET = "Hoja 1"


def read_sheet_as_text(excel_path: str, sheet_name: str) -> str:
    # Usamos esto para buscar los bloques de definición "StatusCode = ..."
    try:
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
    except Exception as e:
        raise ValueError(f"No se pudo leer la hoja '{sheet_name}'. {e}")

    text_content = []
    for row in df.values:
        row_str = " ".join(str(cell) for cell in row if pd.notna(cell))
        text_content.append(row_str)

    return "\n".join(text_content)


def extract_declared_codes_from_table(excel_path: str, sheet_name: str) -> set[int]:
    """
    Lee la tabla estructurada de la Imagen 1.
    Busca la columna 'Http Status Code' y recolecta los números debajo.
    """
    try:
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
    except:
        return set()

    target_col_idx = None
    start_row_idx = None

    # 1. Buscar dónde está el encabezado "Http Status Code"
    for r_idx, row in df.iterrows():
        for c_idx, val in enumerate(row):
            val_str = str(val).strip().lower()
            if "http" in val_str and "status" in val_str and "code" in val_str:
                target_col_idx = c_idx
                start_row_idx = r_idx + 1  # Los datos empiezan en la siguiente fila
                break
        if target_col_idx is not None:
            break

    if target_col_idx is None:
        return set()

    # 2. Leer hacia abajo hasta encontrar vacío o algo que no sea número
    codes = set()
    for r_idx in range(start_row_idx, len(df)):
        val = df.iat[r_idx, target_col_idx]

        # Si la celda está vacía, asumimos fin de la tablita
        if pd.isna(val) or str(val).strip() == "":
            continue  # O break, dependiendo de si hay huecos. Mejor continue si es solo una celda vacía.

        # Intentamos convertir a int (400, 500)
        try:
            # Limpieza por si viene como "400.0" o " 400 "
            clean_val = str(val).split('.')[0].strip()
            code_int = int(clean_val)
            if 100 <= code_int <= 599:
                codes.add(code_int)
        except ValueError:
            # Si encontramos texto que no es número, asumimos que terminó la tabla de códigos
            break

    return codes


def extract_statuscode_blocks(sheet_text: str) -> dict[int, str]:
    # Busca los bloques amarillos de la Imagen 2: "StatusCode = 403"
    pattern = r"(StatusCode\s*=\s*(4\d{2}|5\d{2}))"
    matches = list(re.finditer(pattern, sheet_text, re.IGNORECASE))

    blocks = {}
    for i, match in enumerate(matches):
        status = int(match.group(2))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sheet_text)
        blocks[status] = sheet_text[start:end]

    return blocks


def validate_error_definitions(excel_path: str) -> dict:
    issues = []

    # 1. Obtener códigos DECLARADOS (Tabla superior Imagen 1)
    declared_codes = extract_declared_codes_from_table(excel_path, CONTRACT_SHEET)

    # 2. Obtener bloques DEFINIDOS (Bloques amarillos Imagen 2)
    try:
        sheet_text = read_sheet_as_text(excel_path, CONTRACT_SHEET)
        defined_blocks = extract_statuscode_blocks(sheet_text)
    except Exception as e:
        return {"details": [{"sheet": CONTRACT_SHEET, "attribute": "Lectura", "level": "ERROR", "message": str(e),
                             "blocks_vobo": True}]}

    if not declared_codes:
        issues.append({
            "sheet": CONTRACT_SHEET,
            "attribute": "Header Http Status Code",
            "level": "ERROR",
            "category": "STATUSCODE",
            "blocks_vobo": True,
            "message": "No se encontró la columna 'Http Status Code' con valores numéricos en la Hoja 1."
        })

    # 3. Cruzar información
    for code in declared_codes:
        if code not in defined_blocks:
            issues.append({
                "sheet": CONTRACT_SHEET,
                "attribute": f"StatusCode {code}",
                "level": "ERROR",
                "category": "STATUSCODE",
                "blocks_vobo": True,
                "message": f"El código {code} está listado en la tabla de resumen pero no tiene su bloque de detalle ('StatusCode = {code}') más abajo."
            })
            continue

        block_content = defined_blocks[code]
        missing = []
        for field in REQUIRED_FIELDS:
            if not re.search(rf"\b{field}\b", block_content, re.IGNORECASE):
                missing.append(field)

        if missing:
            issues.append({
                "sheet": CONTRACT_SHEET,
                "attribute": f"StatusCode {code}",
                "level": "ERROR",
                "category": "STATUSCODE",
                "blocks_vobo": True,
                "message": f"Definición incompleta. Faltan los campos: {', '.join(sorted(missing))}."
            })

    return {"details": issues}