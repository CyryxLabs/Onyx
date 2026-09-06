from __future__ import annotations

import pytest

from core.site_recipe_catalog_v1 import PALETTE, SiteRecipeCatalogV1, SiteRecipeDenied


def test_every_recipe_is_deterministic_runnable_and_uses_official_palette() -> None:
    catalog = SiteRecipeCatalogV1(enabled=True)
    for recipe in catalog.recipes():
        one = catalog.plan(recipe_id=recipe, project_slug="cyryx-demo", title="Cyryx <Labs>", summary="Governed execution.")
        two = catalog.plan(recipe_id=recipe, project_slug="cyryx-demo", title="Cyryx <Labs>", summary="Governed execution.")
        assert one == two
        assert tuple(item.relative_path for item in one.files) == ("index.html", "styles.css", "app.js")
        assert "Cyryx &lt;Labs&gt;" in one.files[0].content
        assert all(color in one.files[1].content for color in PALETTE.values())
        assert one.network_calls == one.process_calls == one.writes_performed == 0
        assert one.phase6_payload()["plan_sha256"] == one.plan_sha256


def test_recipe_rejects_unknown_or_unsafe_inputs_and_is_default_off() -> None:
    with pytest.raises(SiteRecipeDenied):
        SiteRecipeCatalogV1(enabled=False)
    catalog = SiteRecipeCatalogV1(enabled=True)
    with pytest.raises(ValueError):
        catalog.plan(recipe_id="shell", project_slug="bad", title="x", summary="x")
    with pytest.raises(ValueError):
        catalog.plan(recipe_id="company_site", project_slug="../escape", title="x", summary="x")
