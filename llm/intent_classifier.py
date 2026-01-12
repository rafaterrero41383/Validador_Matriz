# llm/intent_classifier.py
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
Eres un clasificador de intención para un agente de gobierno técnico.

Devuelve SOLO una de estas etiquetas exactas:
- VALIDATE_VOBO
- EXPLAIN_ERROR
- HELP
- OUT_OF_SCOPE
"""

KEYWORD_VALIDATE = {
    "valida",
    "validar",
    "validar vobo",
    "valida vobo",
    "valida el vobo",
    "validar el vobo",
    "vobo",
}

def classify_intent(user_message: str) -> str:
    text = user_message.lower().strip()

    # 🔥 ATAJO DETERMINISTA (CRÍTICO)
    for kw in KEYWORD_VALIDATE:
        if kw in text:
            return "VALIDATE_VOBO"

    # --- fallback LLM ---
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
