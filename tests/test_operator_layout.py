from kc_l.runtime import build_operator_repo_status, get_operator_layout


def test_operator_layout_is_clean_and_present():
    layout = get_operator_layout()
    assert layout.course_materials_root.exists()
    assert layout.hierarchy_root.exists()
    assert layout.runs_root.exists()
    assert layout.active_library_pointer.exists()

    status = build_operator_repo_status()
    assert status["ok"] is True
    assert status["inputs"]["course_material_file_count"] == 0
    assert status["inputs"]["hierarchy_file_count"] == 0
    assert status["runtime_state"]["runs_clean"] is True
    assert status["runtime_state"]["frozen_library_clean"] is True
    assert status["runtime_state"]["active_pointer_state"] == "none"
