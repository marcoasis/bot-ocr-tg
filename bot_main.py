import io
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from PIL import Image
from dotenv import load_dotenv
import os

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# --- Tu código local ---
from ocr import extract_fields_safely  # usamos tu OCR ya creado
from db_utils import save_ticket       # función para guardar en SQLite
print("✅ Módulos importados correctamente.")

# ===== Config & logging =====
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Falta TELEGRAM_BOT_TOKEN en .env")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot-ocr-tickets")

# ===== Conversación =====
CHOOSING, EDITING = range(2)

@dataclass
class TicketDraft:
    store: Optional[str] = None
    date: Optional[str] = None
    total: Optional[str] = None
    currency: str = "MXN"
    raw_text: Optional[str] = None
    used_pre: bool = True

def summary_md(td: TicketDraft) -> str:
    return (
        "**Vista previa del ticket**\n\n"
        f"🏬 *Tienda:* {td.store or '—'}\n"
        f"📅 *Fecha:* {td.date or '—'}\n"
        f"💵 *Total:* {td.total or '—'} {td.currency}\n"
    )

def confirm_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="confirm"),
            InlineKeyboardButton("✏️ Editar", callback_data="edit"),
        ],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(kb)

def edit_field_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("Tienda", callback_data="edit_store"),
            InlineKeyboardButton("Fecha", callback_data="edit_date"),
            InlineKeyboardButton("Total", callback_data="edit_total"),
        ],
        [InlineKeyboardButton("⬅️ Volver", callback_data="back_to_confirm")],
    ]
    return InlineKeyboardMarkup(kb)

# ===== Handlers =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! 👋 Envíame una *foto del ticket*.\n\n"
        "Yo haré OCR y te mostraré los datos para confirmar o editar antes de guardar.",
        parse_mode="Markdown",
    )

async def responder_hola(update, context):
    text = (update.message.text or "").lower()
    if "hola" in text or "hi" in text or "hello" in text:
        await update.message.reply_text("¡Hola! 👋 Envíame una foto del ticket para empezar.")
    elif "gracias" in text or "thank you" in text:
        await update.message.reply_text("¡De nada! 😊 Si necesitas algo más, solo envíame otra foto.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recibe la foto, hace OCR y prepara el borrador."""
    try:
        if not update.message or not update.message.photo:
            return

        # 1) Descargar la versión de mayor resolución
        photo = update.message.photo[-1]
        file = await photo.get_file()
        bio = io.BytesIO()
        await file.download_to_memory(out=bio)
        bio.seek(0)

        # 2) Abrir con PIL
        img = Image.open(bio).convert("RGB")

        # 3) OCR con tu helper de 'intento doble'
        store, date, total, text, used_pre = extract_fields_safely(img)

        # 4) Guardar draft en user_data
        td = TicketDraft(
            store=store,
            date=date,
            total=total,
            raw_text=text,
            used_pre=used_pre,
        )
        context.user_data["draft"] = td

        # 5) Mostrar resumen + botones
        await update.message.reply_text(
            summary_md(td),
            reply_markup=confirm_keyboard(),
            parse_mode="Markdown",
        )
        return CHOOSING
    except Exception as e:
        logger.exception("Error procesando foto: %s", e)
        await update.message.reply_text(
            "😬 Hubo un error procesando la imagen. Intenta con otra foto o envíala como archivo."
        )

async def on_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las acciones del teclado principal."""
    if not update.callback_query:
        return
    q = update.callback_query
    await q.answer()

    td: TicketDraft = context.user_data.get("draft")
    if not td:
        await q.edit_message_text("No tengo un ticket en edición. Envíame una foto de ticket.")
        return ConversationHandler.END

    if q.data == "confirm":
        # Guardar y terminar
        save_ticket(td.store, td.date, td.total, td.currency, td.raw_text)
        await q.edit_message_text(
            summary_md(td) + "\n\n✅ *Guardado en la base de datos.*",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    if q.data == "edit":
        await q.edit_message_text(
            summary_md(td) + "\n\n¿Qué campo quieres editar?",
            reply_markup=edit_field_keyboard(),
            parse_mode="Markdown",
        )
        return EDITING

    if q.data == "cancel":
        await q.edit_message_text("Operación cancelada. Puedes enviarme otro ticket cuando quieras.")
        context.user_data.pop("draft", None)
        return ConversationHandler.END

async def on_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el menú de edición: elegir campo o volver."""
    if not update.callback_query:
        return
    q = update.callback_query
    await q.answer()

    td: TicketDraft = context.user_data.get("draft")
    if not td:
        await q.edit_message_text("No tengo un ticket en edición. Envíame una foto de ticket.")
        return ConversationHandler.END

    if q.data == "back_to_confirm":
        await q.edit_message_text(
            summary_md(td),
            reply_markup=confirm_keyboard(),
            parse_mode="Markdown",
        )
        return CHOOSING

    # Guardamos qué campo se va a editar
    field = None
    if q.data == "edit_store":
        field = "store"
        prompt = "Escribe el *nombre de la tienda*:"
    elif q.data == "edit_date":
        field = "date"
        prompt = "Escribe la *fecha* con formato **DD/MM/AAAA**:"
    elif q.data == "edit_total":
        field = "total"
        prompt = "Escribe el *total* (solo número, ej. `101.00`):"
    else:
        await q.edit_message_text("Opción no válida. Volvamos a empezar con /start.")
        return ConversationHandler.END

    context.user_data["edit_field"] = field
    await q.edit_message_text(prompt, parse_mode="Markdown")
    return EDITING  # seguimos esperando texto del usuario

async def on_text_during_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """El usuario envía el valor del campo a editar."""
    td: TicketDraft = context.user_data.get("draft")
    field = context.user_data.get("edit_field")
    if not td or not field:
        await update.message.reply_text("No hay edición activa. Envíame una foto de ticket.")
        return ConversationHandler.END

    value = (update.message.text or "").strip()
    if not value:
        await update.message.reply_text("No recibí texto. Intenta otra vez.")
        return EDITING

    # Validación simple
    if field == "total":
        value = value.replace(",", ".")
        try:
            float(value)
        except:
            await update.message.reply_text("Formato inválido. Ejemplo válido: 101.00")
            return EDITING

    setattr(td, field, value)
    context.user_data["draft"] = td
    context.user_data.pop("edit_field", None)

    # Volver a la pantalla de confirmación
    await update.message.reply_text(
        summary_md(td),
        reply_markup=confirm_keyboard(),
        parse_mode="Markdown",
    )
    return CHOOSING

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("draft", None)
    await update.message.reply_text("Cancelado. Envía una foto cuando quieras.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.PHOTO, handle_photo),
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(on_choice, pattern="^(confirm|edit|cancel)$"),
            ],
            EDITING: [
                CallbackQueryHandler(on_edit, pattern="^(edit_store|edit_date|edit_total|back_to_confirm)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_during_edit),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("start", start))

    logger.info("Bot arrancando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
