import streamlit as st
import tempfile
import re

from validator.vobo import run_vobo
from llm.intent_classifier import classify_intent
from llm.advisor import explain_errors, explain_error  # backward compat

st.set_page_config(
    page_title="Agente VoBo – Matriz de Transformación",
    layout="wide"
)

st.title("🤖 Agente de Gobierno – VoBo Matriz de Transformación")

# -----------------------------
# Session state
# -----------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "excel_path" not in st.session_state:
    st.session_state.excel_path = None

if "context" not in st.session_state:
    st.session_state.context = {"errors": []}

if "file_loaded" not in st.session_state:
    st.session_state.file_loaded = False

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "last_uploaded_name" not in st.session_state:
    st.session_state.last_uploaded_name = None

# -----------------------------
# Render chat history
# -----------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# -----------------------------
# File uploader
# -----------------------------
uploaded_file = st.file_uploader(
    "📎 Carga la matriz de transformación (Excel)",
    type=["xlsx"],
    key=f"excel_uploader_{st.session_state.uploader_key}"
)

should_load_file = (
        uploaded_file is not None and (
        (not st.session_state.file_loaded)
        or (uploaded_file.name != st.session_state.last_uploaded_name)
)
)

if should_load_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(uploaded_file.read())
        st.session_state.excel_path = tmp.name

    st.session_state.file_loaded = True
    st.session_state.last_uploaded_name = uploaded_file.name
    st.session_state.context["errors"] = []

    st.session_state.messages.append({
        "role": "assistant",
        "content": "📄 Archivo cargado correctamente. Cuando quieras, escribe **valida** para ejecutar el VoBo."
    })

    st.rerun()

# -----------------------------
# Load another file
# -----------------------------
if st.session_state.file_loaded:
    if st.button("🔄 Cargar otro archivo"):
        st.session_state.file_loaded = False
        st.session_state.excel_path = None
        st.session_state.context["errors"] = []
        st.session_state.last_uploaded_name = None
        st.session_state.uploader_key += 1

        st.session_state.messages.append({
            "role": "assistant",
            "content": "Puedes cargar un nuevo archivo Excel cuando quieras."
        })

        st.rerun()


# -----------------------------
# Intent shortcuts (NO LLM)
# -----------------------------
def quick_intent(user_message: str) -> str | None:
    """
    Atajo determinista para no depender del LLM con palabras clave críticas.
    """
    text = user_message.strip().lower()

    # valida / validar / valida vobo / validar vobo
    if re.fullmatch(r"(valida|validar)(\s+vobo)?", text):
        return "VALIDATE_VOBO"

    # explica / explicar
    if text.startswith("explica") or text.startswith("explicar"):
        return "EXPLAIN_ERROR"

    # ayuda
    if text in {"ayuda", "help", "?"}:
        return "HELP"

    return None


# -----------------------------
# Chat input
# -----------------------------
user_input = st.chat_input("Escribe tu mensaje...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 1) primero intent determinista
    intent = quick_intent(user_input)

    # 2) si no aplica, usa LLM
    if intent is None:
        intent = classify_intent(user_input)

    response = ""

    # -------------------------
    # VALIDATE VOBO
    # -------------------------
    if intent == "VALIDATE_VOBO":
        if not st.session_state.excel_path:
            response = "❗ Primero debes cargar un archivo Excel."
        else:
            with st.spinner("Validando matriz de transformación..."):
                result = run_vobo(st.session_state.excel_path)

            issues = result.get("details", [])
            st.session_state.context["errors"] = issues

            # Separa bloqueantes vs warnings
            blocking = [e for e in issues if e.get("blocks_vobo") is True or e.get("level") == "ERROR"]
            warnings = [e for e in issues if e.get("level") == "WARN" and e not in blocking]

            if result.get("vobo") is True:
                response = "✅ **La matriz de transformación ha aprobado el VoBo**\n\n"
            else:
                response = "❌ **La matriz de transformación NO aprueba el VoBo**\n\n"


            # --- FUNCIÓN AUXILIAR PARA FORMATO ---
            def format_issue_line(err):
                sheet_raw = str(err.get("sheet", "¿?")).strip()
                attr = err.get("attribute", "¿?")
                cell = err.get("cell", "")  # Dato nuevo (si existe)
                msg = err.get("message", "")

                # 1. Evitar "Hoja Hoja 4" -> "Hoja 4"
                if sheet_raw.lower().startswith("hoja"):
                    sheet_display = f"**{sheet_raw}**"
                else:
                    sheet_display = f"Hoja **{sheet_raw}**"

                # 2. Agregar Celda si existe
                location_str = sheet_display
                if cell:
                    location_str += f" (Celda `{cell}`)"

                line = f"- {location_str} | Atributo `{attr}`"
                if msg:
                    line += f"  \n  ↳ {msg}"
                return line


            # -------------------------------------

            if blocking:
                response += "## ❌ Errores que bloquean\n"
                for err in blocking:
                    response += format_issue_line(err) + "\n"
                response += "\n"

            if warnings:
                response += "## ⚠️ Advertencias\n"
                for err in warnings:
                    response += format_issue_line(err) + "\n"

            if issues:
                response += "\nPuedes pedirme que **explique un error o advertencia** (por hoja/atributo)."

    # -------------------------
    # EXPLAIN ERROR
    # -------------------------
    elif intent == "EXPLAIN_ERROR":
        issues = st.session_state.context.get("errors", [])
        if not issues:
            response = "No hay errores para explicar. Primero escribe **valida**."
        else:
            response = explain_errors(user_input, issues)
            if not response.strip():
                response = explain_error(issues[0])

    # -------------------------
    # HELP
    # -------------------------
    elif intent == "HELP":
        response = (
            "Puedo ayudarte a:\n"
            "- Escribe **valida** para ejecutar el VoBo\n"
            "- Escribe **explica** + hoja/atributo para detallar un error\n"
        )

    else:
        response = (
            "Estoy enfocado en validar **Matrices de Transformación**.\n\n"
            "Comandos:\n"
            "- **valida**\n"
            "- **explica ...**\n"
        )

    st.session_state.messages.append({"role": "assistant", "content": response})
    with st.chat_message("assistant"):
        st.markdown(response)