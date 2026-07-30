# HandsFreeBusan

AI travel assistant for foreign visitors using the Busan metro — luggage storage,
directions, and payment help, delivered through a chat interface.

## Structure

```
handsfreebusan-repo/
├─ android/   # Jetpack Compose app (chat UI + API client)
└─ backend/   # FastAPI service (Solar LLM tool-calling + recommendation engine)
```

## Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in UPSTAGE_API_KEY
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI: http://localhost:8000/docs · health check: `GET /health`

> **Secrets:** the real `.env` is never committed — copy `.env.example` and add your
> own `UPSTAGE_API_KEY`.
>
> **Data:** the organizer-provided dataset (`발제사 데이터/`) is intentionally **not**
> included in this repository. Without it the engine runs in reduced/fallback mode; the
> API contract is identical.

## Android

Open the `android/` folder in Android Studio and run on an emulator.

The app talks to the backend at `http://10.0.2.2:8000` (the host machine's `localhost`
as seen from the Android emulator). Change `baseUrl` in
`android/app/src/main/java/com/HandsFreeBusan/app/data/api/ApiClient.kt` for a physical
device or a different host.
