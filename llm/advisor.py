import re
from typing import List, Dict, Any


def _norm(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def _norm_attr(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\xa0", "")
    s = re.sub(r"\s+", "", s)
    return s.strip()


def _extract_sheet_numbers(user_message: str) -> List[str]:
    """Extrae referencias a hojas."""
    msg = _norm(user_message)
    nums = re.findall(r"\bhoja\s*(\d+)\b", msg)
    return [f"Hoja {n}" for n in nums]


def _extract_attribute_candidates(user_message: str) -> List[str]:
    """Extrae posibles nombres de atributos."""
    raw = user_message or ""
    ticks = re.findall(r"`([^`]+)`", raw)
    candidates = list(ticks)

    # Regex para paths tipo 'objeto.propiedad'
    paths = re.findall(r"([A-Za-z_][A-Za-z0-9_\[\]\.]{3,})", raw)
    for p in paths:
        if "." in p or "_" in p: # Aceptamos _ también
            candidates.append(p)

    seen = set()
    out = []
    for c in candidates:
        c2 = _norm_attr(c)
        if not c2 or c2 in seen:
            continue
        seen.add(c2)
        out.append(c2)
    return out


def _pick_relevant_errors(user_message: str, errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Selecciona el error más probable basado en lo que escribe el usuario."""
    attrs = set(_extract_attribute_candidates(user_message))
    sheets = set(_extract_sheet_numbers(user_message))

    picked = []
    for e in errors:
        e_attr = _norm_attr(e.get("attribute", ""))
        e_sheet = str(e.get("sheet", "")).strip()

        if attrs and e_attr in attrs:
            picked.append(e)
            continue
        if sheets and e_sheet in sheets:
            picked.append(e)
            continue

    if picked:
        seen = set()
        unique = []
        for e in picked:
            key = (e.get("sheet"), e.get("attribute"), e.get("category"))
            if key in seen: continue
            seen.add(key)
            unique.append(e)
        return unique

    return errors[:1]  # Si no encuentra match, explica el primero


def _explain_one_error(e: Dict[str, Any]) -> str:
    sheet = e.get("sheet", "General")
    attr = e.get("attribute", "")
    cat = (e.get("category") or "").upper()
    msg = e.get("message", "").strip()

    header = f"### 🧐 Análisis: {sheet} | `{attr}`"

    # --- CATEGORÍA: STATUSCODE (Errores HTTP) ---
    if cat == "STATUSCODE":
        return (
            f"{header}\n\n"
            f"**Problema:** Inconsistencia en la definición de códigos HTTP.\n"
            f"- **Por qué sucede:** El estándar REST exige reglas estrictas. Por ejemplo, un `204 No Content` no debe devolver nada, o un `400` debe tener una estructura de error estándar.\n"
            f"- **Impacto:** Si no se corrige, el API Gateway o el consumidor (Frontend/App) fallarán al interpretar la respuesta.\n"
            f"- **Solución:** Revisa la hoja 1. Asegúrate que los campos `code`, `message`, `description` existan y sean obligatorios para errores.\n\n"
            f"> *Detalle técnico:* {msg}"
        )

    # --- CATEGORÍA: SEMANTIC_BIAN (IA) ---
    if cat == "SEMANTIC_BIAN":
        return (
            f"{header}\n\n"
            f"**Sugerencia de Inteligencia Artificial (BIAN)**\n"
            f"- **Análisis:** El nombre actual del atributo parece no alinearse con las mejores prácticas del estándar bancario BIAN v12 o está en español/notación húngara.\n"
            f"- **Recomendación:** Considera renombrarlo para mejorar la interoperabilidad y claridad del contrato.\n"
            f"- **Nota:** Esto es una advertencia (WARN). Si el nombre es mandatorio por un legado, puedes justificarlo.\n\n"
            f"> *La IA dice:* {msg}"
        )

    # --- CATEGORÍA: SQL_CONSISTENCY ---
    if cat == "SQL_CONSISTENCY":
        return (
            f"{header}\n\n"
            f"**Problema:** Incoherencia entre Documentación y Código SQL.\n"
            f"- **Por qué sucede:** En el script `INSERT INTO` estás usando una columna que no declaraste en la tabla de arriba.\n"
            f"- **Riesgo:** Esto causará errores en tiempo de ejecución o confusión a los desarrolladores. Es 'código fantasma'.\n"
            f"- **Solución:** Agrega la columna a la tabla de definición o elimínala del script SQL.\n\n"
            f"> *Detalle:* {msg}"
        )

    # --- CATEGORÍA: DUPLICATE ---
    if cat == "DUPLICATE":
        return (
            f"{header}\n\n"
            f"**Problema:** Ambigüedad por duplicidad.\n"
            f"- **Explicación:** Has definido el atributo `{attr}` dos veces en la misma hoja. El validador no sabe cuál definición es la correcta.\n"
            f"- **Solución:** Borra la fila duplicada.\n\n"
            f"> *Detalle:* {msg}"
        )

    # --- CATEGORÍA: CONSISTENCY (Obligatoriedad) ---
    if cat == "CONSISTENCY":
        return (
            f"{header}\n\n"
            f"**Problema:** Ruptura de Contrato (Obligatoriedad).\n"
            f"- **Explicación:** En la Hoja 1 (Contrato) dijiste que este campo es **Obligatorio (Yes)**, pero en esta hoja técnica aparece como **Opcional** o no está marcado.\n"
            f"- **Riesgo Crítico:** El backend podría enviar un `null` en un campo que el consumidor espera que siempre tenga datos, rompiendo la app.\n"
            f"- **Solución:** Marca el campo como Obligatorio (Yes/Si) en esta hoja también.\n\n"
            f"> *Detalle:* {msg}"
        )

    # --- CATEGORÍA: CONTRACT_MISMATCH (Tipos) ---
    if cat == "CONTRACT_MISMATCH":
        return (
            f"{header}\n\n"
            f"**Problema:** Incompatibilidad de Tipos de Dato.\n"
            f"- **Explicación:** El Contrato espera un tipo (ej. `Number`) pero la implementación está usando otro (ej. `String`).\n"
            f"- **Solución:** Cambia el tipo en esta hoja para que coincida con la Hoja 1, o actualiza la Hoja 1 si el contrato estaba mal.\n\n"
            f"> *Detalle:* {msg}"
        )

    # --- CATEGORÍA: UNDEFINED_ATTRIBUTE ---
    if cat == "UNDEFINED_ATTRIBUTE":
        return (
            f"{header}\n\n"
            f"**Problema:** Atributo no identificado en el Contrato.\n"
            f"- **Explicación:** Este atributo no existe en la Hoja 1 y tampoco se utiliza en hojas posteriores como variable de paso.\n"
            f"- **Solución:** Si es un dato nuevo, agrégalo a la Hoja 1. Si es un dato intermedio, asegúrate de que se use en algún paso siguiente.\n\n"
            f"> *Detalle:* {msg}"
        )

    # Fallback genérico
    return (
        f"**Hoja {sheet} | `{attr}`**\n\n"
        f"Error detectado: {msg}\n"
        "Revisa la definición en la Hoja 1 y asegúrate que coincida con esta hoja."
    )


def explain_errors(user_message: str, errors: List[Dict[str, Any]]) -> str:
    picked = _pick_relevant_errors(user_message, errors)

    blocks = []
    for e in picked:
        blocks.append(_explain_one_error(e))

    if not blocks:
        return "No pude encontrar el error específico que mencionas. Intenta escribir el nombre del atributo tal como aparece en el reporte."

    return "\n\n---\n\n".join(blocks)


def explain_error(error: Dict[str, Any]) -> str:
    return _explain_one_error(error)