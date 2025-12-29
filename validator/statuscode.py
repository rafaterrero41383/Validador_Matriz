# validator/statuscode.py
import pandas as pd
import re


REQUIRED_FIELDS = {"code", "message", "description"}


def read_sheet_as_text(excel_path: str, sheet_name=0) -> str:
    df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
    return "\n".join(
        str(cell)
        for row in df.values
        for cell in row
        if pd.notna(cell)
    )


def extract_declared_http_codes(sheet_text: str) -> set[int]:
    if "Http Status Code" not in sheet_text:
        return set()

    after_header = sheet_text.split("Http Status Code", 1)[1]
    return {
        int(code)
        for code in re.findall(r"\b(4\d{2}|5\d{2})\b", after_header)
    }


def extract_statuscode_blocks(sheet_text: str) -> dict[int, str]:
    pattern = r"(StatusCode\s*=\s*(4\d{2}|5\d{2}))"
    matches = list(re.finditer(pattern, sheet_text))

    blocks = {}

    for i, match in enumerate(matches):
        status = int(match.group(2))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sheet_text)
        blocks[status] = sheet_text[start:end]

    return blocks


def missing_required_fields(block_text: str) -> set[str]:
    found = {
        field
        for field in REQUIRED_FIELDS
        if re.search(rf"\b{field}\b", block_text, re.IGNORECASE)
    }
    return REQUIRED_FIELDS - found


def validate_error_definitions(excel_path: str) -> dict:
    sheet_text = read_sheet_as_text(excel_path)

    declared_codes = extract_declared_http_codes(sheet_text)
    blocks = extract_statuscode_blocks(sheet_text)

    errors = []

    for code in declared_codes:
        if code not in blocks:
            errors.append({
                "section": "StatusCode",
                "statusCode": code,
                "error": "StatusCode no definido en la hoja"
            })
            continue

        missing = missing_required_fields(blocks[code])
        if missing:
            errors.append({
                "section": "StatusCode",
                "statusCode": code,
                "missingFields": sorted(missing)
            })

    if errors:
        return {
            "vobo": False,
            "message": "La matriz de transformación no ha aprobado el VoBo",
            "details": errors
        }

    return {
        "vobo": True,
        "message": "La matriz de transformación ha aprobado el VoBo",
        "details": []
    }
