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
    """
    Extrae "hoja 2", "Hoja 3", etc. Devuelve ["Hoja 2", "Hoja 3"]
    """
    msg = _norm(user_message)
    nums = re.findall(r"\bhoja\s*(\d+)\b", msg)
    return [f"Hoja {n}" for n in nums]


def _extract_attribute_candidates(user_message: str) -> List[str]:
    """
    Extrae posibles atributos del texto del usuario:
    - tokens con puntos: a.b.c
    - tokens con []: a[].b[].c
    - acepta que vengan con backticks
    """
    raw = user_message or ""
    # primero: lo que venga entre backticks
    ticks = re.findall(r"`([^`]+)`", raw)
    candidates = list(ticks)

    # luego: tokens que parezcan paths (con . y opcional [])
    # Ej: partyReferenceDataDirectoryEntry[].directDebitMandate[].amount
    paths = re.findall(r"([A-Za-z_][A-Za-z0-9_\[\]\.]{3,})", raw)
    for p in paths:
        if "." in p:
            candidates.append(p)

    # normalizar y deduplicar manteniendo orden
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
    """
    Selecciona errores relevantes según:
    - atributos mencionados
    - hojas mencionadas
    Si no hay match, devuelve los primeros 3 para no dejar al usuario en el aire.
    """
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
        # dedupe por (sheet, attribute, category)
        seen = set()
        unique = []
        for e in picked:
            key = (e.get("sheet"), e.get("attribute"), e.get("category"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(e)
        return unique

    return errors[:3]  # fallback


def _explain_one_error(e: Dict[str, Any]) -> str:
    sheet = e.get("sheet", "General")
    attr = e.get("attribute", "")
    cat = (e.get("category") or "").upper()
    msg = e.get("message", "").strip()

    # Plantillas por categoría (sin inventar DB/SQL)
    if cat == "CONTRACT":
        return (
            f"**Hoja {sheet} | Atributo `{attr}`**\n\n"
            f"Este error es de **Contrato Canónico (Hoja 1)**.\n\n"
            f"- **Qué significa:** el atributo aparece en una hoja posterior (mapeo/implementación), pero el validador no lo encuentra definido en la **Hoja 1** (o en hojas previas, según la regla).\n"
            f"- **Por qué bloquea VoBo:** rompe el contrato; hay implementación sin definición contractual.\n"
            f"- **Cómo corregir:**\n"
            f"  1) Si el atributo *sí debe existir*, agrégalo/corrige su definición en **Hoja 1** (Request o Response, según aplique) con el path exacto.\n"
            f"  2) Si el atributo *no debe existir*, elimínalo del mapeo en la hoja técnica.\n\n"
            f"{('**Detalle del motor:** ' + msg) if msg else ''}"
        )

    if cat == "HEADERS":
        return (
            f"**Hoja {sheet} | Header `{attr}`**\n\n"
            f"Falta un **header obligatorio** para capa **Pro_**.\n\n"
            f"- **Qué significa:** el header requerido no está declarado en la sección Headers/Entrada.\n"
            f"- **Por qué bloquea VoBo:** rompe el estándar contractual de consumo.\n"
            f"- **Cómo corregir:** agrega el header en Hoja 1 (Headers) y refléjalo en hojas siguientes si aplica.\n\n"
            f"{('**Detalle del motor:** ' + msg) if msg else ''}"
        )

    if cat == "CONSISTENCY":
        return (
            f"**Hoja {sheet} | Atributo `{attr}`**\n\n"
            f"Este error es de **Consistencia** con la Hoja 1.\n\n"
            f"- **Qué significa:** la **obligatoriedad** y/o el **tipo de dato** en esta hoja no coincide con lo definido en la Hoja 1.\n"
            f"- **Por qué bloquea VoBo:** el contrato queda ambiguo/inconsistente.\n"
            f"- **Cómo corregir:** alinear `Obligatoriedad` y `Tipo` con la definición de Hoja 1 (match exacto).\n\n"
            f"{('**Detalle del motor:** ' + msg) if msg else ''}"
        )

    if cat == "SEMANTIC":
        return (
            f"**Hoja {sheet} | Atributo `{attr}`**\n\n"
            f"Esto es una **sugerencia BIAN Semantic API** (no necesariamente bloqueante si decidiste flexibilidad).\n\n"
            f"- **Qué significa:** el nombre/estructura del atributo podría no alinearse a semántica BIAN v12.\n"
            f"- **Qué hacer:** evaluar renombrar o justificar excepción en gobierno.\n\n"
            f"{('**Detalle del motor:** ' + msg) if msg else ''}"
        )

    # fallback
    return (
        f"**Hoja {sheet} | `{attr}`**\n\n"
        f"{msg or 'Error detectado por el motor. Revisa la definición en Hoja 1 y consistencia entre hojas.'}"
    )


def explain_errors(user_message: str, errors: List[Dict[str, Any]]) -> str:
    picked = _pick_relevant_errors(user_message, errors)

    # si el usuario pidió explícitamente dos atributos, los explicamos ambos (si aparecen)
    blocks = []
    for e in picked:
        blocks.append(_explain_one_error(e))

    if not blocks:
        return "No pude identificar el error que quieres explicar. Intenta pegando el **Atributo** tal como aparece o indicando **Hoja N**."

    # Si son varios, se separan de forma limpia
    return "\n\n---\n\n".join(blocks)


# Backward compat: explica solo uno
def explain_error(error: Dict[str, Any]) -> str:
    return _explain_one_error(error)
