import pandas as pd
import re
import os
import json
from openai import OpenAI

client = None
if os.getenv("OPENAI_API_KEY"):
    client = OpenAI()

TYPE_KEYWORDS = {
    "string", "varchar", "char", "text", "number", "decimal", "int", "integer",
    "date", "datetime", "boolean", "bool", "object", "array"
}


# =============================================================================
# HELPERS
# =============================================================================

def _get_excel_coord(row_idx, col_idx):
    if row_idx is None or col_idx is None: return ""
    col_str = ""
    col_num = col_idx + 1
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        col_str = chr(65 + remainder) + col_str
    return f"{col_str}{row_idx + 1}"


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
    v = v.split("(")[0].strip()
    return v in TYPE_KEYWORDS


def _validate_array_syntax(attr_name, dtype, sheet_name, issues_list, cell_ref=""):
    name = str(attr_name).strip()
    dt = str(dtype).strip().lower()

    if not name or not dt or dt == "nan": return

    has_brackets_at_end = name.endswith("[]")
    is_array = "array" in dt

    if has_brackets_at_end and not is_array:
        issues_list.append({
            "sheet": sheet_name, "attribute": name, "level": "WARN", "category": "SYNTAX",
            "cell": cell_ref,
            # TEXTO UNIFICADO
            "message": f"Sintaxis: El nombre termina en '[]' pero el tipo es '{dtype}'. Debería ser 'Array'."
        })
    elif is_array and not has_brackets_at_end:
        issues_list.append({
            "sheet": sheet_name, "attribute": name, "level": "WARN", "category": "SYNTAX",
            "cell": cell_ref,
            # TEXTO UNIFICADO
            "message": f"Sintaxis: El tipo es 'Array' pero no termina en '[]'."
        })


def _extract_summary_table(df: pd.DataFrame):
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
    blocks = {}
    current_code = None
    regex_header = re.compile(r"status\s*code\s*[:=]?\s*(\d+)", re.IGNORECASE)

    for i, row in df.iterrows():
        row_text = " ".join([str(x) for x in row if pd.notna(x)])

        match = regex_header.search(row_text)
        if match:
            current_code = int(match.group(1))
            blocks[current_code] = []
            continue

        if current_code is not None:
            if "atributo" in row_text.lower() and "tipo" in row_text.lower(): continue

            clean_cells = []
            attr_found = False
            attr_val = ""
            attr_col = -1

            for col_idx, val in enumerate(row):
                s = str(val).strip()
                if s and s.lower() != 'nan':
                    clean_cells.append(s)
                    if not attr_found:
                        attr_val = s
                        attr_col = col_idx
                        attr_found = True

            if not clean_cells: continue

            raw_attr = attr_val
            raw_io, raw_mand, raw_type = "", "", ""

            for cell in clean_cells[1:]:
                c_low = cell.lower()
                if c_low in ["yes", "no", "si"] and not raw_mand:
                    raw_mand = cell
                    continue
                if any(x in c_low for x in ["entrada", "salida", "output", "input"]) and not raw_io:
                    raw_io = cell
                    continue
                if _looks_like_type(c_low) and not raw_type:
                    raw_type = cell
                    continue

            if raw_attr and (raw_type or raw_mand):
                blocks[current_code].append({
                    "attribute": raw_attr,
                    "io": raw_io,
                    "mandatory": raw_mand,
                    "type": raw_type,
                    "cell": _get_excel_coord(i, attr_col)
                })

    return blocks


def _check_coherence_with_llm(summary_list):
    if not client: return []
    clean_list = [{"code": x["code"], "alias": x["alias"], "desc": x["description"]} for x in summary_list]

    # CAMBIO IMPORTANTE: Prompt ajustado para eliminar ruido
    prompt = (
        "Eres un validador estricto de APIs. Analiza la coherencia entre Códigos HTTP y Descripciones. "
        "REGLA DE ORO: Si la descripción es estándar, correcta o razonable para el código, IGNÓRALA. "
        "NO devuelvas nada si está bien. "
        "SOLO reporta si hay una CONTRADICCIÓN SEMÁNTICA GRAVE (Ej: 200 dice 'Error Interno', 500 dice 'Éxito'). "
        "Devuelve JSON: { \"issues\": [ { \"code\": 0, \"message\": \"Explica la contradicción\" } ] } "
        "Si todo está bien, devuelve issues vacío."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(clean_list)}],
            temperature=0, response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("issues", [])
    except:
        return []


def validate_error_definitions(excel_path: str) -> dict:
    issues = []
    try:
        xls = pd.ExcelFile(excel_path)
        sheet_name = xls.sheet_names[0]
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
    except:
        return {"details": []}

    summary_codes = _extract_summary_table(df)
    llm_issues = _check_coherence_with_llm(summary_codes)
    for i in llm_issues:
        issues.append({
            "sheet": sheet_name, "attribute": f"StatusCode {i.get('code')}", "level": "WARN", "category": "SEMANTIC",
            "message": f"🤖 IA Semántica: {i.get('message')}"
        })

    defined_blocks = _parse_detailed_blocks(df)

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

        if code not in defined_blocks:
            if 400 <= code < 600:
                issues.append(
                    {"sheet": sheet_name, "attribute": f"StatusCode {code}", "level": "ERROR", "blocks_vobo": True,
                     "message": "Falta definición detallada del error."})
            continue

        attrs = defined_blocks[code]

        if code == 204 and len(attrs) > 0:
            issues.append(
                {"sheet": sheet_name, "attribute": f"StatusCode {code}", "level": "ERROR", "blocks_vobo": True,
                 "category": "STATUSCODE", "message": "204 No Content debe estar vacío."})
        elif code == 200 and len(attrs) == 0:
            issues.append(
                {"sheet": sheet_name, "attribute": f"StatusCode {code}", "level": "ERROR", "blocks_vobo": True,
                 "category": "STATUSCODE", "message": "200 OK debe tener atributos."})

        found_names = set()
        for attr in attrs:
            _validate_array_syntax(attr['attribute'], attr['type'], sheet_name, issues, cell_ref=attr.get('cell', ''))
            found_names.add(_normalize(attr['attribute']))

            if 400 <= code < 600:
                name = _normalize(attr['attribute'])
                if name in ["code", "message", "description"]:
                    if attr['type'] and "string" not in _normalize(attr['type']):
                        issues.append(
                            {"sheet": sheet_name, "attribute": f"Error {code}.{attr['attribute']}", "level": "ERROR",
                             "cell": attr.get('cell', ''),
                             "message": f"Debe ser String (se detectó '{attr['type']}')."})
                    if attr['mandatory'] and not _is_mandatory(attr['mandatory']):
                        issues.append(
                            {"sheet": sheet_name, "attribute": f"Error {code}.{attr['attribute']}", "level": "ERROR",
                             "cell": attr.get('cell', ''),
                             "message": "Debe ser Obligatorio."})
                    if attr['io'] and not _is_output(attr['io']):
                        issues.append(
                            {"sheet": sheet_name, "attribute": f"Error {code}.{attr['attribute']}", "level": "ERROR",
                             "cell": attr.get('cell', ''),
                             "message": "Debe ser de Salida."})

        if 400 <= code < 600:
            required = {"code", "message", "description"}
            missing = required - found_names
            if missing:
                issues.append({
                    "sheet": sheet_name, "attribute": f"StatusCode {code}", "level": "ERROR", "blocks_vobo": True,
                    "message": f"Estructura de error incompleta. Faltan: {', '.join(missing)}."
                })

    return {"details": issues}