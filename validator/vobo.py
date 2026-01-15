import pandas as pd
from validator.statuscode import validate_error_definitions
from validator.backend_mapping import validate_backend_mapping
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

    # 1. Ejecutar validadores
    issues.extend(validate_error_definitions(excel_path).get("details", []))
    issues.extend(validate_backend_mapping(excel_path).get("details", []))
    issues.extend(validate_bian_alignment(excel_path).get("details", []))

    # 2. Deduplicar
    issues = _dedupe_issues(issues)

    # 3. Política VoBo
    # Regla base: Bloquea si es ERROR explícito
    blocking_issues = []
    for e in issues:
        if e.get("blocks_vobo") is True or e.get("level") == "ERROR":
            blocking_issues.append(e)

    vobo_ok = len(blocking_issues) == 0

    # CAMBIO 3: Regla de límite de tolerancia (Strike 3)
    # Si ya estaba aprobado por errores críticos, revisamos si tiene demasiados warnings
    if vobo_ok and len(issues) > 3:
        vobo_ok = False
        main_message = (
            "❌ **VoBo Rechazado (Exceso de hallazgos)**\n"
            "Aunque no hay errores de estructura críticos, el archivo tiene más de 3 observaciones.\n\n"
            "**Resuelva estos problemas para proceder a dar el VoBo a la matriz de Transformación.**"
        )
    elif vobo_ok:
        if issues:
            main_message = "⚠️ **VoBo Aprobado con Observaciones**\nEl archivo cumple la estructura técnica, pero revisa las sugerencias."
        else:
            main_message = "✅ **VoBo Aprobado Exitosamente**\nLa matriz de transformación es perfecta."
    else:
        main_message = "❌ **VoBo Rechazado**\nSe encontraron errores bloqueantes en la estructura o contrato."

    return {
        "vobo": vobo_ok,
        "message": main_message,
        "details": issues,
    }