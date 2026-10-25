from mock_stream import FT_T, build_stream
from pitchmind_contracts import Insight, MatchEvent, Moment, Overlay, StatSnapshot, parse_wire


def test_stream_is_valid_ordered_and_grounded() -> None:
    meta, messages = build_stream()
    assert messages[0] == meta

    events = {m.id: m for m in messages if isinstance(m, MatchEvent)}
    moments = {m.id: m for m in messages if isinstance(m, Moment)}
    insights = [m for m in messages if isinstance(m, Insight)]
    overlays = [m for m in messages if isinstance(m, Overlay)]
    snapshots = [m for m in messages if isinstance(m, StatSnapshot)]

    for msg in messages:
        assert parse_wire(msg.model_dump_json()) == msg

    ids = [e.id for e in events.values()]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    times = [e.t for e in events.values()]
    assert times == sorted(times)

    for moment in moments.values():
        assert set(moment.evidence) <= events.keys()

    for ins in insights:
        assert ins.moment_id is not None
        moment = moments[ins.moment_id]
        for claim in ins.claims:
            assert set(claim.evidence) <= events.keys()
            # Grounding rule: every metric a claim cites must be a fact the moment supplied.
            for key, value in claim.metrics.items():
                assert moment.metrics[key] == value

    assert {o.insight_id for o in overlays if o.insight_id} == {i.id for i in insights}
    assert any(i.fallback for i in insights), "mock must include a template-fallback example"
    assert any(o.rtl for o in overlays)

    final = snapshots[-1]
    assert final.t == FT_T
    assert (final.score.home, final.score.away) == (2, 1)
    previous = None
    for snap in snapshots:
        if previous:
            assert snap.home.shots >= previous.home.shots
            assert snap.home.xg >= previous.home.xg
        previous = snap
