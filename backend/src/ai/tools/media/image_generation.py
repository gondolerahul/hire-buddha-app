"""
Image Generation Tool using Google Gemini API.

Supports:
- Text-to-image generation
- Image editing with reference images
- Vertex AI for all Google model access (no direct AI Studio calls)
- Cost logging via IntegrationRegistry SKU
"""
import logging
import json
import base64
import os
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from src.ai.tools.base import Tool

logger = logging.getLogger(__name__)

# Try to import Google GenAI SDK
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logger.warning("google.genai SDK not available for image generation")


class ImageGenerationTool(Tool):
    """
    AI tool for generating images using Google Gemini image generation models.
    
    API key resolution order (per request):
      1. IntegrationRegistry DB lookup using company_id from execution context
         (looks up by model_name SKU, then by service_category='IMAGE_GENERATION',
          then by provider='google')
      2. GOOGLE_API_KEY env var
      3. GEMINI_API_KEY env var
    
    Accepts a model name, prompt, and optional reference image to generate images.
    """
    name = "image_generation"
    description = (
        "Generate images from text prompts using AI models. "
        "Can also edit existing images by providing a reference image. "
        "Input should be a JSON string with: "
        "'prompt' (text description of desired image), "
        "and optionally 'model_name' (leave empty to use the configured default), "
        "and optionally 'reference_image_path' (path to an existing image for editing)."
    )

    # Output directory root — everything under artifact/system-generated/
    BASE_ARTIFACT_DIR = Path(__file__).resolve().parents[3] / "artifact" / "system-generated"
    # Fallback legacy dir (kept for safety, unused in new code)
    OUTPUT_DIR = str(BASE_ARTIFACT_DIR / "generated_images")

    def get_function_schema(self) -> Dict[str, Any]:
        """Return JSON schema for Gemini function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "model_name": {
                        "type": "string",
                        "description": "The image generation model to use. Leave empty to use the system default."
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Text description of the image to generate"
                    },
                    "reference_image_path": {
                        "type": "string",
                        "description": "Optional path to a reference image for image editing/modification"
                    }
                },
                "required": ["model_name", "prompt"]
            }
        }

    async def _resolve_vertex_metadata(self, model_name: str, company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Resolve the Vertex AI service_metadata from the integration registry."""
        if company_id:
            try:
                from uuid import UUID as _UUID
                from src.common.database import AsyncSessionLocal
                from src.config.service import ConfigService

                async with AsyncSessionLocal() as db:
                    config_service = ConfigService(db)
                    company_uuid = _UUID(str(company_id))

                    # Strategy 1: any IMAGE_GENERATION category entry for this company
                    from src.config.models import IntegrationRegistry
                    from sqlalchemy import select
                    result = await db.execute(
                        select(IntegrationRegistry).where(
                            IntegrationRegistry.company_id == company_uuid,
                            IntegrationRegistry.service_category == "IMAGE_GENERATION",
                            IntegrationRegistry.status == "active",
                        )
                    )
                    entry = result.scalars().first()
                    if entry and entry.service_metadata:
                        return entry.service_metadata

                    # Strategy 2: any 'google' or 'gemini' provider
                    integration = await config_service.get_integration_by_provider(company_uuid, "google")
                    if not integration:
                        integration = await config_service.get_integration_by_provider(company_uuid, "gemini")
                    if integration and integration.service_metadata:
                        return integration.service_metadata

            except Exception as e:
                logger.warning(f"[ImageGen] DB integration lookup failed (company={company_id}): {e}")

        return None

    async def _resolve_model_name_from_defaults(self, company_id: Optional[str] = None) -> Optional[str]:
        """Resolve the default image generation model from task defaults."""
        if not company_id:
            return None
        try:
            from uuid import UUID as _UUID
            from src.common.database import AsyncSessionLocal
            from src.config.service import ConfigService

            async with AsyncSessionLocal() as db:
                config_service = ConfigService(db)
                company_uuid = _UUID(str(company_id))
                integration, _ = await config_service.resolve_model_for_task(
                    company_id=company_uuid,
                    task_type="text_to_image",
                )
                if integration and integration.model_name:
                    logger.info(f"[ImageGen] Resolved model from task defaults: {integration.model_name}")
                    return integration.model_name
        except Exception as e:
            logger.warning(f"[ImageGen] Failed to resolve model from task defaults: {e}")
        return None

    def _get_output_dir(self, company_id: Optional[str] = None) -> Path:
        """Resolve the output directory for saving generated images.
        
        Saves to artifact/system-generated/{company_id}/{YYYY-MM-DD}/images/
        """
        from datetime import datetime as _dt
        date_str = _dt.utcnow().strftime("%Y-%m-%d")
        if company_id:
            out = self.BASE_ARTIFACT_DIR / str(company_id) / date_str / "images"
        else:
            out = self.BASE_ARTIFACT_DIR / "default" / date_str / "images"
        out.mkdir(parents=True, exist_ok=True)
        return out

    async def run(self, input_data: str) -> str:
        """Execute image generation without extra context (env-var API key only)."""
        return await self.run_with_context(input_data, context=None)

    async def run_with_context(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Execute image generation with execution context for DB key lookup.

        Args:
            input_data: JSON string with model_name, prompt, optional reference_image_path
            context: Execution context dict that may contain 'company_id' and 'user_id'

        Returns:
            JSON string with generation result including saved image path(s)
        """
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input. Expected: {\"model_name\": \"...\", \"prompt\": \"...\"}"})

        model_name = params.get("model_name") or None  # treat empty string as None
        prompt = params.get("prompt")
        reference_image_path = params.get("reference_image_path")

        # Pull company/user from context (injected by ToolExecutor)
        company_id = None
        user_id = None
        if context:
            company_id = context.get("company_id") or params.get("company_id")
            user_id = context.get("user_id") or params.get("user_id")

        if not prompt:
            return json.dumps({"error": "Missing required parameter: 'prompt'"})

        if not GENAI_AVAILABLE:
            return json.dumps({"error": "Google GenAI SDK not installed. Run: pip install google-genai"})

        # Resolve model_name from task defaults if not explicitly provided
        if not model_name:
            model_name = await self._resolve_model_name_from_defaults(company_id)
        if not model_name:
            return json.dumps({
                "error": (
                    "No image generation model specified and no default configured. "
                    "Please configure a 'text_to_image' task default in AI Model Configuration, "
                    "or pass 'model_name' explicitly."
                )
            })

        # Resolve Vertex AI service_metadata from DB
        service_metadata = await self._resolve_vertex_metadata(model_name, company_id)
        if not service_metadata or not service_metadata.get("project_id"):
            return json.dumps({
                "error": (
                    f"No Vertex AI configuration found for image generation model '{model_name}'. "
                    f"Please configure a 'google' integration with project_id in service_metadata "
                    f"(service_category='IMAGE_GENERATION' or provider_name='google') "
                    f"for company {company_id}."
                )
            })

        try:
            from src.common.genai_factory import build_vertex_genai_client_sync
            client = build_vertex_genai_client_sync(service_metadata)

            # Determine output directory
            output_dir = self._get_output_dir(company_id)

            result = {
                "model": model_name,
                "prompt": prompt,
                "images": [],
                "text_response": None,
                "image_path": None,  # Convenience: path to the first generated image
            }

            logger.info(f"[ImageGen] Generating with model={model_name}, company={company_id}, prompt='{prompt[:80]}...'")

            # Per-image cost for billing (Imagen 4 standard pricing)
            # imagen-4.0-generate-001 = $0.04/image, fast = $0.02, ultra = $0.06
            image_cost_map = {
                "imagen-4.0-generate-001": 0.04,
                "imagen-4-fast": 0.02,
                "imagen-4-ultra": 0.06,
            }
            image_cost = image_cost_map.get(model_name, 0.04)

            # ── Imagen models use generate_image API ──────────────────────────
            if "imagen" in model_name.lower():
                imagen_config = types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/png",
                )

                response = client.models.generate_images(
                    model=model_name,
                    prompt=prompt,
                    config=imagen_config,
                )

                if response.generated_images:
                    for gen_img in response.generated_images:
                        image_id = str(uuid.uuid4())[:8]
                        image_filename = f"panel_{image_id}.png"
                        image_path = str(output_dir / image_filename)

                        # gen_img.image is a google.genai.types.Image object
                        # Its save() only accepts a filepath string (not PIL.Image)
                        gen_img.image.save(image_path)

                        file_size = os.path.getsize(image_path)
                        result["images"].append({
                            "path": image_path,
                            "filename": image_filename,
                            "size_bytes": file_size,
                        })
                        if result["image_path"] is None:
                            result["image_path"] = image_path

                        logger.info(f"[ImageGen] Imagen image saved to {image_path}")

            # ── Gemini image models use generate_content API ──────────────────
            else:
                # Build content parts
                contents = []

                # Add reference image if provided
                if reference_image_path and os.path.exists(reference_image_path):
                    logger.info(f"Loading reference image from {reference_image_path}")
                    with open(reference_image_path, "rb") as f:
                        image_bytes = f.read()

                    ext = os.path.splitext(reference_image_path)[1].lower()
                    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                                ".webp": "image/webp", ".gif": "image/gif"}
                    mime_type = mime_map.get(ext, "image/png")
                    contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

                # Add text prompt
                contents.append(prompt)

                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"]
                    )
                )

                if response.candidates and response.candidates[0].content:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, 'text') and part.text:
                            result["text_response"] = part.text
                        elif hasattr(part, 'inline_data') and part.inline_data:
                            image_id = str(uuid.uuid4())[:8]
                            image_filename = f"panel_{image_id}.png"
                            image_path = str(output_dir / image_filename)

                            image_data = part.inline_data.data
                            if isinstance(image_data, str):
                                image_data = base64.b64decode(image_data)

                            with open(image_path, "wb") as f:
                                f.write(image_data)

                            result["images"].append({
                                "path": image_path,
                                "filename": image_filename,
                                "size_bytes": len(image_data)
                            })
                            if result["image_path"] is None:
                                result["image_path"] = image_path

                            logger.info(f"[ImageGen] Image saved to {image_path}")

            if not result["images"]:
                logger.warning(f"[ImageGen] No image parts in response for model={model_name}. Response: {response}")
                return json.dumps({
                    "error": "No image was generated. The model may have filtered the request or returned text only.",
                    "text_response": result.get("text_response")
                })

            result["image_count"] = len(result["images"])

            # ── Register each image in the artifacts DB ───────────────────────────
            if company_id:
                try:
                    from uuid import UUID as _UUID
                    from src.common.database import AsyncSessionLocal
                    from src.ai.artifact_service import ArtifactService, ORIGIN_SYSTEM
                    import mimetypes as _mime

                    async with AsyncSessionLocal() as _db:
                        art_svc = ArtifactService(_db)
                        for img_info in result["images"]:
                            img_path = Path(img_info["path"])
                            with open(img_path, "rb") as _f:
                                img_bytes = _f.read()
                            await art_svc.save_artifact(
                                file_bytes=img_bytes,
                                file_name=img_info["filename"],
                                mime_type="image/png",
                                file_category="images",
                                origin=ORIGIN_SYSTEM,
                                company_id=_UUID(str(company_id)),
                                purpose=f"AI-generated image: {prompt[:200]}",
                                generated_by=f"image_generation:{model_name}",
                                extra_metadata={"model": model_name, "prompt": prompt, "size_bytes": img_info["size_bytes"]},
                            )
                except Exception as _reg_err:
                    logger.warning(f"[ImageGen] Artifact DB registration failed (non-fatal): {_reg_err}")
            # ────────────────────────────────────────────────────────────────────────────

            # ── Record billing event for image generation ─────────────────────────
            if company_id:
                try:
                    from decimal import Decimal as _Decimal
                    from uuid import UUID as _UUID
                    from src.common.database import AsyncSessionLocal
                    from src.billing.billing_service import BillingService
                    from src.billing.credit_service import CreditService

                    async with AsyncSessionLocal() as _db:
                        _num_images = len(result["images"])
                        _total_cost = _Decimal(str(image_cost)) * _num_images

                        billing_svc = BillingService(_db)
                        await billing_svc.record_billing_event(
                            company_id=_UUID(str(company_id)),
                            base_cost=_total_cost,
                            grouping_type="tool",
                            grouping_value="image_generation",
                            image_gen_count=_num_images,
                            other_ai_cost=_total_cost,
                        )
                        credit_svc = CreditService(_db)
                        try:
                            await credit_svc.consume(_UUID(str(company_id)), _total_cost)
                        except Exception:
                            pass  # Don't block the result if credit deduction fails
                except Exception as _billing_err:
                    logger.warning(f"[ImageGen] Billing event failed (non-fatal): {_billing_err}")
            # ─────────────────────────────────────────────────────────────────────

            return json.dumps(result)

        except Exception as e:
            logger.error(f"[ImageGen] Image generation error: {e}", exc_info=True)
            return json.dumps({"error": f"Image generation failed: {str(e)}"})
