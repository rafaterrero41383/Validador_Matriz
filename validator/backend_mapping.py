import pandas as pd
import re

TYPE_FAMILIES = {
    "string": "TEXT", "varchar": "TEXT", "char": "TEXT", "text": "TEXT", "nvarchar": "TEXT", "alphanumeric": "TEXT",
    "number": "NUMBER", "decimal": "NUMBER", "int": "NUMBER", "integer": "NUMBER",
    "numeric": "NUMBER", "float": "NUMBER", "double": "NUMBER", "smallint": "NUMBER", "bigint": "NUMBER",
    "date": "DATE", "timestamp": "DATE", "datetime": "DATE", "time": "DATE",
    "boolean": "BOOL", "bit": "BOOL", "tinyint": "BOOL", "bool": "BOOL",
    "object": "OBJECT", "array": "ARRAY"
}

KEYWORDS_TO_SKIP = {
    "origen", "atributo", "tipo de dato", "backend", "servicio",
    "backend - input", "backend - output", "nan", "none", "n/a", "tipo",
    "mapeo transacción", "función", "destino", "obligatoriedad", "descripción",
    "requerido", "mandatory", "field", "name", "nombre", "column",
    "request body", "headers", "response body", "entrada", "salida"
}


# =============================================================================
# HELPERS
# =============================================================================

def _get_excel_coord(row_idx, col_idx):
    """Convierte indices (0, 0) a coordenadas Excel (A1)."""
    if row_idx is None or col_idx is None: return ""
    col_str = ""
    col_num = col_idx + 1
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        col_str = chr(65 + remainder) + col_str
    return f"{col_str}{row_idx + 1}"


def _normalize(text: str) -> str:
    return text.strip().lower() if isinstance(text, str) else ""


def _loose_normalize(text: str) -> str:
    if not isinstance(text, str): return ""
    clean = str(text).strip().lower()
    if "." in clean: clean = clean.split(".")[-1]
    # CAMBIO: Mantenemos el guion bajo "_" para validación estricta
    return clean.replace(" ", "")


def _get_type_family(type_str: str) -> str:
    if not type_str: return "UNKNOWN"
    clean = type_str.split("(")[0].strip().lower()
    return TYPE_FAMILIES.get(clean, "UNKNOWN")


def _is_mandatory(val: str) -> bool:
    v = _normalize(str(val))
    return v in ["si", "yes", "s", "y", "true", "requerido", "required", "mandatory", "mandatorio", "1"]


def _validate_array_syntax(attr_name, dtype, sheet, issues_list, cell_ref=""):
    name = str(attr_name).strip()
    dt = str(dtype).strip().lower()
    if not name or not dt or dt == "nan": return

    has_brackets_at_end = name.endswith("[]")
    is_array = "array" in dt

    if has_brackets_at_end and not is_array:
        issues_list.append({
            "sheet": sheet, "attribute": name, "level": "WARN", "category": "SYNTAX",
            "cell": cell_ref,
            "message": f"Sintaxis: Termina en '[]' pero el tipo es '{dtype}'. Debería ser 'Array'."
        })
    elif is_array and not has_brackets_at_end:
        issues_list.append({
            "sheet": sheet, "attribute": name, "level": "WARN", "category": "SYNTAX",
            "cell": cell_ref,
            "message": f"Sintaxis: Es tipo 'Array' pero no termina en '[]'."
        })


def _find_table_structure(df: pd.DataFrame):
    ATTR = ["atributo", "campo", "field", "name", "nombre", "column"]
    TYPE = ["tipo", "type", "datatype", "formato"]
    OBLIG = ["obligatoriedad", "requerido", "mandatory", "required", "nulo"]

    for i, row in df.iterrows():
        r = [str(v).strip().lower() for v in row]
        attr = [x for x, v in enumerate(r) if any(k == v for k in ATTR)]
        typ = [x for x, v in enumerate(r) if any(k in v for k in TYPE) and "cambio" not in v]
        obl = [x for x, v in enumerate(r) if any(k in v for k in OBLIG)]
        if attr and typ: return i, attr, typ, obl

    return None, [], [], []


def _load_contract_definitions(df: pd.DataFrame, sheet_name: str, issues: list) -> dict:
    contract_map = {}
    header, attr_c, type_c, obl_c = _find_table_structure(df)
    if header is None: return {}

    idx_a = attr_c[0]
    idx_t = type_c[0]
    idx_o = obl_c[0] if obl_c else None

    for i in range(len(df)):
        if i == header: continue
        row = df.iloc[i]
        try:
            raw_a = str(row.iloc[idx_a]).strip()
            raw_t = str(row.iloc[idx_t]).strip()
            raw_o = str(row.iloc[idx_o]).strip() if idx_o else ""
        except:
            continue

        norm = _loose_normalize(raw_a)
        if not raw_a or raw_a.lower() in ["nan", "n/a"]: continue
        if norm in KEYWORDS_TO_SKIP: continue

        current_cell = _get_excel_coord(i, idx_a)
        _validate_array_syntax(raw_a, raw_t, sheet_name, issues, cell_ref=current_cell)

        fam = _get_type_family(raw_t)
        if fam != "UNKNOWN" or _normalize(raw_o) in ["yes", "no", "si"]:
            contract_map[norm] = {"original_name": raw_a, "type": raw_t, "mandatory": _is_mandatory(raw_o)}
    return contract_map


# =============================================================================
# SQL PARSERS
# =============================================================================

def _extract_sql_columns(sql_text: str) -> tuple[str, set]:
    # Limpieza: quitamos comentarios, saltos de línea y espacios extra
    clean = re.sub(r"--.*", "", sql_text).replace("\n", " ").strip()
    # Normalizar espacios alrededor de signos
    clean = re.sub(r"\s*=\s*", "=", clean)

    cols = set()

    # --- CASO INSERT ---
    if "INSERT INTO" in clean.upper():
        m = re.search(r"INSERT\s+INTO\s+.*?\((.*?)\)\s*VALUES", clean, re.IGNORECASE)
        if m:
            for c in m.group(1).split(","):
                if c.strip(): cols.add(_loose_normalize(c.strip()))
            return "INSERT", cols

    # --- CASO UPDATE ---
    if "UPDATE" in clean.upper() and "SET" in clean.upper():
        matches = re.findall(r"([a-zA-Z0-9_\.]+)=[\?a-zA-Z0-9_']", clean)
        for m in matches:
            cols.add(_loose_normalize(m))
        return "INSERT", cols

    # --- CASO DELETE ---
    if "DELETE" in clean.upper() and "FROM" in clean.upper():
        matches = re.findall(r"([a-zA-Z0-9_\.]+)=[\?a-zA-Z0-9_']", clean)
        for m in matches:
            cols.add(_loose_normalize(m))
        return "INSERT", cols

    # --- CASO SELECT ---
    if "SELECT" in clean.upper():
        m = re.search(r"SELECT\s+(.*?)\s+FROM", clean, re.IGNORECASE)
        if m:
            for c in m.group(1).split(","):
                if not c.strip(): continue
                for part in re.split(r"\s+AS\s+|\s+", c, flags=re.IGNORECASE):
                    if part.upper() not in ["DISTINCT", "TOP", "ALL"]:
                        cols.add(_loose_normalize(part))
            return "SELECT", cols

    return "UNKNOWN", set()


# =============================================================================
# VALIDACIÓN BACKEND
# =============================================================================

def validate_backend_mapping(excel_path: str) -> dict:
    issues = []
    xls = pd.ExcelFile(excel_path)
    sheet_names = xls.sheet_names
    if not sheet_names: return {"details": []}

    try:
        df_c = pd.read_excel(excel_path, sheet_name=sheet_names[0], header=None)
        c_defs = _load_contract_definitions(df_c, sheet_names[0], issues)
    except:
        c_defs = {}

    for i in range(1, len(sheet_names)):
        sh = sheet_names[i]
        try:
            df = pd.read_excel(excel_path, sheet_name=sh, header=None)
        except:
            continue

        start, a_cols, t_cols, o_cols = _find_table_structure(df)
        if start is None: continue

        in_dest, out_orig = set(), set()
        curr_sect = "INPUT"

        for r_idx in range(len(df)):
            row = df.iloc[r_idx]
            txt = "".join([str(x) for x in row]).lower()

            # Detección de secciones
            if "backend - output" in txt:
                curr_sect = "OUTPUT";
                continue
            if "backend - input" in txt:
                curr_sect = "INPUT";
                continue

            # Fin de lectura por SQL (simple check inicial)
            if "insert into" in txt or "select " in txt or "update " in txt or "delete " in txt:
                break

            if r_idx <= start: continue

            # --- Validar que la fila no sea un header repetido o basura ---
            try:
                # Chequeamos la primera celda de atributo
                cell_val = str(row.iloc[a_cols[0]]).strip().lower()
                if cell_val in KEYWORDS_TO_SKIP or cell_val == "nan" or cell_val == "": continue
            except:
                continue

            # --- Recolección estricta ---
            val_to_add = None
            val_col_idx = None

            if curr_sect == "INPUT" and len(a_cols) > 1:
                raw = str(row.iloc[a_cols[1]]).strip()
                if raw and raw.lower() not in ["nan", "n/a", ""]:
                    in_dest.add(_loose_normalize(raw))
                    val_to_add = raw
                    val_col_idx = a_cols[1]

            elif curr_sect == "OUTPUT" and len(a_cols) > 0:
                raw = str(row.iloc[a_cols[0]]).strip()
                if raw and raw.lower() not in ["nan", "n/a", ""] and not raw.isspace():
                    out_orig.add(_loose_normalize(raw))
                    val_to_add = raw
                    val_col_idx = a_cols[0]

            # Validar Array Syntax (Solo si detectamos un valor real)
            if val_to_add:
                chk_t = t_cols[0]
                if curr_sect == "INPUT" and len(a_cols) > 1:
                    chk_t = (t_cols[1] if len(t_cols) > 1 else t_cols[0])

                try:
                    t_val = str(row.iloc[chk_t]).strip()
                    if t_val and t_val.lower() != "nan":
                        current_cell = _get_excel_coord(r_idx, val_col_idx)
                        _validate_array_syntax(val_to_add, t_val, sh, issues, cell_ref=current_cell)
                except:
                    pass

        # === SOLUCIÓN ROBUSTA: Unir texto celda por celda ===
        # Esto evita que Pandas corte líneas largas, agregue índices de fila o 'NaN'
        raw_text_parts = []
        for r_i in range(len(df)):
            for c_i in range(len(df.columns)):
                val = str(df.iloc[r_i, c_i]).strip()
                # Solo agregamos si tiene texto y no es un valor nulo
                if val and val.lower() not in ['nan', 'none', 'n/a']:
                    raw_text_parts.append(val)

        full_text = " ".join(raw_text_parts)
        sql_t, sql_c = _extract_sql_columns(full_text)

        if sql_t == "SELECT":
            if not out_orig:
                issues.append({"sheet": sh, "attribute": "Estructura Output", "level": "WARN",
                               "category": "SQL_CONSISTENCY",
                               "message": "Se detectó una incongruencia: SELECT presente pero Backend-Output vacío."})
            elif (out_orig - sql_c):
                issues.append({"sheet": sh, "attribute": "SQL Consistency", "level": "WARN",
                               "category": "SQL_CONSISTENCY",
                               "message": f"Se detectó una incongruencia entre los atributos y la consulta de BD. Se sugiere renombrar el atributo. (Discrepancias: {', '.join(out_orig - sql_c)})"})

        elif sql_t == "INSERT":  # Aplica para INSERT, UPDATE, DELETE
            if out_orig:
                issues.append({"sheet": sh, "attribute": "Estructura Output", "level": "WARN",
                               "category": "SQL_CONSISTENCY",
                               "message": "Operación de escritura presente pero Backend-Output tiene datos."})

            missing = in_dest - sql_c
            if missing:
                issues.append({"sheet": sh, "attribute": "SQL Consistency", "level": "WARN",
                               "category": "SQL_CONSISTENCY",
                               "message": f"Se detectó una incongruencia entre los atributos y la consulta de BD. Se sugiere renombrar el atributo. (Discrepancias: {', '.join(missing)})"})

    return {"details": issues}