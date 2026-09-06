"""Deterministic Cyryx site recipes for the existing governed site lifecycle.

Recipes produce a bounded file plan only.  They never write files, run package
managers, start preview servers, publish, open a shell or access the network.
The existing Phase 6/site-project authorities remain responsible for every
materialized file and verified build/publish receipt.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from typing import Final


FEATURE_FLAG: Final = "ONYX_SITE_RECIPES_V1"
RECIPE_IDS: Final = ("company_site", "knowledge_portal", "operations_console")
PALETTE: Final = {
    "onyx": "#050607", "obsidian": "#0A0D0F", "graphite": "#11161A",
    "gunmetal": "#1B2227", "steel": "#8C949E", "silver": "#C7C9CC",
    "core_teal": "#0F6B68", "teal_glow": "#19C7C0",
}
_SLUG = re.compile(r"[a-z][a-z0-9-]{2,63}")


class SiteRecipeContractError(ValueError):
    pass


class SiteRecipeDenied(PermissionError):
    pass


def _text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise SiteRecipeContractError(f"{label} is invalid")
    clean = " ".join(value.split())
    if len(clean) > maximum:
        raise SiteRecipeContractError(f"{label} is invalid")
    return clean


@dataclass(frozen=True, slots=True)
class SiteRecipeFileV1:
    relative_path: str
    content: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SiteRecipePlanV1:
    recipe_id: str
    project_slug: str
    files: tuple[SiteRecipeFileV1, ...]
    plan_sha256: str
    required_postconditions: tuple[str, ...]
    network_calls: int = 0
    process_calls: int = 0
    writes_performed: int = 0

    def phase6_payload(self) -> dict[str, object]:
        return {
            "recipe_id": self.recipe_id,
            "project_slug": self.project_slug,
            "plan_sha256": self.plan_sha256,
            "files": tuple({
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "content": item.content,
            } for item in self.files),
            "required_postconditions": self.required_postconditions,
        }


class SiteRecipeCatalogV1:
    def __init__(self, *, enabled: bool) -> None:
        if type(enabled) is not bool or not enabled:
            raise SiteRecipeDenied("site recipes are disabled")
        self.background_workers = 0
        self.polling_interval = None

    @staticmethod
    def recipes() -> tuple[str, ...]:
        return RECIPE_IDS

    def plan(
        self,
        *,
        recipe_id: str,
        project_slug: str,
        title: str,
        summary: str,
        primary_action: str = "Start a mission",
    ) -> SiteRecipePlanV1:
        if recipe_id not in RECIPE_IDS:
            raise SiteRecipeContractError("recipe is unknown")
        if type(project_slug) is not str or _SLUG.fullmatch(project_slug) is None:
            raise SiteRecipeContractError("project_slug is invalid")
        title_value = _text(title, "title", 120)
        summary_value = _text(summary, "summary", 360)
        action_value = _text(primary_action, "primary_action", 80)
        label = {
            "company_site": "CYRYX LABS / COMPANY",
            "knowledge_portal": "CYRYX LABS / KNOWLEDGE",
            "operations_console": "CYRYX LABS / OPERATIONS",
        }[recipe_id]
        html_text = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{summary}"><title>{title}</title><link rel="stylesheet" href="styles.css"></head>
<body><a class="skip" href="#main">Skip to content</a><header><span class="mark">ONYX</span><span>{label}</span></header>
<main id="main"><p class="eyebrow">GOVERNED AI EXECUTION</p><h1>{title}</h1><p class="summary">{summary}</p>
<button id="primary" type="button">{action}</button><section aria-label="System status"><article><b>CONTEXT</b><span>Bounded</span></article>
<article><b>AUTHORITY</b><span>Owner controlled</span></article><article><b>EVIDENCE</b><span>Receipt backed</span></article></section></main>
<footer>Cyryx Labs · Onyx</footer><script src="app.js" defer></script></body></html>
""".format(
            title=html.escape(title_value), summary=html.escape(summary_value),
            action=html.escape(action_value), label=html.escape(label),
        )
        css_text = """:root{color-scheme:dark;--onyx:#050607;--obsidian:#0A0D0F;--graphite:#11161A;--gunmetal:#1B2227;--steel:#8C949E;--silver:#C7C9CC;--teal:#0F6B68;--glow:#19C7C0}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% 18%,#0f2425 0,var(--onyx) 36%);color:var(--silver);font:16px/1.6 Inter,system-ui,sans-serif;min-height:100vh}header,footer{display:flex;justify-content:space-between;padding:24px 6vw;color:var(--steel);font:12px monospace;letter-spacing:.15em;border-color:var(--gunmetal)}header{border-bottom:1px solid var(--gunmetal)}footer{border-top:1px solid var(--gunmetal)}.mark,.eyebrow{color:var(--glow)}main{width:min(1100px,88vw);margin:14vh auto}.eyebrow{font:12px monospace;letter-spacing:.2em}h1{max-width:850px;font-size:clamp(42px,8vw,104px);line-height:.95;letter-spacing:-.05em;margin:.25em 0}.summary{max-width:680px;color:var(--steel);font-size:clamp(18px,2vw,24px)}button{margin:30px 0 70px;padding:15px 23px;border:1px solid var(--glow);background:var(--teal);color:white;border-radius:3px;font-weight:700}button:focus-visible,a:focus-visible{outline:3px solid var(--glow);outline-offset:4px}section{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--gunmetal)}article{display:flex;flex-direction:column;padding:24px;background:var(--obsidian)}article b{font:12px monospace;color:var(--glow)}article span{color:var(--steel)}.skip{position:absolute;left:-9999px}.skip:focus{left:12px;top:12px;background:var(--silver);color:var(--onyx);padding:8px;z-index:10}@media(max-width:700px){section{grid-template-columns:1fr}main{margin:10vh auto}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important}}
"""
        js_text = """'use strict';document.getElementById('primary').addEventListener('click',()=>{document.getElementById('primary').setAttribute('aria-pressed','true');});
"""
        source = (("index.html", html_text), ("styles.css", css_text), ("app.js", js_text))
        files = tuple(SiteRecipeFileV1(path, content, hashlib.sha256(content.encode()).hexdigest()) for path, content in source)
        payload = {"recipe_id": recipe_id, "project_slug": project_slug,
                   "files": [(x.relative_path, x.sha256) for x in files]}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return SiteRecipePlanV1(
            recipe_id, project_slug, files, digest,
            ("site_files_verified", "site_accessibility_checked", "site_preview_verified"),
        )


__all__ = ["FEATURE_FLAG", "PALETTE", "SiteRecipeFileV1", "SiteRecipePlanV1",
           "SiteRecipeCatalogV1", "SiteRecipeContractError", "SiteRecipeDenied"]
