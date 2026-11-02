from app.algorithms.bfs import find_evacuation_route
from app.services.building import load_building


def test_finds_route_from_room_to_exit():
    result = find_evacuation_route(load_building(), "room-101")
    assert result["found"] is True
    assert result["route"][0] == "room-101"
    assert result["route"][-1].startswith("exit-")
    assert result["segments"] == len(result["corridors"])


def test_avoids_blocked_corridor():
    building = load_building()
    result = find_evacuation_route(building, "room-201")
    assert result["found"] is True
    assert "c8" not in result["corridors"]


def test_respects_unavailable_exit():
    result = find_evacuation_route(load_building(), "room-101", unavailable_exits={"exit-north"})
    assert result["found"] is True
    assert result["exit"] == "exit-south"


def test_no_route_message():
    building = {"nodes": [{"id": "room-x", "type": "room"}, {"id": "exit-x", "type": "exit"}], "corridors": []}
    result = find_evacuation_route(building, "room-x")
    assert result["found"] is False
    assert "No valid route" in result["message"]


def test_unknown_room_message():
    result = find_evacuation_route(load_building(), "missing")
    assert result["found"] is False
    assert "not found" in result["message"]
