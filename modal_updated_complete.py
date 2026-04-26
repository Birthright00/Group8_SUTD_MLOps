"""
Complete Modal deployment for Interior Design AI.

Pipeline (chained — chatbot now feeds FLUX, no longer a side-channel):

    [image + user style prompt]
        |
        v
    VisionModel                  (Qwen2.5-VL-7B + VL LoRA, A100-40GB)
        analyze_image        --> detected objects
        generate_edits       --> edit_suggestions (draft, per-object)
        |
        v
    InteriorChatbot              (Qwen2.5-1.5B + CHATBOT_QWEN_ADAPTOR, A100-40GB)
        review_edit_plan     --> design_review.review_markdown
                                 (structured per-object critique with materials,
                                  textures, colours, lighting)
        |
        |   extract_polished_prompts()
        |       parses the markdown's "Proposed:" lines
        |       into polished_prompts = {object: enriched_fill_prompt}
        |       misses fall back to raw VLM suggestion per-object
        v
    fill_prompts = {**edit_suggestions, **polished_prompts}  <-- what FLUX sees
        |
        v
    ImageGenerator               (FLUX.1-Fill-dev + Grounding DINO + SAM2, A100-80GB)
        edit_multiple_objects_sequential
            for each object:
                Grounding DINO -> box
                SAM2           -> mask
                FLUX           -> INPAINT_CFG.iterations_per_object refinement passes
                                  (seed = INPAINT_CFG.seed + i)
                next object starts from this object's final pass
        |
        v
    edited_images { object_order, object_intermediates, iteration_details, final }

All FLUX / mask / iteration knobs are centralised in INPAINT_CFG (InpaintConfig
dataclass below) so tuning happens in one place instead of across ~10 call sites.

Endpoints:
    POST /complete_pipeline   full chain, optionally generates images
    POST /analyze             vision + chatbot + one-object image edit
    POST /edit_image          direct detection -> segmentation -> inpainting
    POST /chat                standalone chatbot

Usage:
    modal deploy modal_updated_complete.py
"""

import modal
import os
from dataclasses import dataclass
from pathlib import Path

# ============================================================================
# APP SETUP
# ============================================================================

app = modal.App("interior-design-complete")

# ============================================================================
# IMAGES & MOUNTS
# ============================================================================

# Model IDs
VISION_MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"
CHATBOT_MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
FLUX_MODEL_ID = "black-forest-labs/FLUX.1-Fill-dev"
GROUNDING_DINO_ID = "IDEA-Research/grounding-dino-base"
SAM2_ID = "facebook/sam2-hiera-small"


# ----------------------------------------------------------------------------
# Inpainting configuration — single source of truth. Change a value here and
# every FLUX / mask call site below picks it up. Keep the mask fields in sync
# with interior_image_generator/pipeline/settings.py so local and Modal runs
# produce comparable outputs.
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class InpaintConfig:
    # FLUX.1-Fill-dev
    num_inference_steps: int = 28
    guidance_scale: float = 30.0
    max_sequence_length: int = 512
    resolution: int = 1024
    seed: int = 42

    # Mask preprocessing
    mask_dilation_px: int = 8
    crop_padding: float = 0.25

    # Refinement passes over the same mask per object
    iterations_per_object: int = 10


INPAINT_CFG = InpaintConfig()

# ----------------------------------------------------------------------------
# Per-style guidance used to build both the chatbot system prompt AND the
# structured analysis prompt. The key is matched case-insensitively against
# substrings of the user's prompt ("Japanese themed house" -> "japanese").
# Unknown prompts fall back to STYLE_GUIDANCE_FALLBACK, which keeps the output
# structure intact but drops style-specific vocabulary.
#
# To add a new style, drop another entry into this dict — no other changes
# needed; resolve_style_guidance + build_chatbot_system_prompt + build_analysis_prompt
# all read from here.
# ----------------------------------------------------------------------------
STYLE_GUIDANCE = {
    "japanese": {
        "authenticity": "Japanese design authenticity (wabi-sabi, shibui, ma)",
        "material_examples": "washi paper, undyed ramie linen, hinoki cypress, urushi lacquer, tatami rush, sugi cedar, raw cotton",
        "finish_examples": "matte grain, urushi satin lacquer, diffused shoji-filtered glow, hand-brushed patina",
        "colour_examples": "warm off-white, weathered ash-grey, indigo (ai-zome), cedar brown, sumi black",
        "cultural_ref": "Japanese",
        # Culturally-specific furniture forms a rewrite can reference instead of
        # Western silhouettes. Use these to anchor the description in Japan,
        # e.g. a "sofa" might become a low tatami platform with zabuton cushions.
        "furniture_forms": (
            "chabudai (low table), zabuton (floor cushion), zaisu (legless chair), "
            "shoji screen, byobu (folding screen), tansu chest, kotatsu (heated table), "
            "tatami mat, noren curtain, tokonoma alcove, fusuma sliding panel"
        ),
        # Design principles to invoke so the sentence reads as culturally grounded
        # rather than "Western object + Japanese materials".
        "design_concepts": (
            "wabi-sabi (beauty in imperfection), ma (intentional negative space), "
            "shibui (elegant simplicity), kanso (simplicity), mottainai (respect for materials)"
        ),
    },
    "scandinavian": {
        "authenticity": "Scandinavian design authenticity (hygge, functionalism, lagom)",
        "material_examples": "light oak, ash, birch, undyed wool, linen, sheepskin",
        "finish_examples": "pale matte finish, soft velvet, brushed steel, whitewashed grain",
        "colour_examples": "chalk white, pale grey, muted sage, warm beige, smoky blue",
        "cultural_ref": "Nordic",
        "furniture_forms": (
            "tapered-leg armchair, slat-back bench, light-wood credenza, "
            "Danish cord seat, woollen throw, woven rya rug, pendant globe lamp"
        ),
        "design_concepts": (
            "hygge (cosy contentment), lagom (balanced restraint), "
            "functionalism (honest materials, no ornament), democratic design"
        ),
    },
    "industrial": {
        "authenticity": "industrial design authenticity (utilitarian, exposed structure)",
        "material_examples": "blackened steel, raw concrete, reclaimed brick, patinated leather, salvaged timber",
        "finish_examples": "matte powder coat, polished concrete, weathered metal, oxidised brass",
        "colour_examples": "graphite, rust, oxidised copper, charcoal, bone white",
        "cultural_ref": "industrial / warehouse",
        "furniture_forms": (
            "riveted steel frame, cast-iron pipe shelving, factory cart, "
            "trestle table, rolling caster base, Edison-bulb pendant, tolix stool"
        ),
        "design_concepts": (
            "exposed structure (beams, ducts, pipework), honest utility, "
            "adaptive reuse of salvage, patina as aesthetic"
        ),
    },
    "minimalist": {
        "authenticity": "minimalist design authenticity (restraint, negative space)",
        "material_examples": "honed plaster, matte lacquer, pale stone, raw linen, travertine",
        "finish_examples": "ultra-matte, honed, soft-touch, brushed chalk",
        "colour_examples": "chalk white, warm greige, pale limestone, soft ivory",
        "cultural_ref": "minimalist",
        "furniture_forms": (
            "low monolithic bench, single-slab plinth, recessed niche, "
            "handle-free cabinetry, floating shelf, paper pendant, tonal tapestry"
        ),
        "design_concepts": (
            "negative space as subject, tonal palette, reduction to essentials, "
            "continuous surface, one statement gesture per room"
        ),
    },
    "bohemian": {
        "authenticity": "bohemian design authenticity (layered textures, eclectic sources)",
        "material_examples": "rattan, jute, hand-loomed cotton, terracotta, brass, macramé",
        "finish_examples": "woven grain, hammered metal, hand-glazed ceramic, patinated wood",
        "colour_examples": "rust, ochre, saffron, deep teal, warm terracotta",
        "cultural_ref": "bohemian / globally-inspired",
        "furniture_forms": (
            "peacock chair, kilim rug, macramé wall hanging, pouf ottoman, "
            "carved teak chest, hanging rattan pendant, layered textile throw"
        ),
        "design_concepts": (
            "layered textiles, mixed cultural references, plants as structure, "
            "collected over curated, warm lived-in imperfection"
        ),
    },
}

STYLE_GUIDANCE_FALLBACK = {
    "authenticity": "the user's chosen design style",
    "material_examples": "specific species of wood, weave type, or stone variety",
    "finish_examples": "matte, satin, brushed, or polished",
    "colour_examples": "specific named colours with undertones",
    "cultural_ref": "the user's target style",
}

STYLE_ALIASES = {
    "japanese": ("japan", "japandi", "zen", "wabi", "shoji", "tatami"),
    "scandinavian": ("scandi", "nordic", "danish", "swedish", "finnish"),
    "industrial": ("loft", "warehouse", "brutalist"),
    "minimalist": ("minimal", "clean lines", "pared back"),
    "bohemian": ("boho", "eclectic", "global", "artisan"),
}


def resolve_style_key(user_prompt: str) -> str | None:
    """Return the canonical style key detected from the user's prompt, if any."""
    lowered = (user_prompt or "").lower()
    for key in STYLE_GUIDANCE:
        if key in lowered:
            return key
    for key, aliases in STYLE_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return key
    return None


def resolve_style_guidance(user_prompt: str) -> dict:
    """Pick a style guidance block by scanning the user's prompt for a known style keyword or alias.

    NOTE: Style guidance disabled - letting the fine-tuned chatbot generate its own vocabulary.
    To re-enable, uncomment the lines below.
    """
    # style_key = resolve_style_key(user_prompt)
    # if style_key:
    #     return STYLE_GUIDANCE[style_key]
    return STYLE_GUIDANCE_FALLBACK


def build_chatbot_system_prompt(user_prompt: str) -> str:
    """Style-specific chatbot system prompt, built from STYLE_GUIDANCE."""
    guidance = resolve_style_guidance(user_prompt)
    style_key = resolve_style_key(user_prompt) or "custom"
    return (
        "You are an expert interior design consultant.\n"
        f"Target style family: {style_key}.\n"
        f"Review the proposed redesign with a focus on material specificity, {guidance['authenticity']}, "
        "renderability for a 3D workflow, tactile visual detail, and preserving each object's original identity "
        "and function. Follow the user's required output structure exactly."
    )


def build_object_fallback_prompt(user_prompt: str, object_name: str, object_desc: str) -> str:
    """Create a richer fallback prompt than '<style> style <object>' when generation fails."""
    guidance = resolve_style_guidance(user_prompt)
    return (
        f"{object_name} redesigned for {user_prompt}, keeping the object's role and overall proportions from "
        f"the original ({object_desc}) while changing the visible materials to specific options such as "
        f"{guidance['material_examples']}, using {guidance['finish_examples']}, and a palette of "
        f"{guidance['colour_examples']}"
    )


def build_edit_generation_prompt(user_prompt: str, objects: dict) -> str:
    """Prompt the VLM to emit stable, per-object JSON drafts that the chatbot can polish.

    The VLM's LoRA is fine-tuned for object description, not style transformation,
    so the prompt has to be aggressive about demanding a FULL re-description in
    the target style — otherwise the model takes the easy path of appending one
    material term to the original description ("<original> with <style> finish").
    """
    guidance = resolve_style_guidance(user_prompt)
    style_key = resolve_style_key(user_prompt) or "custom"
    object_list = "\n".join([f"- {obj}: {desc}" for obj, desc in objects.items()])
    example_object, example_desc = next(iter(objects.items()))

    # Concrete worked example so the model understands we want a full rewrite,
    # not a suffix-append. Uses the user's actual style vocabulary.
    example_rewrite = (
        f"{example_object} reimagined as a {style_key}-style {example_object}, "
        f"crafted from {guidance['material_examples'].split(',')[0].strip()} "
        f"with {guidance['finish_examples'].split(',')[0].strip()} surfaces, "
        f"in {guidance['colour_examples'].split(',')[0].strip()} tones"
    )

    return f"""You are rewriting every object in a room to match a target interior design style.

Target user request: "{user_prompt}"
Canonical style family: {style_key}
Authenticity framing: {guidance['authenticity']}

Current objects (name: current description):
{object_list}

Task — for EVERY object above, write ONE NEW sentence describing that object
as if it belonged in an authentic {style_key} room. This is a REWRITE, not an
edit of the current description. Do not copy or append to the current wording.

Every sentence MUST explicitly name at least one of each:
  - material (choose from or similar to: {guidance['material_examples']})
  - finish / surface quality (choose from or similar to: {guidance['finish_examples']})
  - colour (choose from or similar to: {guidance['colour_examples']})

Constraints:
- Keep the object in the same functional category ({example_object} stays a {example_object}; do not turn a sofa into a bench).
- Do not reuse the literal wording of the current description.
- Do not produce suffix-append outputs like "<current description> with <X> finish" — that is FORBIDDEN.
- Avoid vague words: "nice", "beautiful", "stylish", "modern", "natural wood", "fabric", "traditional style", "cozy".
- Each sentence must be renderable by an image model — concrete, visual, material-specific.

Good example of the expected style (shape of output, not content to copy):
  "{example_object}": "{example_rewrite}"

Bad examples (DO NOT produce these):
  "{example_object}": "{example_desc} with matte finish"   <- just appending, forbidden
  "{example_object}": "beautiful {style_key} {example_object}"   <- vague, forbidden

Output rules:
- Return ONLY valid JSON, no markdown, no code fences, no commentary.
- Include every object key exactly once, spelled identically.
- Each value is a single rich descriptive sentence (≈15–30 words).

JSON shape:
{{
  "{example_object}": "..."
}}
"""


def _is_suffix_append(candidate: str, original_desc: str) -> bool:
    """True when the VLM lazily produced "<original description> + <suffix>".

    The VLM's default failure mode is keeping the original description verbatim
    at the start of the sentence and tacking on a material/finish suffix
    ("framed picture leaning against the wall with diffused warm glow finish").
    We flag that pattern only — a legitimate rewrite that happens to reuse an
    object noun somewhere in the middle of a new sentence is fine.
    """
    if not original_desc:
        return False
    cand = " ".join(candidate.lower().split())
    orig = " ".join(original_desc.lower().split())
    if len(orig) < 10:  # too short to be a reliable signal
        return False
    return cand.startswith(orig)


def _is_style_poor(cleaned: str, user_prompt: str, guidance: dict) -> bool:
    """True when the candidate fails to name a style-specific material/finish/colour.

    At least one of the style's concrete vocabulary words must appear somewhere
    in the sentence, otherwise the VLM produced a generic sentence that ignores
    the selected style (Japanese / Scandinavian / etc.).
    """
    text = cleaned.lower()
    # Collect concrete words from the style's guidance block.
    vocab_parts = [
        guidance.get("material_examples", ""),
        guidance.get("finish_examples", ""),
        guidance.get("colour_examples", ""),
    ]
    tokens = set()
    for part in vocab_parts:
        for phrase in part.split(","):
            phrase = phrase.strip().lower()
            if phrase:
                tokens.add(phrase)
    if not tokens:
        return False
    # Accept if any style token (or a standalone word from a multi-word phrase)
    # shows up in the sentence.
    for phrase in tokens:
        if phrase in text:
            return False
        for word in phrase.split():
            if len(word) > 3 and word in text:
                return False
    # As a last chance, accept if the style key itself (e.g. "japanese") is named.
    style_key = (resolve_style_key(user_prompt) or "").lower()
    if style_key and style_key in text:
        return False
    return True


def parse_edit_suggestions_json(output_text: str, objects: dict, user_prompt: str) -> dict:
    """Parse model JSON robustly and backfill missing / weak / style-poor entries.

    A candidate survives only if it:
      1. Parses as a non-empty string,
      2. Contains no generic filler ("beautiful", "modern", ...),
      3. Is not just the original description with a suffix appended,
      4. Names at least one concrete material/finish/colour from the style vocabulary.
    Anything else falls through to `build_object_fallback_prompt`, which produces
    a guaranteed style-themed sentence.
    """
    import json
    import re

    guidance = resolve_style_guidance(user_prompt)

    if not output_text:
        return {
            obj: build_object_fallback_prompt(user_prompt, obj, desc)
            for obj, desc in objects.items()
        }

    candidates = []
    fenced = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", output_text, re.IGNORECASE)
    candidates.extend(fenced)

    start = output_text.find("{")
    end = output_text.rfind("}") + 1
    if start != -1 and end > start:
        candidates.append(output_text[start:end])

    parsed = {}
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                break
        except (json.JSONDecodeError, ValueError):
            continue

    normalized = {}
    generic_terms = ("beautiful", "nice", "stylish", "modern", "traditional style", "natural wood", "fabric", "cozy")
    for obj, desc in objects.items():
        raw_value = parsed.get(obj) if isinstance(parsed, dict) else None
        if isinstance(raw_value, dict):
            raw_value = (
                raw_value.get("prompt")
                or raw_value.get("description")
                or raw_value.get("proposed")
            )
        accepted = False
        if isinstance(raw_value, str):
            cleaned = " ".join(raw_value.split()).strip()
            if cleaned:
                lowered = cleaned.lower()
                has_generic = any(term in lowered for term in generic_terms)
                suffix_appended = _is_suffix_append(cleaned, desc)
                style_poor = _is_style_poor(cleaned, user_prompt, guidance)
                if not has_generic and not suffix_appended and not style_poor:
                    normalized[obj] = cleaned
                    accepted = True
                else:
                    reasons = []
                    if has_generic:
                        reasons.append("generic-term")
                    if suffix_appended:
                        reasons.append("suffix-append")
                    if style_poor:
                        reasons.append("no-style-vocab")
                    print(f"[WARN] VLM draft for '{obj}' rejected ({', '.join(reasons)}): {cleaned!r}")
        if not accepted:
            normalized[obj] = build_object_fallback_prompt(user_prompt, obj, desc)

    return normalized


def build_vlm_output(
    image_path: str,
    user_prompt: str,
    vision_output: dict,
    edit_suggestions: dict,
) -> dict:
    """Normalize step 1 outputs into the structured payload expected by step 2."""
    object_notes = vision_output.get("objects", {})
    room_type = vision_output.get("room_type", "room")
    scene_style = vision_output.get("scene_style", "unknown")

    return {
        "image_path": image_path,
        "user_prompt": user_prompt,
        "style_key": resolve_style_key(user_prompt) or "custom",
        "vision_output": {
            "objects": list(object_notes.keys()),
            "room_type": room_type,
            "scene_style": scene_style,
            "object_notes": object_notes,
        },
        "edit_plan": {
            "global_style": user_prompt,
            "edits": [
                {"object": obj, "description": desc}
                for obj, desc in edit_suggestions.items()
            ],
        },
    }


POLISH_JSON_OPEN = "<<<POLISH_JSON>>>"
POLISH_JSON_CLOSE = "<<<END_POLISH_JSON>>>"


def build_analysis_prompt(vlm: dict) -> str:
    """Build the structured rewrite prompt for the chatbot model.

    **JSON-first, short-summary-second** structure. The chatbot emits, in order:
      1. The `<<<POLISH_JSON>>> { ... } <<<END_POLISH_JSON>>>` block — one
         rich, culturally-grounded sentence per object. This is the primary
         signal for `extract_polished_prompts` and feeds FLUX.
      2. A short `### Summary` paragraph (3–4 sentences) describing the room's
         overall palette, light quality, and sensory mood. Rendered in the
         ExpertCritique panel.

    **Why the VLM draft is NOT shown to the chatbot:** earlier versions fed the
    VLM's `proposed edit` into this prompt as context. A 1.5B model reads that
    as "here is the answer, echo it" and the chatbot column in the UI ended up
    byte-identical to the VLM column for ~12/13 rows. Withholding the draft
    forces the chatbot to produce an independent rewrite using its own trained
    design vocabulary, so the two columns actually diverge.

    **Why the history behind this prompt:** for rooms with many detected
    objects (~10+), the earlier per-object markdown review blew through the
    1400-token budget before the JSON sentinel ever got emitted, so
    `polished_prompts` came back empty. Putting JSON first + dropping the
    verbose per-object markdown (now redundant with the Suggested Edits table)
    fixes that truncation.
    """
    vout = vlm["vision_output"]
    prompt = vlm["user_prompt"]
    style_key = vlm.get("style_key", "custom")

    object_notes = vout.get("object_notes", {})
    # Only show the chatbot the object NAME and CURRENT description. Do NOT
    # include the VLM's proposed edit — otherwise the chatbot copies it.
    objects_block = "\n".join(
        f"  - {obj} (currently: {desc})"
        for obj, desc in object_notes.items()
    )
    object_names = list(object_notes.keys())
    json_skeleton = ",\n  ".join(f'"{obj}": "..."' for obj in object_names)

    guidance = resolve_style_guidance(prompt)
    furniture_forms = guidance.get("furniture_forms", "")
    design_concepts = guidance.get("design_concepts", "")

    # Build optional anchoring blocks only if the active style provides them,
    # so the fallback style block keeps working without extra fields.
    anchoring_lines = []
    if furniture_forms:
        anchoring_lines.append(
            f"Culturally-specific forms for anchoring (use when the object "
            f"can plausibly become one): {furniture_forms}."
        )
    if design_concepts:
        anchoring_lines.append(
            f"Design principles to invoke where natural: {design_concepts}."
        )
    anchoring_block = ("\n".join(anchoring_lines) + "\n\n") if anchoring_lines else ""

    return (
        f"You are an expert {guidance['cultural_ref']} interior designer producing "
        f"per-object fill prompts for an image-editing pipeline.\n"
        f"Target style family: {style_key}. Authenticity framing: {guidance['authenticity']}.\n"
        f"The user wants: \"{prompt}\"\n\n"
        f"Room: {vout['room_type']} (currently {vout['scene_style']}).\n"
        f"Objects detected (name and current description):\n{objects_block}\n\n"
        f"Your task: REWRITE each object as it would appear in an authentic "
        f"{guidance['cultural_ref']} room. Produce ONE new descriptive sentence "
        f"per object — do NOT echo the current description, do NOT just append "
        f"a material to it. Each sentence must read as CULTURALLY ANCHORED, not "
        f"a Western silhouette with imported materials.\n\n"
        f"Every sentence MUST name at least one material "
        f"(e.g. {guidance['material_examples']}), one finish "
        f"(e.g. {guidance['finish_examples']}), and one colour "
        f"(e.g. {guidance['colour_examples']}).\n"
        f"{anchoring_block}"
        f"When the object plausibly maps to a culturally-specific form, use that "
        f"form instead of the Western name (e.g. a low coffee table becomes a "
        f"chabudai; a floor cushion becomes a zabuton). Keep the object "
        f"recognisably serving its original function.\n\n"
        f"Produce TWO sections in this EXACT order. Emit SECTION 1 FIRST — it "
        f"is the most important output and must not be truncated.\n\n"
        f"SECTION 1 — Machine-readable polished prompts. Emit EXACTLY:\n\n"
        f"{POLISH_JSON_OPEN}\n"
        f"{{\n  {json_skeleton}\n}}\n"
        f"{POLISH_JSON_CLOSE}\n\n"
        f"Every object key above MUST appear exactly once in the JSON, spelled "
        f"identically. Each value is ONE concise sentence (≈18–28 words) that "
        f"reads as {guidance['cultural_ref']}-native.\n\n"
        f"SECTION 2 — After the closing sentinel, write a ### Summary paragraph: "
        f"3–4 sentences describing the complete room's overall palette, light "
        f"quality, and sensory mood in the {guidance['cultural_ref']} idiom. "
        f"No per-object breakdown — this is a holistic summary.\n\n"
        f"FORBIDDEN: echoing the current description ('a sheer white curtain "
        f"covering the window, with ...'); using generic terms ('natural wood', "
        f"'fabric', 'soft material', 'traditional style', 'modern', 'minimalist' "
        f"as the sole qualifier); leaving out any of material/finish/colour.\n"
    )


def _repair_json(raw_json: str) -> str:
    """
    Attempt to repair common JSON malformations from LLM output.

    Fixes:
      - Missing commas between key-value pairs (e.g., `"a": "b" "c": "d"`)
      - Trailing commas before closing braces
      - Truncated strings (adds closing quote)
      - Truncated objects (adds closing brace)
    """
    import re

    s = raw_json.strip()

    # Fix missing commas: `"value" "key"` → `"value", "key"`
    # Pattern: end of string value followed by start of new key without comma
    s = re.sub(r'"\s*\n\s*"', '",\n"', s)
    s = re.sub(r'"\s+"(?=[a-zA-Z_])', '", "', s)

    # Fix trailing commas before closing brace
    s = re.sub(r',\s*}', '}', s)

    # Handle truncated output: count quotes to see if we need to close a string
    quote_count = s.count('"') - s.count('\\"')
    if quote_count % 2 == 1:
        # Odd number of quotes — string was truncated, close it
        s = s.rstrip() + '"'

    # Ensure object is closed
    open_braces = s.count('{')
    close_braces = s.count('}')
    if open_braces > close_braces:
        s = s.rstrip().rstrip(',') + '}' * (open_braces - close_braces)

    return s


def extract_polished_prompts(
    review_markdown: str,
    objects,
    edit_suggestions: dict | None = None,
    user_prompt: str | None = None,
) -> dict:
    """
    Pull per-object polished prompts out of the chatbot's structured review.

    Two parse paths, tried in order:
      1. Sentinel JSON block: <<<POLISH_JSON>>> { ... } <<<END_POLISH_JSON>>>
         (what the current prompt explicitly asks for — most reliable).
      2. Markdown fallback: each object rendered as
            **<object>:**
            - Original: ...
            - Proposed: <rich sensory description>
         We scan for `Proposed:` per object. Kept for older deploys / format drift.

    **Quality gate**: if `edit_suggestions` and `user_prompt` are supplied, each
    candidate is also checked for:
      - byte-identity with the VLM draft (chatbot just copied → drop),
      - style-poor output (no material/finish/colour vocab from the active
        STYLE_GUIDANCE block → drop).
    Dropped entries fall back to the VLM draft in the UI (greyed italic), which
    at least guarantees the fallback template's rich style-themed sentence.

    Returns {object: polished_text} only for objects that parsed successfully
    AND passed the quality gate. Logs a warning per miss/drop so drift is
    visible in Modal logs.
    """
    import json
    import re

    polished = {}
    guidance = resolve_style_guidance(user_prompt or "") if user_prompt is not None else None

    def _accept_polished(obj: str, cleaned: str) -> bool:
        """Shared quality gate for both JSON and regex parse paths."""
        if not cleaned or cleaned.startswith("..."):
            return False
        if edit_suggestions is not None:
            vlm_draft = edit_suggestions.get(obj)
            if isinstance(vlm_draft, str):
                if " ".join(vlm_draft.split()).strip().lower() == cleaned.lower():
                    print(f"[WARN] Chatbot polish for '{obj}' is identical to VLM draft — dropping (UI will fall back to VLM)")
                    return False
        if user_prompt is not None and guidance is not None:
            if _is_style_poor(cleaned, user_prompt, guidance):
                print(f"[WARN] Chatbot polish for '{obj}' has no style vocabulary — dropping: {cleaned!r}")
                return False
        return True

    # --- Path 1: sentinel JSON block ---
    json_match = re.search(
        re.escape(POLISH_JSON_OPEN) + r"\s*(\{[\s\S]*?\})\s*" + re.escape(POLISH_JSON_CLOSE),
        review_markdown,
    )
    if json_match:
        raw_json = json_match.group(1)
        blob = None

        # Try parsing raw JSON first
        try:
            blob = json.loads(raw_json)
        except (json.JSONDecodeError, ValueError) as exc:
            # Attempt repair and retry
            print(f"[INFO] JSON parse failed ({exc}); attempting repair...")
            try:
                repaired = _repair_json(raw_json)
                blob = json.loads(repaired)
                print("[INFO] JSON repair successful")
            except (json.JSONDecodeError, ValueError) as exc2:
                print(f"[WARN] JSON repair also failed ({exc2}); falling back to markdown regex")

        if isinstance(blob, dict):
            for obj in objects:
                value = blob.get(obj)
                if isinstance(value, str):
                    cleaned = " ".join(value.split()).strip()
                    if _accept_polished(obj, cleaned):
                        polished[obj] = cleaned

    # --- Path 2: markdown regex (fills gaps only) ---
    for obj in objects:
        if obj in polished:
            continue
        # Match **obj:** / **[obj]:** / **obj**: (case-insensitive), then the
        # Proposed: line, capturing up to the next bullet/section/blank-line.
        header = rf"\*\*\s*\[?{re.escape(obj)}\]?\s*:?\s*\*\*"
        pattern = (
            header
            + r"[\s\S]*?-\s*Proposed:\s*"
            + r"(.+?)"
            + r"(?=\n\s*-\s|\n\s*####|\n\s*\*\*|\n\s*\n|\Z)"
        )
        m = re.search(pattern, review_markdown, re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        text = " ".join(m.group(1).split())
        if text.startswith("["):
            continue  # literal template echo
        if _accept_polished(obj, text):
            polished[obj] = text

    for obj in objects:
        if obj not in polished:
            print(f"[WARN] Chatbot did not polish '{obj}' — falling back to raw VLM suggestion")

    return polished


def strip_polish_sentinel(review_markdown: str) -> str:
    """Remove the machine-readable JSON block from the review markdown.

    The chatbot emits the `<<<POLISH_JSON>>> ... <<<END_POLISH_JSON>>>` block
    at the HEAD of its output (so it survives even if generation is truncated),
    followed by the human-readable ### Summary section. ExpertCritique should
    show only the Summary, so we cut from the opening sentinel up to and
    including the closing sentinel (plus any trailing whitespace) and return
    whatever comes after.

    If the closing sentinel is missing (chatbot truncated or drifted format),
    we fall back to stripping from the opening sentinel onward — better to
    lose the summary than to leak raw JSON into the UI.
    """
    if not review_markdown:
        return review_markdown
    open_idx = review_markdown.find(POLISH_JSON_OPEN)
    if open_idx == -1:
        return review_markdown
    close_idx = review_markdown.find(POLISH_JSON_CLOSE, open_idx + len(POLISH_JSON_OPEN))
    if close_idx == -1:
        return review_markdown[:open_idx].rstrip()
    head = review_markdown[:open_idx].rstrip()
    tail = review_markdown[close_idx + len(POLISH_JSON_CLOSE):].lstrip()
    if head and tail:
        return f"{head}\n\n{tail}"
    return head or tail


def log_chatbot_polish(review_markdown: str, edit_suggestions: dict, polished: dict, fill_prompts: dict) -> None:
    """
    Emit a detailed before/after trace of the chatbot polish step.

    Purpose: let you verify, from Modal logs alone, that the chatbot's
    style-specific output is actually what FLUX receives. If rendered images
    don't look like the chosen style, the log block here tells you whether
    the chatbot drifted format (empty `polished`) or FLUX ignored a rich prompt.
    """
    markdown_len = len(review_markdown)
    preview_limit = 2000
    preview = review_markdown[:preview_limit]
    truncated_note = f"\n... [truncated — full length {markdown_len} chars]" if markdown_len > preview_limit else ""

    print("=" * 70)
    print(f"[CHATBOT IN]  edit_suggestions ({len(edit_suggestions)} objects):")
    for obj, draft in edit_suggestions.items():
        print(f"               - {obj}: {draft}")

    print(f"[CHATBOT RAW] review_markdown ({markdown_len} chars):")
    if markdown_len == 0:
        print("               <EMPTY — chatbot produced no output; check review_edit_plan>")
    else:
        for line in (preview + truncated_note).splitlines():
            print(f"               {line}")

    print(f"[CHATBOT OUT] polished_prompts ({len(polished)}/{len(edit_suggestions)} parsed):")
    if not polished:
        print("               <EMPTY — regex did not match any object header + Proposed: line>")
    for obj, polished_text in polished.items():
        print(f"               - {obj}: {polished_text}")

    print(f"[CHATBOT → FLUX] fill_prompts (what FLUX actually receives):")
    for obj, prompt in fill_prompts.items():
        source = "polished" if obj in polished else "VLM fallback"
        print(f"               - {obj} [{source}]: {prompt}")
    print("=" * 70)


# Model download functions for build time
def download_vision_models():
    from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
    Qwen2_5_VLForConditionalGeneration.from_pretrained(
        VISION_MODEL_ID,
        cache_dir="/cache"
    )
    AutoProcessor.from_pretrained(VISION_MODEL_ID, cache_dir="/cache")

def download_chatbot_models():
    from transformers import AutoModelForCausalLM, AutoTokenizer
    AutoModelForCausalLM.from_pretrained(CHATBOT_MODEL_ID, cache_dir="/cache")
    AutoTokenizer.from_pretrained(CHATBOT_MODEL_ID, cache_dir="/cache")

def download_flux_models():
    import os
    from diffusers import FluxFillPipeline
    # Use HF_TOKEN from environment for gated model access
    token = os.getenv("HF_TOKEN")
    FluxFillPipeline.from_pretrained(
        FLUX_MODEL_ID,
        cache_dir="/cache",
        token=token
    )

# Image for VLM and Chatbot with LoRA adapters
llm_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "fastapi[standard]",
        "torch",
        "torchvision",
        "transformers>=4.45.0",
        "qwen-vl-utils",
        "peft",
        "accelerate",
        "bitsandbytes",
        "pillow",
    )
    .run_function(download_vision_models)
    .run_function(download_chatbot_models)
    .add_local_dir("qwen25_vl_7b_objdesc_lora", "/root/qwen25_vl_7b_objdesc_lora")
    .add_local_dir("qwen-interior-design-qlora/final-adapter", "/root/chatbot_adapter")
)

# Image for Image Generator (detection + segmentation + inpainting)
image_gen_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "fastapi[standard]",
        "torch>=2.1.0",
        "torchvision>=0.16.0",
        "diffusers>=0.31.0",
        "transformers>=4.45.0",
        "accelerate",
        "safetensors",
        "Pillow",
        "numpy",
        "pydantic>=2.0.0",
        "requests",
    )
    .run_function(download_flux_models, secrets=[modal.Secret.from_dotenv(path="interior_image_generator/.env")])
    .add_local_dir("interior_image_generator", "/root/interior_image_generator")
)

# ============================================================================
# 1. VISION MODEL (VL-7B + VL_LORA)
# ============================================================================

@app.cls(
    image=llm_image,
    gpu="A100-40GB",
    timeout=600,
    scaledown_window=300,
)
class VisionModel:
    """
    Qwen2.5-VL-7B + VL LoRA, running on A100-40GB.

    Two responsibilities:
      analyze_image   — detect household objects from a photo.
      generate_edits  — draft a per-object "transform to this style" plan.

    Uses 4-bit NF4 quantisation (via bitsandbytes) so the 7B model fits in 40GB VRAM
    alongside the VL processor.
    """

    @modal.enter()
    def load_model(self):
        import torch
        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
        from peft import PeftModel
        from qwen_vl_utils import process_vision_info

        print("[LOAD] Loading Qwen2.5-VL-7B with VL_LORA...")

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

        base_model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            VISION_MODEL_ID,
            quantization_config=bnb_config,
            device_map="auto",
            cache_dir="/cache"
        )

        self.model = PeftModel.from_pretrained(
            base_model,
            "/root/qwen25_vl_7b_objdesc_lora"
        )
        self.model.eval()

        self.processor = AutoProcessor.from_pretrained(VISION_MODEL_ID, cache_dir="/cache")
        self.process_vision_info = process_vision_info

        print("[DONE] Vision model loaded!")

    @modal.method()
    def analyze_image(self, image_bytes: bytes) -> dict:
        """
        Run object detection on a room photo.

        Args:
            image_bytes: raw bytes of a JPEG/PNG image.

        Returns:
            {
                "objects":     {name: description, ...},  # parsed objects in detection order
                "room_type":   str,                       # currently hardcoded to "bedroom"
                "scene_style": str,                       # currently hardcoded to "unknown"
                "raw_output":  str,                       # unparsed VLM text, for debugging
            }
        Output is heuristically parsed from the VLM's free-form "<name>: <desc>" lines —
        invalid lines (no colon, numeric prefixes, sentences) are filtered out below.
        """
        import re
        import torch
        from PIL import Image
        import io

        image = Image.open(io.BytesIO(image_bytes))

        prompt = """Identify all household objects and furniture in this image.

Output ONLY in this exact format (no introduction, no preamble):
object_name: detailed visual description

Example:
sofa: modern grey sectional with cushions
table: wooden coffee table with glass top"""

        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt}
            ]
        }]

        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = self.process_vision_info(messages)
        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt"
        ).to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(**inputs, max_new_tokens=256, do_sample=False)

        output_text = self.processor.batch_decode(
            output_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0].split("assistant\n")[-1].strip()

        # Parse the free-form "<object>: <description>" lines into a dict.
        objects = {}
        for line in output_text.split('\n'):
            line = line.strip()

            # Skip empty lines
            if not line:
                continue

            # Only process lines with colon (object_name: description format)
            if ':' not in line:
                continue

            parts = line.split(':', 1)
            if len(parts) != 2:
                continue

            obj_name = parts[0].strip().strip('-').strip().strip('*').strip()
            obj_desc = parts[1].strip()

            # Remove leading numbers (e.g., "1. Sofa" -> "Sofa")
            obj_name = re.sub(r'^\d+[\.\)]\s*', '', obj_name).strip()

            # Skip if object name or description is invalid
            if len(obj_name) < 2 or len(obj_desc) < 5:
                continue

            # Skip if object name is too long (likely a sentence, not an object)
            if len(obj_name.split()) > 4:
                continue

            # Valid object - add to dictionary
            objects[obj_name] = obj_desc

        return {
            "objects": objects,
            "room_type": "bedroom",
            "scene_style": "unknown",
            "raw_output": output_text,
        }

    @modal.method()
    def generate_edits(self, user_prompt: str, objects: dict) -> dict:
        """
        Draft a per-object "transform to this style" plan.

        Args:
            user_prompt: target style, e.g. "Japanese themed" or "Scandinavian".
            objects:     detected objects from analyze_image (empty dict → empty output).

        Returns:
            {object_name: rough_fill_prompt, ...}
            These prompts are generic first-pass descriptions; the chatbot polishes
            them into material-specific prompts before FLUX sees them.

        Falls back to a templated "<style> style <object>" per object if the model's
        JSON output is malformed.
        """
        import torch

        if not objects:
            return {}

        prompt = build_edit_generation_prompt(user_prompt, objects)

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(text=[text], images=None, videos=None, padding=True, return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(**inputs, max_new_tokens=500, temperature=0.2, do_sample=True)

        output_text = self.processor.batch_decode(
            output_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0].split("assistant\n")[-1].strip()

        parsed = parse_edit_suggestions_json(output_text, objects, user_prompt)
        if any(parsed[obj] == build_object_fallback_prompt(user_prompt, obj, desc) for obj, desc in objects.items()):
            print("[WARN] generate_edits: one or more draft edits were weak/missing; used rich fallback prompts")
        return parsed

# ============================================================================
# 2. INTERIOR CHATBOT (1.5B + CHATBOT_QWEN_ADAPTOR)
# ============================================================================
@app.cls(
    image=llm_image,
    gpu="A100-40GB",
    timeout=300,
    scaledown_window=300,
)
class InteriorChatbot:
    """
    Qwen2.5-1.5B + CHATBOT_QWEN_ADAPTOR, running on A100-40GB.

    Fine-tuned on interior-design critiques. Takes a structured VLM payload
    (detected objects + draft edits) and returns a markdown review whose
    per-object `Proposed:` lines are the renderable prompts FLUX consumes.
    4-bit NF4 quantised — tiny enough to share a 40GB GPU with the VLM.
    """

    @modal.enter()
    def load_model(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from peft import PeftModel

        print("[LOAD] Loading Qwen2.5-1.5B with CHATBOT_QWEN_ADAPTOR...")

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

        base_model = AutoModelForCausalLM.from_pretrained(
            CHATBOT_MODEL_ID,
            quantization_config=bnb_config,
            device_map="auto",
            cache_dir="/cache"
        )

        self.model = PeftModel.from_pretrained(base_model, "/root/chatbot_adapter")
        self.model.eval()

        self.tokenizer = AutoTokenizer.from_pretrained(CHATBOT_MODEL_ID, cache_dir="/cache")

        print("[DONE] Chatbot loaded!")

    @modal.method()
    def review_edit_plan(self, vlm_output: dict) -> dict:
        """
        Polish the VLM's draft edits into renderable, material-specific prompts.

        The output markdown is consumed by `extract_polished_prompts()` downstream;
        each `Proposed:` line becomes the fill prompt for one object.

        Args:
            vlm_output: structured payload from `build_vlm_output` — contains
                        the detected objects, their current descriptions, and
                        the draft edit suggestions.

        Returns:
            {
                "review_markdown": str,  # full per-object critique, ready for parsing/display
                "analysis_prompt": str,  # the prompt that was fed to the model (for debugging)
            }
            Returns empty strings when `vlm_output` is empty.
        """
        import torch

        if not vlm_output:
            return {"review_markdown": "", "analysis_prompt": ""}

        analysis_prompt = build_analysis_prompt(vlm_output)
        system_prompt = build_chatbot_system_prompt(vlm_output.get("user_prompt", ""))
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": analysis_prompt},
        ]
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=2000,  # increased buffer for rooms with many objects
                temperature=0.75,
                top_p=0.92,
                do_sample=True,
                repetition_penalty=1.1,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        new_tokens = output_ids[0][inputs.input_ids.shape[1]:]
        improved = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

        return {
            "review_markdown": improved,
            "analysis_prompt": analysis_prompt,
        }



# ============================================================================
# 3. IMAGE GENERATOR (FLUX.1-Fill-dev + Grounding DINO + SAM2)
# ============================================================================

@app.cls(
    image=image_gen_image,
    gpu="A100-80GB",  # FLUX needs 80GB
    secrets=[modal.Secret.from_dotenv(path="interior_image_generator/.env")],
    timeout=3600,  # 60 minutes — matches outer endpoint ceiling so the class timeout doesn't cut short a long sequential edit
    scaledown_window=600,
)
class ImageGenerator:
    """
    FLUX.1-Fill-dev + Grounding DINO + SAM2, running on A100-80GB.

    Owns the full image-edit loop:
      • Grounding DINO locates an object by name.
      • SAM2 turns the bounding box into a binary mask.
      • FLUX.1-Fill-dev inpaints the masked region with the given prompt.

    Public methods:
      inpaint                          — single-shot inpainting via base64 payloads.
      edit_object                      — one-object, multi-iteration refinement.
      edit_multiple_objects_sequential — many-object cumulative editing.

    All inference knobs read from the module-level INPAINT_CFG; no magic numbers
    live inside the methods here.
    """

    @modal.enter()
    def load_models(self):
        import torch
        from diffusers import FluxFillPipeline

        print("[LOAD] Loading FLUX.1-Fill-dev...")

        self.flux_pipe = FluxFillPipeline.from_pretrained(
            FLUX_MODEL_ID,
            torch_dtype=torch.bfloat16,
            cache_dir="/cache"
        ).to("cuda")
        self.flux_pipe.enable_model_cpu_offload()

        print("[DONE] Image generator loaded!")

    @modal.method()
    def inpaint(self, image_b64: str, mask_b64: str, prompt: str,
                width: int = INPAINT_CFG.resolution, height: int = INPAINT_CFG.resolution,
                num_inference_steps: int = INPAINT_CFG.num_inference_steps,
                guidance_scale: float = INPAINT_CFG.guidance_scale,
                seed: int = INPAINT_CFG.seed) -> str:
        """
        Single-shot FLUX inpainting, intended as a standalone remote call.

        Unlike `edit_object`, this does no detection/segmentation/compositing —
        the caller must supply an already-prepared mask. For the higher-level
        "given an object name, edit it" flow, use `edit_object` instead.

        Args:
            image_b64: base64-encoded RGB image.
            mask_b64:  base64-encoded grayscale mask (white = inpaint).
            prompt:    text description of what to generate in the masked region.
            width/height, num_inference_steps, guidance_scale, seed:
                       override INPAINT_CFG defaults per-call.

        Returns:
            base64-encoded PNG of the inpainted result.
        """
        import torch
        from PIL import Image
        import io
        import base64

        # Decode inputs
        image = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
        mask = Image.open(io.BytesIO(base64.b64decode(mask_b64))).convert("L")

        generator = torch.Generator(device="cuda").manual_seed(seed)

        result = self.flux_pipe(
            prompt=prompt,
            image=image,
            mask_image=mask,
            width=width,
            height=height,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            max_sequence_length=INPAINT_CFG.max_sequence_length,
            generator=generator,
        ).images[0]

        # Encode result
        buf = io.BytesIO()
        result.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    @modal.method()
    def edit_object(self, image_bytes: bytes, target_object: str, fill_prompt: str,
                    iterations: int = INPAINT_CFG.iterations_per_object) -> dict:
        """
        End-to-end single-object edit: detect → segment → iteratively inpaint.

        Args:
            image_bytes:   raw input image bytes.
            target_object: name of the object to locate (fed to Grounding DINO).
            fill_prompt:   what to generate in the masked region.
            iterations:    number of refinement passes (same seed → deterministic).

        Returns:
            {
                "final":      PNG bytes of the last refinement pass,
                "iterations": list[bytes] — every refinement pass including final,
            }

        Detection and segmentation run via the interior_image_generator submodule
        (`EditOrchestrator`); inpainting runs locally on this class's FLUX pipe
        rather than over HTTP, so it's much faster than going through the original
        `InpaintPipeline.inpaint` HTTP path.
        """
        import sys
        sys.path.insert(0, "/root/interior_image_generator")

        from PIL import Image
        import io
        from pipeline.edit_orchestrator import EditOrchestrator
        from pipeline.settings import Settings

        # Load image
        image = Image.open(io.BytesIO(image_bytes))

        # Settings here drives detection+segmentation only. FLUX params flow
        # through INPAINT_CFG → self._inpaint_local, so no inpaint knobs here.
        # modal_endpoint_url is set to a non-empty sentinel so InpaintPipeline.__init__ passes.
        settings = Settings(modal_endpoint_url="local")

        orchestrator = EditOrchestrator(settings)

        # Get mask using Grounding DINO + SAM2
        print(f"[DETECT] Detecting and segmenting: {target_object}")
        mask = orchestrator.get_mask(image, target_object)

        # Perform iterative inpainting and save all iterations
        current = image
        iteration_results = []

        for i in range(iterations):
            print(f"[REFINE] Inpainting iteration {i+1}/{iterations}")
            # Use our local FLUX pipeline instead of HTTP endpoint
            current = self._inpaint_local(current, mask, fill_prompt)

            # Save this iteration
            buf = io.BytesIO()
            current.save(buf, format="PNG")
            iteration_results.append(buf.getvalue())

        # Return all iterations
        return {
            "final": iteration_results[-1],  # Final result
            "iterations": iteration_results  # All iterations including final
        }

    @modal.method()
    def edit_multiple_objects_sequential(
        self,
        image_bytes: bytes,
        edit_plan: dict,  # {object_name: fill_prompt}
        iterations_per_object: int = INPAINT_CFG.iterations_per_object
    ) -> dict:
        """
        Sequential multi-object editing with iterative refinement.

        Combines the approach from complete_image_editing.py (sequential)
        with edit_image.py (iterative refinement).

        Args:
            image_bytes: Input image
            edit_plan: Dict mapping object names to fill prompts
            iterations_per_object: Number of refinement iterations per object

        Returns:
            {
                "object_intermediates": {
                    "sofa": <bytes after editing sofa>,
                    "table": <bytes after editing sofa+table>,
                    ...
                },
                "iteration_details": {
                    "sofa": [<iter1>, <iter2>, <iter3>],  # Refinement iterations
                    "table": [<iter1>, <iter2>, <iter3>],
                    ...
                },
                "final": <final image bytes>
            }
        """
        import sys
        sys.path.insert(0, "/root/interior_image_generator")

        from PIL import Image
        import io
        from pipeline.edit_orchestrator import EditOrchestrator
        from pipeline.settings import Settings

        # Load image
        current_image = Image.open(io.BytesIO(image_bytes))

        # Same as edit_object: Settings is detection-only here; FLUX params live in INPAINT_CFG.
        settings = Settings(modal_endpoint_url="local")

        orchestrator = EditOrchestrator(settings)

        object_intermediates = {}
        iteration_details = {}

        total_objects = len(edit_plan)

        print(f"[DEBUG] Edit plan order: {list(edit_plan.keys())}")

        for idx, (target_object, fill_prompt) in enumerate(edit_plan.items(), 1):
            print(f"[{idx}/{total_objects}] Editing object: '{target_object}' -> '{fill_prompt}'")

            try:
                # Get mask for this object
                print(f"  [DETECT] Detecting and segmenting: {target_object}")
                mask = orchestrator.get_mask(current_image, target_object)

                # Iterative refinement for this object
                iterations_for_obj = []
                temp_image = current_image

                for i in range(iterations_per_object):
                    print(f"  [REFINE] Refinement iteration {i+1}/{iterations_per_object}")
                    temp_image = self._inpaint_local(temp_image, mask, fill_prompt, seed=INPAINT_CFG.seed + i)

                    # Save this refinement iteration
                    buf = io.BytesIO()
                    temp_image.save(buf, format="PNG")
                    iterations_for_obj.append(buf.getvalue())

                # Update current image to the refined result
                current_image = temp_image

                # Save intermediate (cumulative result after this object)
                buf = io.BytesIO()
                current_image.save(buf, format="PNG")
                object_intermediates[target_object] = buf.getvalue()
                iteration_details[target_object] = iterations_for_obj

                print(f"  [DONE] Completed editing '{target_object}'")

            except Exception as e:
                print(f"  [WARN] Failed to edit '{target_object}': {e}")
                # Continue with next object
                continue

        # Final image
        final_buf = io.BytesIO()
        current_image.save(final_buf, format="PNG")

        print(f"[DEBUG] object_intermediates keys order: {list(object_intermediates.keys())}")

        return {
            "object_intermediates": object_intermediates,
            "iteration_details": iteration_details,
            "final": final_buf.getvalue()
        }

    def _inpaint_local(self, image, mask, prompt, seed: int = INPAINT_CFG.seed):
        """
        Crop-and-inpaint helper using this class's in-process FLUX pipeline.

        Mirrors the crop/resize/composite logic of `InpaintPipeline.inpaint` in
        the interior_image_generator submodule, but calls FLUX directly instead
        of hitting the Modal HTTP endpoint (saves a round-trip per iteration).

        Args:
            image:  full-size PIL image.
            mask:   binary PIL mask aligned to `image` (white = inpaint).
            prompt: fill prompt for FLUX.
            seed:   RNG seed; callers bump this per iteration for variation.

        Returns:
            New PIL image with the masked region replaced. Returns `image`
            unchanged if the mask is empty (no bbox).
        """
        import torch
        from PIL import Image, ImageFilter
        import io
        import base64

        # Dilate mask. PIL's MaxFilter takes kernel size, which is 2r+1 for radius r.
        mask_dilated = mask.filter(ImageFilter.MaxFilter(size=INPAINT_CFG.mask_dilation_px * 2 + 1))

        # Crop around mask
        bbox = mask_dilated.getbbox()
        if bbox:
            bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad_x = max(16, int(bw * INPAINT_CFG.crop_padding))
            pad_y = max(16, int(bh * INPAINT_CFG.crop_padding))
            W, H = image.size
            x1 = max(0, bbox[0] - pad_x)
            y1 = max(0, bbox[1] - pad_y)
            x2 = min(W, bbox[2] + pad_x)
            y2 = min(H, bbox[3] + pad_y)

            image_crop = image.crop((x1, y1, x2, y2))
            mask_crop = mask_dilated.crop((x1, y1, x2, y2))
        else:
            return image

        # Resize for FLUX
        target_size = INPAINT_CFG.resolution
        aspect = image_crop.width / image_crop.height
        if aspect > 1:
            w, h = target_size, int(target_size / aspect)
        else:
            w, h = int(target_size * aspect), target_size

        image_resized = image_crop.resize((w, h), Image.LANCZOS)
        mask_resized = mask_crop.resize((w, h), Image.NEAREST)

        # Inpaint with FLUX
        generator = torch.Generator(device="cuda").manual_seed(seed)
        result = self.flux_pipe(
            prompt=prompt,
            image=image_resized,
            mask_image=mask_resized,
            width=w,
            height=h,
            guidance_scale=INPAINT_CFG.guidance_scale,
            num_inference_steps=INPAINT_CFG.num_inference_steps,
            max_sequence_length=INPAINT_CFG.max_sequence_length,
            generator=generator,
        ).images[0]

        # Composite back
        result_crop = result.resize(image_crop.size, Image.LANCZOS)
        mask_crop_orig = mask_crop.resize(image_crop.size, Image.NEAREST)

        patch = image_crop.copy()
        patch.paste(result_crop, mask=mask_crop_orig)

        final = image.copy()
        final.paste(patch, (x1, y1))

        return final


# ============================================================================
# HELPER FUNCTIONS FOR ENDPOINTS
# ============================================================================

@app.function(image=llm_image)
def run_analysis_pipeline(image_bytes: bytes, prompt: str) -> dict:
    """
    Full analysis chain: vision → draft edits → chatbot polish → merged fill prompts.

    Splits into four stages:
      1. VisionModel.analyze_image   → vision_output
      2. VisionModel.generate_edits  → edit_suggestions (draft)
      3. InteriorChatbot.review_edit_plan → design_review (structured markdown)
      4. extract_polished_prompts + merge → polished_prompts, fill_prompts

    Args:
        image_bytes: raw image bytes.
        prompt:      user's target style (e.g. "Japanese themed").

    Returns:
        A dict with vision_analysis, edit_suggestions, polished_prompts,
        fill_prompts, vlm_output, and design_review. `fill_prompts` is the one
        callers should hand to FLUX; the others are kept for debugging / display.
    """
    # Create handles once
    vision_model = VisionModel()
    chatbot = InteriorChatbot()

    # Step 1: Vision Analysis
    vision_output = vision_model.analyze_image.remote(image_bytes)

    # Step 1b: Generate first-pass edit suggestions with the vision model
    edit_suggestions = vision_model.generate_edits.remote(
        prompt,
        vision_output.get("objects", {}),
    )

    vlm_output = build_vlm_output(
        image_path="uploads/input_image.jpg",
        user_prompt=prompt,
        vision_output=vision_output,
        edit_suggestions=edit_suggestions,
    )

    # Step 2: Review the step 1 suggestions with the chatbot
    review_output = chatbot.review_edit_plan.remote(vlm_output)

    # Step 2b: Extract polished per-object prompts from the chatbot response.
    # Polished entries drive FLUX + the "Chatbot Suggestion" column in the UI;
    # any object the chatbot skipped falls back to the raw VLM suggestion.
    review_markdown = review_output.get("review_markdown", "")
    polished = extract_polished_prompts(
        review_markdown,
        list(edit_suggestions.keys()),
        edit_suggestions=edit_suggestions,
        user_prompt=prompt,
    )
    fill_prompts = {**edit_suggestions, **polished}
    log_chatbot_polish(review_markdown, edit_suggestions, polished, fill_prompts)

    # Strip the internal sentinel-wrapped JSON before handing the markdown to
    # the ExpertCritique panel — users shouldn't see <<<POLISH_JSON>>> blocks.
    review_output["review_markdown"] = strip_polish_sentinel(review_markdown)

    return {
        "success": True,
        "vision_analysis": vision_output,
        "edit_suggestions": edit_suggestions,
        "polished_prompts": polished,
        "fill_prompts": fill_prompts,
        "vlm_output": vlm_output,
        "design_review": review_output,
    }

# ============================================================================
# WEB ENDPOINTS
# ============================================================================

@app.function(
    image=llm_image,
    timeout=3600  # 60 minutes — matches the proxy and frontend fetch ceilings
)
@modal.asgi_app()
def analyze():
    """
    ASGI endpoint for the full pipeline, with CORS and a 30-minute timeout.

    Flow: Vision → Draft Edits → Chatbot Polish → single-object FLUX edit.
    Only the FIRST detected object is inpainted here (fast preview); use
    /complete_pipeline for multi-object sequential editing.
    """
    from fastapi import FastAPI, Request, Response
    from fastapi.middleware.cors import CORSMiddleware
    import base64
    import json
    import modal

    web_app = FastAPI()

    # Add CORS middleware
    web_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @web_app.post("/")
    async def analyze_endpoint(request: Request):
        try:
            print("=" * 70)
            print("[ANALYZE] NEW REQUEST RECEIVED")

            body = await request.json()
            image_b64 = body.get("image", "")
            prompt = body.get("prompt", "")
            print(f"[ANALYZE] Prompt: {prompt}")
            print(f"[ANALYZE] Image size: {len(image_b64)} bytes")

            if not image_b64 or not prompt:
                print("[ANALYZE] Error: Missing image or prompt")
                return {"error": "Missing image or prompt"}

            try:
                image_bytes = base64.b64decode(image_b64)
                print(f"[ANALYZE] Decoded image: {len(image_bytes)} bytes")
            except Exception as e:
                print(f"[ANALYZE] Error decoding base64: {e}")
                return {"error": "Invalid base64 image"}

            # Use modal.Function.from_name() to get function handles inside ASGI app
            print("[ANALYZE] Looking up Modal functions...")
            pipeline_fn = modal.Function.from_name("interior-design-complete", "run_analysis_pipeline")
            image_gen_cls = modal.Cls.from_name("interior-design-complete", "ImageGenerator")

            # Step 1-3: Run vision analysis + chatbot
            print("[ANALYZE] STEP 1-3: Running VLM pipeline + chatbot review...")
            result = await pipeline_fn.remote.aio(image_bytes, prompt)
            print(f"[ANALYZE] Analysis complete!")
            print(f"[ANALYZE]    - Objects found: {len(result.get('vision_analysis', {}).get('objects', {}))}")
            print(f"[ANALYZE]    - Edit suggestions: {len(result.get('edit_suggestions', {}))}")
            print(f"[ANALYZE]    - Polished by chatbot: {len(result.get('polished_prompts', {}))}")
            print(f"[ANALYZE]    - Review generated: {bool(result.get('design_review', {}).get('review_markdown'))}")

            # Step 4: Generate edited image — use chatbot-polished prompts (falls back to raw VLM per-object)
            edited_image_b64 = None
            fill_prompts = result.get("fill_prompts", {})

            if fill_prompts:
                first_object = list(fill_prompts.keys())[0]
                fill_prompt = fill_prompts[first_object]

                print(f"[ANALYZE] STEP 4: Generating edited image...")
                print(f"[ANALYZE]    - Target object: {first_object}")
                print(f"[ANALYZE]    - Fill prompt: {fill_prompt}")

                generator = image_gen_cls()
                edited_image_bytes = await generator.edit_object.remote.aio(
                    image_bytes,
                    first_object,
                    fill_prompt,
                    iterations=INPAINT_CFG.iterations_per_object,
                )
                edited_image_b64 = base64.b64encode(edited_image_bytes).decode()
                print(f"[ANALYZE] Image generated! Size: {len(edited_image_b64)} bytes")
            else:
                print("[ANALYZE] No edit suggestions, skipping image generation")

            # Add edited image to result
            result["edited_image"] = edited_image_b64

            print("[ANALYZE] REQUEST COMPLETE!")
            print(f"[ANALYZE]    - Edited image included: {edited_image_b64 is not None}")
            print("=" * 70)

            return result

        except Exception as e:
            print(f"[ANALYZE] ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            print("=" * 70)
            return {"error": str(e)}

    return web_app


@app.function(image=image_gen_image, secrets=[modal.Secret.from_dotenv(path="interior_image_generator/.env")])
@modal.fastapi_endpoint(method="POST")
def edit_image(request: dict):
    """
    Complete image editing: Detection → Segmentation → Inpainting.

    Request:
        {
            "image": "base64_encoded_image",
            "target_object": "sofa",
            "fill_prompt": "modern gray sectional sofa",
            "iterations": 3
        }
    """
    import base64
    from fastapi.responses import JSONResponse

    image_b64 = request.get("image", "")
    target_object = request.get("target_object", "")
    fill_prompt = request.get("fill_prompt", "")
    iterations = request.get("iterations", INPAINT_CFG.iterations_per_object)

    if not image_b64 or not target_object:
        return JSONResponse(
            content={"error": "Missing image or target_object"},
            status_code=400,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    try:
        # b64decode raises binascii.Error (a ValueError subclass) on malformed input.
        image_bytes = base64.b64decode(image_b64)
    except ValueError:
        return JSONResponse(
            content={"error": "Invalid base64 image"},
            status_code=400,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    try:
        result_bytes = ImageGenerator().edit_object.remote(image_bytes, target_object, fill_prompt, iterations)

        return JSONResponse(
            content={
                "success": True,
                "image": base64.b64encode(result_bytes).decode()
            },
            headers={"Access-Control-Allow-Origin": "*"}
        )

    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
            headers={"Access-Control-Allow-Origin": "*"}
        )


@app.function(image=llm_image)
@modal.fastapi_endpoint(method="POST")
def chat(request: dict):
    """
    Standalone chat endpoint.

    Request:
        {
            "question": "What is Scandinavian design?",
            "max_new_tokens": 512
        }
    """
    from fastapi.responses import JSONResponse

    question = request.get("question", "")
    max_new_tokens = request.get("max_new_tokens", 512)

    if not question:
        return JSONResponse(
            content={"error": "No question provided"},
            status_code=400,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    try:
        response = InteriorChatbot().chat.remote(question, max_new_tokens)

        return JSONResponse(
            content={
                "success": True,
                "question": question,
                "response": response
            },
            headers={"Access-Control-Allow-Origin": "*"}
        )

    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
            headers={"Access-Control-Allow-Origin": "*"}
        )


# ============================================================================
# COMPLETE PIPELINE ENDPOINT
# ============================================================================

@app.function(
    image=llm_image,
    timeout=3600  # 60 minutes — matches the proxy and frontend fetch ceilings
)
@modal.fastapi_endpoint(method="POST")
def complete_pipeline(request: dict):
    """
    End-to-end pipeline: Vision → Draft Edits → Chatbot Polish → Sequential FLUX.

    Request:
        {
            "image":           "<base64-encoded image>",
            "prompt":          "Japanese themed house",
            "edit_objects":    ["sofa", "wall"],   # optional — defaults to first 3 detected
            "generate_images": true                # optional — default false (skip FLUX)
        }

    Response:
        {
            "success":          true,
            "vision_analysis":  { objects, room_type, scene_style, raw_output },
            "edit_suggestions": { object: raw_vlm_prompt, ... },
            "polished_prompts": { object: chatbot_polished_prompt, ... },  # parser hits only
            "fill_prompts":     { object: prompt_used_for_flux, ... },     # merged with fallback
            "vlm_output":       { ...structured VLM payload... },
            "design_review":    { review_markdown, analysis_prompt },
            "edited_images": {                     # only when generate_images=true
                "object_order":         [ ... ],
                "object_intermediates": { object: base64_png, ... },
                "iteration_details":    { object: [base64_png, ...], ... },
                "final":                "<base64_png>"
            }
        }

    See INPAINT_CFG at the top of this file for all FLUX / mask / iteration knobs.
    """
    import base64

    from fastapi.responses import JSONResponse

    image_b64 = request.get("image", "")
    prompt = request.get("prompt", "")
    edit_objects = request.get("edit_objects", [])
    generate_images = request.get("generate_images", False)

    if not image_b64 or not prompt:
        return JSONResponse(
            content={"error": "Missing image or prompt"},
            status_code=400,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    try:
        image_bytes = base64.b64decode(image_b64)
    except ValueError:
        return JSONResponse(
            content={"error": "Invalid base64 image"},
            status_code=400,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    try:
        # Step 1: Vision Analysis
        print("[STEP1] Vision Analysis")
        vision_output = VisionModel().analyze_image.remote(image_bytes)

        # Step 2: Generate Edit Suggestions with the vision model
        print("[STEP2] Generate Edit Suggestions")
        edit_suggestions = VisionModel().generate_edits.remote(prompt, vision_output.get("objects", {}))

        # Step 3: Review the structured VLM output with the chatbot
        print("[STEP3] Review Edit Plan")
        vlm_output = build_vlm_output(
            image_path="uploads/input_image.jpg",
            user_prompt=prompt,
            vision_output=vision_output,
            edit_suggestions=edit_suggestions,
        )
        design_review = InteriorChatbot().review_edit_plan.remote(vlm_output)

        # Step 3b: Polish raw VLM suggestions through the chatbot's structured review.
        # fill_prompts is what FLUX sees; per-object fallback to the raw VLM if parsing missed.
        review_markdown = design_review.get("review_markdown", "")
        polished = extract_polished_prompts(
            review_markdown,
            list(edit_suggestions.keys()),
            edit_suggestions=edit_suggestions,
            user_prompt=prompt,
        )
        fill_prompts = {**edit_suggestions, **polished}
        print(f"[STEP3b] Chatbot polished {len(polished)}/{len(edit_suggestions)} objects")
        log_chatbot_polish(review_markdown, edit_suggestions, polished, fill_prompts)

        # Strip the internal sentinel-wrapped JSON before returning — the
        # ExpertCritique panel shouldn't show <<<POLISH_JSON>>> tokens.
        design_review["review_markdown"] = strip_polish_sentinel(review_markdown)

        result = {
            "success": True,
            "vision_analysis": vision_output,
            "edit_suggestions": edit_suggestions,
            "polished_prompts": polished,
            "fill_prompts": fill_prompts,
            "vlm_output": vlm_output,
            "design_review": design_review,
        }

        # Step 4: Generate Edited Images (optional)
        if generate_images and fill_prompts:
            print("[STEP4] Sequential Multi-Object Editing with Iterative Refinement")

            # Determine which objects to edit - PRESERVE ORIGINAL DETECTION ORDER
            detected_objects = vision_output.get("objects", {})

            if edit_objects:
                # User specified which objects - use original order
                edit_plan = {obj: fill_prompts[obj] for obj in detected_objects.keys()
                            if obj in edit_objects and obj in fill_prompts}
            else:
                # Edit first 3 objects from ORIGINAL DETECTION ORDER
                first_3_objects = list(detected_objects.keys())[:3]
                edit_plan = {obj: fill_prompts[obj] for obj in first_3_objects if obj in fill_prompts}

            if edit_plan:
                print(f"[PLAN] Edit plan: {list(edit_plan.keys())}")

                # Use sequential multi-object editing
                generator = ImageGenerator()
                edit_result = generator.edit_multiple_objects_sequential.remote(
                    image_bytes,
                    edit_plan,
                    iterations_per_object=INPAINT_CFG.iterations_per_object,
                )

                # edit_result contains:
                # {
                #   "object_intermediates": {obj: bytes_after_obj},
                #   "iteration_details": {obj: [iter1, iter2, iter3]},
                #   "final": final_bytes
                # }

                # Format for frontend with explicit ordering
                object_order = list(edit_result["object_intermediates"].keys())
                print(f"[DEBUG] Sending object_order to frontend: {object_order}")

                result["edited_images"] = {
                    "object_order": object_order,  # Explicit ordering
                    "object_intermediates": {
                        obj: base64.b64encode(img_bytes).decode()
                        for obj, img_bytes in edit_result["object_intermediates"].items()
                    },
                    "iteration_details": {
                        obj: [base64.b64encode(it).decode() for it in iterations]
                        for obj, iterations in edit_result["iteration_details"].items()
                    },
                    "final": base64.b64encode(edit_result["final"]).decode()
                }

                print(f"[DONE] Generated {len(edit_result['object_intermediates'])} object transformations")
            else:
                print("[WARN] No valid objects to edit")
                result["edited_images"] = {}

        return JSONResponse(
            content=result,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
            headers={"Access-Control-Allow-Origin": "*"}
        )


# ============================================================================
# LOCAL TESTING
# ============================================================================

@app.local_entrypoint()
def test():
    """Test all three models locally."""
    import base64

    print("=" * 60)
    print("Testing Complete Interior Design AI Pipeline")
    print("=" * 60)

    # Load test image
    with open("test_image.jpg", "rb") as f:
        image_bytes = f.read()
    image_b64 = base64.b64encode(image_bytes).decode()

    # Test complete pipeline
    print("\n[TEST] Testing complete pipeline...")
    result = complete_pipeline.remote({
        "image": image_b64,
        "prompt": "Japanese themed house",
        "edit_objects": [],  # Don't generate images in test
        "generate_images": False
    })

    print("\n[RESULTS] Results:")
    print(f"Objects detected: {list(result['vision_analysis']['objects'].keys())}")
    print(f"Edit suggestions: {list(result['edit_suggestions'].keys())}")

    print("\n[DONE] All tests passed!")
