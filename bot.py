import hashlib
import hmac
import os
import random
import threading
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
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

bot = telebot.TeleBot(BOT_TOKEN)

previous_state = None
monitoring_enabled = True


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


def get_power_state(grid_in, load_out):
    if grid_in > 10:
        return "grid_on"
    elif grid_in < 10 and load_out > 0:
        return "grid_off"
    else:
        return "idle"


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
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("🔄 refresh", callback_data="refresh"))
    return markup


def is_authorized(user_id):
    if not ALLOWED_USERS or ALLOWED_USERS[0] == "":
        return True
    return str(user_id) in ALLOWED_USERS


def send_alert_to_users(message):
    if not ALLOWED_USERS or ALLOWED_USERS[0] == "":
        return

    for user_id in ALLOWED_USERS:
        if user_id:
            try:
                bot.send_message(user_id, message, parse_mode="HTML")
            except Exception as e:
                print(f"Failed to send alert to {user_id}: {e}")


def monitor_power_state():
    global previous_state

    while monitoring_enabled:
        try:
            sn = get_sn()
            if sn:
                status = get_power_status(sn)
                if status["success"]:
                    current_state = get_power_state(
                        status["grid_in"], status["load_out"]
                    )

                    if previous_state is not None and previous_state != current_state:
                        if current_state == "grid_on" and previous_state == "grid_off":
                            alert_msg = (
                                f"✅ <b>Світло УВІМКНЕНО!</b>\n\n"
                                f"🔋 battery: {status['soc']}%\n"
                                f"⚡ grid input: {status['grid_in']} W"
                            )
                            send_alert_to_users(alert_msg)
                            print(f"[ALERT] Grid power ON")

                        elif (
                            current_state == "grid_off" and previous_state == "grid_on"
                        ):
                            alert_msg = (
                                f"🔋😢 <b>Світло ВИМКНЕНО!</b>\n\n"
                                f"🔋 battery: {status['soc']}%\n"
                                f"📤 load output: {status['load_out']} W"
                            )
                            send_alert_to_users(alert_msg)
                            print(f"[ALERT] Grid power OFF")

                    previous_state = current_state

        except Exception as e:
            print(f"Monitor error: {e}")

        time.sleep(CHECK_INTERVAL)


@bot.message_handler(commands=["start"])
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

    if call.data == "refresh":
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


@bot.message_handler(func=lambda message: True)
def echo_all(message):
    if not is_authorized(message.from_user.id):
        return
    bot.reply_to(message, "Use /start to check your EcoFlow station")


if __name__ == "__main__":
    print("🤖 EcoFlow Telegram Bot started...")
    print(f"📡 Monitoring interval: {CHECK_INTERVAL} seconds")

    monitor_thread = threading.Thread(target=monitor_power_state, daemon=True)
    monitor_thread.start()

    print(f"📡 Polling for updates...")
    bot.infinity_polling()
