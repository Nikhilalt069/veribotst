import telebot
import time
from dotenv import load_dotenv
import os
import psycopg2
from flask import Flask, request
import threading
import logging
import requests

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Load environment variables
load_dotenv()

# Configuration from .env with error checking
TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TOKEN:
    logger.error("Error: TELEGRAM_TOKEN not found")
    exit(1)

OWNER_ID = int(os.getenv('OWNER_ID'))
POSTGRES_URI = os.getenv('POSTGRES_URI')
if not POSTGRES_URI:
    logger.error("Error: POSTGRES_URI not found")
    exit(1)

# Print confirmation
print(f"Token loaded: {TOKEN[:5]}...{TOKEN[-5:]}")
print(f"Owner ID loaded: {OWNER_ID}")

# Initialize bot
bot = telebot.TeleBot(TOKEN, threaded=True)

# Connect to PostgreSQL
def get_db_connection():
    return psycopg2.connect(POSTGRES_URI)

# Store authorized users with IDs
authorized_users = {OWNER_ID}

# Helper function to format username
def format_username(username):
    username = username.lower().strip().replace('@', '')
    return f"@{username}"

# Helper function to get verification data
def get_verified_user(username):
    formatted_username = format_username(username)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT username, service FROM verified_users
            WHERE username = %s OR username = %s OR username = %s OR username = %s
        """, (formatted_username, formatted_username.lower(), 
              formatted_username.replace('_', ''), formatted_username.replace('_', '-')))
        
        result = cur.fetchone()
        cur.close()
        conn.close()

        if result:
            return {"username": result[0], "service": result[1]}
        return None
    except Exception as e:
        logger.error(f"Database error: {e}")
        return None

# Helper function to save verification data
def save_verified_user(username, service):
    formatted_username = format_username(username)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO verified_users (username, service)
            VALUES (%s, %s)
            ON CONFLICT (username) DO UPDATE SET service = EXCLUDED.service
        """, (formatted_username, service))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving user: {e}")

# Helper function to remove verified user
def remove_verified_user(username):
    formatted_username = format_username(username)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM verified_users WHERE username = %s", (formatted_username,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error removing user: {e}")

# Check if user is authorized
def is_authorized(user):
    return user.id in authorized_users

# Escape MarkdownV2 special characters
def escape_markdown(text):
    special_chars = '_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in special_chars else char for char in str(text))

@bot.message_handler(commands=['check'])
def check_verification(message):
    try:
        if len(message.text.split()) > 1:
            username = message.text.split()[1].strip()
        elif message.reply_to_message and message.reply_to_message.from_user.username:
            username = message.reply_to_message.from_user.username
        else:
            bot.reply_to(message, "Usage:\n1. Reply to a message with /check\n2. Or use: /check username")
            return
        
        user_data = get_verified_user(username)
        display_name = format_username(username).upper()

        if user_data:
            service = user_data.get('service', 'Unknown').upper()
            response = (
                f"*🟢 {escape_markdown(display_name)} is verified for:*\n\n"
                f"{escape_markdown(service)}\n\n"
                f"*💬 We still recommend using escrow:*\n"
                f"[Scrizon](https://t\\.me/scrizon) \\| [Cupid](https://t\\.me/cupid)"
            )
        else:
            response = (
                f"*🔴 {escape_markdown(display_name)} is not verified\\!*\n\n"
                f"*⚠️ We highly recommend using escrow:*\n"
                f"[Scrizon](https://t\\.me/scrizon) \\| [Cupid](https://t\\.me/cupid)"
            )

        bot.reply_to(message, response, parse_mode='MarkdownV2', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error in check_verification: {e}")

@bot.message_handler(commands=['add'])
def add_verified(message):
    try:
        if not is_authorized(message.from_user):
            bot.reply_to(message, "You are not authorized to use this command.")
            return

        args = message.text.split(maxsplit=2)
        if len(args) != 3:
            bot.reply_to(message, "Usage: /add username - Service")
            return

        username = format_username(args[1])
        service = args[2]

        save_verified_user(username, service)
        bot.reply_to(message, f"{username} has been added as verified for {service}.")
    except Exception as e:
        logger.error(f"Error in add_verified: {e}")

@bot.message_handler(commands=['remove'])
def remove_verified(message):
    try:
        if not is_authorized(message.from_user):
            bot.reply_to(message, "You are not authorized to use this command.")
            return

        if len(message.text.split()) != 2:
            bot.reply_to(message, "Usage: /remove username")
            return

        username = message.text.split()[1]
        if get_verified_user(username):
            remove_verified_user(username)
            bot.reply_to(message, f"{username} has been removed from verified users.")
        else:
            bot.reply_to(message, f"{username} is not a verified user.")
    except Exception as e:
        logger.error(f"Error in remove_verified: {e}")

@app.route('/')
def home():
    return f"Bot is running"

@app.route('/health')
def health():
    return "OK", 200

@bot.message_handler(commands=['ping'])
def ping_command(message):
    bot.reply_to(message, "Pong! Bot is working!")

def bot_polling():
    while True:
        try:
            bot.polling(timeout=60, long_polling_timeout=60, non_stop=True)
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            time.sleep(10)

if __name__ == '__main__':
    polling_thread = threading.Thread(target=bot_polling)
    polling_thread.daemon = True
    polling_thread.start()

    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
