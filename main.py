import httpx
import logging
from fastapi import FastAPI, Request

app = FastAPI()

TOKEN = "8273691312:AAGY4a8YidXubM5C1s2Q6PuZdGsUk4iYmvM"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TOKEN}"
SUPPORT_PHONE = "+031 1111 333"
RECEPTION_PHONE = "+031 1111 333"
SALES_PHONE = "+031 1111 333"

logging.basicConfig(level=logging.INFO)

async def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                json=payload,
                timeout=5
            )
            response.raise_for_status()
        except httpx.RequestError as e:
            logging.error(f"Error sending message: {e}")

async def handle_message(data, chat_id):
    text = data["message"].get("text", "")
    if text == "/start":
        keyboard = {
            "inline_keyboard": [
                [{"text": "پیگیری پذیرش", "callback_data": "reception"}],
                [{"text": "پیگیری فروش", "callback_data": "sales"}],
            ]
        }
        await send_message(chat_id, "با سلام!\nلطفا وضعیت خود را مشخص کنید: ", reply_markup=keyboard)
    elif text == "/support":
        await send_message(chat_id, f"برای ارتباط با ما لطفا موضوع خود را مطرح کرده و شماره تماس خود را بنویسید. همچنین می‌توانید با پشتیبانی تماس بگیرید: \n{SUPPORT_PHONE}")

async def handle_callback_query(data, chat_id):
    data_choice = data["callback_query"]["data"]
    await handle_callback(chat_id, data_choice)

async def handle_callback(chat_id, data_choice):
    if data_choice == "reception":
        await send_message(chat_id, f"برای پیگیری وضعیت پذیرش خود با شماره زیر در ارتباط باشید: \n {RECEPTION_PHONE}")
    elif data_choice == "sales":
        await send_message(chat_id, f"شماره مرکز واحد فروش: \n {SALES_PHONE}")

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    logging.info(f"Incoming update: {data}")

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        await handle_message(data, chat_id)
    elif "callback_query" in data:
        chat_id = data["callback_query"]["message"]["chat"]["id"]
        await handle_callback_query(data, chat_id)

    return {"ok": True}
