from __future__ import annotations

import csv
import io
import os
import random
from pathlib import Path
from typing import Any

import requests
from deep_translator import GoogleTranslator
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "spanish_cards_with_categories.csv"
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
DEFAULT_CATEGORIES = [
    "Basic Words",
    "Normal Express",
    "Sentences",
    "Items",
    "Places",
    "Home",
    "Going out to eat",
    "Directions",
    "Calendar",
]

app = FastAPI(title="Spanish Flashcards Web")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def load_cards() -> list[dict[str, str]]:
    if not DATA_FILE.exists():
        return []

    rows: list[dict[str, str]] = []
    with open(DATA_FILE, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            spanish = (row.get("spanish") or "").strip()
            english = (row.get("english") or "").strip()
            category = (row.get("category") or "").strip() or "Uncategorized"
            if spanish and english:
                rows.append(
                    {
                        "spanish": spanish,
                        "english": english,
                        "category": category,
                    }
                )
    return rows


def get_categories(cards: list[dict[str, str]]) -> list[str]:
    card_categories = {card["category"] for card in cards}
    return sorted(card_categories.union(DEFAULT_CATEGORIES))


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    cards = load_cards()
    categories = get_categories(cards)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "cards": cards,
            "categories": categories,
            "total": len(cards),
            "voice_enabled": bool(ELEVENLABS_API_KEY),
        },
    )


@app.get("/health")
def health() -> dict[str, Any]:
    cards = load_cards()
    return {
        "ok": True,
        "card_count": len(cards),
        "voice_enabled": bool(ELEVENLABS_API_KEY),
    }


@app.get("/api/cards")
def api_cards(category: str = Query(default="All")) -> JSONResponse:
    cards = load_cards()
    if category != "All":
        cards = [card for card in cards if card["category"] == category]
    random.shuffle(cards)
    return JSONResponse({"cards": cards, "count": len(cards)})


@app.get("/api/translate")
def translate_text(
    text: str = Query(..., min_length=1, max_length=300),
) -> JSONResponse:
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    try:
        spanish = GoogleTranslator(source="en", target="es").translate(clean_text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Translation failed: {exc}") from exc

    if not spanish:
        raise HTTPException(status_code=502, detail="Translation returned no text.")

    return JSONResponse(
        {
            "english": clean_text,
            "spanish": spanish,
        }
    )


@app.get("/api/speak")
def speak(
    text: str = Query(..., min_length=1, max_length=300),
    lang: str = Query(default="es"),
    speed: str = Query(default="normal"),
) -> StreamingResponse:
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY is not configured.")

    if lang not in {"es", "en"}:
        raise HTTPException(status_code=400, detail="Unsupported language.")

    if speed not in {"normal", "slow"}:
        raise HTTPException(status_code=400, detail="Unsupported speed mode.")

    if speed == "slow":
        voice_settings = {
            "stability": 0.75,
            "similarity_boost": 0.8,
            "style": 0.0,
            "use_speaker_boost": True,
            "speed": 0.7,
        }
    else:
        voice_settings = {
            "stability": 0.45,
            "similarity_boost": 0.8,
            "style": 0.0,
            "use_speaker_boost": True,
            "speed": 1.0,
        }

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": voice_settings,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=45)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Voice request failed: {exc}") from exc

    if response.status_code != 200:
        detail = response.text[:500] if response.text else "Unknown ElevenLabs error"
        raise HTTPException(status_code=502, detail=detail)

    return StreamingResponse(io.BytesIO(response.content), media_type="audio/mpeg")
