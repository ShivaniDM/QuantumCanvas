# Setting up the AI explanation (optional)

The app works without it: every run already gets a **verified explanation** rendered from the math layer's step log.
An LLM only adds friendlier wording, and its text is thrown away if any number or direction disagrees with that log.

## 1. Get a free Cloudflare Workers AI key (no card)
1. Sign in at dash.cloudflare.com → **Workers AI** → **Use REST API**.
2. **Create a Workers AI API Token** (a custom token with only *Workers AI – Read* and *Workers AI – Edit* is safest). Copy it once, into a password manager.
3. On the same page copy your **Account ID**.

## 2. Put three settings in Azure (server side only)
App Service → **Settings → Environment variables** (older portals: **Configuration → Application settings**):

```
LLM_BASE_URL = https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1
LLM_API_KEY  = <the token>
LLM_MODEL    = @cf/meta/llama-3.1-8b-instruct
```
Optional second provider, used automatically when the first runs out of quota (Groq example):
```
LLM_FALLBACK_BASE_URL = https://api.groq.com/openai/v1
LLM_FALLBACK_API_KEY  = <groq key>
LLM_FALLBACK_MODEL    = <a Groq model name>
```
`LLM_DAILY_REQUEST_BUDGET` (default 100) stops the app from using up a free daily allowance. Save and let the app restart.

## 3. Check it
```bash
cd backend
python tools/check_llm.py
```
It makes one call and prints the status, latency, tokens and reply. It never prints the key. `GET /health` also shows `llm_configured` (how many providers), never the values.

## Rules
* Never put the key in the frontend, in a `VITE_`/`REACT_APP_`-style variable, or in git. `.env` is git-ignored; `.env.example` lists the names only.
* The browser only talks to **your** backend (`POST /explain`); only the backend talks to the provider.
* Keys are redacted from every run record, server log line and error message (there is a test with a fake key).
* Switching provider = changing these values. No code change.
