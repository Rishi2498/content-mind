"""End-to-end verification of the ContentMind memory loop.

Runs the full story against the API using the deterministic strategy engine so
it works without any external keys:

    add content -> analyze -> remember -> recall -> reason -> recommend
    -> observe result -> learn -> remember again -> better recommendation

    python scripts/e2e_check.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LLM_PROVIDER", "heuristic")
os.environ.setdefault("ENVIRONMENT", "test")

# The plan output uses arrows and em dashes; keep the Windows console happy.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

OK, BAD = "  [ok]  ", "  [FAIL]"
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{OK if condition else BAD} {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> int:
    init_db()
    with TestClient(app) as client:
        # ---------------------------------------------------------------- reset
        section("STEP 0 — reset to a clean slate")
        reset = client.post("/api/demo/reset").json()
        check("reset cleared content", reset["content_deleted"] >= 0, f"deleted={reset['content_deleted']}")

        health = client.get("/api/health").json()
        print(f"        memory backend : {health['memory']['backend']} (degraded={health['memory']['degraded']})")
        print(f"        llm            : {health['llm']['provider']}")

        # ------------------------------------------------- BEFORE MEMORY
        section('STEP 1 — BEFORE MEMORY: "What should I post next week?"')
        before = client.post("/api/chat", json={"message": "What should I post next week?"}).json()
        print()
        print(before["answer"][:700])
        print()
        check(
            "answer acknowledges missing history",
            "don't have any content history" in before["answer"].lower()
            or "no content history" in before["answer"].lower(),
        )
        check("confidence is low", before["confidence"] == "low")
        check("no memories used", before["memory_count"] == 0)

        before_plan = client.post(
            "/api/plans/generate", json={"days": 7, "posts_per_day": 1}
        ).json()
        check("baseline plan is not memory-driven", before_plan["plan"]["used_memory"] is False)
        check("baseline plan has 7 items", len(before_plan["plan"]["items"]) == 7)

        # -------------------------------------------------------- SEED
        section("STEP 2 — give ContentMind the content history")
        seeded = client.post(
            "/api/demo/seed", json={"records": 72, "remember": True, "brand_name": "Northwind AI", "reset_first": True}
        ).json()
        print(
            f"        content={seeded['content_created']}  insights={seeded['insights_created']}  "
            f"memories={seeded['memories_retained']}  backend={seeded['memory_backend']}"
        )
        check("seeded 72 content items", seeded["content_created"] == 72, f"created={seeded['content_created']}")
        n = seeded["content_created"]
        check("memories were retained", seeded["memories_retained"] > 0)
        check("insights were extracted", seeded["insights_created"] > 0)
        if seeded["warnings"]:
            print(f"        warnings: {seeded['warnings']}")

        analytics = client.get("/api/analytics").json()
        print(f"        avg engagement : {analytics['avg_engagement_rate']*100:.2f}%")
        print(f"        top topic      : {analytics['top_topic']['key']} ({analytics['top_topic']['index_vs_average']}x)")
        print(f"        top platform   : {analytics['top_platform']['key']} ({analytics['top_platform']['index_vs_average']}x)")
        check("analytics computed", analytics["content_count"] == n, f"count={analytics['content_count']}")
        check("top topic is a real winner", analytics["top_topic"]["index_vs_average"] > 1.0)
        check("weak topics detected", any(s["index_vs_average"] < 0.8 for s in analytics["by_topic"]))

        gaps = client.get("/api/analytics/gaps").json()
        print(f"        gaps detected  : {[g['topic'] for g in gaps['gaps']]}")
        check("content gaps detected", len(gaps["gaps"]) > 0)
        check("gaps use hedged language", all("may" in g["reason"] or "potential" in g["reason"].lower() or "test" in g["reason"].lower() for g in gaps["gaps"]))

        # ------------------------------------------------- AFTER MEMORY
        section('STEP 3 — AFTER MEMORY: ask the exact same question')
        after = client.post("/api/chat", json={"message": "What should I post next week?"}).json()
        print()
        print(after["answer"][:2200])
        print()
        check("memories were recalled", after["memory_count"] > 0, f"count={after['memory_count']}")
        check("answer cites content history", str(n) in after["answer"], f"expected {n}")
        check("answer is memory-backed", len(after["answer"]) > len(before["answer"]))
        check("confidence improved", after["confidence"] in {"medium", "high"})
        check("memories surfaced with the answer", len(after["memories_used"]) > 0)

        # -------------------------------------------------------- PLAN
        section("STEP 4 — generate a memory-driven plan")
        plan_result = client.post(
            "/api/plans/generate", json={"days": 7, "posts_per_day": 1, "platforms": ["LinkedIn", "Blog"]}
        ).json()
        plan = plan_result["plan"]
        print(f"\n        {plan['title']}  ({plan['date_range']})")
        print(f"        {plan['strategy_summary']}\n")
        for item in plan["items"]:
            print(f"        {item['date'][:10]}  {item['platform']:<10} {item['format']:<16} {item['title']}")
            print(f"                  why: {item['reason'][:160]}")
            if item["memory_used"]:
                print(f"                  memory: {str(item['memory_used'][0])[:140]}")
            print()
        check("plan used memory", plan["used_memory"] is True)
        check("plan used history", plan["used_historical"] is True)
        check("7 items generated", len(plan["items"]) == 7)
        check("every item has a reason", all(len(i["reason"]) > 20 for i in plan["items"]))
        check("every item cites memory", all(len(i["memory_used"]) > 0 for i in plan["items"]))
        check("plan records gaps considered", len(plan["gaps_considered"]) > 0)
        topics = [i["topic"] for i in plan["items"]]
        check("topics are not all identical", len(set(topics)) > 1, f"{sorted(set(topics))}")
        check(
            "no topic is repeated in the plan",
            len(set(topics)) == len(topics),
            f"duplicates={[t for t in set(topics) if topics.count(t) > 1]}",
        )
        check(
            "plan targets detected gaps",
            any(t in {g["topic"] for g in gaps["gaps"]} for t in topics),
            f"topics={topics}",
        )

        # --------------------------------------------------------- LEARN
        section("STEP 5 — publish and feed results back (OBSERVE → LEARN)")
        memory_before = client.get("/api/memory/status").json()["memory_count"]
        published = client.post(
            "/api/demo/publish-plan", json={"days": 7, "posts_per_day": 2, "platforms": ["LinkedIn"]}
        ).json()
        print(f"        {published['message']}")
        check("content created from the plan", published["content_created"] > 0)
        check("learning happened from results", published["insights_created"] > 0)
        memory_after = client.get("/api/memory/status").json()["memory_count"]
        check(
            "the memory bank grew after learning",
            memory_after > memory_before,
            f"{memory_before} -> {memory_after}",
        )

        learned = client.get("/api/memory").json()
        print(f"        'What I've learned': {learned['total']} insights across {len(learned['categories'])} categories")
        check("learned page populated", learned["total"] > 0)
        check("gaps present in learned", "gaps" in learned["categories"] or "strategy" in learned["categories"])

        # ------------------------------------------------- IMPROVEMENT
        section("STEP 6 — ask again: the recommendation has changed")
        final = client.post("/api/chat", json={"message": "What should I post next week?"}).json()
        print()
        print(final["answer"][:2000])
        print()
        check("content count grew", final["content_analyzed"] > n, f"now={final['content_analyzed']}")
        check("memories are still being recalled", final["memory_count"] > 0, f"count={final['memory_count']}")
        health = client.get("/api/health").json()
        check("health reports a memory backend", health["memory"]["backend"] in {"hindsight", "local"})
        check("health reports degraded state honestly", health["memory"]["degraded"] is (health["memory"]["backend"] == "local"))

        final_plan = client.post(
            "/api/plans/generate", json={"days": 7, "posts_per_day": 1, "platforms": ["LinkedIn", "Blog"]}
        ).json()
        final_topics = [i["topic"] for i in final_plan["plan"]["items"]]
        print(f"        first plan topics : {topics}")
        print(f"        later plan topics : {final_topics}")
        check(
            "recommendations changed after learning",
            set(final_topics) != set(topics) or topics != final_topics,
            f"{topics} -> {final_topics}",
        )

        # --------------------------------------------------------- DEMO
        section("STEP 7 — demo compare (without memory vs with memory)")
        compare = client.post("/api/demo/compare").json()
        print()
        print("--- WITHOUT MEMORY ---")
        print(compare["without_memory"]["answer"][:700])
        print()
        print("--- WITH MEMORY ---")
        print(compare["with_memory"]["answer"][:1400])
        print()
        check("baseline has no memories", compare["without_memory"]["memories_used"] == [])
        check("informed answer cites memories", len(compare["with_memory"]["memories_used"]) > 0)
        check(
            "informed answer is substantially richer",
            len(compare["with_memory"]["answer"]) > len(compare["without_memory"]["answer"]) * 1.5,
        )

        # ------------------------------------------------- API VALIDATION
        section("STEP 8 — validation and error handling")
        r = client.post("/api/content", json={"title": "ab"})
        check("rejects a too-short title", r.status_code == 422, f"status={r.status_code}")
        r = client.post("/api/content", json={"title": "Valid title", "impressions": -5})
        check("rejects negative impressions", r.status_code == 422, f"status={r.status_code}")
        r = client.get("/api/content/999999")
        check("404 for missing content", r.status_code == 404)
        r = client.post("/api/plans/generate", json={"days": 999})
        check("rejects an out-of-range plan", r.status_code == 422, f"status={r.status_code}")
        r = client.get("/api/memory/recall", params={"query": "ai automation tutorials"})
        check("recall endpoint responds", r.status_code == 200 and "memories" in r.json())
        ctx = client.get("/api/memory/context", params={"request": "what should I post next"}).json()
        check("strategy context exposes memories", len(ctx["memories"]) > 0)
        r = client.get("/api/analytics")
        check("analytics responds", r.status_code == 200)
        r = client.get("/api/chat/suggestions")
        check("chat suggestions respond", len(r.json()["suggestions"]) == 8)

    section("RESULT")
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
