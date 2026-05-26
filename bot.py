"""
DRAY ÉLECTROMÉNAGER — Bot Telegram
Génère des devis PDF à partir d'un message naturel
"""

import os
import json
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pdf_generator import generate_pdf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GROQ_API_KEY   = os.environ.get("GROQ_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Numéro de devis auto-incrémenté (en mémoire, reset au redémarrage)
devis_counter = {"n": 300060}

SYSTEM_PROMPT = """Tu es l'assistant commercial de DRAY ÉLECTROMÉNAGER.
Ton rôle : extraire les infos nécessaires pour générer un devis, poser des questions si des infos manquent, puis confirmer.

Infos OBLIGATOIRES pour un devis :
- Nom du client
- Au moins 1 produit avec son prix

Infos OPTIONNELLES (demande-les si pas données) :
- Adresse client
- Téléphone client
- Marque des produits
- Référence produit

RÈGLES :
1. Si toutes les infos obligatoires sont présentes → réponds UNIQUEMENT avec un JSON valide (pas de texte autour)
2. Si des infos manquent → pose UNE SEULE question claire et courte en français
3. Le JSON doit avoir exactement ce format :

{
  "ready": true,
  "client": {
    "nom": "DUPONT Jean",
    "adresse": "2 rue de la Paix",
    "cp_ville": "75001 Paris",
    "tel": "06 12 34 56 78",
    "mail": ""
  },
  "produits": [
    {"code": "REF001", "designation": "Télévision 65 pouces", "marque": "Samsung", "qty": 1, "prix": 899.00, "remise": 0},
    {"code": "REF002", "designation": "Four encastrable", "marque": "Smeg", "qty": 1, "prix": 549.00, "remise": 0}
  ]
}

Si infos manquantes → réponds juste en français, sans JSON.
"""


def ask_groq(messages: list) -> str:
    """Appel API Groq"""
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1000,
        },
        timeout=30
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Message de bienvenue"""
    await update.message.reply_text(
        "👋 Bonjour ! Je suis l'assistant devis de *DRAY ÉLECTROMÉNAGER*.\n\n"
        "Envoyez-moi les infos du devis en langage naturel, par exemple :\n\n"
        "_« Client Dupont Jean, 06 12 34 56 78, Paris 75001 — télé Samsung 65\" 899€, frigo Bosch 649€ »_\n\n"
        "Je vous pose des questions si besoin, puis je génère le PDF ! 📄",
        parse_mode="Markdown"
    )
    context.user_data["history"] = []


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Traite chaque message utilisateur"""
    user_text = update.message.text

    # Init historique si besoin
    if "history" not in context.user_data:
        context.user_data["history"] = []

    # Ajoute le message à l'historique
    context.user_data["history"].append({
        "role": "user",
        "content": user_text
    })

    # Indicateur de frappe
    await update.message.chat.send_action("typing")

    # Construction messages pour Groq
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + context.user_data["history"]

    try:
        reply = ask_groq(messages)
    except Exception as e:
        logger.error(f"Groq error: {e}")
        await update.message.reply_text("❌ Erreur de connexion à l'IA. Réessayez dans quelques secondes.")
        return

    # Ajoute la réponse à l'historique
    context.user_data["history"].append({
        "role": "assistant",
        "content": reply
    })

    # Tente de parser le JSON
    try:
        # Cherche le JSON dans la réponse (au cas où il y a du texte autour)
        start_idx = reply.find("{")
        end_idx   = reply.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            json_str = reply[start_idx:end_idx]
            data = json.loads(json_str)
            if data.get("ready"):
                # Génération du PDF
                await update.message.reply_text("⏳ Génération du devis en cours...")
                num = devis_counter["n"]
                devis_counter["n"] += 1
                pdf_path = generate_pdf(data, num)
                await update.message.reply_document(
                    document=open(pdf_path, "rb"),
                    filename=f"Devis_Dray_{num}.pdf",
                    caption=f"✅ *Devis N° {num}* généré avec succès !\n\n"
                            f"👤 Client : {data['client']['nom']}\n"
                            f"📦 {len(data['produits'])} article(s)\n"
                            f"💶 Total TTC : {sum(p['qty']*p['prix']*(1-p['remise']/100) for p in data['produits']):.2f} €",
                    parse_mode="Markdown"
                )
                # Reset historique pour un nouveau devis
                context.user_data["history"] = []
                return

    except (json.JSONDecodeError, KeyError):
        pass  # Pas un JSON = question de l'IA, on répond normalement

    # Réponse texte (question ou confirmation)
    await update.message.reply_text(reply)


async def nouveau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remet à zéro pour un nouveau devis"""
    context.user_data["history"] = []
    await update.message.reply_text("🔄 Nouveau devis ! Envoyez-moi les informations.")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("nouveau", nouveau))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot démarré...")
    app.run_polling()


if __name__ == "__main__":
    main()
