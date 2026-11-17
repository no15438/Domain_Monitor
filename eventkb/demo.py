"""Synthetic acquisition: announcement → completion, late news and correction."""
from .store import Store


def seed(store: Store):
    store.create_event(event_id="acquisition-demo-en", topic="synthetic", identity_key="north-buys-south-2026-en", title="Demo: North acquires South", kind="acquisition")
    def evidence(key, revision, date, body):
        return store.add_evidence(source_key=f"english-demo/{key}", revision=revision, publisher="Synthetic filing", url=f"https://example.invalid/{key}/{revision}", published_at=date, body=body)["id"]
    first = evidence("announcement", "1", "2026-01-01T09:00:00Z", "Synthetic filing: North proposes acquiring South for CNY 100 million. Both parties are in Shanghai.")
    common = dict(valid_from="2026-01-01T00:00:00Z", evidence_id=first)
    announced = store.assert_fact("acquisition-demo-en", field="status", value="announced", message_key="status-announced", **common)
    store.assert_fact("acquisition-demo-en", field="participants", value=[{"entity_id":"north","name":"North","role":"buyer"},{"entity_id":"south","name":"South","role":"target"}], message_key="parties", **common)
    amount = store.assert_fact("acquisition-demo-en", field="amount", value={"value":100,"currency":"CNY","unit":"million"}, message_key="amount", **common)
    store.assert_fact("acquisition-demo-en", field="location", value="Shanghai", message_key="location", **common)
    done = evidence("completion", "1", "2026-02-01T09:00:00Z", "Synthetic filing: the acquisition completed on February 1.")
    store.assert_fact("acquisition-demo-en", field="status", value="completed", valid_from="2026-02-01T00:00:00Z", evidence_id=done, message_key="completion", relation="transition", target_id=announced["id"], reviewed=True, reason="Reviewed official completion notice")
    correction = evidence("announcement", "2", "2026-02-03T09:00:00Z", "Synthetic correction: the original amount should be CNY 120 million. Other fields are unchanged.")
    store.assert_fact("acquisition-demo-en", field="amount", value={"value":120,"currency":"CNY","unit":"million"}, valid_from="2026-01-01T00:00:00Z", evidence_id=correction, message_key="amount-corrected", relation="correction", target_id=amount["id"], reviewed=True, reason="Announcement revision 2 corrects a typographical error")
    late = evidence("late-reprint", "1", "2026-01-01T10:00:00Z", "Synthetic late reprint: the acquisition was proposed in January. This does not describe its February state.")
    store.assert_fact("acquisition-demo-en", field="status", value="announced", valid_from="2026-01-01T00:00:00Z", valid_to="2026-02-01T00:00:00Z", evidence_id=late, message_key="late-old-status")
    store.set_memory("acquisition-demo-en", importance=0.95, pinned=True, reason="Retain the key transition and filing correction")
    store.create_event(event_id="rumour-demo-en", topic="synthetic", identity_key="synthetic-rumour-en", title="Demo: unconfirmed rumour", kind="rumour")
    for n, value in enumerate(("approved", "denied")):
        ev = evidence(f"rumour-{n}", "1", "2026-02-02T00:00:00Z", f"Synthetic conflicting report: {value}")
        store.assert_fact("rumour-demo-en", field="status", value=value, valid_from="2026-02-02T00:00:00Z", evidence_id=ev, confidence=0.4, message_key=f"rumour-{n}")
    store.set_memory("rumour-demo-en", importance=0.2, mode="summary", reason="Low importance with conflicting sources; preserve evidence and reduce attention")
    return {"events":["acquisition-demo-en","rumour-demo-en"], "synthetic":True}
