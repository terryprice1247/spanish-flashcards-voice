from __future__ import annotations

import csv
import io
import json
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
SAVED_PHRASES_FILE = BASE_DIR / "data" / "saved_phrases.json"
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


def load_saved_phrases() -> list[dict[str, Any]]:
    if not SAVED_PHRASES_FILE.exists():
        return []

    try:
        with open(SAVED_PHRASES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []

    cleaned: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        english = str(item.get("english", "")).strip()
        spanish = str(item.get("spanish", "")).strip()
        favorite = bool(item.get("favorite", False))
        stored = bool(item.get("stored", False))

        if english and spanish:
            cleaned.append(
                {
                    "english": english,
                    "spanish": spanish,
                    "favorite": favorite,
                    "stored": stored,
                }
            )

    return cleaned


def save_saved_phrases(phrases: list[dict[str, Any]]) -> None:
    SAVED_PHRASES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SAVED_PHRASES_FILE, "w", encoding="utf-8") as f:
        json.dump(phrases, f, ensure_ascii=False, indent=2)


def phrase_matches(item: dict[str, Any], english: str, spanish: str) -> bool:
    return (
        str(item.get("english", "")).strip().casefold() == english.strip().casefold()
        and str(item.get("spanish", "")).strip().casefold() == spanish.strip().casefold()
    )


def find_saved_phrase_index(
    saved_phrases: list[dict[str, Any]],
    english: str,
    spanish: str,
) -> int:
    for idx, item in enumerate(saved_phrases):
        if phrase_matches(item, english, spanish):
            return idx
    return -1


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
    saved_phrases = load_saved_phrases()
    active_count = sum(1 for item in saved_phrases if not item.get("stored", False))
    stored_count = sum(1 for item in saved_phrases if item.get("stored", False))
    return {
        "ok": True,
        "card_count": len(cards),
        "saved_phrase_count": len(saved_phrases),
        "active_saved_phrase_count": active_count,
        "stored_saved_phrase_count": stored_count,
        "voice_enabled": bool(ELEVENLABS_API_KEY),
    }


@app.get("/api/cards")
def api_cards(category: str = Query(default="All")) -> JSONResponse:
    cards = load_cards()
    if category != "All":
        cards = [card for card in cards if card["category"] == category]
    random.shuffle(cards)
    return JSONResponse({"cards": cards, "count": len(cards)})


@app.get("/api/saved-phrases")
def get_saved_phrases() -> JSONResponse:
    phrases = load_saved_phrases()
    return JSONResponse(
        {
            "ok": True,
            "phrases": phrases,
            "count": len(phrases),
            "active_count": sum(1 for item in phrases if not item.get("stored", False)),
            "stored_count": sum(1 for item in phrases if item.get("stored", False)),
        }
    )


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

    return JSONResponse({"english": clean_text, "spanish": spanish})


@app.post("/api/save-phrase")
async def save_phrase(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    english = str(payload.get("english", "")).strip()
    spanish = str(payload.get("spanish", "")).strip()

    if not english or not spanish:
        raise HTTPException(status_code=400, detail="English and Spanish are required.")

    saved_phrases = load_saved_phrases()
    existing_index = find_saved_phrase_index(saved_phrases, english, spanish)

    if existing_index >= 0:
        item = saved_phrases[existing_index]
        was_stored = bool(item.get("stored", False))
        if was_stored:
            item["stored"] = False
            save_saved_phrases(saved_phrases)
            return JSONResponse(
                {
                    "ok": True,
                    "saved": False,
                    "restored": True,
                    "message": "Phrase restored to the active deck.",
                    "phrase": item,
                }
            )

        return JSONResponse(
            {
                "ok": True,
                "saved": False,
                "restored": False,
                "message": "Phrase already saved.",
                "phrase": item,
            }
        )

    new_phrase = {
        "english": english,
        "spanish": spanish,
        "favorite": False,
        "stored": False,
    }
    saved_phrases.append(new_phrase)
    save_saved_phrases(saved_phrases)

    return JSONResponse(
        {
            "ok": True,
            "saved": True,
            "restored": False,
            "message": "Phrase saved.",
            "phrase": new_phrase,
        }
    )


@app.patch("/api/saved-phrases/store")
async def store_saved_phrase(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    english = str(payload.get("english", "")).strip()
    spanish = str(payload.get("spanish", "")).strip()
    saved_phrases = load_saved_phrases()
    phrase_index = find_saved_phrase_index(saved_phrases, english, spanish)

    if phrase_index < 0:
        raise HTTPException(status_code=404, detail="Saved phrase not found.")

    saved_phrases[phrase_index]["stored"] = True
    save_saved_phrases(saved_phrases)

    return JSONResponse(
        {
            "ok": True,
            "message": "Phrase stored for later.",
            "phrase": saved_phrases[phrase_index],
        }
    )


@app.patch("/api/saved-phrases/restore")
async def restore_saved_phrase(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    english = str(payload.get("english", "")).strip()
    spanish = str(payload.get("spanish", "")).strip()
    saved_phrases = load_saved_phrases()
    phrase_index = find_saved_phrase_index(saved_phrases, english, spanish)

    if phrase_index < 0:
        raise HTTPException(status_code=404, detail="Saved phrase not found.")

    saved_phrases[phrase_index]["stored"] = False
    save_saved_phrases(saved_phrases)

    return JSONResponse(
        {
            "ok": True,
            "message": "Phrase restored to the active deck.",
            "phrase": saved_phrases[phrase_index],
        }
    )


@app.delete("/api/saved-phrases")
async def delete_saved_phrase(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    english = str(payload.get("english", "")).strip()
    spanish = str(payload.get("spanish", "")).strip()
    saved_phrases = load_saved_phrases()
    phrase_index = find_saved_phrase_index(saved_phrases, english, spanish)

    if phrase_index < 0:
        raise HTTPException(status_code=404, detail="Saved phrase not found.")

    deleted = saved_phrases.pop(phrase_index)
    save_saved_phrases(saved_phrases)

    return JSONResponse(
        {
            "ok": True,
            "message": "Saved copy permanently deleted.",
            "deleted_phrase": deleted,
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

    voice_settings = {
        "stability": 0.75 if speed == "slow" else 0.45,
        "similarity_boost": 0.8,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 0.7 if speed == "slow" else 1.0,
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
