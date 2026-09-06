from kc_l.runtime import render_main_quest_config, validate_main_quest_config_mode


def test_local_main_quest_config_is_structurally_valid():
    report = validate_main_quest_config_mode("local_gpu")
    assert report["ok"] is True
    assert report["status_scope"] == "operator_shell_only"
    assert report["validation_scope"] == "operator_shell_config_only"
    assert report["full_pipeline_runnable_claimed"] is False
    assert report["strict_runtime_readiness_checked"] is False
    assert report["example_overlay"] is True
    assert report["warnings"]


def test_hpc_main_quest_config_is_structurally_valid():
    report = validate_main_quest_config_mode("hpc_gpu")
    assert report["ok"] is True
    assert report["status_scope"] == "operator_shell_only"
    assert report["validation_scope"] == "operator_shell_config_only"
    assert report["full_pipeline_runnable_claimed"] is False
    assert report["strict_runtime_readiness_checked"] is False
    assert report["example_overlay"] is True
    assert report["warnings"]


def test_render_without_persist_keeps_expected_output_paths():
    result = render_main_quest_config("hpc_gpu", persist=False)
    assert result.output_yaml_path.as_posix().endswith("data/work/cache/generated_configs/main_quest.hpc_gpu.yaml")
    assert result.output_report_path.as_posix().endswith("data/work/cache/generated_configs/main_quest.hpc_gpu.validation.json")
