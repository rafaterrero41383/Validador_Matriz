import pandas as pd
import re
import os
import json
from openai import OpenAI

# Configuración de Cliente OpenAI
client = None
if os.getenv("OPENAI_API_KEY"):
    client = OpenAI()

# =============================================================================
# CONSTANTES DE TIPOS (Para detección inteligente)
# =============================================================================
TYPE_KEYWORDS = {
    "string", "varchar", "char", "text", "number", "decimal", "int", "integer",
    "date", "datetime", "boolean", "bool", "object", "array"
}


# =============================================================================
# HELPERS DE PARSEO
# =============================================================================

def _normalize(text):
    return str(text).strip().lower() if text else ""


def _is_mandatory(val: str) -> bool:
    v = _normalize(str(val))
    return v in ["si", "yes", "s", "y", "true", "requerido", "required", "mandatory", "1"]


def _is_output(val: str) -> bool:
    v = _normalize(str(val))
    return "salida" in v or "output" in v or "response" in v or "respuesta" in v


def _looks_like_type(val: str) -> bool:
    v = _normalize(str(val))
    # Limpiamos paréntesis ej: varchar(50) -> varchar
    v = v.split("(")[0].strip()
    return v in TYPE_KEYWORDS


def _validate_array_syntax(attr_name, dtype, sheet_name, issues_list):
    """Regla: [] al FINAL del nombre <-> Tipo Array"""
    name = str(attr_name).strip()
    dt = str(dtype).strip().lower()

    if not name or not dt or dt == "nan": return

    has_brackets_at_end = name.endswith("[]")
    is_array = "array" in dt

    if has_brackets_at_end and not is_array:
        issues_list.append({
            "sheet": sheet_name, "attribute": name, "level": "WARN", "category": "SYNTAX",
            "message": f"Sintaxis: El nombre termina en '[]' pero el tipo es '{dtype}'. Debería ser 'Array'."
        })
    elif is_array and not has_brackets_at_end:
        issues_list.append({
            "sheet": sheet_name, "attribute": name, "level": "WARN", "category": "SYNTAX",
            "message": f"Sintaxis: El tipo es 'Array' pero no termina en '[]'."
        })


def _extract_summary_table(df: pd.DataFrame):
    """Busca la tabla de resumen 'Gestión Códigos de Errores'."""
    summary = []
    start_row = None

    for i, row in df.iterrows():
        row_str = [str(v).lower() for v in row]
        if any("http status code" in s for s in row_str):
            start_row = i
            break

    if start_row is None: return []

    headers = df.iloc[start_row]
    idx_code, idx_alias, idx_desc = None, None, None

    for c, val in enumerate(headers):
        v = str(val).lower()
        if "code" in v:
            idx_code = c
        elif "alias" in v:
            idx_alias = c
        elif "descri" in v:
            idx_desc = c

    if idx_code is None: return []

    for i in range(start_row + 1, len(df)):
        row = df.iloc[i]
        val_code = str(row.iloc[idx_code]).strip()

        if not val_code or not val_code.replace(".", "").isdigit():
            if idx_alias and str(row.iloc[idx_alias]).strip():
                pass
            else:
                break

        try:
            summary.append({
                "code": int(float(val_code)),
                "alias": str(row.iloc[idx_alias]).strip() if idx_alias else "",
                "description": str(row.iloc[idx_desc]).strip() if idx_desc else ""
            })
        except:
            continue

    return summary


def _parse_detailed_blocks(df: pd.DataFrame):
    """Escanea la hoja buscando bloques 'StatusCode = X' con lectura FLEXIBLE."""
    blocks = {}
    current_code = None
    regex_header = re.compile(r"status\s*code\s*=\s*(\d+)", re.IGNORECASE)

    for i, row in df.iterrows():
        row_text = " ".join([str(x) for x in row if pd.notna(x)])

        # 1. Detectar cabecera de bloque (Fila Amarilla)
        match = regex_header.search(row_text)
        if match:
            current_code = int(match.group(1))
            blocks[current_code] = []
            continue

        # 2. Leer atributos dentro del bloque
        if current_code is not None:
            # Saltamos encabezados repetidos
            if "atributo" in row_text.lower() and "tipo" in row_text.lower(): continue

            # Recolectamos celdas no vacías de la fila
            clean_cells = []
            for val in row:
                s = str(val).strip()
                if s and s.lower() != 'nan':
                    clean_cells.append(s)

            if not clean_cells: continue

            # --- LECTURA INTELIGENTE ---
            # En lugar de usar índices fijos (row[1], row[4]), buscamos por contenido.
            # Asumimos que el Atributo es el PRIMER valor no vacío.
            raw_attr = clean_cells[0]

            # El resto lo buscamos en las celdas siguientes
            raw_io = ""
            raw_mand = ""
            raw_type = ""

            for cell in clean_cells[1:]:
                c_low = cell.lower()

                # Detectar Mandatorio
                if c_low in ["yes", "no", "si"] and not raw_mand:
                    raw_mand = cell
                    continue

                # Detectar IO
                if any(x in c_low for x in ["entrada", "salida", "output", "input"]) and not raw_io:
                    raw_io = cell
                    continue

                # Detectar Tipo
                if _looks_like_type(c_low) and not raw_type:
                    raw_type = cell
                    continue

            # Si logramos identificar al menos Atributo y (Tipo o Mandatorio), lo guardamos
            if raw_attr and (raw_type or raw_mand):
                blocks[current_code].append({
                    "attribute": raw_attr,
                    "io": raw_io,  # Puede quedar vacía si falla detección
                    "mandatory": raw_mand,
                    "type": raw_type
                })

    return blocks


# =============================================================================
# VALIDACIÓN CON LLM
# =============================================================================

def _check_coherence_with_llm(summary_list):
    if not client: return []

    clean_list = [{"code": x["code"], "alias": x["alias"], "desc": x["description"]} for x in summary_list]

    # PROMPT TOLERANTE
    prompt = (
        "Analiza la coherencia semántica de estos códigos de error HTTP. "
        "Detecta CONTRADICCIONES GRAVES (ej. 200 descrito como Error, 404 como Éxito). "
        "Si la descripción es razonable, NO reportes nada. "
        "Devuelve JSON: { \"issues\": [ { \"code\": 400, \"message\": \"Razón clara\" } ] }"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(clean_list)}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("issues", [])
    except Exception:
        return []


# =============================================================================
# LÓGICA PRINCIPAL
# =============================================================================

def validate_error_definitions(excel_path: str) -> dict:
    issues = []
    try:
        xls = pd.ExcelFile(excel_path)
        sheet_name = xls.sheet_names[0]
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
    except Exception as e:
        return {"details": []}

    # 1. Resumen
    summary_codes = _extract_summary_table(df)

    # 2. IA Check
    llm_issues = _check_coherence_with_llm(summary_codes)
    for i in llm_issues:
        msg = str(i.get('message', '')).lower()
        if "correcto" in msg or "adecuado" in msg or "valido" in msg: continue

        issues.append({
            "sheet": sheet_name, "attribute": f"StatusCode {i.get('code')}", "level": "WARN", "category": "SEMANTIC",
            "message": f"🤖 IA Semántica: {i.get('message')}"
        })

    # 3. Detalles
    defined_blocks = _parse_detailed_blocks(df)

    # 4. Validar Respuestas Exitosas (200 vs 204)
    success_codes = [c for c in defined_blocks.keys() if 200 <= c < 300]
    if not success_codes:
        issues.append({"sheet": sheet_name, "attribute": "StatusCode 2xx", "level": "WARN",
                       "message": "No se detectó ningún bloque de respuesta exitosa (200/204)."})

    all_codes_to_check = list(summary_codes)
    for c in success_codes:
        if not any(x['code'] == c for x in summary_codes): all_codes_to_check.append({'code': c})

    for item in all_codes_to_check:
        code = item.get('code')
        if not code: continue

        # A) Existencia del bloque (errores)
        if code not in defined_blocks:
            if 400 <= code < 600:
                issues.append(
                    {"sheet": sheet_name, "attribute": f"StatusCode {code}", "level": "ERROR", "blocks_vobo": True,
                     "message": "Falta definición detallada del error."})
            continue

        attrs = defined_blocks[code]

        # B) Reglas 200 vs 204
        if code == 204 and len(attrs) > 0:
            issues.append(
                {"sheet": sheet_name, "attribute": f"StatusCode {code}", "level": "ERROR", "blocks_vobo": True,
                 "category": "STATUSCODE", "message": "204 No Content debe estar vacío."})
        elif code == 200 and len(attrs) == 0:
            issues.append(
                {"sheet": sheet_name, "attribute": f"StatusCode {code}", "level": "ERROR", "blocks_vobo": True,
                 "category": "STATUSCODE", "message": "200 OK debe tener atributos."})

        # C) Validación de Atributos
        found_names = set()
        for attr in attrs:
            _validate_array_syntax(attr['attribute'], attr['type'], sheet_name, issues)
            found_names.add(_normalize(attr['attribute']))

            # Validaciones estrictas para Errores Estándar (4xx/5xx)
            if 400 <= code < 600:
                name = _normalize(attr['attribute'])
                if name in ["code", "message", "description"]:
                    # Validamos lo que pudimos extraer
                    if attr['type'] and "string" not in _normalize(attr['type']):
                        issues.append(
                            {"sheet": sheet_name, "attribute": f"Error {code}.{attr['attribute']}", "level": "ERROR",
                             "message": f"Debe ser String (se detectó '{attr['type']}')."})
                    if attr['mandatory'] and not _is_mandatory(attr['mandatory']):
                        issues.append(
                            {"sheet": sheet_name, "attribute": f"Error {code}.{attr['attribute']}", "level": "ERROR",
                             "message": "Debe ser Obligatorio."})
                    if attr['io'] and not _is_output(attr['io']):
                        issues.append(
                            {"sheet": sheet_name, "attribute": f"Error {code}.{attr['attribute']}", "level": "ERROR",
                             "message": "Debe ser de Salida."})

        # D) Estructura Incompleta en Errores
        if 400 <= code < 600:
            required = {"code", "message", "description"}
            missing = required - found_names
            if missing:
                issues.append({
                    "sheet": sheet_name, "attribute": f"StatusCode {code}", "level": "ERROR", "blocks_vobo": True,
                    "message": f"Estructura de error incompleta. Faltan: {', '.join(missing)}."
                })

    return {"details": issues}