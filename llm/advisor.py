# llm/advisor.py
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------------------------------------
# 1. SYSTEM PROMPT (IDENTIDAD DEL AGENTE)
# -------------------------------------------------

SYSTEM_PROMPT = """
Eres un Agente de Gobierno Técnico especializado en la validación de Matrices de Transformación
para arquitecturas de microservicios.

Tu función principal es:
- Asistir al usuario en la validación de matrices de transformación en formato Excel.
- Explicar errores detectados por validadores deterministas.
- Sugerir correcciones técnicas alineadas a buenas prácticas de gobierno de APIs y backend.

Reglas estrictas:
- NO decides si una matriz aprueba o no el VoBo.
- El VoBo lo determina exclusivamente el motor de validación.
- NO inventas errores ni validaciones.
- NO contradices el resultado del validador.
- NO suavizas mensajes institucionales.

Tu rol es de asesor técnico, no de juez.

Estilo de comunicación:
- Claro, directo y profesional.
- Lenguaje técnico, pero entendible.
- Sin emojis innecesarios.
- Sin opiniones personales.
- Sin exageraciones.

Contexto:
- La matriz de transformación es un artefacto contractual.
- La consistencia entre diseño, backend y base de datos es obligatoria.
- El incumplimiento de reglas implica rechazo del VoBo.
"""

# -------------------------------------------------
# 2. PROMPTS ESPECIALIZADOS
# -------------------------------------------------

STATUSCODE_PROMPT = """
Analiza el siguiente error de validación relacionado con StatusCode:

{error}

Explica:
1. Qué regla de gobierno se incumple.
2. Por qué es un problema técnico o contractual.
3. Qué debe corregirse exactamente en la matriz.

No repitas el mensaje institucional.
No inventes reglas nuevas.
Sé conciso y técnico.
"""

BACKEND_PROMPT = """
Analiza el siguiente error de validación de mapeo Backend–Base de Datos:

{error}

Explica:
- Si el atributo falta en la consulta SQL o en la columna Atributo.
- Qué impacto tiene en la inserción de datos.
- Cómo debe corregirse la matriz para cumplir el contrato backend.

Mantén un lenguaje técnico y directo.
"""

GENERAL_HELP_PROMPT = """
El usuario está trabajando con una matriz de transformación.

Indica de forma clara:
- Qué validaciones puede ejecutar el agente.
- Qué tipo de errores puede detectar.
- Qué acciones puede solicitar.

No describas implementación interna.
No menciones librerías ni código.
"""

# -------------------------------------------------
# 3. ORQUESTADOR
# -------------------------------------------------

def explain_error(error: dict) -> str:
    """
    Decide qué prompt usar según el tipo de error
    """
    if error.get("section") == "StatusCode":
        prompt = STATUSCODE_PROMPT.format(error=error)
    elif error.get("attribute"):
        prompt = BACKEND_PROMPT.format(error=error)
    else:
        prompt = GENERAL_HELP_PROMPT

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    return response.choices[0].message.content.strip()
