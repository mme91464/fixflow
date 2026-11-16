"""
FixFlow core logic: the AI agent, safety guardrails, business rules, and storage.

How it works (the one-sentence version for Q&A):
Every turn, the app sends the conversation to Gemini, which either asks one more
question or, once it has everything, returns a filled-in work order (JSON).
Our own code then applies the business rules (who to dispatch and how fast).
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Demo company setup (fictional)
# ---------------------------------------------------------------------------

COMPANY = "Classic City Student Living"

TENANTS = {
    "Jordan Lee": {"property": "The Magnolia", "unit": "Bldg B, Unit 214"},
    "Ava Patel": {"property": "The Magnolia", "unit": "Bldg A, Unit 107"},
    "Marcus Hill": {"property": "Oak Street Flats", "unit": "Unit 3C"},
    "Sofia Ramirez": {"property": "Oak Street Flats", "unit": "Unit 5A"},
    "Ethan Brooks": {"property": "The Magnolia", "unit": "Bldg C, Unit 302"},
    "Chloe Nguyen": {"property": "Oak Street Flats", "unit": "Unit 2B"},
    "Tyler Washington": {"property": "The Magnolia", "unit": "Bldg A, Unit 115"},
    "Hannah Kim": {"property": "Oak Street Flats", "unit": "Unit 4D"},
}

# Models to try, in order. The first one that works on your API key is used.
# You can override with GEMINI_MODEL in .streamlit/secrets.toml.
DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]

MAX_QUESTIONS = 3
DATA_FILE = Path(__file__).parent / "work_orders.json"


# ---------------------------------------------------------------------------
# Structured output schema (what Gemini must return every turn)
# ---------------------------------------------------------------------------

class Category(str, Enum):
    PLUMBING = "Plumbing"
    ELECTRICAL = "Electrical"
    HVAC = "Heating & Cooling"
    APPLIANCE = "Appliance"
    PEST = "Pest Control"
    LOCKS = "Doors, Locks & Windows"
    GENERAL = "General Repair"


class Urgency(str, Enum):
    EMERGENCY = "Emergency"
    URGENT = "Urgent"
    ROUTINE = "Routine"


class Status(str, Enum):
    ASK = "ask"
    COMPLETE = "complete"


class WorkOrderDraft(BaseModel):
    category: Category = Field(description="Best category for the issue.")
    urgency: Urgency = Field(description="Emergency, Urgent, or Routine, using the urgency rules.")
    urgency_reason: str = Field(description="One short sentence explaining the urgency choice.")
    location_in_unit: str = Field(description="Room or area, e.g. 'kitchen'. 'Unknown' if not known yet.")
    item_or_appliance: str = Field(description="The fixture or appliance involved, e.g. 'kitchen sink drain'.")
    issue_summary: str = Field(description="One clear sentence a technician could act on.")
    tenant_reported_details: list[str] = Field(description="Short factual bullet points the tenant reported.")
    access_notes: str = Field(description="Pets, permission to enter, or best times. 'None given' if not discussed.")


class AgentTurn(BaseModel):
    status: Status = Field(description="'ask' to ask one more question, 'complete' when the work order is ready.")
    message_to_tenant: str = Field(description="What to say to the tenant this turn. Friendly, short, plain language.")
    safety_concern: bool = Field(description="True if there is any risk to people or major property damage.")
    work_order: WorkOrderDraft = Field(description="Your best current draft of the work order.")


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""You are FixFlow, the maintenance request assistant for {COMPANY}, a student housing
property management company. Tenants are college students who often describe problems vaguely
("my sink is acting weird"). Your job is to turn their message into a complete, accurate work order
so the property manager can dispatch the right technician the first time, without calling the tenant back.

RULES
1. Safety first. If anything suggests gas smell, smoke, fire, sparking or burning smell from outlets,
   carbon monoxide alarm, active flooding or water near electrical, or a ceiling sagging/collapsing:
   set safety_concern = true, urgency = Emergency, and status = complete immediately. Tell the tenant
   the specific safety step (for gas or fire: leave the unit now and call 911 from outside; for active
   flooding: shut off the water valve under the fixture if it is safe to do so). Do not ask more questions.
2. Ask ONE question at a time. Each question must be specific and easy for a non-expert to answer
   (offer examples or choices, e.g. "Is the water draining slowly, or not at all?").
3. Only ask what a technician actually needs: which room, which fixture or appliance, what exactly is
   happening, how long, and anything that changes urgency. Never ask for info you already have.
4. You may ask at most {MAX_QUESTIONS} follow-up questions in total. The number already asked is given
   below. When it reaches {MAX_QUESTIONS}, you MUST return status = complete with your best judgment.
5. Return status = complete as soon as you know the room, the item, and what is wrong, AND you can
   point to a specific trade. Do not complete with General Repair or a vague item like "odor" or
   "noise" while you still have questions left: use them to narrow down the source first
   (where is it strongest, near a drain/vent/wall/appliance, what does it look/sound/smell like, how long).
   Only use General Repair if, after asking, it truly doesn't fit another category.
   When complete, message_to_tenant should confirm what you understood in one or two sentences and
   say it has been sent to their property manager. Do not ask a new question or give instructions
   about future requests.
6. Never promise a specific arrival time or cost. Never give repair instructions beyond basic safety steps.
7. If the message is not a maintenance issue, politely say you only handle maintenance requests and
   keep status = ask.

URGENCY RULES
- Emergency: risk to people or major ongoing property damage (see rule 1), no heat when it is freezing,
  sewage backup, no water at all in the unit, tenant cannot secure the unit (exterior door won't lock).
- Urgent: a core function is broken but nobody is in danger. Examples: refrigerator not cooling,
  only toilet not working, no A/C in hot weather, no hot water, leak that is contained, oven not working,
  locked out of unit.
- Routine: inconvenient but livable. Examples: slow drain, dripping faucet, broken blind, loose cabinet,
  one light out, dishwasher not draining, minor pest sighting.

CATEGORIES: Plumbing, Electrical, Heating & Cooling, Appliance, Pest Control, Doors, Locks & Windows, General Repair.
Dishwashers, refrigerators, ovens, washers and dryers are Appliance even if water is involved.

SMELLS (common and often vague, so narrow them down):
- Rotten eggs / sulfur: possible gas leak → Emergency (rule 1).
- Burning, hot plastic, electrical: Electrical, Emergency if ongoing.
- Sewage or sewer smell, especially near drains or the toilet: Plumbing (dry drain trap or sewer line), Urgent.
- Dead animal / rotting / decay smell, often strongest near one wall, vent or cabinet: Pest Control
  (likely a dead rodent), Urgent.
- Musty / damp: possible hidden leak or mold, General Repair or Plumbing if a water source is found.
- Spoiled food smell near the fridge: Appliance.
"""


# ---------------------------------------------------------------------------
# Business rules (decision logic). This is OUR code, not the AI.
# ---------------------------------------------------------------------------

TRADE_BY_CATEGORY = {
    Category.PLUMBING: "Plumber",
    Category.ELECTRICAL: "Electrician",
    Category.HVAC: "HVAC technician",
    Category.APPLIANCE: "Appliance technician",
    Category.PEST: "Pest control vendor",
    Category.LOCKS: "Locksmith / handyman",
    Category.GENERAL: "Maintenance handyman",
}

DISPATCH_BY_URGENCY = {
    Urgency.EMERGENCY: {"window": "Within 2 hours", "action": "Page on-call tech now and call the tenant"},
    Urgency.URGENT: {"window": "Within 24 hours", "action": "Schedule next available slot"},
    Urgency.ROUTINE: {"window": "Within 3 to 5 business days", "action": "Add to weekly route"},
}

# Hard-coded safety guardrail. Even if the AI misses it, these phrases force Emergency.
SAFETY_PATTERNS = {
    "gas": r"\b(smell(s|ing)? (like )?gas|gas (smell|leak)|rotten eggs?)\b",
    "fire": r"\b(fire(?! (alarm|drill|extinguisher))|flames?|smoke(?! (detector|alarm))|smoking|burning smell|smells? (like )?burning)\b",
    "electrical": r"\b(spark(s|ed|ing|y)?|outlet.{0,30}(hot|melt|burn|smok)|burn(t|ed)? mark|scorch|exposed wires?|electrical shock|got shocked)\b",
    "carbon monoxide": r"\b(carbon monoxide|co alarm|co detector)\b",
    "flooding": r"\b(flood(ing|ed)?|water (is )?(everywhere|all over)|burst(ed)? pipe|pipe (burst|broke)|gushing|spraying|water (is )?pouring|overflowing|won'?t stop (leaking|spraying))\b",
    "ceiling": r"\b(ceiling.{0,25}(collaps|sag|cav|fall)|caving in)\b",
}

SAFETY_MESSAGES = {
    "gas": "If you smell gas: leave the unit now, don't flip any switches, and call 911 from outside.",
    "fire": "If there is fire or smoke: get out now and call 911.",
    "electrical": "Stay away from the outlet or wires and don't touch anything. If you can safely reach the breaker panel, switch that circuit off.",
    "carbon monoxide": "If a CO alarm is going off: get everyone outside to fresh air now and call 911.",
    "flooding": "If it is safe, turn off the water valve under the fixture (or the main shutoff) and keep water away from outlets.",
    "ceiling": "Move away from the area under the ceiling and keep others out of the room.",
}


SAFETY_TRADE = {
    "gas": "Gas utility emergency line + plumber",
    "carbon monoxide": "Fire dept (911), then HVAC technician",
    "fire": "Fire dept (911), then maintenance supervisor",
    "electrical": "Electrician (emergency call)",
}


def check_safety(text: str) -> list[str]:
    """Return the list of safety issues found by keyword (the guardrail)."""
    t = text.lower()
    return [name for name, pat in SAFETY_PATTERNS.items() if re.search(pat, t)]


def apply_business_rules(draft: WorkOrderDraft, safety_hits: list[str]) -> dict:
    """Turn the AI's draft into a dispatch decision using fixed company rules."""
    urgency = draft.urgency
    overridden = False
    if safety_hits and urgency != Urgency.EMERGENCY:
        urgency = Urgency.EMERGENCY
        overridden = True
    dispatch = DISPATCH_BY_URGENCY[urgency]
    trade = TRADE_BY_CATEGORY[draft.category]
    for hit in safety_hits:  # some hazards need a specific responder regardless of category
        if hit in SAFETY_TRADE:
            trade = SAFETY_TRADE[hit]
            break
    return {
        "category": draft.category.value,
        "urgency": urgency.value,
        "urgency_reason": draft.urgency_reason
        + (f" [Guardrail override: keyword match for {', '.join(safety_hits)}]" if overridden else ""),
        "trade": trade,
        "dispatch_window": dispatch["window"],
        "next_action": dispatch["action"],
        "location_in_unit": draft.location_in_unit,
        "item_or_appliance": draft.item_or_appliance,
        "issue_summary": draft.issue_summary,
        "tenant_reported_details": draft.tenant_reported_details,
        "access_notes": draft.access_notes,
        "guardrail_override": overridden,
        "safety_flags": safety_hits,
    }


# ---------------------------------------------------------------------------
# The agent: real Gemini version
# ---------------------------------------------------------------------------

class GeminiAgent:
    def __init__(self, api_key: str, model: str | None = None):
        from google import genai  # imported here so offline mode works without the package
        from google.genai import types

        # Give up on any single request after 45 seconds, and retry an overloaded model only briefly
        # (the SDK's default retries can stall for minutes), so we switch to a backup model fast.
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=45_000,
            retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1, max_delay=4),
        ))
        self.models = [model] + [m for m in DEFAULT_MODELS if m != model] if model else list(DEFAULT_MODELS)
        self.active_model: str | None = None
        self.label = "Gemini"

    def _contents(self, history: list[dict]):
        from google.genai import types

        contents = []
        for msg in history:
            role = "user" if msg["role"] == "tenant" else "model"
            parts = [types.Part.from_text(text=msg["text"] or "(photo attached)")]
            for img in msg.get("images", []):
                parts.append(types.Part.from_bytes(data=img["data"], mime_type=img["mime"]))
            contents.append(types.Content(role=role, parts=parts))
        return contents

    def next_turn(self, history: list[dict], questions_asked: int) -> AgentTurn:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT
            + f"\nFollow-up questions already asked in this conversation: {questions_asked} of {MAX_QUESTIONS}.",
            response_mime_type="application/json",
            response_schema=AgentTurn,
            temperature=0.2,
        )
        contents = self._contents(history)
        # Start with the model that worked last; if Google says it's overloaded, fall back to the others.
        candidates = [self.active_model] + [m for m in self.models if m != self.active_model] \
            if self.active_model else self.models
        last_err: Exception | None = None
        for model in candidates:
            for attempt in range(2):
                try:
                    resp = self.client.models.generate_content(model=model, contents=contents, config=config)
                    self.active_model = model
                    self.label = f"Gemini ({model})"
                    if isinstance(resp.parsed, AgentTurn):
                        return resp.parsed
                    return AgentTurn.model_validate_json(resp.text)
                except errors.ClientError as e:
                    last_err = e
                    if e.code == 429:  # free-tier rate limit: wait and retry
                        time.sleep(5 * (attempt + 1))
                        continue
                    if e.code in (400, 404) and "model" in str(e).lower():
                        break  # model not available on this key, try the next one
                    raise
                except errors.ServerError as e:
                    last_err = e
                    time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Could not reach Gemini: {last_err}")


# ---------------------------------------------------------------------------
# Offline test mode (NOT AI). Only for testing the screens without an API key.
# ---------------------------------------------------------------------------

class OfflineAgent:
    """Simple keyword rules so the interface can be tested without a key. Never demo this."""

    label = "OFFLINE TEST MODE (keyword rules, not AI)"

    KEYWORDS = [
        (Category.APPLIANCE, ["fridge", "refrigerator", "oven", "stove", "dishwasher", "washer", "dryer", "microwave"]),
        (Category.PLUMBING, ["sink", "toilet", "drain", "leak", "faucet", "shower", "pipe", "water"]),
        (Category.ELECTRICAL, ["outlet", "light", "power", "breaker", "switch", "spark"]),
        (Category.HVAC, ["heat", "a/c", "ac ", "air condition", "thermostat", "hvac", "furnace"]),
        (Category.PEST, ["roach", "bug", "mice", "mouse", "ants", "pest", "rat"]),
        (Category.LOCKS, ["lock", "door", "window", "key"]),
    ]
    QUESTIONS = [
        "Which room is this in?",
        "What exactly is happening? For example, is it not working at all, leaking, or making a noise?",
        "How long has this been going on?",
    ]

    def next_turn(self, history: list[dict], questions_asked: int) -> AgentTurn:
        text = " ".join(m["text"].lower() for m in history if m["role"] == "tenant")
        cat = next((c for c, words in self.KEYWORDS if any(w in text for w in words)), Category.GENERAL)
        hits = check_safety(text)
        done = bool(hits) or questions_asked >= 2
        urgency = Urgency.EMERGENCY if hits else Urgency.ROUTINE
        draft = WorkOrderDraft(
            category=cat,
            urgency=urgency,
            urgency_reason="Offline test rule.",
            location_in_unit="See details",
            item_or_appliance=cat.value,
            issue_summary=history[0]["text"][:120],
            tenant_reported_details=[m["text"] for m in history if m["role"] == "tenant"],
            access_notes="None given",
        )
        msg = "Thanks, I've got what I need and sent this to your property manager." if done else self.QUESTIONS[questions_asked]
        return AgentTurn(status=Status.COMPLETE if done else Status.ASK, message_to_tenant=msg,
                         safety_concern=bool(hits), work_order=draft)


def shrink_image(data: bytes, max_side: int = 1024) -> tuple[bytes, str]:
    """Phone photos are often 3 to 12 MB. Resize to max 1024px JPEG (usually under 200 KB) so the AI
    responds in seconds. A technician-level diagnosis doesn't need more detail than that."""
    try:
        import io

        from PIL import Image, ImageOps

        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))  # keep phone photos upright
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return data, "image/jpeg"


def make_agent(api_key: str | None, model: str | None = None):
    if api_key:
        return GeminiAgent(api_key, model)
    return OfflineAgent()


# ---------------------------------------------------------------------------
# Storage (a simple JSON file so the manager view sees tenant submissions)
# ---------------------------------------------------------------------------

def _seed_orders() -> list[dict]:
    from sample_orders import SAMPLES

    now = datetime.now()
    samples = sorted(SAMPLES, key=lambda s: -s["hours_ago"])  # oldest first, so IDs go up over time
    orders = []
    for i, s in enumerate(samples):
        draft = WorkOrderDraft(
            category=Category(s["category"]), urgency=Urgency(s["urgency"]),
            urgency_reason=s["urgency_reason"], location_in_unit=s["location"],
            item_or_appliance=s["item"], issue_summary=s["summary"],
            tenant_reported_details=s["details"], access_notes=s["access"],
        )
        wo = apply_business_rules(draft, s["safety"])
        transcript = [{"role": r, "text": t} for r, t in s["transcript"]]
        wo.update({
            "id": f"WO-{1001 + i}",
            "created": (now - timedelta(hours=s["hours_ago"])).strftime("%Y-%m-%d %H:%M"),
            "tenant": s["tenant"], **TENANTS[s["tenant"]],
            "status": s["status"],
            "questions_asked": max(sum(m["role"] == "assistant" for m in transcript) - 1, 0),
            "chat_seconds": s["seconds"],
            "transcript": transcript,
            "model": "Sample data",
            "sample": True,
        })
        orders.append(wo)
    return orders


def load_orders() -> list[dict]:
    if not DATA_FILE.exists():
        save_orders(_seed_orders())
    try:
        return json.loads(DATA_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def save_orders(orders: list[dict]) -> None:
    DATA_FILE.write_text(json.dumps(orders, indent=2))


def add_order(wo: dict) -> dict:
    orders = load_orders()
    next_num = max([int(o["id"].split("-")[1]) for o in orders] + [1000]) + 1
    wo["id"] = f"WO-{next_num}"
    wo["created"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    wo.setdefault("status", "New")
    orders.append(wo)
    save_orders(orders)
    return wo


def update_status(order_id: str, status: str) -> None:
    orders = load_orders()
    for o in orders:
        if o["id"] == order_id:
            o["status"] = status
    save_orders(orders)


ALL_TRADES = list(dict.fromkeys(list(TRADE_BY_CATEGORY.values()) + list(SAFETY_TRADE.values())))


def override_order(order_id: str, urgency: str | None = None, trade: str | None = None) -> None:
    """A manager changes the AI's call. The change and the AI's original call are both kept,
    so the override rate can be monitored (a key pilot metric)."""
    orders = load_orders()
    for o in orders:
        if o["id"] != order_id:
            continue
        o.setdefault("ai_original", {"urgency": o["urgency"], "trade": o["trade"]})
        log = o.setdefault("override_log", [])
        if urgency and urgency != o["urgency"]:
            log.append(f"Urgency {o['urgency']} → {urgency}")
            o["urgency"] = urgency
            d = DISPATCH_BY_URGENCY[Urgency(urgency)]
            o["dispatch_window"], o["next_action"] = d["window"], d["action"]
        if trade and trade != o["trade"]:
            log.append(f"Trade {o['trade']} → {trade}")
            o["trade"] = trade
        o["overridden"] = (o["urgency"] != o["ai_original"]["urgency"]
                           or o["trade"] != o["ai_original"]["trade"])
    save_orders(orders)


def reset_orders() -> None:
    save_orders(_seed_orders())


def get_secret(name: str) -> str | None:
    """Read from Streamlit secrets if available, else environment variables."""
    try:
        import streamlit as st

        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)
