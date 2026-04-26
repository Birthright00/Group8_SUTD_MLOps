# Interior Design AI - Project Overview

## Problem Statement

### The Cost Barrier in Interior Design

Interior design services represent a significant financial commitment for homeowners:

| Service Type | Cost Range |
|--------------|------------|
| Full Interior Design Services | $34,000 - $234,000 |
| Small Surface Redesign | $11,000 - $15,000 |

Beyond the financial barrier, there's a fundamental challenge: **it's difficult to envision design ideas and definitively decide whether they match your desired outcome before committing**. Clients often struggle to visualize how proposed changes will look in their actual space, leading to costly revisions or dissatisfaction.

### Problem Context

When designing homes, homeowners face several challenges:

1. **Visualization Gap** - 2D mood boards and material samples don't convey how a redesigned room will actually feel
2. **Expensive Iteration** - Each design revision with a professional incurs additional costs
3. **Communication Barriers** - Translating abstract style preferences ("I want it to feel Japanese") into specific material and colour choices is difficult
4. **Commitment Anxiety** - Fear of making expensive decisions that can't be easily reversed

### How Might We...

> **How might we utilise self-hosted, open source models to explore and create an intuitive application for envisioning interior design ideas?**

---

## Our Solution

An AI-powered interior design visualization tool that transforms photos of existing spaces into redesigned rooms matching a user's chosen aesthetic style - instantly and at no cost per use.

### Key Capabilities

1. **Upload any room photo** - Works with real interior photographs
2. **Choose a design style** - Japanese, Scandinavian, Industrial, Minimalist, Bohemian, or custom prompts
3. **AI analyzes the space** - Detects furniture, decor, and architectural elements
4. **Generates specific redesign suggestions** - Material-specific prompts (e.g., "hinoki cypress frame with urushi lacquer finish" not just "wooden frame")
5. **Produces photorealistic transformations** - See your actual room reimagined in the chosen style

---

## Technical Plan & Architecture

### Overview

```
User Browser (React Frontend)
    |
    v
Local Proxy Server (Flask, handles long timeouts)
    |
    v
Modal Serverless GPUs
    |
    +-- VisionModel (Qwen2.5-VL-7B + LoRA)
    |     - Detects objects in room
    |     - Generates initial edit suggestions
    |
    +-- InteriorChatbot (Qwen2.5-1.5B + LoRA)
    |     - Fine-tuned on interior design critiques
    |     - Polishes suggestions with specific materials/textures/colours
    |
    +-- ImageGenerator (FLUX.1-Fill-dev + Grounding DINO + SAM2)
          - Locates and segments each object
          - Inpaints with style-specific prompts
```

### Models Used (All Open Source / Self-Hosted)

| Component | Model | Purpose |
|-----------|-------|---------|
| Vision Analysis | Qwen2.5-VL-7B-Instruct + Custom LoRA | Object detection and scene understanding |
| Design Expertise | Qwen2.5-1.5B-Instruct + Custom LoRA | Style-specific material/finish suggestions |
| Object Detection | Grounding DINO | Locate objects by name in images |
| Segmentation | SAM2 | Generate precise masks for inpainting |
| Image Generation | FLUX.1-Fill-dev | Photorealistic inpainting |

### Pipeline Flow

**Step 1: Vision Analysis (~30s)**
- Input: Interior photo
- Output: Detected objects with descriptions
- Example: `{"sofa": "modern grey sectional", "table": "wooden coffee table"}`

**Step 2: Draft Edit Suggestions (~20s)**
- Input: Detected objects + user's style prompt
- Output: Per-object transformation prompts
- Quality filtering rejects generic outputs ("beautiful modern sofa") in favor of specific ones

**Step 3: Chatbot Polish (~10s)**
- Input: Draft suggestions
- Output: Material-specific, render-ready prompts
- Example: `"traditional Japanese futon in undyed ramie linen with hinoki cypress frame, warm off-white tones"`

**Step 4: Sequential Inpainting (~8-12 min)**
- For each object:
  1. Grounding DINO locates the object
  2. SAM2 generates a precise mask
  3. FLUX.1-Fill-dev inpaints with the polished prompt
  4. Multiple refinement passes with different seeds
- Edits accumulate (sofa → sofa+table → sofa+table+chair)

### Style Intelligence

The system includes curated style vocabularies for authentic results:

| Style | Materials | Finishes | Colours |
|-------|-----------|----------|---------|
| Japanese | washi paper, hinoki cypress, urushi lacquer, tatami rush | matte grain, satin lacquer, shoji-filtered glow | warm off-white, indigo, cedar brown |
| Scandinavian | light oak, birch, undyed wool, linen | pale matte, soft velvet, whitewashed grain | chalk white, pale grey, muted sage |
| Industrial | blackened steel, raw concrete, reclaimed brick | matte black, patinated, exposed welds | charcoal, rust brown, gunmetal |
| Minimalist | honed plaster, matte lacquer, pale stone | seamless matte, crisp edges | pure white, warm grey, soft black |
| Bohemian | rattan, jute, hand-loomed cotton, terracotta | woven texture, hand-finished | terracotta, mustard, teal |

---

## Current Experimentation Status

### What's Working

- [x] End-to-end pipeline from image upload to transformed output
- [x] Multi-object sequential editing (edits accumulate correctly)
- [x] Style-specific vocabulary injection
- [x] Iterative refinement passes for quality improvement
- [x] React frontend with transformation carousel
- [x] Proxy server handling Modal cold starts (40-minute timeout)

### Active Experiments

1. **VLM LoRA Fine-tuning** - Improving object description quality and style adherence
2. **Chatbot LoRA Training** - Better material/texture specificity in polished prompts
3. **Prompt Engineering** - Reducing fallback to template prompts
4. **Inpainting Parameters** - Tuning guidance scale, inference steps, mask dilation

### Known Limitations

- Cold start time: 5-10 minutes on first request (model loading)
- Processing time: 10-15 minutes for 3 objects with refinement passes
- VLM sometimes produces generic suggestions requiring fallback templates
- Style vocabulary limited to 5 predefined styles (extensible via config)

---

## Infrastructure

| Component | Technology | Purpose |
|-----------|------------|---------|
| GPU Compute | Modal Labs (Serverless) | A100-40GB for VLM/Chatbot, A100-80GB for FLUX |
| Frontend | React + Vite | User interface |
| Proxy | Flask | Handle long timeouts, CORS |
| Deployment | Modal CLI | One-command deploy |

### Cost Model

- **No per-image licensing fees** - All models are open source
- **Pay-per-second GPU usage** - Only charged when processing
- **Self-hostable** - Can migrate to own infrastructure if needed

---

## Repository Structure

```
Group8_SUTD_MLOps/
├── modal_updated_complete.py    # Main backend (3 AI models)
├── proxy_server.py              # Local timeout-handling proxy
├── deploy_utf8.py               # Deployment script
├── frontend/                    # React application
├── qwen25_vl_7b_objdesc_lora/   # Vision model LoRA weights
├── qwen-interior-design-qlora/  # Chatbot LoRA weights
└── interior_image_generator/    # FLUX pipeline (submodule)
```

---

## Future Directions

1. **Real-time preview** - Faster single-object edits for interactive exploration
2. **Style mixing** - Combine elements from multiple styles
3. **Budget-aware suggestions** - Filter materials by price tier
4. **AR integration** - View transformations overlaid on live camera feed
5. **Multi-room consistency** - Maintain style coherence across spaces
