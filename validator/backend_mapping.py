import pandas as pd
import re

# =============================================================================
# 1. MATRIZ DE COMPATIBILIDAD DE TIPOS
# =============================================================================

TYPE_FAMILIES = {
    # Familia Texto
    "string": "TEXT", "varchar": "TEXT", "char": "TEXT", "text": "TEXT", "nvarchar": "TEXT",
    # Familia Numérica
    "number": "NUMBER", "decimal": "NUMBER", "int": "NUMBER", "integer": "NUMBER",
    "numeric": "NUMBER", "float": "NUMBER", "double": "NUMBER", "smallint": "NUMBER", "bigint": "NUMBER",
    # Familia Fecha
    "date": "DATE", "timestamp": "DATE", "datetime": "DATE", "time": "DATE",
    # Familia Booleana
    "boolean": "BOOL", "bit": "BOOL", "tinyint": "BOOL", "bool": "BOOL",
    # Otros
    "object": "OBJECT", "array": "ARRAY"
}

KEYWORDS_TO_SKIP = {
    "origen", "atributo", "tipo de dato", "backend", "servicio",
    "backend - input", "backend - output", "nan", "none", "tipo",
    "mapeo transacción", "función", "destino", "obligatoriedad"
}

CONTRACT_SHEET = "Hoja 1"


# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def _normalize(text: str) -> str:
    if not isinstance(text, str): return ""
    return text.strip().lower()


def _loose_normalize(text: str) -> str:
    return _normalize(text).replace("_", "").replace(" ", "")


def _get_type_family(type_str: str) -> str:
    if not type_str: return "UNKNOWN"
    clean = type_str.split("(")[0].strip().lower()
    return TYPE_FAMILIES.get(clean, "UNKNOWN")


def _load_contract_types(excel_path: str) -> dict:
    try:
        df = pd.read_excel(excel_path, sheet_name=CONTRACT_SHEET, header=None)
    except:
        return {}
    contract_map = {}
    attr_idx, type_idx, start_row = -1, -1, -1
    for i, row in df.iterrows():
        row_str = [str(v).strip().lower() for v in row]
        if "atributo" in row_str:
            try:
                attr_idx = row_str.index("atributo")
                type_idx = next((idx for idx, val in enumerate(row_str) if val in ["tipo", "tipo de dato"]), -1)
                if attr_idx != -1 and type_idx != -1:
                    start_row = i
                    break
            except:
                continue
    if start_row != -1:
        for i in range(start_row + 1, len(df)):
            row = df.iloc[i]
            attr = str(row.iloc[attr_idx]).strip()
            dtype = str(row.iloc[type_idx]).strip().lower()
            if attr and attr.lower() != "nan":
                contract_map[_loose_normalize(attr)] = dtype
    return contract_map


def _find_table_structure(df: pd.DataFrame):
    for i, row in df.iterrows():
        row_str = [str(val).strip().lower() for val in row]
        attr_cols = [idx for idx, val in enumerate(row_str) if "atributo" in val]
        type_cols = [idx for idx, val in enumerate(row_str) if "tipo" in val or "tipo de dato" in val]
        if attr_cols and type_cols:
            return i, attr_cols, type_cols
    return None, [], []


# =============================================================================
# LÓGICA PRINCIPAL
# =============================================================================

def validate_backend_mapping(excel_path: str) -> dict:
    issues = []
    contract_types = _load_contract_types(excel_path)
    xls = pd.ExcelFile(excel_path)

    for sheet_name in xls.sheet_names:
        if sheet_name == CONTRACT_SHEET: continue
        try:
            df_raw = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
        except:
            continue

        start_row, attr_cols, type_cols = _find_table_structure(df_raw)
        if start_row is None: continue

        idx_type_origin = type_cols[0] if len(type_cols) > 0 else None
        idx_type_db = type_cols[1] if len(type_cols) > 1 else None

        defined_attributes_loose = set()

        for r_idx in range(start_row + 1, len(df_raw)):
            row = df_raw.iloc[r_idx]
            primary_val = str(row.iloc[attr_cols[0]]).strip().lower()
            if "insert into" in primary_val or "select " in primary_val: break
            if "backend - output" in primary_val: break
            if primary_val in KEYWORDS_TO_SKIP: continue
            if not primary_val or primary_val == "nan": continue

            attr_origin = str(row.iloc[attr_cols[0]]).strip()
            type_origin = str(row.iloc[idx_type_origin]).strip().lower() if idx_type_origin is not None else ""

            attr_db = ""
            type_db = ""
            if len(attr_cols) > 1: attr_db = str(row.iloc[attr_cols[-1]]).strip()
            if idx_type_db is not None: type_db = str(row.iloc[idx_type_db]).strip().lower()

            ref_attr = attr_db if attr_db and attr_db.lower() != "nan" else attr_origin
            if ref_attr and ref_attr.lower() != "nan":
                defined_attributes_loose.add(_loose_normalize(ref_attr))

            # --- VALIDACIÓN DE COHERENCIA (AHORA COMO SUGERENCIA) ---
            origin_key = _loose_normalize(attr_origin)
            if origin_key in contract_types:
                contract_type = contract_types[origin_key]
                family_contract = _get_type_family(contract_type)
                family_db = _get_type_family(type_db)

                if family_db != "UNKNOWN" and family_contract != "UNKNOWN":
                    is_obj_to_text = (family_contract == "OBJECT" and family_db == "TEXT")

                    if family_contract != family_db and not is_obj_to_text:
                        # 🔥 CAMBIO CLAVE AQUÍ: WARN en vez de ERROR
                        issues.append({
                            "sheet": sheet_name,
                            "attribute": attr_origin,
                            "level": "WARN",  # Era ERROR
                            "category": "CONTRACT_MISMATCH",
                            "blocks_vobo": False,  # Era True
                            "message": (
                                f"El tipo de dato de Base de Datos ('{type_db}') NO es compatible con lo definido "
                                f"en el Contrato Hoja 1 ('{contract_type}'). "
                                f"Se sugiere cambiar el tipo de dato a {family_contract}."  # Mensaje suavizado
                            )
                        })

        sheet_text = df_raw.to_string()
        if "INSERT INTO" in sheet_text.upper():
            issues.extend(_validate_sql_consistency(sheet_text, defined_attributes_loose, sheet_name))

    return {"details": issues}


def _validate_sql_consistency(text, valid_attrs_loose, sheet_name):
    issues = []
    matches = re.finditer(r"INSERT\s+INTO\s+.*?\((.*?)\)\s*VALUES", text, re.IGNORECASE | re.DOTALL)
    for m in matches:
        columns = [c.strip() for c in m.group(1).replace("\n", "").split(",")]
        for col in columns:
            if not col: continue
            if _loose_normalize(col) not in valid_attrs_loose:
                issues.append({
                    "sheet": sheet_name,
                    "attribute": f"SQL Column: {col}",
                    "level": "WARN",
                    "category": "SQL_CONSISTENCY",
                    "blocks_vobo": False,
                    "message": f"La columna '{col}' del INSERT no se encontró explícitamente definida en la tabla."
                })
    return issues