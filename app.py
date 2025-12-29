import streamlit as st
import tempfile

from validator.vobo import run_vobo
from llm.intent_classifier import classify_intent
from llm.advisor import explain_error

# -------------------------------------------------
# Configuración de la página
# -------------------------------------------------
st.set_page_config(
    page_title="Agente VoBo – Matriz de Transformación",
    layout="wide"
)

st.title("🤖 Agente de Gobierno – VoBo Matriz de Transformación")

# -------------------------------------------------
# Inicialización de estado (OBLIGATORIO)
# -------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "excel_path" not in st.session_state:
    st.session_state.excel_path = None

if "context" not in st.session_state:
    st.session_state.context = {
        "errors": []
    }

if "file_loaded" not in st.session_state:
    st.session_state.file_loaded = False

# -------------------------------------------------
# Mostrar historial del chat
# -------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# -------------------------------------------------
# Carga de archivo Excel
# -------------------------------------------------
uploaded_file = st.file_uploader(
    "📎 Carga la matriz de transformación (Excel)",
    type=["xlsx"]
)

if uploaded_file and not st.session_state.file_loaded:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(uploaded_file.read())
        st.session_state.excel_path = tmp.name

    st.session_state.file_loaded = True

    st.session_state.messages.append({
        "role": "assistant",
        "content": "📄 Archivo cargado correctamente. Cuando quieras, dime **valida el VoBo**."
    })

    st.rerun()

# -------------------------------------------------
# Botón para cargar otro archivo
# -------------------------------------------------
if st.session_state.file_loaded:
    if st.button("🔄 Cargar otro archivo"):
        st.session_state.file_loaded = False
        st.session_state.excel_path = None
        st.session_state.context["errors"] = []
        st.session_state.messages.append({
            "role": "assistant",
            "content": "Puedes cargar un nuevo archivo Excel cuando quieras."
        })
        st.rerun()

# -------------------------------------------------
# Entrada de chat
# -------------------------------------------------
user_input = st.chat_input("Escribe tu mensaje...")

if user_input:
    # Guardar mensaje del usuario
    st.session_state.messages.append({
        "role": "user",
        "content": user_input
    })

    with st.chat_message("user"):
        st.markdown(user_input)

    # -------------------------------------------------
    # Clasificación de intención
    # -------------------------------------------------
    intent = classify_intent(user_input)
    response = ""

    # -------------------------------------------------
    # VALIDAR VOBO
    # -------------------------------------------------
    if intent == "VALIDATE_VOBO":
        if not st.session_state.excel_path:
            response = "❗ Primero debes cargar un archivo Excel."
        else:
            with st.spinner("Validando matriz de transformación..."):
                result = run_vobo(st.session_state.excel_path)

            # Guardar errores en memoria
            st.session_state.context["errors"] = result["details"]

            if result["vobo"]:
                response = f"✅ **{result['message']}**"
            else:
                response = f"❌ **{result['message']}**\n\n"
                response += "Se detectaron los siguientes errores:\n"
                for err in result["details"]:
                    response += f"- Hoja **{err.get('sheet', 'General')}**"
                    if "statusCode" in err:
                        response += f" | StatusCode `{err['statusCode']}`"
                    if "attribute" in err:
                        response += f" | Atributo `{err['attribute']}`"
                    response += "\n"

                response += "\nPuedes pedirme que **explique un error**."

    # -------------------------------------------------
    # EXPLICAR ERROR
    # -------------------------------------------------
    elif intent == "EXPLAIN_ERROR":
        errors = st.session_state.context.get("errors", [])

        if not errors:
            response = "No hay errores para explicar. Primero valida el VoBo."
        else:
            response = explain_error(errors[0])

    # -------------------------------------------------
    # AYUDA
    # -------------------------------------------------
    elif intent == "HELP":
        response = explain_error({})

    # -------------------------------------------------
    # FUERA DE ALCANCE
    # -------------------------------------------------
    else:
        response = (
            "Estoy enfocado en validar **Matrices de Transformación**.\n\n"
            "Puedes pedirme:\n"
            "- **Validar el VoBo**\n"
            "- **Explicar errores**\n"
            "- Ayuda sobre las validaciones disponibles"
        )

    # -------------------------------------------------
    # Mostrar respuesta del agente
    # -------------------------------------------------
    st.session_state.messages.append({
        "role": "assistant",
        "content": response
    })

    with st.chat_message("assistant"):
        st.markdown(response)
