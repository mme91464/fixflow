"""
FixFlow evaluation: runs realistic maintenance scenarios through the real agent and scores it.

A second Gemini call plays the tenant, answering FixFlow's questions using only the facts in
test_cases.json, so each scenario is a full multi-turn conversation like the live app.

Usage:
    export GEMINI_API_KEY="your-key"        (Mac)   |   set GEMINI_API_KEY=your-key   (Windows)
    python evaluate.py                       # runs all 20 cases (about 5 to 10 minutes on the free tier)
    python evaluate.py --limit 5             # quick check
    python evaluate.py --offline             # test the script without a key (keyword rules, not AI)

Outputs: eval_results.csv (one row per scenario) and eval_summary.md (metrics for your slides).
"""

import argparse
import csv
import json
import os
import time
from pathlib import Path

import fixflow_core as fc

HERE = Path(__file__).parent

TENANT_SIM_PROMPT = """You are role-playing a college student renter answering a maintenance chatbot.
Answer the chatbot's latest question in one short, casual sentence, using ONLY these facts:
{facts}
If the facts don't answer the question, say you're not sure. Never volunteer extra details or diagnose the problem."""


def simulate_tenant(agent, facts, history):
    """Second AI call that plays the tenant. Uses the same model fallback as the app,
    so an overloaded model doesn't stall the whole evaluation."""
    client = getattr(agent, "client", None)
    if client is None:  # offline: just hand over the facts
        return facts
    from google.genai import errors, types

    convo = "\n".join(f"{'Chatbot' if m['role'] == 'assistant' else 'You'}: {m['text']}" for m in history)
    config = types.GenerateContentConfig(
        system_instruction=TENANT_SIM_PROMPT.format(facts=facts), temperature=0.3)
    first = agent.active_model
    models = ([first] if first else []) + [m for m in agent.models if m != first]
    last_err = None
    for model in models:
        for attempt in range(2):
            try:
                resp = client.models.generate_content(model=model, contents=convo + "\nYou:", config=config)
                return resp.text.strip()
            except errors.ClientError as e:
                last_err = e
                if e.code == 429:
                    print("    (rate limit, waiting 15s)", flush=True)
                    time.sleep(15)
                    continue
                break  # model not available on this key: try the next one
            except Exception as e:  # 503 overload, timeout: move on to a backup model
                last_err = e
                print(f"    ({model} busy, trying a backup model)", flush=True)
                break
    raise RuntimeError(f"Simulated tenant failed on every model: {last_err}")


def run_case(agent, case, pause):
    history = [{"role": "tenant", "text": case["opening"]}]
    questions = 0
    start = time.time()
    while True:
        hits = fc.check_safety(" ".join(m["text"] for m in history if m["role"] == "tenant"))
        turn = agent.next_turn(history, questions)
        time.sleep(pause)
        finished = turn.status == fc.Status.COMPLETE or questions >= fc.MAX_QUESTIONS or bool(hits)
        history.append({"role": "assistant", "text": turn.message_to_tenant})
        if finished:
            wo = fc.apply_business_rules(turn.work_order, hits)
            return wo, questions, history, time.time() - start
        questions += 1
        history.append({"role": "tenant", "text": simulate_tenant(agent, case["facts"], history)})
        time.sleep(pause)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--pause", type=float, default=4.0, help="seconds between API calls (free-tier rate limits)")
    args = ap.parse_args()

    cases = json.loads((HERE / "test_cases.json").read_text())[: args.limit]
    key = None if args.offline else os.environ.get("GEMINI_API_KEY")
    if not key and not args.offline:
        raise SystemExit("Set GEMINI_API_KEY first, or run with --offline to test the script.")

    agent = fc.make_agent(key, os.environ.get("GEMINI_MODEL"))
    pause = 0 if args.offline else args.pause

    rows = []
    for case in cases:
        print(f"Scenario {case['id']}: {case['opening'][:50]} ...", flush=True)
        try:
            wo, q, history, secs = run_case(agent, case, pause)
        except Exception as e:
            print(f"    skipped: {str(e)[:120]}", flush=True)
            continue
        exp_cat = case["expected_category"] if isinstance(case["expected_category"], list) else [case["expected_category"]]
        row = {
            "id": case["id"],
            "opening": case["opening"],
            "expected_category": " or ".join(exp_cat),
            "predicted_category": wo["category"],
            "category_correct": wo["category"] in exp_cat,
            "expected_urgency": case["expected_urgency"],
            "predicted_urgency": wo["urgency"],
            "urgency_correct": wo["urgency"] == case["expected_urgency"],
            "questions_asked": q,
            "guardrail_override": wo["guardrail_override"],
            "trade": wo["trade"],
            "issue_summary": wo["issue_summary"],
            "seconds": round(secs, 1),
            "transcript": " | ".join(f"{m['role']}: {m['text']}" for m in history),
        }
        rows.append(row)
        mark = lambda ok: "✓" if ok else "✗"
        print(f"#{case['id']:>2} {mark(row['category_correct'])} {wo['category']:<22} "
              f"{mark(row['urgency_correct'])} {wo['urgency']:<9} q={q}  {case['opening'][:45]}")

    if not rows:
        raise SystemExit("Every scenario failed. Google may be overloaded: wait 10 minutes and try again.")
    with open(HERE / "eval_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    pct = lambda x, d: f"{100 * x / d:.0f}%" if d else "n/a"
    emerg = [r for r in rows if r["expected_urgency"] == "Emergency"]
    non_emerg = [r for r in rows if r["expected_urgency"] != "Emergency"]
    caught = sum(r["predicted_urgency"] == "Emergency" for r in emerg)
    over = sum(r["predicted_urgency"] == "Emergency" for r in non_emerg)
    misses = [r for r in rows if not (r["category_correct"] and r["urgency_correct"])]

    summary = f"""# FixFlow evaluation results

Model: {getattr(agent, 'label', 'unknown')}  ·  Scenarios: {n}

| Metric | Result | Target |
|---|---|---|
| Category accuracy (right trade dispatched) | {pct(sum(r['category_correct'] for r in rows), n)} | 90%+ |
| Urgency accuracy | {pct(sum(r['urgency_correct'] for r in rows), n)} | 80%+ |
| Emergency catch rate | {pct(caught, len(emerg))} ({caught} of {len(emerg)}) | 100% |
| False emergency rate | {pct(over, len(non_emerg))} ({over} of {len(non_emerg)}) | under 10% |
| Avg follow-up questions | {sum(r['questions_asked'] for r in rows) / n:.1f} | 3 or fewer |
| Completed within question cap | {pct(sum(r['questions_asked'] <= fc.MAX_QUESTIONS for r in rows), n)} | 100% |
| Guardrail overrides (AI missed, keywords caught) | {sum(r['guardrail_override'] for r in rows)} | — |

## Misses to discuss (and what you changed)
""" + ("\n".join(f"- #{r['id']} \"{r['opening']}\": expected {r['expected_category']} / {r['expected_urgency']}, "
                 f"got {r['predicted_category']} / {r['predicted_urgency']}" for r in misses) or "- None") + "\n"
    (HERE / "eval_summary.md").write_text(summary)
    print("\n" + summary)
    print("Saved eval_results.csv and eval_summary.md")


if __name__ == "__main__":
    main()
