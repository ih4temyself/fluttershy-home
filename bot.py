import hashlib
import hmac
import os
import random
import time

import requests
import telebot
from dotenv import load_dotenv
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

load_dotenv()

ACCESS_KEY = os.getenv("EF_ACCESS_KEY")
SECRET_KEY = os.getenv("EF_SECRET_KEY")
HOST = os.getenv("HOST")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "").split(",")

bot = telebot.TeleBot(BOT_TOKEN)


def create_headers(query_params=None):
    if query_params is None:
        query_params = {}

    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sorted_keys = sorted(query_params.keys())
    param_str = ""

    for key in sorted_keys:
        param_str += f"{key}={query_params[key]}&"

    sign_str = (
        f"{param_str}accessKey={ACCESS_KEY}&" f"nonce={nonce}&" f"timestamp={timestamp}"
    )

    signature = hmac.new(
        SECRET_KEY.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    return {
        "accessKey": ACCESS_KEY,
        "nonce": nonce,
        "timestamp": timestamp,
        "sign": signature,
    }


def get_sn():
    url = f"{HOST}/iot-open/sign/device/list"
    resp = requests.get(url, headers=create_headers())
    data = resp.json()

    if data["code"] == "0" and data["data"]:
        return data["data"][0]["sn"]
    return None


def get_power_status(sn):
    url = f"{HOST}/iot-open/sign/device/quota/all"
    params = {"sn": sn}
    headers = create_headers(params)
    resp = requests.get(url, headers=headers, params=params)
    data = resp.json()

    if data["code"] == "0":
        metrics = data["data"]
        return {
            "soc": metrics.get("cmsBattSoc", 0),
            "grid_in": metrics.get("powGetSysGrid", 0),
            "load_out": metrics.get("powGetSysLoad", 0),
            "success": True,
        }
    return {"success": False, "error": data}


def format_status_message(status, sn):
    if not status["success"]:
        return "❌ Error getting station data"

    soc = status["soc"]
    grid_in = status["grid_in"]
    load_out = status["load_out"]

    if grid_in > 10:
        power_state = "✅ Grid Power ON"
    elif grid_in < 10 and load_out > 0:
        power_state = "🔋😢 Running on Battery (Grid OFF)"
    else:
        power_state = "💤 Idle/Standby"

    message = (
        f"🔌 <b>стан екофлоу</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 SN: <code>{sn}</code>\n\n"
        f"🔋 battery: <b>{soc}%</b>\n"
        f"⚡ grid input: <b>{grid_in} W</b>\n"
        f"📤 load output: <b>{load_out} W</b>\n\n"
        f"status: {power_state}"
    )

    return message


def create_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 status", callback_data="status"),
        InlineKeyboardButton("🔄 refresh", callback_data="refresh"),
        InlineKeyboardButton("ℹ️ help", callback_data="help"),
    )
    return markup


def is_authorized(user_id):
    if not ALLOWED_USERS or ALLOWED_USERS[0] == "":
        return True
    return str(user_id) in ALLOWED_USERS


@bot.message_handler(commands=["start"])
def send_welcome(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "❌ Unauthorized. Contact bot owner.")
        return

    welcome_text = "/status to check current power status\n/help for all commands"
    bot.send_message(message.chat.id, welcome_text, reply_markup=create_keyboard())


@bot.message_handler(commands=["help"])
def send_help(message):
    if not is_authorized(message.from_user.id):
        return

    help_text = "/status - current station status\n"
    bot.send_message(
        message.chat.id, help_text, parse_mode="HTML", reply_markup=create_keyboard()
    )


@bot.message_handler(commands=["status"])
def send_status(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "❌ unauthorized")
        return

    loading_msg = bot.send_message(message.chat.id, "⏳ checking station...")

    try:
        sn = get_sn()
        if not sn:
            bot.edit_message_text(
                "❌ Device not found", message.chat.id, loading_msg.message_id
            )
            return

        status = get_power_status(sn)
        status_message = format_status_message(status, sn)

        bot.edit_message_text(
            status_message,
            message.chat.id,
            loading_msg.message_id,
            parse_mode="HTML",
            reply_markup=create_keyboard(),
        )
    except Exception as e:
        bot.edit_message_text(
            f"❌ Error: {str(e)}", message.chat.id, loading_msg.message_id
        )


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if not is_authorized(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Unauthorized")
        return

    if call.data in ["status", "refresh"]:
        try:
            sn = get_sn()
            if not sn:
                bot.answer_callback_query(
                    call.id, "❌ Device not found", show_alert=True
                )
                return

            status = get_power_status(sn)
            status_message = format_status_message(status, sn)

            bot.edit_message_text(
                status_message,
                call.message.chat.id,
                call.message.message_id,
                parse_mode="HTML",
                reply_markup=create_keyboard(),
            )
            bot.answer_callback_query(call.id, "✅ Updated")
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                bot.answer_callback_query(call.id, "Already up to date")
            else:
                bot.answer_callback_query(call.id, "❌ Error", show_alert=True)
        except Exception:
            bot.answer_callback_query(call.id, "❌ Error", show_alert=True)

    elif call.data == "help":
        bot.answer_callback_query(call.id)
        help_text = "/status - current station status\n"
        try:
            bot.edit_message_text(
                help_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode="HTML",
                reply_markup=create_keyboard(),
            )
        except telebot.apihelper.ApiTelegramException:
            pass


@bot.message_handler(func=lambda message: True)
def echo_all(message):
    if not is_authorized(message.from_user.id):
        return
    bot.reply_to(message, "Use /status to check your EcoFlow station")


if __name__ == "__main__":
    print("🤖 EcoFlow Telegram Bot started...")
    print(f"📡 Polling for updates...")
    bot.infinity_polling()
