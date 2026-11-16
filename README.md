# FixFlow

AI maintenance request triage for student housing (MIST 5400, Track 2: Product).
A tenant describes a problem in their own words, FixFlow asks up to 3 targeted follow-up questions,
and the property manager gets a complete, prioritized work order with the right trade to dispatch.

## What's in this folder

| File | What it does |
|---|---|
| `app.py` | The app: tenant portal, manager dashboard, "How it works" page |
| `fixflow_core.py` | The AI agent (Gemini + system prompt), safety guardrail, business rules, storage |
| `evaluate.py` | Runs 20 realistic scenarios through the real AI and scores it (for your evaluation slide) |
| `test_cases.json` | The 20 scenarios and their correct answers (edit or add your own) |
| `requirements.txt` | Python packages needed |
| `.streamlit/secrets.toml.example` | Template for your API key |

## Step 1: Get a free Gemini API key (5 min)

1. Go to **aistudio.google.com** and sign in with a Google account.
2. Click **Get API key**, then **Create API key**. Copy it.
3. Keep it private. Don't paste it into slides, group chats, or GitHub.

## Step 2: Run it on your laptop (10 min)

You need Python 3.10 or newer (python.org). Open a terminal in this folder, then:

```
pip install -r requirements.txt
```

Make a copy of `.streamlit/secrets.toml.example` named `.streamlit/secrets.toml`, and paste your key in:

```
GEMINI_API_KEY = "paste-your-key-here"
```

Then start the app:

```
streamlit run app.py
```

It opens in your browser. The sidebar should say **AI connected: Gemini (...)** in green.
If it says **Offline test mode** in red, the key isn't being found. Never demo in offline mode:
that mode uses keyword rules, not AI.

## Step 3: Put it online so anyone can try it (15 min)

This gives you a link to share with Professor Yu and to use in the live demo.

1. Create a free account at **github.com**. Click **New repository**, name it `fixflow`, make it Public, and create it.
2. Click **uploading an existing file** and drag in everything in this folder **except** `.streamlit/secrets.toml`.
   (The `.gitignore` file already excludes it if you use Git.)
3. Go to **share.streamlit.io**, sign in with GitHub, and click **Create app**.
4. Pick your `fixflow` repo, branch `main`, main file `app.py`.
5. Open **Advanced settings**, and in **Secrets** paste: `GEMINI_API_KEY = "your-key"`
6. Click **Deploy**. In a minute or two you'll have a link like `fixflow-yourname.streamlit.app`.

Note: free Streamlit apps go to sleep after a few days without visits. Open the link the morning of the demo
to wake it up. Submitted work orders reset when the app restarts; that's fine for a prototype.

## Step 4: Run the evaluation (for the 8-point evaluation section)

```
# Mac
export GEMINI_API_KEY="your-key"
# Windows (Command Prompt)
set GEMINI_API_KEY=your-key

python evaluate.py
```

It runs all 20 scenarios as full conversations (a second AI call plays the tenant using only the facts
in `test_cases.json`) and writes `eval_summary.md` (metrics table for your slide) and `eval_results.csv`
(every conversation). Takes about 5 to 10 minutes because of free-tier rate limits.
Use `python evaluate.py --limit 5` for a quick check.

Good story for the slides: run it, look at the misses, change something (the system prompt's urgency rules
in `fixflow_core.py`, or a safety keyword), run it again, and show before vs. after. The guide asks for
"what you found and what you changed." Then add a few results from classmates or roommates trying the live link.

Tip: `python evaluate.py --offline` runs the same scenarios with simple keyword rules instead of AI.
That's a useful baseline to compare against ("keyword rules got X% of emergencies, FixFlow got Y%").

## Suggested live demo (about 3 minutes of your 10)

1. **Tenant portal**, logged in as Jordan Lee. Type: `my sink is acting weird`.
   Answer the follow-ups naturally. Point to the "Behind the scenes" panel: real structured JSON from Gemini.
2. When it completes, read the business rules line: Plumbing → Plumber, Routine → 3 to 5 days.
3. **Start a new request.** Type: `I smell gas in the kitchen`. The safety alert appears instantly and it skips
   the questions and goes straight to Emergency.
4. **Manager dashboard.** Both new orders are at the top, the emergency in red, with the trade, window, and
   full transcript. Change one to Dispatched.
5. Optional stretch: attach a photo (the + in the chat box) of a sink or appliance.

Record a 60-second screen recording of this flow beforehand as a backup in case the Wi-Fi fails.

## How it works (for Q&A)

Every turn, the app sends the conversation to Gemini with our system prompt. Gemini must reply in a fixed
JSON format (structured output): either one more question, or a completed work order with category and
urgency. Then **our own code** applies the company's rules: category decides the trade, urgency decides the
dispatch window. A keyword safety guardrail runs before the AI and can force Emergency even if the AI misses it.

## Guardrails (for the ethics slide)

- Keyword safety override for gas, fire, sparking, CO alarms, flooding, and ceiling collapse
- Instant safety instructions (leave the unit, call 911) shown before the AI responds
- Hard cap of 3 follow-up questions so tenants don't get stuck
- Never promises arrival times or costs; no repair advice beyond basic safety steps
- Full transcript saved so a human can check the AI's reasoning
- Uses made-up tenants only. On the free Gemini tier, Google may use inputs to improve its products,
  so a real deployment would need the paid tier before handling real tenant data.

## Troubleshooting

- **"Couldn't reach the AI" / 429 error:** free-tier rate limit. Wait a minute and try again.
- **Model not found:** the app tries several current Gemini models automatically. To force one, add
  `GEMINI_MODEL = "model-name"` to your secrets (model names are listed in Google AI Studio).
- **Reset demo data** in the sidebar clears submitted orders and restores the 3 sample orders.
