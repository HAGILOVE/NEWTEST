"""Several objects selected: one panel edits them all, in one undo step."""
import pytest

from aether.gui.api import dispatch
from aether.gui.state import Session


def session():
    s = Session()
    s.new_project("Multi")
    for i, x in enumerate(("0mm", "5mm", "10mm")):
        dispatch(s, "modeler.draw", {"shape": "box", "name": f"B{i}",
                                     "params": {"position": [x, "0mm", "0mm"],
                                                "size": ["4mm", "4mm", "4mm"]}})
    return s


def test_material_colour_and_transparency_apply_to_every_selected_object():
    s = session()
    names = ["B0", "B1", "B2"]
    dispatch(s, "modeler.setProperty", {"names": names, "prop": "material",
                                        "value": "copper"})
    dispatch(s, "modeler.setProperty", {"names": names, "prop": "color",
                                        "value": "#d64545"})
    dispatch(s, "modeler.setProperty", {"names": names, "prop": "transparency",
                                        "value": 0.4})
    for o in s.design.solids:
        assert o.material.name.lower() == "copper"
        assert o.display_color == "#d64545"
        assert o.display_transparency == pytest.approx(0.4)


def test_one_undo_reverts_the_whole_multi_edit():
    s = session()
    before = [o.material.name for o in s.design.solids]
    dispatch(s, "modeler.setProperty", {"names": ["B0", "B1", "B2"],
                                        "prop": "material", "value": "copper"})
    dispatch(s, "edit.undo")
    assert [o.material.name for o in s.design.solids] == before


def test_a_bad_value_changes_nothing():
    s = session()
    with pytest.raises(Exception):
        dispatch(s, "modeler.setProperty", {"names": ["B0", "B1"],
                                            "prop": "material",
                                            "value": "no_such_material"})
    assert all(o.material.name == "vacuum" for o in s.design.solids)


def test_renaming_many_objects_at_once_is_refused():
    s = session()
    with pytest.raises(ValueError, match="one at a time"):
        dispatch(s, "modeler.setProperty", {"names": ["B0", "B1"],
                                            "prop": "name", "value": "X"})


def test_sheets_and_solids_can_be_edited_together():
    s = session()
    dispatch(s, "modeler.draw", {"shape": "rectangle", "name": "R0",
                                 "params": {"position": ["0mm", "0mm", "0mm"],
                                            "size": ["3mm", "3mm"],
                                            "plane": "xy"}})
    dispatch(s, "modeler.setProperty", {"names": ["B0", "R0"],
                                        "prop": "color", "value": "#2b79c2"})
    assert s.design.get_solid("B0").display_color == "#2b79c2"
    assert s.design.sheets[0].display_color == "#2b79c2"
    # solve-inside is meaningless for a sheet and the whole edit is refused
    with pytest.raises(ValueError):
        dispatch(s, "modeler.setProperty", {"names": ["B0", "R0"],
                                            "prop": "solveInside",
                                            "value": False})
    assert s.design.get_solid("B0").solve_inside is True
