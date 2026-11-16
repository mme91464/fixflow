"""
FixFlow: AI maintenance request triage for student housing.
Run locally with:  streamlit run app.py
"""

import html
import time
from datetime import datetime

import streamlit as st

from fixflow_core import (
    COMPANY,
    MAX_QUESTIONS,
    SAFETY_MESSAGES,
    TENANTS,
    OfflineAgent,
    Status,
    add_order,
    apply_business_rules,
    check_safety,
    get_secret,
    ALL_TRADES,
    load_orders,
    make_agent,
    override_order,
    reset_orders,
    shrink_image,
    update_status,
)

st.set_page_config(page_title="FixFlow", page_icon="🔧", layout="wide")

URGENCY_ORDER = {"Emergency": 0, "Urgent": 1, "Routine": 2}
URGENCY_HINT = {
    "Emergency": "Respond within 2 hours",
    "Urgent": "Respond within 24 hours",
    "Routine": "Respond within 3 to 5 business days",
}
STATUSES = ["New", "Dispatched", "Completed"]
esc = html.escape


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@500;600;700&display=swap');

:root {
  --bg: #121418; --surface: #1B1F26; --raised: #232833; --line: #2E3440;
  --ink: #E8EBF0; --muted: #A6ADBB; --faint: #7E8696;
  --pine: #4C8DF6; --mint: #7DB0FF; --pine-tint: #1A2740;
  --emergency: #F0634A; --emergency-solid: #C23A22; --emergency-tint: #3A1D18;
  --urgent: #E8AD3A; --urgent-tint: #3A2E14;
  --routine: #2EC4B6; --routine-tint: #13302E;
}
/* Pin the look even if the theme file is missing */
.stApp { background: var(--bg); color: var(--ink); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: #0E1013; border-right: 1px solid #1F232B; }
[data-testid="stSidebar"] * { color: #D7DBE3; }
.block-container { padding-top: 2.2rem; max-width: 1280px; }
.stApp p, .stApp li, .stApp label { color: inherit; }
[data-testid="stCaptionContainer"], .stApp small { color: var(--muted) !important; }

/* Page header */
.ff-head { display: flex; justify-content: space-between; align-items: flex-end;
  border-bottom: 1px solid var(--line); padding-bottom: .8rem; margin-bottom: 1.4rem; }
.ff-head h1 { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 2.7rem;
  line-height: 1; margin: 0; padding: 0; color: var(--ink); letter-spacing: -0.01em; }
.ff-head .sub { color: var(--muted); font-size: 1rem; margin-top: .4rem; }
.ff-head .right { text-align: right; color: var(--muted); font-size: .9rem; line-height: 1.35; }
.ff-head .right strong { color: var(--ink); font-weight: 600; }

/* Dispatch board (summary strip) */
.board { display: grid; grid-template-columns: 1.25fr 1fr 1fr 1fr 1fr; background: var(--surface);
  border: 1px solid var(--line); border-radius: 8px; overflow: hidden; margin-bottom: 1.4rem; }
.board .cell { padding: 1rem 1.25rem 1.05rem; border-left: 1px solid var(--line); }
.board .cell:first-child { border-left: none; }
.board .label { font-size: .9rem; font-weight: 600; color: var(--muted); display: flex; align-items: center; gap: .45rem; }
.board .num { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 3.4rem;
  line-height: 1; margin-top: .35rem; color: var(--ink); font-variant-numeric: tabular-nums; }
.board .num small { font-size: 1.3rem; font-weight: 600; color: var(--muted); margin-left: .2rem; }
.board .note { font-size: .82rem; color: var(--faint); margin-top: .3rem; }
.board .cell.hot { background: var(--emergency-solid); }
.board .cell.hot .label, .board .cell.hot .num, .board .cell.hot .note { color: #FFF6F3; }
.board .cell.ops { background: #171A20; }
.board .cell.ops .num { font-size: 2.4rem; margin-top: .75rem; }
.dot { width: .62rem; height: .62rem; border-radius: 50%; display: inline-block; flex: none; }
.dot.e { background: var(--emergency); } .dot.u { background: var(--urgent); } .dot.r { background: var(--routine); }
.cell.hot .dot.e { background: #FFF6F3; }

/* Urgency group headers */
.group { display: flex; align-items: baseline; gap: .6rem; margin: 1.6rem 0 .6rem;
  border-bottom: 1px solid var(--line); padding-bottom: .35rem; }
.group h3 { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 1.45rem; margin: 0; padding: 0; color: var(--ink); }
.group .count { color: var(--muted); font-size: .95rem; }
.group .hint { margin-left: auto; color: var(--faint); font-size: .88rem; }

/* Work-order tickets */
[class*="st-key-wo-"] { background: var(--surface); border-radius: 8px; border-color: var(--line) !important; }
[class*="st-key-wo-emergency"] { border-left: 6px solid var(--emergency) !important; }
[class*="st-key-wo-urgent"] { border-left: 6px solid var(--urgent) !important; }
[class*="st-key-wo-routine"] { border-left: 6px solid var(--routine) !important; }
.t-top { display: flex; align-items: center; gap: .7rem; flex-wrap: wrap; }
.t-id { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 1.15rem; color: var(--ink); }
.t-cat { font-weight: 600; color: var(--muted); }
.t-time { color: var(--faint); font-size: .88rem; }
.t-new { font-size: .8rem; font-weight: 600; color: var(--mint); background: var(--pine-tint);
  padding: .08rem .5rem; border-radius: 999px; }
.t-chg { font-size: .8rem; font-weight: 600; color: var(--urgent); background: var(--urgent-tint);
  padding: .08rem .5rem; border-radius: 999px; }
.t-summary { font-size: 1.08rem; font-weight: 600; color: var(--ink); margin: .45rem 0 .7rem; line-height: 1.35; }
.t-grid { display: grid; grid-template-columns: 1.1fr 1fr 1.2fr; gap: 1.2rem; }
.f-label { font-size: .78rem; color: var(--faint); font-weight: 500; }
.f-val { font-size: .95rem; color: var(--ink); line-height: 1.35; margin-bottom: .45rem; }
.f-val.strong { font-weight: 600; color: var(--mint); }

/* Urgency pills (always text + dot, never color alone) */
.pill { display: inline-flex; align-items: center; gap: .4rem; font-weight: 600; font-size: .85rem;
  padding: .15rem .6rem; border-radius: 999px; }
.pill.e { background: var(--emergency-tint); color: var(--emergency); }
.pill.u { background: var(--urgent-tint); color: var(--urgent); }
.pill.r { background: var(--routine-tint); color: var(--routine); }

/* Emergency banner */
.sos { display: flex; align-items: center; gap: .9rem; background: var(--emergency-tint); border: 1px solid #5A2A21;
  border-left: 6px solid var(--emergency); border-radius: 8px; padding: .7rem 1rem; margin: -0.4rem 0 1.2rem; }
.sos .sos-t { font-weight: 700; color: var(--emergency); white-space: nowrap; }
.sos .sos-b { color: var(--ink); font-size: .95rem; }
.sos .sos-b b { white-space: nowrap; color: #FFFFFF; }

/* Resident portal */
.res-card { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: .8rem 1rem; }
.res-card .name { font-weight: 600; font-size: 1.05rem; color: var(--ink); }
.res-card .addr { color: var(--muted); font-size: .92rem; }
.st-key-chatpanel { background: var(--surface); border-radius: 8px; border-color: var(--line) !important; }
.st-key-sysview { background: #171B22; border-radius: 8px; border-color: var(--line) !important; }
.sys-title { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 1.35rem; margin: 0; color: var(--ink); }
.sys-sub { color: var(--muted); font-size: .9rem; margin: .15rem 0 .8rem; }
.qsteps { display: flex; gap: .35rem; margin: .2rem 0 .3rem; }
.qsteps span { flex: 1; height: 6px; border-radius: 3px; background: var(--line); }
.qsteps span.on { background: var(--mint); }
.qlabel { font-size: .85rem; color: var(--muted); margin-bottom: .8rem; }
.rule-line { font-size: .95rem; margin: .25rem 0; color: var(--ink); }
.try { color: var(--muted); font-size: .9rem; margin: .4rem 0 .3rem; }
.st-key-ex_pick button { background: var(--raised) !important; border: 1px solid var(--line) !important;
  color: var(--ink) !important; }
.st-key-ex_pick button:hover { border-color: var(--mint) !important; color: var(--mint) !important; }

/* My requests */
.req { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 1rem 1.2rem; margin-bottom: .8rem; }
.req .top { display: flex; align-items: center; gap: .7rem; flex-wrap: wrap; }
.req .sum { font-weight: 600; font-size: 1.05rem; margin: .5rem 0 .8rem; color: var(--ink); }
.track { display: grid; grid-template-columns: repeat(3, 1fr); gap: .35rem; }
.track .seg { height: 6px; border-radius: 3px; background: var(--line); }
.track .seg.on { background: var(--mint); }
.track .lab { font-size: .82rem; color: var(--faint); margin-top: .3rem; }
.track .lab.on { color: var(--ink); font-weight: 600; }
.req .meta { display: flex; gap: 2rem; margin-top: .8rem; flex-wrap: wrap; }
.empty { background: var(--surface); border: 1px dashed var(--line); border-radius: 8px; padding: 1.4rem; color: var(--muted); }

/* Work-order receipt */
.receipt { background: var(--raised); border: 1px solid var(--line); border-top: 3px dashed var(--mint);
  border-radius: 0 0 8px 8px; padding: 1rem 1.2rem; margin-top: .6rem; }
.receipt .top { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
.receipt .wo { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 1.9rem; line-height: 1; color: var(--ink); }
.receipt .msg { color: var(--muted); margin: .2rem 0 .8rem; }
.receipt .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }

/* How it works */
.flow { display: grid; grid-template-columns: repeat(5, 1fr); gap: .8rem; margin: .4rem 0 1.6rem; }
.step { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 1rem; }
.step .n { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 2rem; color: var(--mint); line-height: 1; }
.step h4 { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 1.2rem; margin: .4rem 0 .3rem; padding: 0; color: var(--ink); }
.step p { font-size: .92rem; color: var(--muted); margin: 0 0 .7rem; line-height: 1.4; }
.tag { font-size: .78rem; font-weight: 600; padding: .1rem .5rem; border-radius: 999px; }
.tag.ai { background: #2B2440; color: #C7B5F0; } .tag.code { background: var(--pine-tint); color: var(--mint); }
.tag.you { background: var(--raised); color: var(--muted); }
.rules { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--line); }
.rules th { text-align: left; font-size: .85rem; color: var(--muted); font-weight: 600; padding: .6rem .9rem;
  border-bottom: 1px solid var(--line); background: #171A20; }
.rules td { padding: .65rem .9rem; border-bottom: 1px solid var(--line); font-size: .95rem; vertical-align: top; color: var(--ink); }
.h2 { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 1.5rem; margin: 1.6rem 0 .6rem; color: var(--ink); }
.guard { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem 2rem; }
.guard div { padding-left: 1rem; border-left: 3px solid var(--mint); font-size: .95rem; line-height: 1.4; color: var(--ink); }

/* Sidebar */
.brand { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 2.1rem; line-height: 1;
  color: #F3F5F8 !important; letter-spacing: -0.01em; }
.brand-sub { color: #8E97A8 !important; font-size: .9rem; margin: .25rem 0 1.2rem; }
.conn { display: flex; align-items: center; gap: .5rem; font-size: .88rem; color: #C3CAD6 !important; }
.conn .dot { background: var(--mint); box-shadow: 0 0 0 3px rgba(125,176,255,.18); }

@media (max-width: 900px) {
  .board, .flow, .t-grid, .receipt .grid, .guard { grid-template-columns: 1fr; }
  .board .cell { border-left: none; border-top: 1px solid var(--line); }
}
</style>
""", unsafe_allow_html=True)


def pill(urgency: str) -> str:
    k = urgency[0].lower()
    return f"<span class='pill {k}'><span class='dot {k}'></span>{esc(urgency)}</span>"


def page_header(title: str, sub: str, right: str = "") -> None:
    st.markdown(
        f"<div class='ff-head'><div><h1>{esc(title)}</h1><div class='sub'>{sub}</div></div>"
        f"<div class='right'>{right}</div></div>",
        unsafe_allow_html=True,
    )


def field(label: str, value: str, strong: bool = False) -> str:
    return (f"<div class='f-label'>{esc(label)}</div>"
            f"<div class='f-val{' strong' if strong else ''}'>{esc(str(value))}</div>")


def fmt_time(stamp: str) -> str:
    try:
        d = datetime.strptime(stamp, "%Y-%m-%d %H:%M")
    except ValueError:
        return stamp
    today = datetime.now().date()
    if d.date() == today:
        day = "Today"
    elif (today - d.date()).days == 1:
        day = "Yesterday"
    else:
        day = d.strftime("%a %b %-d")
    return f"{day}, {d.strftime('%-I:%M %p')}"


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

@st.cache_resource
def get_agent(api_key, model):
    return make_agent(api_key, model)


agent = get_agent(get_secret("GEMINI_API_KEY"), get_secret("GEMINI_MODEL"))
offline = isinstance(agent, OfflineAgent)


def new_conversation():
    st.session_state.history = []          # messages sent to / from the AI
    st.session_state.display = []          # what the resident sees (includes safety alerts)
    st.session_state.questions_asked = 0
    st.session_state.done = False
    st.session_state.last_turn = None
    st.session_state.submitted = None
    st.session_state.start_time = None
    st.session_state.safety_shown = set()


if "history" not in st.session_state:
    new_conversation()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(f"<div class='brand'>FixFlow</div><div class='brand-sub'>{esc(COMPANY)}</div>",
                unsafe_allow_html=True)
    view = st.radio("Go to", ["Resident portal", "Manager dashboard", "How it works"],
                    label_visibility="collapsed")
    st.divider()
    if offline:
        st.error("**Offline test mode.** No Gemini API key found, so keyword rules are standing in for the AI. "
                 "Add your key before demoing (see README).")
    else:
        st.markdown(f"<div class='conn'><span class='dot'></span>Connected to {esc(agent.label)}</div>",
                    unsafe_allow_html=True)
    show_ai = st.toggle("Show system view", value=True,
                        help="Shows the structured data the AI returns each turn, next to the chat.")
    st.divider()
    if st.button("Reset demo data", use_container_width=True,
                 help="Clears submitted requests and restores the sample work orders."):
        reset_orders()
        new_conversation()
        st.rerun()


# ---------------------------------------------------------------------------
# Resident portal
# ---------------------------------------------------------------------------

def render_message(msg):
    if msg["role"] == "safety":
        with st.chat_message("assistant", avatar=":material/warning:"):
            st.error(msg["text"])
        return
    is_user = msg["role"] == "tenant"
    with st.chat_message("user" if is_user else "assistant",
                         avatar=":material/person:" if is_user else ":material/build:"):
        if msg["text"]:
            st.markdown(msg["text"])
        for img in msg.get("images", []):
            st.image(img["data"], width=240)


def handle_tenant_message(text, files, tenant_name):
    images = []
    for f in files or []:
        data, mime = shrink_image(f.getvalue())  # big phone photos made the AI slow
        images.append({"data": data, "mime": mime})
    if not text and not images:
        return
    if st.session_state.start_time is None:
        st.session_state.start_time = time.time()

    msg = {"role": "tenant", "text": text or "", "images": images}
    st.session_state.history.append(msg)
    st.session_state.display.append(msg)

    # Guardrail 1: keyword safety check runs before the AI, so the resident sees the safety step instantly.
    all_text = " ".join(m["text"] for m in st.session_state.history if m["role"] == "tenant")
    hits = check_safety(all_text)
    for h in hits:
        if h not in st.session_state.safety_shown:
            st.session_state.safety_shown.add(h)
            st.session_state.display.append({"role": "safety", "text": "**Safety first:** " + SAFETY_MESSAGES[h]})

    try:
        turn = agent.next_turn(st.session_state.history, st.session_state.questions_asked)
    except Exception as e:  # show the error and let the resident resend
        st.session_state.history.pop()
        st.session_state.display = [m for m in st.session_state.display if m is not msg]
        st.session_state.error = f"FixFlow couldn't reach the AI, so your message wasn't sent. Send it again. ({e})"
        return

    st.session_state.last_turn = turn
    must_finish = st.session_state.questions_asked >= MAX_QUESTIONS
    finished = turn.status == Status.COMPLETE or must_finish or bool(hits)

    reply = turn.message_to_tenant
    if finished and turn.status != Status.COMPLETE:
        reply = "Thanks, that's everything I need. I've sent this to your property manager."
    elif not finished:
        st.session_state.questions_asked += 1

    bot_msg = {"role": "assistant", "text": reply}
    st.session_state.history.append(bot_msg)
    st.session_state.display.append(bot_msg)

    if finished:
        wo = apply_business_rules(turn.work_order, hits)
        wo.update({
            "tenant": tenant_name,
            **TENANTS[tenant_name],
            "questions_asked": st.session_state.questions_asked,
            "chat_seconds": int(time.time() - st.session_state.start_time),
            "transcript": [{"role": m["role"], "text": m["text"]} for m in st.session_state.display],
            "photo_attached": any(m.get("images") for m in st.session_state.history),
            "model": agent.label,
        })
        st.session_state.submitted = add_order(wo)
        st.session_state.done = True


def receipt(wo: dict) -> str:
    return f"""
<div class='receipt'>
  <div class='top'><div class='wo'>{esc(wo['id'])}</div>{pill(wo['urgency'])}</div>
  <div class='msg'>Your request was sent to {esc(COMPANY)}. You don't need to call the office.</div>
  <div class='grid'>
    <div>{field('Issue', wo['item_or_appliance'], True)}</div>
    <div>{field('Category', wo['category'])}</div>
    <div>{field('Expected response', wo['dispatch_window'])}</div>
  </div>
</div>"""


EXAMPLES = ["my sink is acting weird", "I smell gas", "something smells weird"]
EMERGENCY_LINE = "(706) 555-0142"   # fictional number for the demo
TRACK = [("New", "Received"), ("Dispatched", "Technician assigned"), ("Completed", "Completed")]


def emergency_banner():
    st.markdown(
        "<div class='sos'><span class='sos-t'>Emergency?</span><span class='sos-b'>For gas smell, fire, smoke or "
        f"active flooding, leave the unit and call <b>911</b>, then the 24/7 maintenance line at <b>{EMERGENCY_LINE}</b>. "
        "Don't wait for a reply here.</span></div>",
        unsafe_allow_html=True,
    )


def my_requests(tenant_name: str):
    mine = sorted((o for o in load_orders() if o["tenant"] == tenant_name),
                  key=lambda o: o["created"], reverse=True)
    if not mine:
        st.markdown("<div class='empty'>No requests yet. Report an issue and it will show up here, "
                    "with its status as your property manager works on it.</div>", unsafe_allow_html=True)
        return
    for o in mine:
        step = [s for s, _ in TRACK].index(o["status"])
        segs = "".join(f"<div><div class='seg{' on' if i <= step else ''}'></div>"
                       f"<div class='lab{' on' if i == step else ''}'>{lab}</div></div>"
                       for i, (_, lab) in enumerate(TRACK))
        st.markdown(
            f"<div class='req'><div class='top'>{pill(o['urgency'])}<span class='t-id'>{esc(o['id'])}</span>"
            f"<span class='t-time'>Filed {esc(fmt_time(o['created']))}</span></div>"
            f"<div class='sum'>{esc(o['issue_summary'])}</div>"
            f"<div class='track'>{segs}</div>"
            f"<div class='meta'><div>{field('Category', o['category'])}</div>"
            f"<div>{field('Expected response', o['dispatch_window'])}</div></div></div>",
            unsafe_allow_html=True,
        )


def tenant_view():
    tenant_name = st.session_state.get("tenant_name", list(TENANTS)[0])
    t = TENANTS[tenant_name]
    page_header("Report a maintenance issue",
                "Describe the problem in your own words. FixFlow asks a few quick questions, "
                "then sends a complete request to your property manager.")
    emergency_banner()

    if show_ai:
        left, right = st.columns([3, 2], gap="large")
    else:
        left = st.container()
    with left:
        a, b = st.columns([2, 3])
        with a:
            st.selectbox("Viewing as resident (demo)", list(TENANTS), key="tenant_name",
                         on_change=new_conversation)
        with b:
            st.markdown(f"<div class='res-card'><div class='name'>{esc(tenant_name)}</div>"
                        f"<div class='addr'>{esc(t['property'])}, {esc(t['unit'])}</div></div>",
                        unsafe_allow_html=True)

        report_tab, requests_tab = st.tabs(["Report an issue", "My requests"])
        with requests_tab:
            my_requests(tenant_name)

        with report_tab:
            with st.container(border=True, key="chatpanel"):
                if not st.session_state.display:
                    with st.chat_message("assistant", avatar=":material/build:"):
                        st.markdown("Hi! What's going on in your apartment? Describe it however you like. "
                                    "You can attach a photo too.")
                    st.markdown("<div class='try'>Or start with an example:</div>", unsafe_allow_html=True)
                    def pick_example():
                        st.session_state.pending_example = st.session_state.ex_pick
                        st.session_state.ex_pick = None
                    st.pills("Examples", EXAMPLES, key="ex_pick", on_change=pick_example,
                             label_visibility="collapsed")
                for msg in st.session_state.display:
                    render_message(msg)

                if err := st.session_state.pop("error", None):
                    st.error(err)

                if st.session_state.done:
                    st.markdown(receipt(st.session_state.submitted), unsafe_allow_html=True)
                    st.write("")
                    if st.button("Report another issue", type="primary"):
                        new_conversation()
                        st.rerun()

            if not st.session_state.done:
                pending = st.session_state.pop("pending_example", None)
                value = st.chat_input("Describe the problem", accept_file=True,
                                      file_type=["jpg", "jpeg", "png", "webp"])
                if value or pending:
                    if value:
                        text = value if isinstance(value, str) else value.text
                        files = [] if isinstance(value, str) else value.files
                    else:
                        text, files = pending, []
                    with st.spinner("FixFlow is reading your message..."):
                        handle_tenant_message(text, files, tenant_name)
                    st.rerun()

    if show_ai:
        with right:
            with st.container(border=True, key="sysview"):
                st.markdown("<div class='sys-title'>System view</div>"
                            "<div class='sys-sub'>What the AI returned on its latest turn. "
                            "This structured data is what the manager's system receives.</div>",
                            unsafe_allow_html=True)
                q = st.session_state.questions_asked
                steps = "".join(f"<span class='{'on' if i < q else ''}'></span>" for i in range(MAX_QUESTIONS))
                st.markdown(f"<div class='qsteps'>{steps}</div>"
                            f"<div class='qlabel'>Follow-up questions used: {q} of {MAX_QUESTIONS}</div>",
                            unsafe_allow_html=True)
                turn = st.session_state.last_turn
                if turn is None:
                    st.caption("Nothing yet. The AI's output appears here after the resident's first message.")
                else:
                    st.json(turn.model_dump(mode="json"), expanded=True)
                if st.session_state.done:
                    wo = st.session_state.submitted
                    st.markdown("**Company rules applied**")
                    st.markdown(
                        f"<div class='rule-line'>{esc(wo['category'])} → dispatch <b>{esc(wo['trade'])}</b></div>"
                        f"<div class='rule-line'>{esc(wo['urgency'])} → <b>{esc(wo['dispatch_window'])}</b>, "
                        f"{esc(wo['next_action'].lower())}</div>",
                        unsafe_allow_html=True)
                    if wo["guardrail_override"]:
                        st.warning("The safety guardrail raised this to Emergency.")


# ---------------------------------------------------------------------------
# Manager dashboard
# ---------------------------------------------------------------------------

def dispatch_board(orders: list[dict]) -> str:
    open_orders = [o for o in orders if o["status"] != "Completed"]
    n = {u: sum(o["urgency"] == u for o in open_orders) for u in URGENCY_ORDER}
    new_e = sum(o["urgency"] == "Emergency" and o["status"] == "New" for o in open_orders)
    avg_q = sum(o["questions_asked"] for o in orders) / len(orders) if orders else 0
    avg_t = sum(o["chat_seconds"] for o in orders) / len(orders) if orders else 0
    hot = " hot" if n["Emergency"] else ""
    e_note = (f"{new_e} not yet dispatched" if new_e else "All dispatched") if n["Emergency"] else "None open"
    return f"""
<div class='board'>
  <div class='cell{hot}'><div class='label'><span class='dot e'></span>Emergencies open</div>
    <div class='num'>{n['Emergency']}</div><div class='note'>{e_note}</div></div>
  <div class='cell'><div class='label'><span class='dot u'></span>Urgent open</div>
    <div class='num'>{n['Urgent']}</div><div class='note'>Within 24 hours</div></div>
  <div class='cell'><div class='label'><span class='dot r'></span>Routine open</div>
    <div class='num'>{n['Routine']}</div><div class='note'>Within 3 to 5 days</div></div>
  <div class='cell ops'><div class='label'>Follow-up questions</div>
    <div class='num'>{avg_q:.1f}<small>avg</small></div><div class='note'>Per request, max {MAX_QUESTIONS}</div></div>
  <div class='cell ops'><div class='label'>Time to file a request</div>
    <div class='num'>{avg_t / 60:.1f}<small>min</small></div><div class='note'>No callback needed</div></div>
</div>"""


def ticket(o: dict) -> None:
    u = o["urgency"].lower()
    with st.container(border=True, key=f"wo-{u}-{o['id']}"):
        top, chg_col, status_col = st.columns([4.6, 1.1, 1.1], vertical_alignment="center")
        new_tag = "" if o.get("sample") else "<span class='t-new'>Filed through FixFlow</span>"
        chg_tag = "<span class='t-chg'>Changed by manager</span>" if o.get("overridden") else ""
        top.markdown(
            f"<div class='t-top'>{pill(o['urgency'])}<span class='t-id'>{esc(o['id'])}</span>"
            f"<span class='t-cat'>{esc(o['category'])}</span>"
            f"<span class='t-time'>{esc(fmt_time(o['created']))}</span>{new_tag}{chg_tag}</div>",
            unsafe_allow_html=True,
        )
        with chg_col.popover("Change call", icon=":material/edit:", use_container_width=True):
            st.markdown("**Change the AI's call**")
            st.caption("The AI's original decision is kept for monitoring.")
            trades = ALL_TRADES if o["trade"] in ALL_TRADES else ALL_TRADES + [o["trade"]]
            st.selectbox("Urgency", list(URGENCY_ORDER), index=list(URGENCY_ORDER).index(o["urgency"]),
                         key=f"ov_u_{o['id']}")
            st.selectbox("Dispatch", trades, index=trades.index(o["trade"]), key=f"ov_t_{o['id']}")
            st.button("Save change", key=f"ov_save_{o['id']}", type="primary",
                      on_click=lambda oid=o["id"]: override_order(
                          oid, st.session_state[f"ov_u_{oid}"], st.session_state[f"ov_t_{oid}"]))
        status_col.selectbox(
            "Status", STATUSES, index=STATUSES.index(o["status"]), key=f"status_{o['id']}",
            label_visibility="collapsed",
            on_change=lambda oid=o["id"]: update_status(oid, st.session_state[f"status_{oid}"]),
        )
        st.markdown(
            f"<div class='t-summary'>{esc(o['issue_summary'])}</div>"
            f"<div class='t-grid'>"
            f"<div>{field('Resident', o['tenant'])}{field('Unit', o['property'] + ', ' + o['unit'])}</div>"
            f"<div>{field('Dispatch', o['trade'], True)}{field('Respond', o['dispatch_window'])}</div>"
            f"<div>{field('Where', o['location_in_unit'] + ': ' + o['item_or_appliance'])}"
            f"{field('Access', o['access_notes'])}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        with st.expander("Details, AI reasoning and conversation"):
            d1, d2 = st.columns([1, 1.3], gap="large")
            with d1:
                st.markdown("**What the resident reported**")
                for d in o["tenant_reported_details"]:
                    st.markdown(f"- {d}")
                st.markdown(f"**Why {o['urgency'].lower()}:** {o['urgency_reason']}")
                st.markdown(f"**Next step:** {o['next_action']}")
                if o.get("override_log"):
                    orig = o["ai_original"]
                    st.markdown(f"**Changed by manager:** {'; '.join(o['override_log'])}  \n"
                                f"AI's original call: {orig['urgency']}, {orig['trade']}")
                meta = [f"{o['questions_asked']} follow-up question{'s' if o['questions_asked'] != 1 else ''}",
                        f"{o['chat_seconds']} seconds to file"]
                if o.get("photo_attached"):
                    meta.append("photo attached")
                if o.get("model"):
                    meta.append(o["model"])
                st.caption(", ".join(meta))
            with d2:
                st.markdown("**Conversation**")
                for m in o["transcript"]:
                    who = {"tenant": "Resident", "assistant": "FixFlow", "safety": "Safety alert"}[m["role"]]
                    st.markdown(f"**{who}:** {m['text']}")


def manager_view():
    orders = load_orders()
    filed_live = sum(not o.get("sample") for o in orders)
    page_header(
        "Work orders",
        "Sorted by urgency, newest first. Every request arrives complete, with the right trade assigned.",
        f"<strong>{esc(COMPANY)}</strong><br>{datetime.now().strftime('%A, %B %-d')}",
    )
    st.markdown(dispatch_board(orders), unsafe_allow_html=True)

    f0, f1, f2 = st.columns([1.4, 1.3, 1.1])
    query = f0.text_input("Search", placeholder="Resident, unit, or issue", label_visibility="collapsed")
    urg_filter = f1.multiselect("Urgency", list(URGENCY_ORDER), default=list(URGENCY_ORDER),
                                label_visibility="collapsed", placeholder="Filter by urgency")
    status_filter = f2.multiselect("Status", STATUSES, default=["New", "Dispatched"],
                                   label_visibility="collapsed", placeholder="Filter by status")

    q = query.strip().lower()

    def matches(o):
        hay = " ".join([o["tenant"], o["property"], o["unit"], o["issue_summary"], o["category"],
                        o["item_or_appliance"], o["id"]]).lower()
        return o["urgency"] in urg_filter and o["status"] in status_filter and (not q or q in hay)

    shown = sorted((o for o in orders if matches(o)), key=lambda o: o["created"], reverse=True)
    if not shown:
        st.info("No work orders match. Clear the search or add a status to the filter.")
    for urgency in URGENCY_ORDER:
        group = [o for o in shown if o["urgency"] == urgency]
        if not group:
            continue
        st.markdown(
            f"<div class='group'><h3>{urgency}</h3><span class='count'>{len(group)} shown</span>"
            f"<span class='hint'>{URGENCY_HINT[urgency]}</span></div>",
            unsafe_allow_html=True,
        )
        for o in group:
            ticket(o)

    changed = sum(bool(o.get("overridden")) for o in orders)
    st.caption(f"{filed_live} request{'s' if filed_live != 1 else ''} filed through FixFlow this session. "
               f"Managers changed the AI's call on {changed} of {len(orders)} orders. "
               "The other orders are sample data for the demo.")


# ---------------------------------------------------------------------------
# How it works
# ---------------------------------------------------------------------------

def how_it_works():
    page_header("How FixFlow works",
                "A resident's vague message becomes a dispatch-ready work order in under two minutes.")
    steps = [
        ("Resident describes it", "In their own words, with an optional photo. No forms or menus.", "you", "Resident"),
        ("Safety check", "Our keyword guardrail spots gas, fire, sparking or flooding and shows safety steps instantly.", "code", "Our code"),
        ("AI asks and classifies", f"Gemini asks up to {MAX_QUESTIONS} targeted questions, then returns a structured work order.", "ai", "Gemini AI"),
        ("Company rules decide", "Category picks the trade. Urgency picks the response window.", "code", "Our code"),
        ("Manager dispatches", "The queue is sorted by urgency with the full conversation attached.", "you", "Manager"),
    ]
    st.markdown(
        "<div class='flow'>" + "".join(
            f"<div class='step'><div class='n'>{i}</div><h4>{esc(t)}</h4><p>{esc(d)}</p>"
            f"<span class='tag {k}'>{esc(who)}</span></div>"
            for i, (t, d, k, who) in enumerate(steps, 1)) + "</div>",
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown("<div class='h2'>Decision rules</div>", unsafe_allow_html=True)
        rows = [
            (pill("Emergency"), "Page the on-call tech and call the resident", "Within 2 hours"),
            (pill("Urgent"), "Schedule the next available slot", "Within 24 hours"),
            (pill("Routine"), "Add to the weekly route", "Within 3 to 5 business days"),
        ]
        st.markdown(
            "<table class='rules'><tr><th>AI urgency</th><th>Company action</th><th>Response window</th></tr>"
            + "".join(f"<tr><td>{a}</td><td>{esc(b)}</td><td>{esc(c)}</td></tr>" for a, b, c in rows)
            + "</table>", unsafe_allow_html=True)
        st.write("")
        trades = [("Plumbing", "Plumber"), ("Electrical", "Electrician"), ("Heating & Cooling", "HVAC technician"),
                  ("Appliance", "Appliance technician"), ("Pest Control", "Pest control vendor"),
                  ("Doors, Locks & Windows", "Locksmith or handyman"), ("General Repair", "Maintenance handyman")]
        st.markdown(
            "<table class='rules'><tr><th>AI category</th><th>Trade dispatched</th></tr>"
            + "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in trades)
            + "</table>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='h2'>Guardrails</div>", unsafe_allow_html=True)
        guards = [
            "Keyword safety override for gas, fire, sparking, CO alarms, flooding and ceiling collapse",
            "Safety instructions shown before the AI even responds",
            f"Hard cap of {MAX_QUESTIONS} follow-up questions so residents never get stuck",
            "Never promises arrival times or costs, and gives no repair advice beyond safety steps",
            "Every conversation is saved so a person can check the AI's reasoning",
            "Demo uses made-up residents only; a real deployment would use a paid, private AI tier",
        ]
        st.markdown("<div class='guard' style='grid-template-columns:1fr'>"
                    + "".join(f"<div>{esc(g)}</div>" for g in guards) + "</div>", unsafe_allow_html=True)
        st.markdown("<div class='h2'>Built with</div>", unsafe_allow_html=True)
        st.markdown("Python and Streamlit for the app, the Gemini API with structured output for the AI, "
                    "and plain Python rules for dispatch decisions.")


if view == "Resident portal":
    tenant_view()
elif view == "Manager dashboard":
    manager_view()
else:
    how_it_works()
