import pandas as pd
from validator.statuscode import validate_error_definitions
from validator.backend_mapping import validate_backend_mapping
# Importamos el nuevo validador
from validator.bian_validation import validate_bian_alignment

def _dedupe_issues(issues: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for i in issues:
        key = (
            str(i.get("sheet", "")).strip(),
            str(i.get("attribute", "")).strip(),
            str(i.get("category", "")).strip(),
            str(i.get("level", "")).strip(),
            str(i.get("message", "")).strip(),
        )
        if key in seen: continue
        seen.add(key)
        unique.append(i)
    return unique


def run_vobo(excel_path: str) -> dict:
    issues: list[dict] = []

    # 1. Ejecutar validadores estructurales y técnicos (Lógica Determinista)
    # Errores y Status Codes
    issues.extend(validate_error_definitions(excel_path).get("details", []))
    # Mapeo Backend y Tipos
    issues.extend(validate_backend_mapping(excel_path).get("details", []))

    # 2. Ejecutar validador Semántico BIAN (Lógica IA)
    # Nota: Esto consume API, si quieres que sea opcional, podrías poner un flag.
    issues.extend(validate_bian_alignment(excel_path).get("details", []))

    # 3. Deduplicar
    issues = _dedupe_issues(issues)

    # 4. Política VoBo
    blocking_issues = []
    for e in issues:
        # Solo bloquea si es explícitamente ERROR o blocks_vobo=True
        if e.get("blocks_vobo") is True or e.get("level") == "ERROR":
            blocking_issues.append(e)

    vobo_ok = len(blocking_issues) == 0

    # 5. Mensaje Final Personalizado
    if vobo_ok:
        if issues:
            main_message = "⚠️ **VoBo Aprobado con Observaciones**\nEl archivo cumple la estructura técnica, pero revisa las sugerencias BIAN y advertencias."
        else:
            main_message = "✅ **VoBo Aprobado Exitosamente**\nLa matriz de transformación es perfecta."
    else:
        main_message = "❌ **VoBo Rechazado**\nSe encontraron errores bloqueantes en la estructura o contrato."

    return {
        "vobo": vobo_ok,
        "message": main_message,
        "details": issues,
    }