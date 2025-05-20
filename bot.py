# bot.py
from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import logging
import re
import json

import db_manager
import sickw_api
from config import TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_ID, CARRIER_CHECK_SERVICE_ID, CREDIT_PRICE_PER_CHECK, WEB_APP_URL

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Conversation States ---
GET_IMEI = 1 # State for waiting for IMEI input in conversational mode

# --- Helper Functions ---
def is_admin(user_id: int) -> bool:
    """Checks if the given user ID is the admin."""
    return user_id == ADMIN_TELEGRAM_ID

def format_sickw_result(result_data: dict) -> str:
    """Formats the SICKW BETA API result into a readable string."""
    if not result_data:
        return "No specific details available."

    lines = []
    # Prioritize 'result' field if it's a dict
    if 'result' in result_data and isinstance(result_data['result'], dict):
        for key, value in result_data['result'].items():
            lines.append(f"**{key.replace('_', ' ').title()}**: {value}")
    elif 'result' in result_data and isinstance(result_data['result'], str):
        # Handle cases where 'result' is a string, e.g., "Error S03..."
        lines.append(f"**Result**: {result_data['result']}")

    # Add other top-level fields if useful
    if 'imei' in result_data and 'result' not in result_data: # Avoid duplication if IMEI is in 'result'
        lines.append(f"**IMEI**: {result_data['imei']}")
    if 'status' in result_data:
        lines.append(f"**Status**: {result_data['status'].title()}")

    return "\n".join(lines)


# --- Telegram Bot Commands ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and offers to open the Web App via a persistent keyboard."""
    user = update.effective_user
    if user:
        if not db_manager.user_exists(user.id):
            db_manager.register_user(user.id)
            logger.info(f"New user registered: {user.id} ({user.full_name})")

        # Create a ReplyKeyboardMarkup with a WebApp button
        # This is CRUCIAL for sendData() to work from the Web App
        keyboard = [[KeyboardButton("Open IMEI Checker App", web_app=WebAppInfo(url=WEB_APP_URL))]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

        await update.message.reply_html(
            f"Hi {user.mention_html()}! 👋\n"
            "I'm your IMEI Carrier Checker Bot.\n\n"
            "You can use me to check iPhone carrier and other information.\n"
            f"Each successful check costs <b>{CREDIT_PRICE_PER_CHECK} credit</b>.\n\n"
            "✨ Use the new interactive Web App for a smoother experience! ✨\n"
            "Tap the 'Open IMEI Checker App' button below to launch it."
            "\n\nOr use the menu button (usually a '/' symbol) to see other commands like /balance and /help."
            , reply_markup=reply_markup # Attach the ReplyKeyboardMarkup
        )
    else:
        await update.message.reply_text("Hello! I'm your IMEI Carrier Checker Bot. Please use /start to begin.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message with available commands, potentially including the WebApp button."""
    # For consistency, let's keep the ReplyKeyboard here as well.
    keyboard = [[KeyboardButton("Open IMEI Checker App", web_app=WebAppInfo(url=WEB_APP_URL))]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    await update.message.reply_html(
        "Here are the commands you can use:\n"
        "• /balance - Check your current credit balance.\n"
        "• /check_imei - Start an IMEI check (conversational).\n"
        "• /add_credits - Learn how to add more credits.\n"
        "• /help - Get this message again.\n"
        "• /open_app - Launch the IMEI Checker Web App button.\n\n" # Added /open_app to help text
        "Remember to use the 'Open IMEI Checker App' button below for quick checks!"
        , reply_markup=reply_markup
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Checks and displays the user's current credit balance."""
    user_id = update.effective_user.id
    credits = db_manager.get_user_credits(user_id)
    await update.message.reply_text(f"Your current credit balance is: {credits} credits.")

async def add_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Provides instructions on how to add credits."""
    admin_info = "the administrator"
    if ADMIN_TELEGRAM_ID:
        try:
            admin_user = await context.bot.get_chat(ADMIN_TELEGRAM_ID)
            admin_info = f"@{admin_user.username}" if admin_user.username else f"the administrator (ID: {ADMIN_TELEGRAM_ID})"
        except Exception:
            pass # Fallback to generic text if admin info can't be fetched

    await update.message.reply_text(
        f"To add credits, please contact {admin_info} and inform them of your Telegram User ID: `{update.effective_user.id}`. "
        f"Each credit costs ${CREDIT_PRICE_PER_CHECK}.\n\n"
        "Once payment is confirmed, the admin will add credits to your account manually."
    )

# --- New Command to Explicitly Show Web App Button ---
async def open_app_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the reply keyboard with the Web App launch button."""
    user = update.effective_user
    if user:
        keyboard = [[KeyboardButton("Open IMEI Checker App", web_app=WebAppInfo(url=WEB_APP_URL))]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

        await update.message.reply_html(
            f"Hi {user.mention_html()}! 👋\n"
            "Tap the button below to open the IMEI Checker Web App.\n"
            "This button will stay at the bottom of your chat for easy access."
            , reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("Please use this command in a private chat.")

# --- Conversational IMEI Check Functions (for /check_imei command) ---

async def start_imei_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation for IMEI checking (old conversational mode)."""
    user_id = update.effective_user.id
    current_credits = db_manager.get_user_credits(user_id)

    if current_credits < CREDIT_PRICE_PER_CHECK:
        await update.message.reply_text(
            f"You don't have enough credits for this check. You need {CREDIT_PRICE_PER_CHECK} credit, but you have {current_credits}."
            "\nPlease use `/add_credits` to top up or use the Web App for a smoother experience: /start (then tap button)."
        )
        return ConversationHandler.END # End the conversation if not enough credits

    await update.message.reply_text(
        "Please send me the IMEI or Serial number you want to check. "
        "It should be 14-16 digits long (spaces/hyphens will be removed automatically)."
    )
    return GET_IMEI # Set the state to GET_IMEI

async def process_imei_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processes the IMEI input from the user in conversational mode."""
    user_id = update.effective_user.id
    raw_imei = update.message.text.strip()
    imei = re.sub(r'\D', '', raw_imei) # Remove all non-digit characters

    if not re.fullmatch(r'^\d{14,16}$', imei):
        await update.message.reply_text(
            "The provided input does not look like a valid IMEI/Serial number. "
            "Please provide a 14-16 digit number. Try again."
        )
        return GET_IMEI # Stay in the same state to allow re-entry

    current_credits = db_manager.get_user_credits(user_id)
    if current_credits < CREDIT_PRICE_PER_CHECK:
        await update.message.reply_text(
            f"You don't have enough credits for this check. You need {CREDIT_PRICE_PER_CHECK} credit, but you have {current_credits}."
            "\nPlease use `/add_credits` to top up or use the Web App: /start (then tap button)."
        )
        return ConversationHandler.END

    if raw_imei != imei:
        await update.message.reply_text(f"Recognized IMEI: `{imei}` (non-digit characters removed).")

    await update.message.reply_text(f"Checking IMEI: `{imei}`. This may take a moment...", parse_mode='Markdown')

    db_manager.deduct_credits(user_id, CREDIT_PRICE_PER_CHECK)
    await update.message.reply_text(f"1 credit deducted. Your new balance: {db_manager.get_user_credits(user_id)} credits.")

    sickw_response = sickw_api.check_imei_sickw(imei, CARRIER_CHECK_SERVICE_ID)

    if sickw_response and sickw_response.get("status") == "success":
        formatted_result = format_sickw_result(sickw_response)
        await update.message.reply_markdown(
            f"✅ *Check Result for IMEI `{imei}`:*\n\n{formatted_result}"
        )
    else:
        error_message = sickw_response.get("result", "An unknown error occurred with the SICKW API.") if sickw_response else "Failed to get a response from the SICKW API."
        await update.message.reply_text(
            f"❌ *Error during IMEI check for `{imei}`:*\n"
            f"{error_message}\n\n"
            "Please try again or contact support if the issue persists."
        )
        db_manager.add_credits(user_id, CREDIT_PRICE_PER_CHECK)
        await update.message.reply_text(f"Credits refunded due to check failure. Your balance: {db_manager.get_user_credits(user_id)} credits.")

    return ConversationHandler.END # End the conversation

async def cancel_imei_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the conversational IMEI checking."""
    await update.message.reply_text("IMEI check canceled. You can start a new one with /check_imei or by opening the Web App.")
    return ConversationHandler.END


# --- Admin Commands ---

async def admin_add_credits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to add credits to a user."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: `/admin_add_credits <user_id> <amount>`\n"
            "Example: `/admin_add_credits 123456789 10`"
        )
        return

    try:
        target_user_id = int(context.args[0])
        amount = int(context.args[1])
        if amount <= 0:
            await update.message.reply_text("Amount must be a positive number.")
            return

        if not db_manager.user_exists(target_user_id):
            await update.message.reply_text(f"User with ID `{target_user_id}` not found in the database.")
            return

        db_manager.add_credits(target_user_id, amount)
        await update.message.reply_text(f"Successfully added {amount} credits to user `{target_user_id}`.")
        # Optionally notify the target user
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🎉 {amount} credits have been added to your account by the administrator! "
                     f"Your new balance is: {db_manager.get_user_credits(target_user_id)} credits."
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_user_id} about credit top-up: {e}")

    except ValueError:
        await update.message.reply_text("Invalid user ID or amount. Please provide numbers.")

# --- Handler for Web App data ---

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Receives and processes data sent from the Telegram Web App."""
    user_id = update.effective_user.id
    web_app_data = update.effective_message.web_app_data.data # This is the JSON string from the web app
    logger.info(f"Received Web App data from user {user_id}: {web_app_data}")

    try:
        data = json.loads(web_app_data)
        action = data.get('action')

        if action == 'check_imei':
            imei_from_webapp = data.get('imei')
            if not imei_from_webapp:
                await update.message.reply_text("IMEI was not provided from Web App.")
                return

            sanitized_imei = re.sub(r'\D', '', imei_from_webapp)

            if not re.fullmatch(r'^\d{14,16}$', sanitized_imei):
                response_to_user = "Invalid IMEI/Serial format from Web App. Please enter a 14-16 digit number."
                await update.message.reply_text(f"❌ {response_to_user}")
                return

            current_credits = db_manager.get_user_credits(user_id)
            if current_credits < CREDIT_PRICE_PER_CHECK:
                response_to_user = f"You don't have enough credits for this check. You need {CREDIT_PRICE_PER_CHECK} credit, but you have {current_credits}."
                await update.message.reply_text(f"❌ {response_to_user}\nPlease use `/add_credits` to top up.")
                return

            db_manager.deduct_credits(user_id, CREDIT_PRICE_PER_CHECK)
            await update.message.reply_text(f"1 credit deducted. Your new balance: {db_manager.get_user_credits(user_id)} credits.")
            await update.message.reply_text(f"Checking IMEI: `{sanitized_imei}` via Web App request. This may take a moment...", parse_mode='Markdown')

            sickw_response = sickw_api.check_imei_sickw(sanitized_imei, CARRIER_CHECK_SERVICE_ID)

            if sickw_response and sickw_response.get("status") == "success":
                formatted_result = format_sickw_result(sickw_response)
                await update.message.reply_markdown(
                    f"✅ *Check Result for IMEI `{sanitized_imei}` (from Web App):*\n\n{formatted_result}"
                )
            else:
                error_message = sickw_response.get("result", "An unknown error occurred with the SICKW API.") if sickw_response else "Failed to get a response from the SICKW API."
                await update.message.reply_text(
                    f"❌ *Error during IMEI check for `{sanitized_imei}` (from Web App):*\n"
                    f"{error_message}\n\n"
                    "Please try again or contact support if the issue persists."
                )
                db_manager.add_credits(user_id, CREDIT_PRICE_PER_CHECK)
                await update.message.reply_text(f"Credits refunded due to check failure. Your balance: {db_manager.get_user_credits(user_id)} credits.")

        # Handle 'request_balance' from Web App
        elif action == 'request_balance':
            credits = db_manager.get_user_credits(user_id)
            await update.message.reply_text(f"Your current credit balance (from Web App request) is: {credits} credits.")

        else:
            await update.message.reply_text(f"Unknown action or missing data from Web App: {web_app_data}")

    except json.JSONDecodeError:
        await update.message.reply_text("Received invalid data from Web App.")
    except Exception as e:
        logger.error(f"Error processing Web App data: {e}", exc_info=True)
        await update.message.reply_text("An internal error occurred while processing Web App data.")


# --- Error Handling ---

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles unknown commands."""
    await update.message.reply_text("Sorry, I don't understand that command. Use /help for available commands.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs the error and sends a message to the administrator."""
    logger.error(f"Update {update} caused error {context.error}")
    if ADMIN_TELEGRAM_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=f"An error occurred: `{context.error}`\nUpdate: `{update}`"
            )
        except Exception:
            pass # Ignore if admin cannot be notified


# --- Main Function to Run the Bot ---
def main() -> None:
    """Starts the bot."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("add_credits", add_credits_command))
    application.add_handler(CommandHandler("admin_add_credits", admin_add_credits_command))
    application.add_handler(CommandHandler("open_app", open_app_command)) # Handler for the new /open_app command

    # Conversation Handler for IMEI Check (for /check_imei)
    imei_check_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("check_imei", start_imei_conversation)],
        states={
            GET_IMEI: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_imei_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel_imei_conversation)],
    )
    application.add_handler(imei_check_conv_handler)

    # Handler for Web App data (IMPORTANT!)
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))

    # Message handler for unknown commands (this must be the LAST MessageHandler)
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Error handler
    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    db_manager.init_db() # Ensure DB is initialized on startup
    print("Bot starting...")
    main()
