# llm/intent_classifier.py
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
Eres un clasificador de intención para un agente de gobierno técnico.

Tu única tarea es clasificar la intención del usuario.
No respondas preguntas.
No expliques nada.

Devuelve SOLO una de estas etiquetas exactas:
- VALIDATE_VOBO
- EXPLAIN_ERROR
- HELP
- OUT_OF_SCOPE
"""

def classify_intent(user_message: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0
    )

    intent = response.choices[0].message.content.strip()

    if intent not in {
        "VALIDATE_VOBO",
        "EXPLAIN_ERROR",
        "HELP",
        "OUT_OF_SCOPE"
    }:
        return "OUT_OF_SCOPE"

    return intent
