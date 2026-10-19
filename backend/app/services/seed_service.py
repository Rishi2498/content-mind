"""Synthetic seed data.

Deliberately *not* uniform. Real accounts are noisy, so the generator mixes a
handful of real patterns with enough variance that the agent has to actually
learn rather than pattern-match a rule.

Hidden patterns (the agent should rediscover them, not be told them):
  strong   practical AI automation tutorials and guides
  strong   customer stories / case studies
  medium   thought leadership, prompt engineering, newsletters
  weak     generic company announcements and AI news roundups
  thin     AI ROI, AI security, AI costs, adoption mistakes   -> the gaps
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

# topic -> (engagement multiplier, sampling weight). The thin-weight topics are
# the deliberate content gaps: they must stay near-zero so the gap engine has
# something real to find.
TOPIC_PROFILE: dict[str, tuple[float, float]] = {
    "AI automation": (2.10, 5.0),
    "Customer stories": (1.85, 3.0),
    "AI ROI": (0.95, 0.18),
    "AI security": (0.90, 0.15),
    "AI implementation costs": (0.88, 0.12),
    "AI adoption mistakes": (0.92, 0.15),
    "Prompt engineering": (1.45, 3.0),
    "Customer support AI": (1.25, 2.0),
    "AI news": (0.62, 3.5),
    "Chatbots": (1.10, 2.0),
    "Machine learning": (0.95, 1.6),
    "Data privacy": (0.80, 1.0),
    "Webinars": (0.85, 1.2),
    "Product updates": (0.55, 2.0),
    "Company announcements": (0.45, 1.8),
    "Thought leadership": (1.20, 1.6),
}

# content_type -> engagement multiplier
TYPE_PROFILE: dict[str, float] = {
    "tutorial": 1.55,
    "how-to guide": 1.40,
    "case study": 1.35,
    "customer story": 1.45,
    "how-to": 1.40,
    "list post": 1.20,
    "thread": 1.10,
    "thought leadership": 1.00,
    "newsletter": 0.95,
    "webinar": 0.75,
    "news roundup": 0.60,
    "announcement": 0.45,
    "product update": 0.50,
}

# platform -> (engagement multiplier, ctr multiplier, base impression reach)
PLATFORM_PROFILE: dict[str, tuple[float, float, float]] = {
    "LinkedIn": (1.30, 0.75, 22_000),
    "Blog": (1.15, 1.55, 11_000),
    "Newsletter": (1.05, 1.20, 9_000),
    "YouTube": (0.90, 0.80, 16_000),
    "X": (0.70, 0.55, 13_000),
    "Instagram": (0.65, 0.45, 10_000),
}

# Which content types are plausible on which platforms
PLATFORM_TYPES: dict[str, tuple[str, ...]] = {
    "LinkedIn": ("carousel", "text post", "document post", "list post", "thread", "case study", "customer story"),
    "Blog": ("tutorial", "how-to guide", "thought leadership", "case study", "news roundup", "list post"),
    "Newsletter": ("newsletter", "roundup", "thought leadership", "case study"),
    "YouTube": ("tutorial", "webinar", "how-to guide"),
    "X": ("thread", "text post", "news roundup", "announcement"),
    "Instagram": ("carousel", "reel", "image post", "announcement"),
}

AUDIENCES = ("CTOs and engineering leaders", "marketing leaders", "data and ML teams", "startup founders", "enterprise IT", "developers")

# (topic, title) pairs — realistic, non-templated, and unique so a seeded corpus
# never collapses into duplicate rows.
TITLE_BANK: dict[str, tuple[str, ...]] = {
    "AI automation": (
        "Automating your incident postmortem with AI",
        "9 repetitive support tasks you can hand to an agent today",
        "A 12-step checklist for automating any manual workflow",
        "How we replaced a 6-hour weekly report with one script",
        "Trigger-based automation: when to fire an agent, and when not to",
        "Build your first agentic workflow in an afternoon",
        "Where to draw the line between automation and a human handoff",
        "Automating the boring half of on-call",
        "Why our automation stalled until we automated the handoffs",
        "Anatomy of an automation that actually stuck",
        "Automating data entry without losing the exceptions",
        "The 3-week rollout plan for your first internal agent",
        "Idempotency for humans: making AI workflows safe to re-run",
        "Automating a two-person finance close",
    ),
    "Customer stories": (
        "How Northwind cut ticket volume by 38% in one quarter",
        "Case study: an 11-person team automating finance close",
        "What a logistics team learned automating 4,000 tickets a month",
        "From 9 tools to 3: one customer's automation journey",
        "How a support lead found 6 hours a week without hiring",
        "Case study: rolling AI out to 200 support agents",
        "The onboarding story that changed our activation number",
        "How one team cut response time from 9 hours to 90 minutes",
    ),
    "AI ROI": (
        "A simple framework for measuring AI ROI",
        "What does an AI project actually cost?",
        "ROI models that survive a finance review",
    ),
    "AI security": (
        "Threat-modelling an agentic system",
        "Securing tool access for autonomous agents",
        "Red-teaming an agent that can write code",
        "Least privilege for tools that take actions",
    ),
    "AI implementation costs": (
        "The hidden line items in an AI implementation",
        "TCO for an AI feature, honestly counted",
        "What it really costs to ship AI in 2026",
    ),
    "AI adoption mistakes": (
        "Five ways AI pilots stall before production",
        "Why your AI pilot has not shipped yet",
        "The adoption mistakes we watched every team make",
        "Rolling out AI: the mistakes that cost us a quarter",
    ),
    "Prompt engineering": (
        "Prompt patterns that survived our production rewrite",
        "Why your prompts break when traffic goes up",
        "Evaluating prompts like you evaluate code",
        "The prompt regression test we wish we had written first",
        "Structuring prompts for tool-calling agents",
        "Few-shot examples: how many you actually need",
        "Token budgets that keep costs predictable",
    ),
    "Customer support AI": (
        "Where AI should stop: designing a clean support handoff",
        "Deflection rates that actually hold up",
        "Support automation that customers do not hate",
        "Triage before you automate",
    ),
    "AI news": (
        "This week's AI news, briefly",
        "Model launch roundup: what changed and what did not",
        "Five announcements worth a skim",
        "The quarterly AI news reset",
        "Four launches, one that matters",
    ),
    "Chatbots": (
        "Chatbots in 2026: what survived the hype",
        "When a chatbot is the right interface",
        "Chatbot vs agent: the difference users feel",
    ),
    "Machine learning": (
        "MLOps on a two-person team",
        "Model monitoring without a platform team",
        "Shipping a model behind a feature flag",
        "Why your model degrades silently",
    ),
    "Data privacy": (
        "Data retention policies for AI workloads",
        "What your stack should never send to a model",
        "Redacting PII before it reaches an LLM",
    ),
    "Webinars": (
        "Live: automating the support handoff",
        "Office hours: bring your workflow",
        "Walkthrough: the 12-step automation checklist",
        "Live teardown of a real agent workflow",
    ),
    "Product updates": (
        "New: scheduled automations",
        "Shipping template galleries",
        "Faster runs, better logs",
        "Reworked integrations hub",
        "Bulk editing for automations",
        "New audit log export",
    ),
    "Company announcements": (
        "Northwind raises a Series B",
        "Northwind is hiring across engineering",
        "We are now a certified cloud partner",
        "Northwind expands into the EU market",
        "Northwind opens a new engineering office",
        "Welcome to our new VP of Product",
    ),
    "Thought leadership": (
        "Automation is an org design problem, not a tooling problem",
        "The quiet cost of manual review at scale",
        "Most AI pilots die in the gap between demo and default",
        "Why buying a tool will not fix your process",
        "The metric your AI programme is probably not tracking",
        "Hiring for the era of agents",
    ),
}

BODY_TEMPLATES = (
    "{title}\n\nWe spent three weeks putting this together, and the short version is: it works, "
    "but only if you fix the handoffs first.\n\n{topic} is where most teams lose the thread. The "
    "tooling is fine. The process around it is not.\n\nHere is what we learned, what we would do "
    "differently, and the numbers behind it.\n\nIf you are working through this yourself, start "
    "with the checklist below.\n\nQuestions? Reply and we will walk through it."
    "\n\n-- The Northwind team",
)


def _render_body(rng: random.Random, title: str, topic: str) -> str:
    template = rng.choice(BODY_TEMPLATES)
    return template.replace("{title}", title).replace("{topic}", topic)


def _pick_topic(rng: random.Random) -> str:
    """Weighted topic draw. Used for the follow-up demo batches."""
    topics = list(TOPIC_PROFILE)
    weights = [TOPIC_PROFILE[t][1] for t in topics]
    return rng.choices(topics, weights=weights, k=1)[0]


def _build_rows(count: int, rng: random.Random, days_back: int = 365) -> list[dict]:
    """Sample ``count`` distinct (topic, title) pairs, weighted by topic.

    Sampling without replacement guarantees the corpus has ``count`` unique
    titles, so the seeded demo never looks artificially repetitive.
    """
    pool: list[tuple[str, str]] = []
    for topic, titles in TITLE_BANK.items():
        for title in titles:
            pool.append((topic, title))
    weights = [TOPIC_PROFILE[topic][1] for topic, _ in pool]

    target = min(count, len(pool))
    # rng.choices-per-call with growing exclusion set: O(n*k) but n<150 here.
    chosen: list[tuple[str, str]] = []
    taken: set[int] = set()
    for _ in range(target):
        remaining = [i for i in range(len(pool)) if i not in taken]
        if not remaining:
            break
        picked = rng.choices(remaining, weights=[weights[i] for i in remaining], k=1)[0]
        taken.add(picked)
        chosen.append(pool[picked])

    now = datetime.now(timezone.utc)
    rows: list[dict] = []

    for topic, title in chosen:
        platform = rng.choices(
            list(PLATFORM_PROFILE), weights=[5.0, 3.2, 2.0, 1.6, 1.4, 1.0], k=1
        )[0]
        content_type = rng.choice(PLATFORM_TYPES[platform])
        if rng.random() < 0.25:
            content_type = rng.choice(list(TYPE_PROFILE))
        audience = rng.choice(AUDIENCES)

        published = now - timedelta(days=rng.randint(1, days_back), hours=rng.randint(0, 23))

        p_mult, ctr_mult, reach = PLATFORM_PROFILE[platform]
        t_mult = TOPIC_PROFILE[topic][0]
        c_mult = TYPE_PROFILE.get(content_type, 1.0)

        multiplier = p_mult * t_mult * c_mult
        # Real accounts are noisy: heavy-tailed randomness, some flops.
        noise = rng.lognormvariate(0.0, 0.45)
        impressions = max(180, int(reach * multiplier * noise * rng.uniform(0.55, 1.6)))

        base_rate = 0.052 * multiplier
        rate = max(0.002, min(0.34, rng.gauss(base_rate, 0.014) * rng.uniform(0.6, 1.45)))
        engagements = max(1, int(impressions * rate))
        shares = int(engagements * rng.uniform(0.08, 0.30))
        comments = int(engagements * rng.uniform(0.04, 0.16))
        likes = max(0, engagements - shares - comments)

        ctr = max(0.001, min(0.4, rng.gauss(0.031 * ctr_mult, 0.011) * rng.uniform(0.5, 1.5)))
        clicks = int(impressions * ctr)

        rows.append(
            {
                "title": title,
                "body": _render_body(rng, title, topic),
                "platform": platform,
                "content_type": content_type,
                "topic": topic,
                "audience": audience,
                "published_at": published,
                "impressions": impressions,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "clicks": clicks,
                "status": "published",
                "source": "seed",
            }
        )

    rows.sort(key=lambda r: r["published_at"], reverse=True)
    return rows


def generate_seed_payloads(count: int = 72, seed: int = 20260929) -> list[dict]:
    """Deterministic given ``seed`` so demos and tests are reproducible."""
    rng = random.Random(seed)
    return _build_rows(count, rng)


def generate_followup_payloads(count: int = 3, seed: int = 777) -> list[dict]:
    """The 'we published the plan and here are the results' step of the demo.

    These are deliberately placed on topics the gap engine surfaces, so the
    next plan visibly reflects them.
    """
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    topics = ("AI ROI", "AI security", "AI adoption mistakes", "AI implementation costs")
    platforms = ("LinkedIn", "Blog", "LinkedIn", "Newsletter")
    titles = (
        "How to calculate AI ROI without fooling yourself",
        "The AI security questions your legal team will ask",
        "Five AI adoption mistakes we made so you don't have to",
        "What an AI implementation actually costs, line by line",
    )
    types = ("how-to guide", "blog post" if False else "thought leadership", "list post", "case study")
    rows = []
    for i in range(count):
        topic = topics[i % len(topics)]
        platform = platforms[i % len(platforms)]
        impressions = int(rng.uniform(14_000, 41_000))
        rate = rng.uniform(0.061, 0.098)
        engagements = max(1, int(impressions * rate))
        shares = int(engagements * rng.uniform(0.12, 0.26))
        comments = int(engagements * rng.uniform(0.05, 0.13))
        rows.append(
            {
                "title": titles[i % len(titles)],
                "body": _render_body(rng, titles[i % len(titles)], topic),
                "platform": platform,
                "content_type": types[i % len(types)],
                "topic": topic,
                "audience": "CTOs and engineering leaders",
                "published_at": now - timedelta(days=rng.randint(0, 4)),
                "impressions": impressions,
                "likes": max(0, engagements - shares - comments),
                "comments": comments,
                "shares": shares,
                "clicks": int(impressions * rng.uniform(0.04, 0.075)),
                "status": "published",
                "source": "manual",
            }
        )
    return rows


def default_brand_profile(brand_name: str) -> dict:
    return {
        "brand_name": brand_name,
        "target_audience": "Engineering and marketing leaders at 50-1000 person B2B companies",
        "tone": "educational, concise and practical — no hype, always concrete examples",
        "preferred_formats": ["tutorial", "how-to guide", "case study", "carousel"],
        "preferred_platforms": ["LinkedIn", "Blog", "Newsletter"],
        "description": (
            "B2B software company selling an AI automation platform. Speaks to technical "
            "and marketing buyers who are sceptical of AI hype and want implementation detail."
        ),
    }
