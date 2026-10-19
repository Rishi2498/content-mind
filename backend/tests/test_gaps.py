"""Gap detection."""

from app.schemas import ContentCreate
from app.services.content_service import all_contents
from app.services.analytics_service import build_analytics
from app.services.content_service import create_content
from app.services.gap_service import detect_gaps


def _seed(db, user_id):
    rows = [
        ("Automate reporting end to end", "AI automation", 10000, 900, 100, 60),
        ("Automate your CRM updates", "AI automation", 9000, 800, 90, 50),
        ("Automate support triage", "AI automation", 8000, 700, 80, 45),
        ("Automate weekly reporting", "AI automation", 7000, 600, 70, 40),
        ("Security hardening for AI agents", "AI security", 6000, 500, 60, 30),
    ]
    for i, (title, topic, imp, l, c, s) in enumerate(rows):
        create_content(
            db,
            ContentCreate(
                title=title,
                body=f"Detailed body for {title} covering practical steps and examples.",
                platform="LinkedIn",
                content_type="carousel",
                topic=topic,
                published_at=f"2026-05-{i + 1:02d}T09:00:00Z",
                impressions=imp,
                likes=l,
                comments=c,
                shares=s,
                clicks=imp // 20,
            ),
            user_id,
        )
    db.commit()
    return all_contents(db, user_id)


def test_detects_gaps_with_covered_anchor(db, user_id):
    _seed(db, user_id)
    contents = all_contents(db, user_id)
    gaps = detect_gaps(build_analytics(contents), contents)

    assert len(gaps.gaps) > 0
    for gap in gaps.gaps:
        assert "potential" in gap.reason.lower() or "may" in gap.reason.lower() or "test" in gap.reason.lower()


def test_gap_reason_does_not_claim_zero_x(db, user_id):
    _seed(db, user_id)
    contents = all_contents(db, user_id)
    gaps = detect_gaps(build_analytics(contents), contents)

    for gap in gaps.gaps:
        assert "0.0x" not in gap.reason


def test_gaps_sorted_by_score_desc(db, user_id):
    _seed(db, user_id)
    contents = all_contents(db, user_id)
    gaps = detect_gaps(build_analytics(contents), contents)

    scores = [g.score for g in gaps.gaps]
    assert scores == sorted(scores, reverse=True)


def test_no_gaps_on_empty_history(db):
    gaps = detect_gaps(build_analytics([]), [])
    assert len(gaps.gaps) == 0
    assert gaps.topics_covered == 0
