# Spanish Flashcards Web v1

A simple web rebuild of the desktop flashcards idea.

## What it does
- Loads cards from `data/spanish_cards_with_categories.csv`
- Filters by category
- Supports English -> Spanish and Spanish -> English prompt modes
- Flip / Next / Prev / Shuffle in the browser
- Speak button that calls ElevenLabs from the backend

## Local run
```bash
pip install -r requirements.txt
uvicorn app:app --reload
```
Then open `http://127.0.0.1:8000`

## ElevenLabs setup
Set these environment variables before running:
- `ELEVENLABS_API_KEY`
- optional: `ELEVENLABS_VOICE_ID`
- optional: `ELEVENLABS_MODEL_ID`

### Windows PowerShell example
```powershell
$env:ELEVENLABS_API_KEY="your_key_here"
uvicorn app:app --reload
```

## Render deploy
1. Push this folder to GitHub
2. Create a new Web Service in Render
3. Connect the repo
4. Render can use the included `render.yaml`
5. Add `ELEVENLABS_API_KEY` in Render environment variables
6. Deploy

## Notes
- Voice works through the server so your API key stays hidden from the browser.
- This version keeps data simple and file-based on purpose.
- Good next upgrades: favorites, review bin, progress tracking, pronunciation scoring.
