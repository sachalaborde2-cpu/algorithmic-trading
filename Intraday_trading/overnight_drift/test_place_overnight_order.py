"""Tests des fonctions pures de place_overnight_order.py (aucun appel IB reel)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from place_overnight_order import (
    NY_TZ,
    build_trade_record,
    is_within_window,
    kill_switch_active,
    now_ny,
    should_skip_entry,
    should_skip_exit,
)


def test_now_ny_returns_tz_aware_datetime_in_new_york():
    ts = now_ny()
    assert ts.tzinfo is not None
    assert ts.tzinfo.key == "America/New_York" if hasattr(ts.tzinfo, "key") else True


def test_is_within_window_true_inside_business_hours_weekday():
    # mardi 2026-09-22, 10h00 NY -> dans la fenetre
    ts = datetime(2026, 9, 22, 10, 0, tzinfo=ZoneInfo(NY_TZ))
    assert is_within_window(ts) is True


def test_is_within_window_false_before_window():
    # mardi, 08h00 NY -> avant l'ouverture, hors fenetre
    ts = datetime(2026, 9, 22, 8, 0, tzinfo=ZoneInfo(NY_TZ))
    assert is_within_window(ts) is False


def test_is_within_window_false_after_window():
    # mardi, 20h00 NY -> bien apres la fenetre de passage quotidien
    ts = datetime(2026, 9, 22, 20, 0, tzinfo=ZoneInfo(NY_TZ))
    assert is_within_window(ts) is False


def test_is_within_window_false_on_weekend():
    # samedi 2026-09-19, 10h00 NY -> marche ferme
    ts = datetime(2026, 9, 19, 10, 0, tzinfo=ZoneInfo(NY_TZ))
    assert is_within_window(ts) is False


def test_kill_switch_active_true_when_file_exists(tmp_path):
    flag = tmp_path / "STOP_TRADING.flag"
    flag.write_text("stop")
    assert kill_switch_active(flag) is True


def test_kill_switch_active_false_when_file_absent(tmp_path):
    flag = tmp_path / "STOP_TRADING.flag"
    assert kill_switch_active(flag) is False


def test_should_skip_entry_true_when_kill_switch_active():
    assert should_skip_entry(kill_switch=True, position_qty=0) is True


def test_should_skip_entry_true_when_position_already_open():
    assert should_skip_entry(kill_switch=False, position_qty=100) is True


def test_should_skip_entry_false_when_clear():
    assert should_skip_entry(kill_switch=False, position_qty=0) is False


def test_should_skip_exit_true_when_already_flat():
    assert should_skip_exit(position_qty=0) is True


def test_should_skip_exit_false_when_position_open():
    assert should_skip_exit(position_qty=100) is False


def test_build_trade_record_fields():
    ts = datetime(2026, 9, 22, 15, 45, tzinfo=ZoneInfo(NY_TZ))
    rec = build_trade_record(
        timestamp_ny=ts, action="BUY", symbol="SPY", quantity=100,
        order_type="MOC", tif="DAY", status="Submitted", fill_price=None,
        note="entree overnight",
    )
    assert rec["timestamp_ny"] == ts.isoformat()
    assert rec["action"] == "BUY"
    assert rec["symbol"] == "SPY"
    assert rec["quantity"] == 100
    assert rec["order_type"] == "MOC"
    assert rec["tif"] == "DAY"
    assert rec["status"] == "Submitted"
    assert rec["fill_price"] is None
    assert rec["note"] == "entree overnight"
    assert list(rec.keys()) == [
        "timestamp_ny", "action", "symbol", "quantity",
        "order_type", "tif", "status", "fill_price", "note",
    ]
