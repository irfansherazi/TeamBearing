from backend.engine.recipe_runner import BLUEPRINTS_DIR, RecipeRegistry


def test_cv_fallback_not_in_blueprints_dir():
    """
    Bug C: Assert that knowledge/blueprints/ does NOT contain cv_fallback.yaml.
    This should FAIL before the fix.
    """
    cv_fallback_path = BLUEPRINTS_DIR / "cv_fallback.yaml"
    assert not cv_fallback_path.exists(), (
        f"cv_fallback.yaml should NOT be in {BLUEPRINTS_DIR}. "
        "It causes ValidationError in RecipeRegistry because it uses 'coordinate_action'."
    )


def test_recipe_registry_loads_without_validation_error(caplog):
    """
    Assert that RecipeRegistry() loads all blueprints without ERROR logs or exceptions.
    This should FAIL before the fix (it will log an error about cv_fallback.yaml).
    """
    # RecipeRegistry logs error instead of raising if a file fails validation
    registry = RecipeRegistry()

    # Check for "FAILED to load 'cv_fallback.yaml'" in logs
    errors = [
        record.message
        for record in caplog.records
        if record.levelname == "ERROR" and "cv_fallback.yaml" in record.message
    ]

    assert not errors, f"RecipeRegistry had errors loading blueprints: {errors}"
    assert "cv_fallback" not in [r.name for r in registry.all_recipes()], "cv_fallback should not be a loaded recipe"


def test_cv_fallback_reference_doc_exists():
    """
    Assert knowledge/docs/cv_fallback_reference.yaml DOES exist.
    This should FAIL before the fix.
    """
    # Based on the prompt, the target is knowledge/docs/cv_fallback_reference.yaml
    # but the blueprints dir is knowledge/blueprints/.
    # Let's check where 'knowledge/docs' would be.
    docs_dir = BLUEPRINTS_DIR.parent / "docs"
    cv_reference_path = docs_dir / "cv_fallback_reference.yaml"

    assert cv_reference_path.exists(), f"Reference doc should exist at {cv_reference_path}"


def test_recipe_registry_skips_non_yaml():
    """
    Sanity check: RecipeRegistry only picks up *.yaml from blueprints dir.
    """
    registry = RecipeRegistry()
    blueprint_files = list(BLUEPRINTS_DIR.glob("*.yaml"))
    # Filtering out cv_fallback.yaml if it exists for this count comparison
    expected_count = len([f for f in blueprint_files if f.name != "cv_fallback.yaml"])

    # If the registry didn't load cv_fallback.yaml due to error,
    # its recipe count should match the number of VALID yaml files.
    assert len(registry.all_recipes()) == expected_count
