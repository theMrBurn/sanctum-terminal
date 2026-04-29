"""StateEvent + buffer + serialization."""
from __future__ import annotations

import time

from core.systems.state_events import (
    LOOP,
    MAX_BUFFERED,
    RITUAL,
    SYSTEM,
    StateEvent,
    StateEventBuffer,
    to_manifest,
)


def test_emit_assigns_monotonic_ids():
    buf = StateEventBuffer()
    a = buf.emit("a", "AAA")
    b = buf.emit("b", "BBB")
    c = buf.emit("c", "CCC")
    assert a.id == 1
    assert b.id == 2
    assert c.id == 3


def test_emit_records_label_kind_register_detail():
    buf = StateEventBuffer()
    e = buf.emit("pillar_sealed", "PILLAR SEALED · NAME",
                 detail="themrburn · age 30", register=RITUAL)
    assert e.kind == "pillar_sealed"
    assert e.label == "PILLAR SEALED · NAME"
    assert e.detail == "themrburn · age 30"
    assert e.register == RITUAL


def test_default_register_is_system():
    buf = StateEventBuffer()
    e = buf.emit("any_kind", "ANY")
    assert e.register == SYSTEM


def test_timestamp_is_monotonic_ish():
    buf = StateEventBuffer()
    a = buf.emit("a", "A")
    time.sleep(0.001)
    b = buf.emit("b", "B")
    assert b.timestamp >= a.timestamp


def test_buffer_caps_at_capacity():
    buf = StateEventBuffer(capacity=3)
    for i in range(5):
        buf.emit(f"k{i}", f"L{i}")
    events = buf.all()
    assert len(events) == 3
    # Oldest dropped — last 3 retained
    assert events[0].label == "L2"
    assert events[1].label == "L3"
    assert events[2].label == "L4"


def test_default_capacity_is_max_buffered():
    buf = StateEventBuffer()
    for i in range(MAX_BUFFERED + 5):
        buf.emit(f"k{i}", f"L{i}")
    assert len(buf.all()) == MAX_BUFFERED


def test_latest_id_returns_max():
    buf = StateEventBuffer()
    assert buf.latest_id() == 0
    buf.emit("a", "A")
    buf.emit("b", "B")
    assert buf.latest_id() == 2


def test_all_returns_a_copy():
    """Mutating the returned list shouldn't affect the buffer."""
    buf = StateEventBuffer()
    buf.emit("a", "A")
    snapshot = buf.all()
    snapshot.clear()
    assert len(buf.all()) == 1


def test_to_manifest_serializes_all_fields():
    buf = StateEventBuffer()
    buf.emit("kind1", "LABEL1", detail="detail1", register=RITUAL)
    buf.emit("kind2", "LABEL2", register=LOOP)
    payload = to_manifest(buf)
    assert len(payload) == 2
    assert payload[0]["kind"] == "kind1"
    assert payload[0]["label"] == "LABEL1"
    assert payload[0]["detail"] == "detail1"
    assert payload[0]["register"] == RITUAL
    assert payload[0]["id"] == 1
    assert "timestamp" in payload[0]
    assert payload[1]["detail"] is None


def test_to_manifest_empty_buffer():
    buf = StateEventBuffer()
    assert to_manifest(buf) == []


def test_event_is_frozen_dataclass():
    """Defensive: StateEvent should be immutable after construction."""
    e = StateEvent(id=1, timestamp=0.0, kind="x", label="X",
                   detail=None, register=SYSTEM)
    try:
        e.id = 99  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised
