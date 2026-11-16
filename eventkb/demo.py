"""Synthetic acquisition: announcement → completion, late news and correction."""
from .store import Store


def seed(store: Store):
    store.create_event(event_id="acquisition-demo", topic="synthetic", identity_key="north-buys-south-2026", title="示例：北辰收购南星", kind="acquisition")
    def evidence(key, revision, date, body):
        return store.add_evidence(source_key=key, revision=revision, publisher="Synthetic filing", url=f"https://example.invalid/{key}/{revision}", published_at=date, body=body)["id"]
    first = evidence("announcement", "1", "2026-01-01T09:00:00Z", "合成数据：北辰拟收购南星，金额 100，双方位于上海。")
    common = dict(valid_from="2026-01-01T00:00:00Z", evidence_id=first)
    announced = store.assert_fact("acquisition-demo", field="status", value="announced", message_key="status-announced", **common)
    store.assert_fact("acquisition-demo", field="participants", value=[{"entity_id":"north","name":"北辰","role":"buyer"},{"entity_id":"south","name":"南星","role":"target"}], message_key="parties", **common)
    amount = store.assert_fact("acquisition-demo", field="amount", value={"value":100,"currency":"CNY","unit":"million"}, message_key="amount", **common)
    store.assert_fact("acquisition-demo", field="location", value="上海", message_key="location", **common)
    done = evidence("completion", "1", "2026-02-01T09:00:00Z", "合成数据：收购于 2 月 1 日完成。")
    store.assert_fact("acquisition-demo", field="status", value="completed", valid_from="2026-02-01T00:00:00Z", evidence_id=done, message_key="completion", relation="transition", target_id=announced["id"], reviewed=True, reason="人工确认正式完成公告")
    correction = evidence("announcement", "2", "2026-02-03T09:00:00Z", "合成数据更正：最初公告金额应为 120，其他字段不变。")
    store.assert_fact("acquisition-demo", field="amount", value={"value":120,"currency":"CNY","unit":"million"}, valid_from="2026-01-01T00:00:00Z", evidence_id=correction, message_key="amount-corrected", relation="correction", target_id=amount["id"], reviewed=True, reason="原公告发布版本 2，修正笔误")
    late = evidence("late-reprint", "1", "2026-01-01T10:00:00Z", "合成迟到报道重刊：1 月时仍拟收购，不代表 2 月的状态。")
    store.assert_fact("acquisition-demo", field="status", value="announced", valid_from="2026-01-01T00:00:00Z", valid_to="2026-02-01T00:00:00Z", evidence_id=late, message_key="late-old-status")
    store.set_memory("acquisition-demo", importance=0.95, pinned=True, reason="保留关键状态转换与公告更正")
    store.create_event(event_id="rumour-demo", topic="synthetic", identity_key="synthetic-rumour", title="示例：未确认传闻", kind="rumour")
    for n, value in enumerate(("approved", "denied")):
        ev = evidence(f"rumour-{n}", "1", "2026-02-02T00:00:00Z", f"合成相反报道：{value}")
        store.assert_fact("rumour-demo", field="status", value=value, valid_from="2026-02-02T00:00:00Z", evidence_id=ev, confidence=0.4, message_key=f"rumour-{n}")
    store.set_memory("rumour-demo", importance=0.2, mode="summary", reason="低重要性且来源冲突，保留证据并降权")
    return {"events":["acquisition-demo","rumour-demo"], "synthetic":True}
