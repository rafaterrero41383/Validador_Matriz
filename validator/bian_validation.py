import pandas as pd
import os
import json
from openai import OpenAI

# Configuración Cliente OpenAI
client = None
if os.getenv("OPENAI_API_KEY"):
    client = OpenAI()


# =============================================================================
# HELPERS DE EXTRACCIÓN
# =============================================================================

def _loose_normalize(text: str) -> str:
    if not isinstance(text, str): return ""
    return str(text).strip().lower().replace("_", "").replace(" ", "")


def _is_backend_sheet(df: pd.DataFrame) -> bool:
    """Detecta si una hoja parece ser de Backend."""
    sample = df.head(15).to_string().lower()
    return "mapeo" in sample or "backend" in sample or "origen" in sample


def _get_excel_coord(row_idx, col_idx):
    """Convierte indices (0, 0) a coordenadas Excel (A1)."""
    col_str = ""
    col_num = col_idx + 1
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        col_str = chr(65 + remainder) + col_str
    return f"{col_str}{row_idx + 1}"


def _extract_candidates_contract(df: pd.DataFrame) -> list:
    candidates = []
    attr_idx, desc_idx = None, None
    ATTR_KW = ["atributo", "campo", "name"]
    DESC_KW = ["descripción", "descripcion", "description"]

    header_row = None
    for i, row in df.iterrows():
        if i > 20: break
        r = [str(v).lower() for v in row]
        curr_attr = next((idx for idx, v in enumerate(r) if any(k in v for k in ATTR_KW)), None)
        curr_desc = next((idx for idx, v in enumerate(r) if any(k in v for k in DESC_KW)), None)

        if curr_attr is not None and curr_desc is not None:
            attr_idx, desc_idx = curr_attr, curr_desc
            header_row = i
            break

    if header_row is None: return []

    for i in range(header_row + 1, len(df)):
        row = df.iloc[i]
        try:
            raw_attr = str(row.iloc[attr_idx]).strip()
            raw_desc = str(row.iloc[desc_idx]).strip()
        except:
            continue

        if not raw_attr or raw_attr.lower() in ["nan", ""]: continue
        if "atributo" in raw_attr.lower(): continue
        if not raw_desc or raw_desc.lower() in ["nan", ""]: raw_desc = "Sin descripción"

        candidates.append({
            "attribute": raw_attr,
            "description": raw_desc,
            "cell": _get_excel_coord(i, attr_idx)
        })

    return candidates


def _extract_candidates_backend(df: pd.DataFrame) -> list:
    candidates = []
    desc_idx = None
    DESC_KW = ["descripción", "descripcion", "description"]
    header_row = None

    for i, row in df.iterrows():
        r = [str(v).lower() for v in row]
        found_desc = next((idx for idx, v in enumerate(r) if any(k in v for k in DESC_KW)), None)
        if found_desc is not None:
            if any("atributo" in x for x in r):
                desc_idx = found_desc
                header_row = i
                break

    if header_row is None: return []

    attr_idx = None
    row_headers = df.iloc[header_row]
    best_dist = 999
    for idx, val in enumerate(row_headers):
        val_str = str(val).lower()
        if "atributo" in val_str or "campo" in val_str or "name" in val_str:
            if idx < desc_idx:
                dist = desc_idx - idx
                if dist < best_dist:
                    best_dist = dist
                    attr_idx = idx

    if attr_idx is None: return []

    seen = set()
    for i in range(header_row + 1, len(df)):
        row = df.iloc[i]
        row_str = "".join([str(x) for x in row]).lower()
        if "backend - input" in row_str or "backend - output" in row_str: continue

        try:
            raw_attr = str(row.iloc[attr_idx]).strip()
            raw_desc = str(row.iloc[desc_idx]).strip()
        except:
            continue

        if not raw_attr or raw_attr.lower() in ["nan", "", "atributo"]: continue
        if "insert into" in raw_attr.lower(): break

        if not raw_desc or raw_desc.lower() in ["nan", ""]: continue
        if raw_attr in seen: continue

        candidates.append({
            "attribute": raw_attr,
            "description": raw_desc,
            "cell": _get_excel_coord(i, attr_idx)
        })
        seen.add(raw_attr)

    return candidates


# =============================================================================
# LÓGICA IA (PROMPT EXTREMADAMENTE TOLERANTE)
# =============================================================================

def _consult_semantic_expert(candidates: list, context_type: str) -> list:
    if not candidates: return []

    # CAMBIO: Prompt diseñado para ignorar discrepancias de negocio y solo ver absurdos.
    system_prompt = (
        "Eres un validador de datos bancarios extremadamente permisivo y silencioso. "
        "Tu única tarea es detectar ERRORES CATASTRÓFICOS de coherencia (ej: Fecha vs Dinero).\n\n"
        "REGLAS OBLIGATORIAS:\n"
        "1. IGNORA discrepancias de negocio: Si el atributo es 'client_id' y la descripción dice 'Unidad de Negocio' o 'Institución', ES VÁLIDO. Asume que hay una lógica interna que desconoces.\n"
        "2. IGNORA descripciones vagas: Si la descripción es 'identificador', 'código', o similar, ES VÁLIDO.\n"
        "3. SOLO REPORTA CONTRADICCIONES IMPOSIBLES: Por ejemplo, un campo llamado 'fecha_nacimiento' con descripción 'Saldo en pesos'.\n"
        "4. Ante la mínima duda de que pueda ser correcto, NO REPORTES NADA. Devuelve lista vacía.\n\n"
        "Analiza la lista y devuelve un JSON con 'issues' SOLO para esos casos imposibles."
    )

    clean_candidates = [{"attribute": c["attribute"], "description": c["description"]} for c in candidates]

    user_content = (
        f"Analiza:\n{json.dumps(clean_candidates, ensure_ascii=False)}\n\n"
        "JSON output: { \"issues\": [ { \"attribute\": \"...\", \"suggestion\": \"...\", \"reason\": \"...\" } ] }"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            temperature=0, response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        return result.get("issues", [])
    except Exception as e:
        return []


# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def validate_bian_alignment(excel_path: str) -> dict:
    if not client: return {"details": []}
    issues = []

    try:
        xls = pd.ExcelFile(excel_path)
        sheet_names = xls.sheet_names
    except:
        return {"details": []}

    for idx, sheet in enumerate(sheet_names):
        try:
            df = pd.read_excel(excel_path, sheet_name=sheet, header=None)
            candidates = []
            context = ""

            if idx == 0:
                candidates = _extract_candidates_contract(df)
                context = "CONTRACT"
            else:
                if _is_backend_sheet(df):
                    candidates = _extract_candidates_backend(df)
                    context = "BACKEND"
                else:
                    continue

            if not candidates: continue

            attr_cell_map = {c["attribute"]: c["cell"] for c in candidates}

            batch_size = 40
            for i in range(0, len(candidates), batch_size):
                batch = candidates[i:i + batch_size]
                suggestions = _consult_semantic_expert(batch, context)

                for s in suggestions:
                    attr_name = s.get("attribute", "Desconocido")
                    cell_loc = attr_cell_map.get(attr_name, "")

                    issues.append({
                        "sheet": sheet,
                        "attribute": attr_name,
                        "cell": cell_loc,
                        "level": "WARN",
                        "category": "SEMANTIC_BIAN",
                        "message": f"🧠 Semántica: {s.get('reason')}. Sugerencia: {s.get('suggestion')}"
                    })

        except Exception as e:
            continue

    return {"details": issues}