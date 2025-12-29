# validator/vobo.py
from validator.statuscode import validate_error_definitions
from validator.backend_mapping import validate_backend_mappings

def run_vobo(excel_path: str) -> dict:
    results = []

    r1 = validate_error_definitions(excel_path)
    results.append(r1)

    r2 = validate_backend_mappings(excel_path)
    results.append(r2)

    all_errors = []
    for r in results:
        if not r["vobo"]:
            all_errors.extend(r["details"])

    if all_errors:
        return {
            "vobo": False,
            "message": "La matriz de transformación no ha aprobado el VoBo",
            "details": all_errors
        }

    return {
        "vobo": True,
        "message": "La matriz de transformación ha aprobado el VoBo",
        "details": []
    }
