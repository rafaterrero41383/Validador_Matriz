import pandas as pd
from validator.statuscode import validate_error_definitions
from validator.backend_mapping import validate_backend_mapping


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

    # 2. Deduplicar
    issues = _dedupe_issues(issues)

    # 3. Política VoBo
    blocking_issues = []
    for e in issues:
        # Solo bloquea si es explícitamente ERROR o blocks_vobo=True
        if e.get("blocks_vobo") is True or e.get("level") == "ERROR":
            blocking_issues.append(e)

    vobo_ok = len(blocking_issues) == 0

    # 4. Mensaje Final Personalizado
    if vobo_ok:
        if issues:  # Si vobo=OK pero hay items en la lista (significa que son Warnings)
            main_message = "⚠️ Se aprueba el VoBo, pero se tienen estas sugerencias"
        else:
            main_message = "✅ La matriz de transformación ha aprobado el VoBo correctamente."
    else:
        main_message = "❌ La matriz de transformación NO aprueba el VoBo."

    return {
        "vobo": vobo_ok,
        "message": main_message,
        "details": issues,
    }