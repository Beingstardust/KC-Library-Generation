from kc_l.runtime import build_merged_schema_profile, load_extension_schema, validate_extension_schema
from kc_l.runtime.schema_profiles import default_extension_template_path


def test_extension_schema_template_validates():
    extension = load_extension_schema(default_extension_template_path())
    assert validate_extension_schema(extension) == []


def test_merged_schema_profile_contains_locked_and_extension_fields():
    merged = build_merged_schema_profile()
    assert "kc_id" in merged["merged_field_ids"]
    assert "teaching_context" in merged["merged_field_ids"]
