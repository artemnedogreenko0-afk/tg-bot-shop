from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os
import httpx  # Библиотека для отправки запросов в Telegram

from .database import init_db, SessionLocal, BotModel

app = FastAPI(title="Telegram Bot Shop API")

# !!! СЮДА ВСТАВЬ ТОКЕН СВОЕГО БОТА ИЗ @BotFather !!!
BOT_TOKEN = "8676699098:AAFuOXqcUpEVy_qSz1fHR4ecafBY-X9QTpg"

class BotCreate(BaseModel):
    name: str
    description: str
    price: int

# Схема для оформления покупки
class BuyRequest(BaseModel):
    bot_id: int

@app.on_event("startup")
async def on_startup():
    init_db()
    db = SessionLocal()
    try:
        bots = db.query(BotModel).all()
        if not bots:
            test_bot1 = BotModel(name="Бот-Автопродажник", description="Автоматически продает цифровые товары.", price=50) # Цена в Stars
            test_bot2 = BotModel(name="Бот-Модератор чатов", description="Удаляет спам, ведет статистику.", price=30)
            db.add(test_bot1)
            db.add(test_bot2)
            db.commit()
    finally:
        db.close()

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/admin")
async def read_admin():
    return FileResponse(os.path.join(FRONTEND_DIR, "admin.html"))

@app.get("/api/bots")
async def get_bots(db: Session = Depends(get_db)):
    return db.query(BotModel).all()

@app.post("/api/bots")
async def create_bot(bot: BotCreate, db: Session = Depends(get_db)):
    new_bot = BotModel(name=bot.name, description=bot.description, price=bot.price)
    db.add(new_bot)
    db.commit()
    db.refresh(new_bot)
    return new_bot

# ЭНДПОИНТ ДЛЯ СОЗДАНИЯ ПЛАТЕЖНОЙ ССЫЛКИ
@app.post("/api/buy")
async def buy_bot(request: BuyRequest, db: Session = Depends(get_db)):
    # Находим бота в базе данных
    bot_item = db.query(BotModel).filter(BotModel.id == request.bot_id).first()
    if not bot_item:
        raise HTTPException(status_code=404, detail="Бот не найден")

    # Формируем запрос к Telegram API для создания инвойса (счета) на Telegram Stars
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
    payload = {
        "title": f"Покупка: {bot_item.name}",
        "description": bot_item.description,
        "payload": f"bot_user_{bot_item.id}", # Внутренний ID заказа
        "provider_token": "",                 # Для Telegram Stars это поле должно быть ПУСТЫМ
        "currency": "XTR",                    # Код валюты Telegram Stars — строго XTR
        "prices": [{"label": "Цена", "amount": bot_item.price}] # Количество звезд
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        res_data = response.json()
        
        if res_data.get("ok"):
            # Возвращаем созданную ссылку на оплату обратно на наш сайт
            return {"invoice_link": res_data["result"]}
        else:
            return JSONResponse(status_code=400, content={"detail": f"Ошибка Telegram: {res_data.get('description')}"})