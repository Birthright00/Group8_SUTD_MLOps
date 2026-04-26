"""
Complete Modal deployment for Interior Design AI - ALL THREE MODELS.

Models:
1. Vision Analysis: Qwen2.5-VL-7B + VL_LORA
2. Interior Chatbot: Qwen2.5-1.5B + CHATBOT_QWEN_ADAPTOR
3. Image Generator: FLUX.1-Fill-dev (Grounding DINO + SAM2 + FLUX)

Usage:
    modal deploy modal_complete.py
"""

import modal
import os
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
    """Vision + Edit Generation model."""

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
        """Analyze image and detect objects."""
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

        # Parse objects
        objects = {}
        import re

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

        return {"objects": objects, "raw_output": output_text}

    @modal.method()
    def generate_edits(self, user_prompt: str, objects: dict) -> dict:
        """Generate edit suggestions."""
        import torch
        import json

        if not objects:
            return {}

        object_list = "\n".join([f"- {obj}: {desc}" for obj, desc in objects.items()])

        prompt = f"""Interior design AI. Transform room to: {user_prompt}

Current objects:
{object_list}

Generate edit suggestions for EVERY object listed above in the new style.
Use the EXACT object names from the list.
Output ONLY valid JSON with ALL objects: {{"object_name": "visual description", ...}}"""

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(text=[text], images=None, videos=None, padding=True, return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(**inputs, max_new_tokens=500, temperature=0.2, do_sample=True)

        output_text = self.processor.batch_decode(
            output_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0].split("assistant\n")[-1].strip()

        # Parse JSON
        try:
            start = output_text.find('{')
            end = output_text.rfind('}') + 1
            if start != -1 and end > start:
                return json.loads(output_text[start:end])
        except:
            pass

        # Fallback - use ALL objects, not just 5
        return {obj: f"{user_prompt} style {obj}" for obj in objects.keys()}


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
    """Fine-tuned interior design chatbot."""

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

    def _generate_response(self, question: str, max_new_tokens: int = 512) -> str:
        """Internal helper to generate chat responses (not a Modal method)."""
        import torch

        messages = [
            {"role": "system", "content": "You are an expert interior designer."},
            {"role": "user", "content": question}
        ]

        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(**inputs, max_new_tokens=max_new_tokens, temperature=0.7, do_sample=True)

        response = self.tokenizer.decode(output_ids[0][len(inputs.input_ids[0]):], skip_special_tokens=True)
        return response.strip()

    @modal.method()
    def chat(self, question: str, max_new_tokens: int = 512) -> str:
        """Answer interior design questions."""
        return self._generate_response(question, max_new_tokens)

    @modal.method()
    def improve_edit_plan(self, vision_output: dict, user_prompt: str, edit_suggestions: dict) -> str:
        """Critique and improve edit suggestions."""
        objects_text = "\n".join([f"- {obj}: {desc}" for obj, desc in vision_output.get("objects", {}).items()])
        edits_text = "\n".join([f"- {obj}: {desc}" for obj, desc in edit_suggestions.items()])

        question = f"""Transform room to: "{user_prompt}"

Current objects:
{objects_text}

Proposed edits:
{edits_text}

As an expert, critique and improve these suggestions. Consider Singapore HDB if applicable."""

        return self._generate_response(question, max_new_tokens=512)


# ============================================================================
# 3. IMAGE GENERATOR (FLUX.1-Fill-dev + Grounding DINO + SAM2)
# ============================================================================

@app.cls(
    image=image_gen_image,
    gpu="A100-80GB",  # FLUX needs 80GB
    secrets=[modal.Secret.from_dotenv(path="interior_image_generator/.env")],
    timeout=1200,
    scaledown_window=600,
)
class ImageGenerator:
    """Complete image editing: Detection → Segmentation → Inpainting."""

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
    def inpaint(self, image_b64: str, mask_b64: str, prompt: str, width: int = 1024, height: int = 1024,
                num_inference_steps: int = 50, guidance_scale: float = 30.0, seed: int = 42) -> str:
        """Inpaint masked region with FLUX."""
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
            max_sequence_length=512,
            generator=generator,
        ).images[0]

        # Encode result
        buf = io.BytesIO()
        result.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    @modal.method()
    def edit_object(self, image_bytes: bytes, target_object: str, fill_prompt: str, iterations: int = 3) -> dict:
        """
        Complete edit pipeline: Detection → Segmentation → Inpainting.

        Returns all iterations for visualization.

        This uses the interior_image_generator submodule.
        """
        import sys
        sys.path.insert(0, "/root/interior_image_generator")

        from PIL import Image
        import io
        from pipeline.edit_orchestrator import EditOrchestrator
        from pipeline.settings import Settings

        # Load image
        image = Image.open(io.BytesIO(image_bytes))

        # Configure settings (using local FLUX via self.inpaint)
        settings = Settings(
            modal_endpoint_url="local",  # We'll override this
            num_inference_steps=50,
            guidance_scale=30.0,
        )

        # Create orchestrator
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
        iterations_per_object: int = 3
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

        # Configure settings
        settings = Settings(
            modal_endpoint_url="local",
            num_inference_steps=50,
            guidance_scale=30.0,
        )

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
                    temp_image = self._inpaint_local(temp_image, mask, fill_prompt, seed=42+i)

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

    def _inpaint_local(self, image, mask, prompt, seed=42):
        """Helper to use local FLUX pipeline."""
        import torch
        from PIL import Image, ImageFilter
        import io
        import base64

        # Dilate mask
        mask_dilated = mask.filter(ImageFilter.MaxFilter(size=17))

        # Crop around mask
        bbox = mask_dilated.getbbox()
        if bbox:
            bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad_x = max(16, int(bw * 0.25))
            pad_y = max(16, int(bh * 0.25))
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
        target_size = 1024
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
            guidance_scale=30.0,
            num_inference_steps=50,
            max_sequence_length=512,
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
    """Helper function to run vision analysis and chatbot"""
    # Create handles once
    vision_model = VisionModel()
    chatbot = InteriorChatbot()

    # Step 1: Vision Analysis
    vision_output = vision_model.analyze_image.remote(image_bytes)

    # Step 2: Edit Suggestions
    edit_suggestions = vision_model.generate_edits.remote(prompt, vision_output.get("objects", {}))

    # Step 3: Chatbot Critique
    chatbot_critique = chatbot.improve_edit_plan.remote(vision_output, prompt, edit_suggestions)

    return {
        "success": True,
        "vision_analysis": vision_output,
        "edit_suggestions": edit_suggestions,
        "chatbot_critique": chatbot_critique,
    }

# ============================================================================
# WEB ENDPOINTS
# ============================================================================

@app.function(
    image=llm_image,
    timeout=1800  # 30 minutes - includes cold starts for all 3 models + image generation
)
@modal.asgi_app()
def analyze():
    """
    Complete analysis pipeline with CORS support: Vision → Edits → Chatbot Critique.
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
            print("[ANALYZE] STEP 1-3: Running vision analysis + chatbot...")
            result = await pipeline_fn.remote.aio(image_bytes, prompt)
            print(f"[ANALYZE] Analysis complete!")
            print(f"[ANALYZE]    - Objects found: {len(result.get('vision_analysis', {}).get('objects', {}))}")
            print(f"[ANALYZE]    - Edit suggestions: {len(result.get('edit_suggestions', {}))}")
            print(f"[ANALYZE]    - Chatbot response: {len(result.get('chatbot_critique', ''))} chars")

            # Step 4: Generate edited image
            edited_image_b64 = None
            edit_suggestions = result.get("edit_suggestions", {})

            if edit_suggestions:
                first_object = list(edit_suggestions.keys())[0]
                fill_prompt = edit_suggestions[first_object]

                print(f"[ANALYZE] STEP 4: Generating edited image...")
                print(f"[ANALYZE]    - Target object: {first_object}")
                print(f"[ANALYZE]    - Fill prompt: {fill_prompt}")

                generator = image_gen_cls()
                edited_image_bytes = await generator.edit_object.remote.aio(
                    image_bytes,
                    first_object,
                    fill_prompt,
                    iterations=3
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
    iterations = request.get("iterations", 3)

    if not image_b64 or not target_object:
        return JSONResponse(
            content={"error": "Missing image or target_object"},
            status_code=400,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    try:
        image_bytes = base64.b64decode(image_b64)
    except:
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
    timeout=1800
)
@modal.fastapi_endpoint(method="POST")
def complete_pipeline(request: dict):
    """
    COMPLETE END-TO-END PIPELINE: Vision → Chatbot → Image Generation.

    Request:
        {
            "image": "base64_encoded_image",
            "prompt": "Japanese themed house",
            "edit_objects": ["sofa", "wall"],  // Objects to actually edit (optional)
            "generate_images": true  // Whether to generate edited images (optional, default false)
        }

    Response:
        {
            "success": true,
            "vision_analysis": {...},
            "edit_suggestions": {...},
            "chatbot_critique": "...",
            "edited_images": {  // Only if generate_images=true
                "sofa": "base64_image",
                "wall": "base64_image"
            }
        }
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
    except:
        return JSONResponse(
            content={"error": "Invalid base64 image"},
            status_code=400,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    try:
        # Step 1: Vision Analysis
        print("[STEP1] Vision Analysis")
        vision_output = VisionModel().analyze_image.remote(image_bytes)

        # Step 2: Generate Edit Suggestions
        print("[STEP2] Generate Edit Suggestions")
        edit_suggestions = VisionModel().generate_edits.remote(prompt, vision_output.get("objects", {}))

        # Step 3: Chatbot Critique
        print("[STEP3] Chatbot Critique")
        chatbot_critique = InteriorChatbot().improve_edit_plan.remote(vision_output, prompt, edit_suggestions)

        result = {
            "success": True,
            "vision_analysis": vision_output,
            "edit_suggestions": edit_suggestions,
            "chatbot_critique": chatbot_critique
        }

        # Step 4: Generate Edited Images (optional)
        if generate_images and edit_suggestions:
            print("[STEP4] Sequential Multi-Object Editing with Iterative Refinement")

            # Determine which objects to edit - PRESERVE ORIGINAL DETECTION ORDER
            detected_objects = vision_output.get("objects", {})

            if edit_objects:
                # User specified which objects - use original order
                edit_plan = {obj: edit_suggestions[obj] for obj in detected_objects.keys()
                            if obj in edit_objects and obj in edit_suggestions}
            else:
                # Edit first 3 objects from ORIGINAL DETECTION ORDER (not edit_suggestions order)
                first_3_objects = list(detected_objects.keys())[:3]
                edit_plan = {obj: edit_suggestions[obj] for obj in first_3_objects if obj in edit_suggestions}

            if edit_plan:
                print(f"[PLAN] Edit plan: {list(edit_plan.keys())}")

                # Use sequential multi-object editing
                generator = ImageGenerator()
                edit_result = generator.edit_multiple_objects_sequential.remote(
                    image_bytes,
                    edit_plan,
                    iterations_per_object=3
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
    print(f"Chatbot critique: {result['chatbot_critique'][:200]}...")

    print("\n[DONE] All tests passed!")
