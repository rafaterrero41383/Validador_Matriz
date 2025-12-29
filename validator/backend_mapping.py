import pandas as pd
import re


# =========================================================
# Normalización para marcadores (maneja doble espacios, tabs, etc.)
# =========================================================

def _norm_text(x: str) -> str:
    """Lower + colapsa whitespace + recorta."""
    x = str(x).replace("\xa0", " ")
    x = re.sub(r"\s+", " ", x)  # colapsar múltiples espacios
    return x.strip().lower()


def _row_contains_marker(df: pd.DataFrame, row_idx: int, marker: str) -> bool:
    marker_n = _norm_text(marker)
    for col_idx in range(df.shape[1]):
        cell = df.iat[row_idx, col_idx]
        if isinstance(cell, str):
            if marker_n in _norm_text(cell):
                return True
    return False


def _find_marker_row(df: pd.DataFrame, marker: str) -> int | None:
    for i in range(len(df)):
        if _row_contains_marker(df, i, marker):
            return i
    return None


# =========================================================
# Ignorados / limpieza de valores de atributos en Excel
# =========================================================

IGNORED_VALUES = {
    "atributo",
    "destino",
    "origen",
    "tipo de dato",
    "obligatoriedad",
    "descripcion",
    "descripción",
    "mapeo transacción",
    "función",
    "backend - input",
    "backend - output",
    "backend",
    "entrada/salida",
    "servicio",
}

def _is_noise_attribute(val: str) -> bool:
    """Ignora headers, vacíos, y basura tipo '1'."""
    if not val:
        return True
    v = val.strip()
    if not v:
        return True
    if _norm_text(v) in IGNORED_VALUES:
        return True
    # ignora números sueltos (ej: SELECT 1, o celdas con 1)
    if re.fullmatch(r"\d+", v):
        return True
    return False


# =========================================================
# Excel parsing: atributos por bloques (col D / índice 3)
# =========================================================

def extract_attributes_between(
    df: pd.DataFrame,
    start_marker: str,
    end_marker: str,
    attribute_col_index: int = 3,  # Columna D (0-based)
) -> set[str]:
    attributes: set[str] = set()
    seen: set[str] = set()

    start_row = _find_marker_row(df, start_marker)
    if start_row is None:
        return set()

    end_row = _find_marker_row(df, end_marker)
    if end_row is None:
        end_row = len(df)

    if end_row <= start_row:
        return set()

    for r in range(start_row + 1, end_row):
        cell = df.iat[r, attribute_col_index]
        if pd.isna(cell):
            continue

        value = str(cell).strip()
        if _is_noise_attribute(value):
            continue

        # ignora duplicados
        if value in seen:
            continue

        seen.add(value)
        attributes.add(value)

    return attributes


def extract_sql_from_sheet(df: pd.DataFrame) -> str | None:
    """
    Extrae el SQL debajo de 'Servicio' en la columna A (índice 0).
    """
    found = False
    for cell in df.iloc[:, 0]:
        if isinstance(cell, str) and _norm_text(cell) == "servicio":
            found = True
            continue
        if found and pd.notna(cell):
            return str(cell)
    return None


# =========================================================
# SQL parsing: SOLO COLUMNAS (no BD/esquema/tabla), en cualquier parte
# =========================================================

_SQL_KEYWORDS = {
    "select", "from", "where", "and", "or", "join", "on",
    "insert", "into", "values", "update", "set", "delete",
    "as", "distinct", "group", "by", "order", "limit",
    "inner", "left", "right", "full", "outer", "cross",
    "is", "null", "not", "in", "like", "between", "exists",
}

def _clean_identifier(x: str) -> str:
    """
    Limpia identificadores: quita comillas, paréntesis, etc.
    y devuelve solo el último segmento si viene tabla.col.
    """
    x = x.strip()
    x = x.strip("`\"'[]()")
    # si viene algo tipo schema.table.column -> nos quedamos con column
    if "." in x:
        x = x.split(".")[-1]
        x = x.strip("`\"'[]()")
    return x.strip()

def extract_sql_attributes(sql: str) -> set[str]:
    """
    Extrae únicamente COLUMNAS reales usadas en la SQL,
    sin importar en qué parte aparezcan (SELECT, INSERT, WHERE, JOIN, etc.).

    Reglas:
    - Ignora BD, esquemas y tablas
    - Ignora palabras reservadas SQL
    - Ignora literales numéricos
    - Ignora tokens incompletos (terminan en '_')
    - Devuelve solo nombres de columnas válidos
    """
    if not sql or not isinstance(sql, str):
        return set()

    # Normalizar SQL
    s = sql.replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    sl = s.lower()

    attrs: set[str] = set()

    SQL_KEYWORDS = {
        "select", "from", "where", "and", "or", "join", "on",
        "insert", "into", "values", "update", "set", "delete",
        "as", "distinct", "group", "by", "order", "limit",
        "inner", "left", "right", "full", "outer", "cross",
        "is", "null", "not", "in", "like", "between", "exists"
    }

    def clean_identifier(x: str) -> str | None:
        if not x:
            return None

        x = x.strip().strip("`\"'[]()")

        # Si viene schema.tabla.col → tomar solo col
        if "." in x:
            x = x.split(".")[-1].strip("`\"'[]()")

        # Reglas de descarte
        if not x:
            return None
        if x.lower() in SQL_KEYWORDS:
            return None
        if re.fullmatch(r"\d+", x):   # solo números
            return None
        if x.endswith("_"):           # token incompleto
            return None
        if len(x) < 3:                # demasiado corto para ser atributo real
            return None

        return x

    # ====================================================
    # INSERT INTO tabla (col1, col2, ...)
    # ====================================================
    insert_match = re.search(
        r"insert\s+into\s+[^()]+\((.*?)\)\s*values",
        s,
        flags=re.IGNORECASE
    )
    if insert_match:
        for c in insert_match.group(1).split(","):
            cid = clean_identifier(c)
            if cid:
                attrs.add(cid)

    # ====================================================
    # UPDATE tabla SET col1=?, col2=? WHERE ...
    # ====================================================
    update_match = re.search(
        r"update\s+.+?\s+set\s+(.*?)(\s+where\s+.*)?$",
        s,
        flags=re.IGNORECASE
    )
    if update_match:
        set_part = update_match.group(1) or ""
        for chunk in set_part.split(","):
            if "=" in chunk:
                left = chunk.split("=", 1)[0]
                cid = clean_identifier(left)
                if cid:
                    attrs.add(cid)

    # ====================================================
    # SELECT col1, col2 FROM ...
    # ====================================================
    select_match = re.search(
        r"select\s+(.*?)\s+from\b",
        s,
        flags=re.IGNORECASE
    )
    if select_match:
        for token in select_match.group(1).split(","):
            t = token.strip()
            # quitar alias
            t = re.sub(r"\s+as\s+.*$", "", t, flags=re.IGNORECASE)
            # quitar funciones: SUM(x) → x
            inner = re.search(r"\(([^)]+)\)", t)
            if inner:
                t = inner.group(1)
            cid = clean_identifier(t)
            if cid and cid != "*":
                attrs.add(cid)

    # ====================================================
    # WHERE / JOIN / ON → columna antes del operador
    # ====================================================
    for ident, _ in re.findall(
        r"([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\s*"
        r"(=|>|<|>=|<=|<>|in|like|between)",
        s,
        flags=re.IGNORECASE
    ):
        cid = clean_identifier(ident)
        if cid:
            attrs.add(cid)

    return attrs

# =========================================================
# Validación por hoja (muestra TODOS los errores)
# =========================================================

def validate_sheet(sheet_name: str, df: pd.DataFrame) -> list[dict]:
    sql = extract_sql_from_sheet(df)
    if not sql:
        return []

    # Columnas reales usadas en la SQL
    sql_attrs = extract_sql_attributes(sql)

    # SOLO Backend - Input
    input_attrs = extract_attributes_between(
        df,
        start_marker="Backend - Input",
        end_marker="Backend - Output",
        attribute_col_index=3  # Columna D
    )

    # Si la hoja no tiene Backend-Input, no se valida
    if not input_attrs:
        return []

    errors: list[dict] = []

    # ===============================
    # Backend-Input → SQL
    # ===============================
    for attr in sorted(input_attrs):
        if attr not in sql_attrs:
            errors.append({
                "sheet": sheet_name,
                "attribute": attr,
                "error": "Atributo de Backend-Input no referenciado en la consulta SQL"
            })

    return errors

# =========================================================
# Validación global
# =========================================================

def validate_backend_mappings(excel_path: str) -> dict:
    xls = pd.ExcelFile(excel_path)
    all_errors: list[dict] = []

    # desde la segunda hoja en adelante
    for sheet_name in xls.sheet_names[1:]:
        df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        all_errors.extend(validate_sheet(sheet_name, df))

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
