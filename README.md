# Interior Design AI - Complete System Documentation

## Quick Start: What to Run

### First-Time Setup: Clone with Submodules

This repository uses a git submodule for the image generation pipeline. Clone with submodules:

```bash
# Option 1: Clone with submodules in one command
git clone --recurse-submodules https://github.com/YOUR_USERNAME/Group8_SUTD_MLOps.git

# Option 2: If already cloned, initialize the submodule
git submodule update --init --recursive
```

This pulls the `interior_image_generator/` directory from its separate repository.

### Environment Variables Setup

This project requires `.env` files in three locations:

**1. Root `.env`** (optional — for local Flask development)
```bash
# Copy from .env.example
cp .env.example .env
```
| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_ENV` | `development` | Flask environment mode |
| `FLASK_DEBUG` | `True` | Enable Flask debug mode |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `5000` | Server port |
| `MAX_FILE_SIZE` | `10485760` | Max upload size (10MB) |

**2. Frontend `.env`** (required for frontend to work)
```bash
cd frontend
cp .env.example .env
```
| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_USE_MODAL` | Yes | `false` for local proxy, `true` for direct Modal |
| `VITE_MODAL_ANALYZE_URL` | If direct Modal | Your Modal analyze endpoint URL |
| `VITE_MODAL_CHAT_URL` | If direct Modal | Your Modal chat endpoint URL |
| `VITE_MODAL_EDIT_IMAGE_URL` | If direct Modal | Your Modal edit endpoint URL |

**3. Image Generator `.env`** (required for FLUX inpainting)
```bash
# Create manually — this file is gitignored
# interior_image_generator/.env
HF_TOKEN=your_huggingface_token_here
```
| Variable | Required | Description |
|----------|----------|-------------|
| `HF_TOKEN` | Yes | HuggingFace token with access to FLUX.1-Fill-dev |

> **Note:** Get your HuggingFace token from https://huggingface.co/settings/tokens. You need to accept the FLUX.1-Fill-dev license at https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev before using the token.

### REQUIRED: Three Components

**Terminal 1: Proxy Server (START FIRST)**
```bash
python proxy_server.py
```
Expected output: `Running on port: 4000` (or next available port)
Purpose: Handles 60-minute timeout covering Modal cold start + sequential editing
Note: Auto-discovers an available port and writes it to `.proxy-port`

**Terminal 2: Frontend (START AFTER PROXY)**
```bash
cd frontend
npm run dev
```
Expected output: `Local: http://localhost:3000/`
Purpose: Web interface
Note: Reads proxy port from `.proxy-port` - must start after proxy server

**One-Time: Deploy Modal Backend**
```bash
# Option 1: Using UTF-8 wrapper (recommended on Windows)
python deploy_utf8.py

# Option 2: Direct deployment
modal deploy modal_updated_complete.py
```
Both commands deploy the same file (`modal_updated_complete.py`); the
wrapper only sets `PYTHONIOENCODING=utf-8` so Windows terminals can render
Modal's Unicode output.
First time: 5-10 minutes (downloads 30GB models)
Run once, or when backend code changes.

**Note:** If you see encoding errors (`'charmap' codec can't encode`), use `python deploy_utf8.py`

**Then Open Browser**
```
http://localhost:3000
```

---

## High-Level Architecture

```
User Browser
    |
    v
Local Proxy Server (auto-discovered port, Flask, 60-min timeout)
    |
    v
Modal Serverless GPUs — modal_updated_complete.py
    |
    +-- VisionModel       (Qwen2.5-VL-7B + LoRA, A100-40GB)
    |     analyze_image   -> detects objects in room
    |     generate_edits  -> drafts per-object edit suggestions
    |
    +-- InteriorChatbot   (Qwen2.5-1.5B + LoRA, A100-40GB)
    |     review_edit_plan -> polishes each suggestion with specific
    |                          materials, textures, colours, lighting
    |                         (fine-tuned on interior design critiques)
    |                         System prompt + per-object material /
    |                          finish / colour vocabulary are selected
    |                          from STYLE_GUIDANCE based on the user's
    |                          prompt (japanese | scandinavian |
    |                          industrial | minimalist | bohemian | ...)
    |
    +-- ImageGenerator    (FLUX.1-Fill-dev, A100-80GB)
          Grounding DINO + SAM2 to locate/mask each object,
          then FLUX inpaints using the chatbot-polished prompts.
```
Raw VLM suggestions act as a fallback for each object when the chatbot's output fails to parse.
Unknown styles fall back to a neutral `STYLE_GUIDANCE_FALLBACK` block that keeps the output structure intact but drops style-specific vocabulary.

---

## How It Works

### Pipeline Flow

**1. Vision Analysis (~30s)** — `VisionModel.analyze_image`
- Input: interior design image.
- Model: Qwen2.5-VL-7B + VL LoRA.
- Output: `vision_analysis.objects` = `{object_name: description}`.
- Example: `{"sofa": "modern grey sectional", "wall": "white painted", ...}`.

**2. Draft Edit Suggestions (~20s)** — `VisionModel.generate_edits`
- Input: detected objects + user style prompt (e.g. "Japanese themed").
- Model: same Qwen2.5-VL-7B, different prompt.
- Output: `edit_suggestions` = `{object_name: rough_fill_prompt}`.
- The prompt (`build_edit_generation_prompt`) is reframed as a REWRITE, not an
  edit: for every object, produce a new sentence as if it belonged in an
  authentic room of the chosen style, naming at least one material, one finish,
  and one colour from that style's `STYLE_GUIDANCE` vocabulary. Suffix-append
  patterns like `"<original description> with <X> finish"` are explicitly
  called out as forbidden.
- **Quality filter (`parse_edit_suggestions_json`)** — before the VLM's draft
  is accepted, each per-object candidate must pass three checks:
  1. **No generic filler** — rejects "beautiful", "modern", "natural wood",
     "fabric", "traditional style", "cozy", "nice", "stylish".
  2. **Not a suffix-append** — rejects candidates whose sentence literally
     starts with the original detection description (the VLM's lazy default).
  3. **Names the style's vocabulary** — rejects candidates that fail to
     mention any word from the active `STYLE_GUIDANCE` block's material /
     finish / colour examples (or the style key itself, e.g. "japanese").
- Rejected rows fall through to `build_object_fallback_prompt()`, a deterministic
  rich template that guarantees a style-themed sentence. Each rejection logs a
  `[WARN]` with the reason (`generic-term`, `suffix-append`, `no-style-vocab`)
  so VLM drift is visible in Modal logs.
- Example accepted: `{"artwork": "hand-brushed sumi-e scroll on washi paper with hinoki cypress frame in warm off-white and weathered ash-grey tones"}`.
- Example rejected (suffix-append): `{"artwork": "framed picture leaning against the wall with diffused warm glow finish"}` — rejected, fallback template used instead.
- These per-object prompts are what the Chatbot polishes next.

**3. Chatbot Polish (~10s)** — `InteriorChatbot.review_edit_plan` + `extract_polished_prompts`
- Input: the structured VLM output (`vision_output` + `edit_suggestions`).
- Model: Qwen2.5-1.5B + CHATBOT_QWEN_ADAPTOR, fine-tuned on interior design critiques.
- **Style routing:** `resolve_style_guidance(user_prompt)` scans the user's prompt
  for a known style keyword (`japanese`, `scandinavian`, `industrial`, `minimalist`,
  `bohemian`) and picks the matching `STYLE_GUIDANCE` block. That block drives both
  the chatbot's **system prompt** (`build_chatbot_system_prompt`) and the per-object
  material / finish / colour / cultural-reference examples in the **analysis prompt**
  (`build_analysis_prompt`). Prompts with no recognised style fall back to
  `STYLE_GUIDANCE_FALLBACK` (generic vocabulary, same structure).
- Raw output: `design_review.review_markdown` contains a machine-readable JSON
  block wrapped in sentinels:
  ```
  <<<POLISH_JSON>>>
  { "sofa": "...", "wall": "...", "table": "..." }
  <<<END_POLISH_JSON>>>
  ```
- `extract_polished_prompts()` parses the JSON block first (robust, no regex
  drift), then falls back to regex-parsing each object's `Proposed:` line for
  anything the JSON missed. Result: `polished_prompts = {object: enriched_fill_prompt}`.
- Merged result: `fill_prompts = {**edit_suggestions, **polished_prompts}`.
  Polished entries override raw ones; objects the chatbot skipped retain the
  raw VLM suggestion (a `[WARN]` is logged so format drift is visible in Modal logs).
- `fill_prompts` is what FLUX sees. The stripped `review_markdown` is still
  returned in the response for display/debugging.

**4. Sequential Multi-Object Inpainting (~8–12 min)** — `ImageGenerator.edit_multiple_objects_sequential`
- Input: original image + `fill_prompts` + objects-to-edit list.
- For each object, in detection order:
  1. **Grounding DINO** → bounding box from the object name.
  2. **SAM2** → binary mask from the box.
  3. **FLUX.1-Fill-dev** → `INPAINT_CFG.iterations_per_object` refinement passes,
     each with a different seed (`INPAINT_CFG.seed + i`) for variation.
  4. The final pass of this object becomes the input image for the next object,
     so edits accumulate rather than stomping each other.
- Knobs live in one place: the `InpaintConfig` dataclass at the top of
  [modal_updated_complete.py](modal_updated_complete.py). Tune
  `num_inference_steps`, `guidance_scale`, `resolution`, `seed`, `mask_dilation_px`,
  `crop_padding`, or `iterations_per_object` there and every call site picks it up.
- Output: `edited_images`:
  - `object_order` — explicit editing sequence (JSON can reorder dict keys; this array doesn't).
  - `object_intermediates` — cumulative result after each object (`sofa` → `sofa+table` → …).
  - `iteration_details` — per-object refinement passes.
  - `final` — complete transformed image.

**5. Frontend Display**
- "What We Found": detected objects.
- "Suggested Edits": four-column table — `# | Object | VLM Suggestion | Chatbot Suggestion`.
  The VLM column shows the raw first-pass draft; the Chatbot column shows the
  fine-tuned chatbot's refinement. Rows the chatbot didn't polish fall back to
  the VLM suggestion in the Chatbot column (rendered in grey italic).
- "Transformed Space": carousel of cumulative transformations, in `object_order`.
- "Refinement Passes": per-object iteration viewer.

---

## Technical Components

### Modal Backend ([modal_updated_complete.py](modal_updated_complete.py))

<details>
<summary><b>Module Docstring (Pipeline Overview)</b></summary>

```
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
dataclass) so tuning happens in one place instead of across ~10 call sites.

Endpoints:
    POST /complete_pipeline   full chain, optionally generates images
    POST /analyze             vision + chatbot + one-object image edit
    POST /edit_image          direct detection -> segmentation -> inpainting
    POST /chat                standalone chatbot

Usage:
    modal deploy modal_updated_complete.py
```
</details>

**VisionModel** — Qwen2.5-VL-7B-Instruct + LoRA, A100-40GB

> *Qwen2.5-VL-7B + VL LoRA, running on A100-40GB. Two responsibilities: `analyze_image` — detect household objects from a photo; `generate_edits` — draft a per-object "transform to this style" plan. Uses 4-bit NF4 quantisation (via bitsandbytes) so the 7B model fits in 40GB VRAM alongside the VL processor.*

- LoRA weights: `qwen25_vl_7b_objdesc_lora/`
- `analyze_image(image_bytes) -> {objects, room_type, scene_style, raw_output}`
- `generate_edits(user_prompt, objects) -> {object_name: fill_prompt}`

**InteriorChatbot** — Qwen2.5-1.5B-Instruct + LoRA, A100-40GB

> *Qwen2.5-1.5B + CHATBOT_QWEN_ADAPTOR, running on A100-40GB. Fine-tuned on interior-design critiques. Takes a structured VLM payload (detected objects + draft edits) and returns a markdown review whose per-object `Proposed:` lines are the renderable prompts FLUX consumes. 4-bit NF4 quantised — tiny enough to share a 40GB GPU with the VLM.*

- LoRA weights: `qwen-interior-design-qlora/final-adapter/`
- `review_edit_plan(vlm_output) -> {review_markdown, analysis_prompt}`
- Produces two things in one call: a markdown per-object critique, plus a
  `<<<POLISH_JSON>>> { ... } <<<END_POLISH_JSON>>>` block mapping each object
  to a polished fill prompt. `extract_polished_prompts` reads the JSON block
  first and falls back to regex-parsing the markdown's `Proposed:` lines. The
  sentinel block is stripped from `review_markdown` before it leaves Modal.
- System prompt and material vocabulary are style-aware: both are built from
  `STYLE_GUIDANCE[style]` using `build_chatbot_system_prompt()` and
  `build_analysis_prompt()`, keyed off the user's target style.

**ImageGenerator** — FLUX.1-Fill-dev, A100-80GB

> *FLUX.1-Fill-dev + Grounding DINO + SAM2, running on A100-80GB. Owns the full image-edit loop: Grounding DINO locates an object by name; SAM2 turns the bounding box into a binary mask; FLUX.1-Fill-dev inpaints the masked region with the given prompt. Public methods: `inpaint` (single-shot), `edit_object` (one-object multi-iteration), `edit_multiple_objects_sequential` (many-object cumulative editing). All inference knobs read from the module-level INPAINT_CFG; no magic numbers live inside the methods.*

- Detection: Grounding DINO. Segmentation: SAM2.
- `edit_multiple_objects_sequential(image_bytes, edit_plan, iterations_per_object)`
  runs the full per-object loop (detect → segment → FLUX refinement passes →
  accumulate).
- All FLUX / mask parameters are read from the module-level `INPAINT_CFG`
  instance of `InpaintConfig` — no hardcoded literals inside methods.

**`InpaintConfig` dataclass** — single source of truth for inference knobs:

| Field | Default | What it controls |
|---|---|---|
| `num_inference_steps` | 28 | FLUX denoising steps per pass |
| `guidance_scale` | 30.0 | How strictly FLUX follows the prompt |
| `max_sequence_length` | 512 | Max prompt tokens |
| `resolution` | 1024 | Target crop size fed to FLUX |
| `seed` | 42 | Base seed; iteration `i` uses `seed + i` |
| `mask_dilation_px` | 8 | Mask expansion before inpainting |
| `crop_padding` | 0.25 | Bbox padding as a fraction of width/height |
| `iterations_per_object` | 10 | Refinement passes per object |

**`extract_polished_prompts(review_markdown, objects)`** — two-path parser with
automatic JSON repair. First attempts to read the `<<<POLISH_JSON>>> { ... } <<<END_POLISH_JSON>>>`
block. If JSON parsing fails (missing commas, truncated output), `_repair_json()`
attempts to fix common malformations before retrying. Falls back to regex-parsing
the markdown's `Proposed:` lines if repair also fails.
Returns only the objects parsed successfully, so callers can merge with
`edit_suggestions` as a per-object fallback. Logs `[INFO]` when repair succeeds,
`[WARN]` when falling back to regex.

**`strip_polish_sentinel(review_markdown)`** — removes the
`<<<POLISH_JSON>>> { ... } <<<END_POLISH_JSON>>>` block from the chatbot's
output before it is returned to the frontend. If the closing sentinel is
missing (e.g. the chatbot drifted format), the function falls back to
dropping everything from the opening sentinel onward.

**`STYLE_GUIDANCE` dict** — single source of truth for style-specific
vocabulary consumed by both the chatbot system prompt and the analysis prompt.
Each entry carries the style's authenticity framing, material / finish / colour
example words, and the cultural reference used in the per-object "Authenticity:"
line of the review. Adding a new style is a one-dict-entry change:

| Key | Authenticity framing | Example materials |
|---|---|---|
| `japanese`     | wabi-sabi, shibui, ma                           | washi paper, ramie linen, hinoki cypress, urushi lacquer |
| `scandinavian` | hygge, functionalism                            | light oak, ash, birch, undyed wool, linen |
| `industrial`   | utilitarian, exposed structure                  | blackened steel, raw concrete, reclaimed brick, patinated leather |
| `minimalist`   | restraint, negative space                       | honed plaster, matte lacquer, pale stone, raw linen |
| `bohemian`     | layered textures, eclectic sources              | rattan, jute, hand-loomed cotton, terracotta, brass |
| *fallback*     | neutral — "the user's chosen design style"      | generic descriptors (species of wood, weave type, stone variety) |

Resolution is a case-insensitive substring match against the user's prompt
(`"Japanese themed house" → japanese`); `resolve_style_guidance()` returns the
fallback block if no key matches. Callers never reach into `STYLE_GUIDANCE`
directly — they use `resolve_style_guidance(user_prompt)`,
`build_chatbot_system_prompt(user_prompt)`, or `build_analysis_prompt(vlm)`.

**Key Functions Reference:**

| Function | Purpose |
|----------|---------|
| `resolve_style_key(user_prompt)` | Return the canonical style key detected from the user's prompt, if any. |
| `resolve_style_guidance(user_prompt)` | Pick a style guidance block by scanning the user's prompt for a known style keyword or alias. |
| `build_chatbot_system_prompt(user_prompt)` | Style-specific chatbot system prompt, built from STYLE_GUIDANCE. |
| `build_object_fallback_prompt(user_prompt, object_name, object_desc)` | Create a richer fallback prompt than `<style> style <object>` when generation fails. |
| `build_edit_generation_prompt(user_prompt, objects)` | Prompt the VLM to emit stable, per-object JSON drafts that the chatbot can polish. |
| `_is_suffix_append(candidate, original_desc)` | True when the VLM lazily produced `<original description> + <suffix>`. |
| `_is_style_poor(cleaned, user_prompt, guidance)` | True when the candidate fails to name a style-specific material/finish/colour. |
| `parse_edit_suggestions_json(output_text, objects, user_prompt)` | Parse model JSON robustly and backfill missing / weak / style-poor entries. |
| `build_vlm_output(vision_analysis, edit_suggestions, user_prompt)` | Normalize step 1 outputs into the structured payload expected by step 2. |
| `build_analysis_prompt(vlm)` | Build the structured rewrite prompt for the chatbot model. |
| `_repair_json(raw_json)` | Attempt to repair common JSON malformations from LLM output (missing commas, trailing commas, truncated strings). |
| `extract_polished_prompts(review_markdown, objects)` | Two-path parser: JSON block first, then regex fallback for `Proposed:` lines. |
| `strip_polish_sentinel(review_markdown)` | Remove the machine-readable JSON block from the review markdown before returning to frontend. |
| `log_chatbot_polish(review_markdown, edit_suggestions, polished, fill_prompts)` | Debug logging for chatbot polish results. |

**Why `object_order` is an explicit array in the response:**
- Python 3.7+ dicts preserve insertion order, but JSON serialisation and
  cross-runtime parsers don't guarantee it.
- `object_order` is a list, which JSON preserves order for, so the frontend
  can render the carousel in editing sequence regardless of dict key ordering.

### Local Proxy (proxy_server.py)

**Why needed:**
- Browser fetch() default abort: short, not enough for long requests.
- Modal cold start: up to several minutes while the 30GB of weights load.
- Sequential editing: 10-20 min depending on `iterations_per_object` and object count.
- Solution: Local Flask proxy whose long timeout matches the frontend and Modal ceilings.

**Configuration:**
- Port: Auto-discovered (scans 4000-4100 for first available port)
- Port file: `.proxy-port` (written on startup, read by Vite)
- Timeout: 3600 seconds (60 minutes) — must match the frontend `fetchWithTimeout`
  value in `frontend/src/utils/api.js` and Modal's `@app.function(timeout=...)` on
  the `complete_pipeline` and `ImageGenerator` decorators.
- Forwards to: Modal `complete_pipeline` endpoint.

### Frontend (React + Vite)

**Key files:**
- frontend/src/App.jsx: Main UI component
- frontend/src/utils/api.js: API communication
- frontend/src/config.js: Configuration (reads from .env)
- frontend/.env: Environment variables (gitignored)
- frontend/.env.example: Template for .env
- frontend/vite.config.js: Vite config (reads proxy port from `.proxy-port`)

**Configuration (frontend/.env):**
```bash
# Set to "true" for Modal (production), "false" for local proxy
VITE_USE_MODAL=false

# Modal endpoints (only used when VITE_USE_MODAL=true)
VITE_MODAL_ANALYZE_URL=https://your-username--your-app.modal.run
VITE_MODAL_CHAT_URL=https://your-username--your-chat.modal.run
VITE_MODAL_EDIT_IMAGE_URL=https://your-username--your-edit.modal.run
```

**Setup:**
1. Copy `frontend/.env.example` to `frontend/.env`
2. Fill in your Modal endpoint URLs
3. Set `VITE_USE_MODAL=false` for local development with proxy

**UI Structure:**

1. **Upload Section**
   - Style preset selector (Minimalist, Industrial, Japanese, etc.)
   - Custom prompt input
   - Image upload with preview

2. **Current Items Viewed** (Gray Header)
   - Table showing detected objects in detection order
   - Format: # | Object | Description
   - Matches "Design Suggestions" ordering

3. **Suggested Edits** (Purple Header)
   - Side-by-side table comparing the two prompt sources
   - Same objects as "Current Items Viewed", in detection order
   - Format: # | Object | VLM Suggestion | Chatbot Suggestion
   - The Chatbot column falls back to the VLM suggestion for any row the
     chatbot didn't polish (rendered in grey italic so the fallback is visible)

4. **Transformed Space** (Carousel)
   - Shows cumulative transformations in **editing order**
   - Uses `object_order` from backend
   - Navigation: Left/Right arrows or progress dots
   - Example: Pass 1: Sofa → Pass 2: Table → Pass 3: Chair
   - Each pass shows cumulative result (sofa → sofa+table → sofa+table+chair)

5. **Refinement Passes** (Per-Object Viewer)
   - Select object via tabs (in editing order)
   - View 3 refinement iterations for selected object
   - Different seeds produce variation across iterations
   - Navigation: Left/Right arrows or iteration dots

---

## File Structure

```
Group8_SUTD_MLOps/
|
+-- modal_updated_complete.py      Main Modal backend (all 3 AI models) — this is what deploys
+-- proxy_server.py                Local CORS proxy server (auto-discovers port)
+-- deploy_utf8.py                 UTF-8 deployment wrapper (targets modal_updated_complete.py)
+-- .proxy-port                    Auto-generated port file (gitignored)
+-- .env / .env.example            Environment variables (HF_TOKEN, etc.)
+-- requirements.txt               Python dependencies
+-- package.json                   Node.js package config
+-- README.md                      This documentation file
+-- PROJECT.md                     Project overview and technical plan
+-- Final Report Group 8.pdf       Final project report
|
+-- frontend/                      React frontend application
|   +-- .env / .env.example       Environment variables (gitignored)
|   +-- src/
|   |   +-- App.jsx               Main UI component
|   |   +-- utils/api.js          API communication layer (extracts object_order)
|   |   +-- config.js             Configuration (reads from .env)
|   |   +-- components/           UI components (ResultsScreen, Carousels, Tables)
|   +-- package.json
|   +-- vite.config.js            Vite config (reads proxy port from .proxy-port)
|
+-- Base & Finetuning/             Training notebooks for model fine-tuning
|   +-- WANDB_BEST_MODEL_Image_Analysis_To_JSON_and_Qwen_Finetune.ipynb   VLM LoRA training
|   +-- interior_chatbot_v2_finetune.ipynb                                Chatbot LoRA training
|
+-- Designer LLM/                  Designer LLM experiments and research
|   +-- interior_chatbot_finetune.ipynb    Chatbot fine-tuning experiments
|   +-- interior_chatbot_RAG.ipynb         RAG-based chatbot experiments
|   +-- output/                            Training outputs
|   +-- Techniques and methods/            Research documentation
|
+-- WB Log Files/                  Weights & Biases training logs
|   +-- QWEN/                      Qwen model training results and metrics
|
+-- qwen25_vl_7b_objdesc_lora/     Vision model LoRA weights (trained adapter)
+-- qwen-interior-design-qlora/    Chatbot model LoRA weights
|   +-- final-adapter/
|
+-- interior_image_generator/      Image generation utilities (git submodule)
|   +-- .env                       HuggingFace token (required, gitignored)
|   +-- pipeline/
|   |   +-- edit_orchestrator.py   Coordinates detection + inpainting
|   |   +-- detection_and_segmentation.py  Grounding DINO + SAM2
|   |   +-- inpaint.py             FLUX.1-Fill-dev wrapper
|   |   +-- settings.py            Pipeline configuration
|   +-- utils/
|       +-- image.py               Image processing utilities
|
+-- OLD AND NOT WORKING/           Legacy code kept for reference
    +-- modal_complete.py          Earlier backend version (not deployed)
```

---

## API Endpoints

### Modal: POST /complete_pipeline

**Request:**
```json
{
  "image": "base64_encoded_image_string",
  "prompt": "Japanese themed house",
  "generate_images": true,
  "edit_objects": []
}
```

**Response:**
```json
{
  "success": true,
  "vision_analysis": {
    "objects": {
      "sofa": "modern grey sectional",
      "wall": "white painted wall",
      "table": "wooden coffee table"
    },
    "room_type": "bedroom",
    "scene_style": "unknown",
    "raw_output": "..."
  },
  "edit_suggestions": {
    "sofa": "traditional Japanese futon",
    "wall": "shoji screen panels",
    "table": "low chabudai table"
  },
  "polished_prompts": {
    "sofa": "weathered ash-grey futon in matte-grain undyed ramie linen, diffused warm glow...",
    "wall": "shoji screen panels of washi paper on kumiko lattice, warm off-white..."
  },
  "fill_prompts": {
    "sofa": "<polished if parsed, raw VLM suggestion otherwise>",
    "wall": "<polished if parsed, raw VLM suggestion otherwise>",
    "table": "<polished if parsed, raw VLM suggestion otherwise>"
  },
  "design_review": {
    "review_markdown": "<<<POLISH_JSON>>>{...}<<<END_POLISH_JSON>>>",
    "analysis_prompt": "..."
  },
  "vlm_output": { "...structured VLM payload..." },
  "edited_images": {
    "object_order": ["sofa", "wall", "table"],
    "object_intermediates": {
      "sofa": "base64_after_sofa",
      "wall": "base64_after_sofa_and_wall",
      "table": "base64_after_sofa_wall_table"
    },
    "iteration_details": {
      "sofa": ["iter1_base64", "iter2_base64", "..."],
      "wall": ["iter1_base64", "iter2_base64", "..."],
      "table": ["iter1_base64", "iter2_base64", "..."]
    },
    "final": "base64_final_image"
  }
}
```

**Key Fields:**
- `edit_suggestions` — raw VLM first-pass prompts (generic).
- `polished_prompts` — chatbot-enriched prompts, only for objects the parser matched.
- `fill_prompts` — the merge (`{...edit_suggestions, ...polished_prompts}`) that
  FLUX actually consumed. Use this if you want to know what each edit was based on.
- `design_review.review_markdown` — chatbot output containing the machine-readable
  `<<<POLISH_JSON>>> ... <<<END_POLISH_JSON>>>` block used to extract polished prompts.
- `object_order` — authoritative editing sequence; trust this over dict key order.
- `object_intermediates` — cumulative image state after each object's edit.
- `iteration_details` — `INPAINT_CFG.iterations_per_object` refinement passes per
  object, each with a different seed.
- `final` — complete transformed image (identical to the last `object_intermediate`).

### Local Proxy: POST /api/analyze
Forwards to Modal complete_pipeline with 60-minute timeout

---

## Debug Features

### Backend Debug Logging

The Modal backend includes comprehensive debug logging to track the editing process:

**Key Log Messages:**
```
[DEBUG] Edit plan order: ['sofa', 'table', 'chair']
  → Shows which objects will be edited and in what sequence

[1/3] Editing object: 'sofa' -> 'traditional Japanese futon'
[2/3] Editing object: 'table' -> 'low chabudai table'
[3/3] Editing object: 'chair' -> 'zaisu floor chair'
  → Shows each object being processed sequentially

[DEBUG] object_intermediates keys order: ['sofa', 'table', 'chair']
  → Confirms order before JSON serialization

[DEBUG] Sending object_order to frontend: ['sofa', 'table', 'chair']
  → Confirms explicit ordering array sent to frontend
```
### Frontend Debug Logging

The frontend logs ordering information to browser console:

**Key Console Messages:**
```javascript
[Frontend] objectOrder from backend: ['sofa', 'table', 'chair']
  → Order received from API

[Frontend] Received object_order from backend: ['sofa', 'table', 'chair']
  → Order used for UI rendering

[Frontend] iterationDetails keys: ['sofa', 'table', 'chair']
  → Iteration details in correct order
```

**View Frontend Logs:**
1. Press F12 in browser
2. Go to Console tab
3. Filter for "[Frontend]" messages

**How Code Flows:**
```
Backend: edit_plan = ['sofa', 'table', 'chair']
         ↓
Backend: object_order = ['sofa', 'table', 'chair'] (explicit array)
         ↓
JSON:    May reorder dict keys to ['chair', 'sofa', 'table']
         ↓
Frontend: Uses object_order array → Displays ['sofa', 'table', 'chair'] ✓
```

---

## Troubleshooting

### Error: "Failed to fetch" / Connection Refused

**Cause:** Proxy server not running, or frontend started before proxy

**Solution:**
```bash
# 1. Start proxy first
python proxy_server.py
# Verify output shows: "Running on port: XXXX"

# 2. Then restart frontend (to pick up the port)
cd frontend
npm run dev
```

### Error: Images not showing in frontend

**Checklist:**
1. Is Modal deployed? Run: `python deploy_utf8.py` (or `modal deploy modal_updated_complete.py`)
2. Is proxy running? Check Terminal 1
3. Is config correct? Check frontend/src/config.js: `USE_MODAL = false`
4. Check browser console (F12) for errors
5. Check proxy terminal for request logs

### Error: "What We Found" and "Design Suggestions" don't match

**Status:** Fixed - Design Suggestions now filters to only show detected objects

### Error: Transformed images showing in wrong order

**Symptom:** Backend logs show editing sofa → table → chair, but frontend shows chair → sofa → table

**Diagnosis:**
1. Check backend logs for: `[DEBUG] Sending object_order to frontend:`
2. Check browser console for: `[Frontend] objectOrder from backend:`
3. These should match the actual editing sequence

**Causes & Fixes:**

**Cause 1: object_order not being sent**
```bash
# Redeploy backend
python deploy_utf8.py
```

**Cause 2: Frontend not using object_order**
```javascript
// Check frontend/src/App.jsx
const objectOrder = results.objectOrder || Object.keys(results.objectIntermediates);
```

**Cause 3: API layer not extracting object_order**
```javascript
// Check frontend/src/utils/api.js line 108
const objectOrder = editedImagesData.object_order || [];

// Should be included in result (line 127)
objectOrder: objectOrder,
```

**Verify Fix:**
1. Backend logs: `[DEBUG] Sending object_order: ['sofa', 'table', 'chair']`
2. Browser console: `[Frontend] objectOrder from backend: ['sofa', 'table', 'chair']`
3. Frontend displays: Sofa (Pass 1) → Table (Pass 2) → Chair (Pass 3)

### Error: Timeout after 2 minutes

**Cause:** Using Modal directly instead of proxy

**Solution:**
```bash
# frontend/.env
VITE_USE_MODAL=false  # MUST be false for local proxy
```

### Error: CORS Policy / Access-Control-Allow-Origin

**Cause:** Actually a timeout issue, not CORS

**Solution:** Ensure proxy is running and USE_MODAL = false

### Error: Encoding errors during Modal deployment

**Symptom:** `'charmap' codec can't encode character '\u2713' in position 0`

**Cause:** Windows terminal encoding doesn't support Unicode checkmarks from Modal CLI

**Solution:**
```bash
# Use UTF-8 wrapper script
python deploy_utf8.py
```

**What it does:**
- Sets `PYTHONIOENCODING=utf-8`
- Converts non-ASCII characters to ASCII-safe equivalents
- Displays deployment status without encoding errors

### Error: Previous edits disappearing during sequential editing

**Symptom:** When editing chair, the sofa and table transformations are lost

**Diagnosis:**
This should NOT happen with the current implementation. If it does:

1. **Check backend logs** for errors during object detection:
   ```
   [WARN] Failed to edit 'chair': Could not detect 'chair' in the image
   ```
   - The detector might fail if the object is heavily modified
   - Try lowering `box_threshold` in Settings

2. **Check mask overlap:**
   - If chair mask overlaps sofa region, it may overwrite previous edits
   - This is expected behavior - masks should be precise

3. **Verify cumulative editing:**
   ```python
   # modal_updated_complete.py, inside edit_multiple_objects_sequential
   current_image = temp_image  # Should preserve previous edits
   ```

**Root cause:** Detection failure on modified image
**Solution:** Sequential editing preserves previous changes via `current_image` accumulation

---

## Performance Expectations

### First Run (Cold Start)
- Model download: 5-10 minutes (one-time, 30GB+)
- Pipeline execution: 15-20 minutes
- Total: 20-30 minutes

### Warm Runs (Models Cached)
- Vision analysis: 30 seconds
- Edit suggestions: 20 seconds
- Image generation: 8-12 minutes (3 objects x 3 iterations)
- Total: 10-15 minutes

### Why So Long?

**Sequential Processing:**
- Objects edited one at a time (not parallel)
- 3 objects = 3 sequential operations

**Iterative Refinement:**
- Each object gets 3 passes with different seeds
- 3 objects x 3 iterations = 9 total inpainting operations

**Model Performance:**
- FLUX.1-Fill-dev: ~30-60 seconds per pass
- Grounding DINO + SAM2: ~10-15 seconds per object

**Total:** ~9 inpainting passes x 45 sec = 6-7 minutes + detection overhead

---

## System Requirements

**Local Machine:**
- Python 3.10+
- Node.js 18+
- Stable internet connection

**Modal (Serverless):**
- A100-40GB GPU (Vision + Chatbot)
- A100-80GB GPU (Image Generator)
- 30GB storage (model weights)
- Billed per second of GPU usage [My money boohoo]

---

## Technical Deep-Dive: Ordering System

### Problem Statement

**Challenge:** Maintain consistent object ordering from backend editing sequence to frontend display

**Why it's hard:**
1. Backend edits objects sequentially in detection order
2. Python 3.7+ dicts maintain insertion order
3. FastAPI JSONResponse serializes dicts
4. JSON spec doesn't guarantee object key ordering
5. Different JSON parsers may reorder alphabetically
6. Frontend receives potentially reordered data

**Real Example:**
```
Backend edit_plan: {'sofa': '...', 'table': '...', 'chair': '...'}
Editing sequence:  sofa → table → chair
JSON transmission: May become alphabetical
Frontend receives: {'chair': '...', 'sofa': '...', 'table': '...'}
UI displays:       chair → sofa → table ❌
```

### Solution Architecture

**1. Backend: Explicit Ordering (modal_updated_complete.py)**

```python
# Inside edit_multiple_objects_sequential — track editing sequence
object_intermediates = {}  # Will be edited in order

for idx, (target_object, fill_prompt) in enumerate(edit_plan.items(), 1):
    # Edit object
    current_image = inpaint(current_image, mask, fill_prompt)
    object_intermediates[target_object] = current_image

# In complete_pipeline — create explicit order array
object_order = list(edit_result["object_intermediates"].keys())
print(f"[DEBUG] Sending object_order to frontend: {object_order}")

# Add to response
result["edited_images"] = {
    "object_order": object_order,  # ← Explicit array
    "object_intermediates": {...},
    "iteration_details": {...},
    "final": ...
}
```

**2. API Layer: Extract ordering (frontend/src/utils/api.js)**

```javascript
// Line 108: Extract object_order from response
const objectOrder = editedImagesData.object_order || [];
console.log('[Frontend] objectOrder from backend:', objectOrder);

// Line 127: Include in result
const result = {
  // ...
  objectOrder: objectOrder,  // ← Pass to UI
};
```

**3. Frontend: Use explicit ordering (frontend/src/App.jsx)**

```javascript
// Line 343: Transformed Space carousel
const objectOrder = results.objectOrder || Object.keys(results.objectIntermediates);
const transformEntries = objectOrder.map(obj => [obj, results.objectIntermediates[obj]]);
// Now displays in correct order: sofa → table → chair ✓

// Line 420: Refinement Passes tabs
const objectOrder = results.objectOrder || Object.keys(results.iterationDetails);
const iterationEntries = objectOrder.map(obj => [obj, results.iterationDetails[obj]]);
// Tabs appear in editing order ✓
```

### Verification

**Check each layer:**

1. **Backend logs:**
   ```
   [DEBUG] Edit plan order: ['sofa', 'table', 'chair']
   [DEBUG] Sending object_order to frontend: ['sofa', 'table', 'chair']
   ```

2. **API response (browser Network tab):**
   ```json
   {
     "edited_images": {
       "object_order": ["sofa", "table", "chair"],
       ...
     }
   }
   ```

3. **Frontend console:**
   ```
   [Frontend] objectOrder from backend: ['sofa', 'table', 'chair']
   [Frontend] Received object_order: ['sofa', 'table', 'chair']
   ```

4. **UI Display:**
   - Carousel: Sofa (Pass 1) → Table (Pass 2) → Chair (Pass 3) ✓
   - Tabs: Sofa | Table | Chair ✓

### Fallback Behavior

If `object_order` is missing or empty:
```javascript
const objectOrder = results.objectOrder || Object.keys(results.objectIntermediates);
```

- Frontend falls back to `Object.keys()` which may be alphabetical
- This ensures UI doesn't break, but order may be wrong
- Check debug logs to diagnose missing `object_order`

---

## Support & Debugging

**Modal Dashboard:**
https://modal.com/apps/raintail0025/main/deployed/interior-design-complete

**View Logs:**
- Modal: Check dashboard during execution
- Proxy: Check Terminal 1 output
- Frontend: Check Terminal 2 output
- Browser: Press F12 → Console tab + Network tab

---

## Quick Reference

### Essential Commands

```bash
# Deploy backend (when code changes)
python deploy_utf8.py

# Start proxy server FIRST (Terminal 1)
python proxy_server.py
# Note: Creates .proxy-port file with auto-discovered port

# Start frontend AFTER proxy (Terminal 2)
cd frontend
npm run dev
# Note: Reads port from .proxy-port - must start after proxy

# View Modal logs
modal app logs interior-design-complete

# Check Modal status
modal app list
```

### Debug Checklist

When something goes wrong:

1. **Check all 3 components running (in order):**
   ```bash
   # Proxy: Should show "Running on port: XXXX"
   # Frontend: Should show "Local: http://localhost:3000/"
   # Modal: Check https://modal.com/apps
   ```

2. **Check configuration:**
   ```bash
   # frontend/.env
   VITE_USE_MODAL=false  # MUST be false for local proxy
   ```

3. **Check .proxy-port file exists:**
   ```bash
   # Should contain a port number (e.g., 4001)
   cat .proxy-port
   ```

3. **Check browser console (F12):**
   ```
   [Frontend] objectOrder from backend: [...]  // Should show correct order
   ```

4. **Check proxy logs:**
   ```
   POST /api/analyze HTTP/1.1" 200  // Should be 200, not 500/timeout
   ```

5. **Check Modal logs:**
   ```
   [DEBUG] Edit plan order: [...]
   [DEBUG] Sending object_order to frontend: [...]
   ```

### Key Methods Reference (modal_updated_complete.py)

Referenced by method name rather than line number, since line numbers drift
every time the file is edited. Grep for the symbol in the file.

- **Vision analysis:** `VisionModel.analyze_image`
- **Draft edit generation:** `VisionModel.generate_edits` + `build_edit_generation_prompt` + `parse_edit_suggestions_json`
- **Chatbot polish:** `InteriorChatbot.review_edit_plan` + `build_analysis_prompt` + `extract_polished_prompts` + `strip_polish_sentinel`
- **Sequential editing:** `ImageGenerator.edit_multiple_objects_sequential`
- **Single-shot inpainting helper:** `ImageGenerator._inpaint_local`
- **Detection + segmentation:** `EditOrchestrator.get_mask` (in `interior_image_generator/pipeline/edit_orchestrator.py`)
- **FLUX/mask knobs:** `INPAINT_CFG` (top of file)
- **Style vocabulary:** `STYLE_GUIDANCE` dict + `resolve_style_guidance` / `resolve_style_key`
- **End-to-end pipeline endpoints:** `run_analysis_pipeline`, `complete_pipeline`, `analyze` (ASGI)

### Configuration Files

**Backend:**
- Modal app: `modal_updated_complete.py`
- Proxy server: `proxy_server.py`
- Deployment helper: `deploy_utf8.py`
- Port file: `.proxy-port` (auto-generated, gitignored)

**Frontend:**
- Main UI: `frontend/src/App.jsx`
- API layer: `frontend/src/utils/api.js`
- Config: `frontend/src/config.js` (reads from .env)
- Environment: `frontend/.env` (gitignored)
- Env template: `frontend/.env.example`
- Vite config: `frontend/vite.config.js` (reads proxy port from `.proxy-port`)

**Models:**
- Vision LoRA: `qwen25_vl_7b_objdesc_lora/`
- Chatbot LoRA: `qwen-interior-design-qlora/final-adapter/`
- Image generator: `interior_image_generator/` (git submodule)

---

## License & Credits

**Models Used:**
- Qwen2.5-VL-7B-Instruct (Vision)
- Qwen2.5-1.5B-Instruct (Chatbot)
- FLUX.1-Fill-dev (Inpainting)
- Grounding DINO (Object Detection)
- SAM2 (Segmentation)

**Infrastructure:**
- Modal Labs (Serverless GPU compute)
- React + Vite (Frontend)
- Flask (Local proxy)

