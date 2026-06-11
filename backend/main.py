from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os
import httpx

from .database import init_db, SessionLocal, BotModel

app = FastAPI(title="Telegram Bot Shop API")

# ================= НАСТРОЙКИ КЛИЕНТА =================
BOT_TOKEN = "8676699098:AAFuOXqcUpEVy_qSz1fHR4ecafBY-X9QTpg"  # <--- ВСТАВЬ СВОЙ ТОКЕН ИЗ @BotFather
ADMIN_PASSWORD = "190240488"  # <--- ТВОЙ ПАРОЛЬ ОТ АДМИНКИ
# =====================================================

class BotCreate(BaseModel):
    name: str
    description: str
    price: int

class BuyRequest(BaseModel):
    bot_id: int

@app.on_event("startup")
async def on_startup():
    init_db()
    db = SessionLocal()
    try:
        bots = db.query(BotModel).all()
        if not bots:
            test_bot1 = BotModel(name="Бот-Автопродажник", description="Автоматически продает цифровые товары в Telegram.", price=50)
            test_bot2 = BotModel(name="Бот-Модератор чатов", description="Удаляет спам, приветствует новичков, ведет статистику.", price=30)
            db.add(test_bot1)
            db.add(test_bot2)
            db.commit()
    finally:
        db.close()

# ЖЕСТКАЯ ПРИВЯЗКА К ПУТИ ВНУТРИ ПАПКИ BACKEND (Для Docker на Render)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Главная страница магазина
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# Защищенный вход в админку
@app.get("/admin")
async def read_admin(request: Request):
    password = request.headers.get("Authorization")
    if password == ADMIN_PASSWORD:
        return FileResponse(os.path.join(FRONTEND_DIR, "admin.html"))
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))

# Получить список ботов
@app.get("/api/bots")
async def get_bots(db: Session = Depends(get_db)):
    return db.query(BotModel).all()

# Создать бота (Доступно только админу по паролю)
@app.post("/api/bots")
async def create_bot(bot: BotCreate, request: Request, db: Session = Depends(get_db)):
    password = request.headers.get("Authorization")
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Неавторизованный доступ")
        
    new_bot = BotModel(name=bot.name, description=bot.description, price=bot.price)
    db.add(new_bot)
    db.commit()
    db.refresh(new_bot)
    return new_bot

# Генерация инвойса на оплату (Telegram Stars)
@app.post("/api/buy")
async def buy_bot(request: BuyRequest, db: Session = Depends(get_db)):
    bot_item = db.query(BotModel).filter(BotModel.id == request.bot_id).first()
    if not bot_item:
        raise HTTPException(status_code=404, detail="Бот не найден")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
    payload = {
        "title": f"Покупка: {bot_item.name}",
        "description": bot_item.description,
        "payload": f"order_bot_{bot_item.id}", 
        "provider_token": "",                 
        "currency": "XTR",                    
        "prices": [{"label": "Цена", "amount": bot_item.price}] 
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        res_data = response.json()
        if res_data.get("ok"):
            return {"invoice_link": res_data["result"]}
        else:
            return JSONResponse(status_code=400, content={"detail": f"Ошибка Telegram: {res_data.get('description')}"})

# Обработчик успешных платежей от Telegram
@app.post("/api/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    
    async with httpx.AsyncClient() as client:
        if "pre_checkout_query" in data:
            query_id = data["pre_checkout_query"]["id"]
            answer_url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerPreCheckoutQuery"
            await client.post(answer_url, json={"pre_checkout_query_id": query_id, "ok": True})
            return {"status": "ok"}

        if "message" in data and "successful_payment" in data["message"]:
            payment_info = data["message"]["successful_payment"]
            chat_id = data["message"]["chat"]["id"]
            
            payload = payment_info["invoice_payload"]
            bot_id = int(payload.replace("order_bot_", ""))
            
            bot_item = db.query(BotModel).filter(BotModel.id == bot_id).first()
            bot_name = bot_item.name if bot_item else "Скрипт Telegram Бота"

            message_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            text_to_user = (
                f"🎉 **Спасибо за оплату!**\n\n"
                f"📦 Твой товар: *{bot_name}*\n"
                f"🔗 Ссылка на скачивание исходного кода: https://github.com/your-repo/bot-archive.zip\n\n"
                f"Если возникнут вопросы по установке — наша поддержка всегда на связи!"
            )
            
            await client.post(message_url, json={
                "chat_id": chat_id,
                "text": text_to_user,
                "parse_mode": "Markdown"
            })
            return {"status": "success"}

    return {"status": "ignored"}