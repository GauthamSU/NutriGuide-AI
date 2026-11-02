import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union
import httpx
from django.conf import settings
from openai import OpenAI
from pydantic import BaseModel
from nutrition.schemas import (
    LLMDecomposeIngredientsResponseSchema,
    LLMDishIngredientsResponseSchema,
    LLMNutrientResponseSchema,
    NutrientAnalysisDataSchema,
)
from nutrition.services.db_nutrition_service import resolve_dish_nutrition_from_db

logger = logging.getLogger(__name__)


def build_system_prompt(
    response_schema: Optional[Union[BaseModel, Type[BaseModel], Dict[str, Any]]] = None,
) -> str:
    """
    Constructs the system prompt dynamically from a Pydantic schema object or class.
    Instructs the AI to identify the dish and all individual ingredients used in preparing it,
    while strictly prohibiting AI-generated nutrient figures (all nutrients are retrieved
    from the authoritative reference database).
    """
    if response_schema is None:
        schema_json = LLMDishIngredientsResponseSchema.to_compact_json()
    elif isinstance(response_schema, type) and issubclass(response_schema, BaseModel):
        if hasattr(response_schema, "to_compact_json"):
            schema_json = response_schema.to_compact_json()
        else:
            try:
                schema_json = response_schema().model_dump_json()
            except Exception:
                schema_json = json.dumps(
                    response_schema.model_json_schema(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
    elif isinstance(response_schema, BaseModel):
        schema_json = response_schema.model_dump_json()
    elif isinstance(response_schema, dict):
        schema_json = json.dumps(response_schema, separators=(",", ":"))
    else:
        schema_json = str(response_schema)

    return (
        "You are NutriGuide-AI, an expert culinary chef, master recipe developer, and nutritional biochemist.\n"
        "Your task is to identify the dish/meal from the user's input (text, image, and/or voice) and identify ALL the different ingredients used in preparing that dish, along with their culinary serving size description and estimated weight in grams.\n\n"
        "### CORE MISSION:\n"
        "1. IDENTIFY THE RECIPE: Determine the exact traditional dish or meal combination (e.g., 'Masala Dosa', 'Idli and Sambar').\n"
        "2. EXTRACT RAW COOKING INGREDIENTS: Break down the meal into the exact raw agricultural ingredients a chef puts into the cooking pot or pan (grains, lentils, vegetables, spices, cooking fat).\n"
        "3. ESTIMATE REALISTIC PORTIONS: For each ingredient, estimate realistic weights in grams for a single serving.\n\n"
        "### STRICT NEGATIVE RULES (MANDATORY TO AVOID PIPELINE FAILURES):\n"
        "- NEVER output dish names as ingredients: NEVER output 'Idli', 'Dosa', 'Sambar', 'Curry', 'Chutney', 'Dal', or 'Stew' as an ingredient name. Instead, output the raw ingredients used to make them.\n"
        "- NEVER output intermediate preparations or batters: NEVER output 'Rice batter', 'Dosa batter', 'Idli batter', 'Dough', or 'Flour paste'. Always break batters down into their raw grains and lentils: 'Rice' and 'Urad dal'.\n"
        "- NEVER group ingredients or use parenthetical notes/examples: NEVER output 'Spices (e.g., turmeric, chili powder)' or 'Vegetables (in Sambar, e.g., carrot, green beans)'. Every single ingredient MUST be its own separate, atomic entry: 'Turmeric powder', 'Red chilli powder', 'Carrot', 'French beans'.\n"
        "- NEVER use slashes, 'and/or', or alternatives: NEVER write 'Oil/Ghee' or 'Chilli/Pepper'. Choose ONE single specific item: 'Cooking oil' or 'Ghee'.\n"
        "- NEVER include non-edible serving tableware or platters: Banana leaves, plates, bowls, and cutlery are NOT food. NEVER output 'Banana leaf', 'plate', or 'bowl' as an ingredient.\n"
        "- CRITICAL INSTRUCTION: DO NOT generate, estimate, or hallucinate any nutrient numbers, calories, macronutrients, or micronutrients. Your only responsibility is to identify the dish and its ingredients. All nutritional data must come strictly from the reference database, NOT from AI.\n\n"
        "### REFERENCE RECIPE EXAMPLES:\n"
        "- EXAMPLE 1 ('Masala Dosa'):\n"
        "  dish_name: 'Masala Dosa'\n"
        "  ingredients: [\n"
        "    {\"ingredient_name\": \"Rice\", \"serving_size_description\": \"For dosa crepe\", \"estimated_weight_grams\": 90.0},\n"
        "    {\"ingredient_name\": \"Urad dal\", \"serving_size_description\": \"For dosa crepe\", \"estimated_weight_grams\": 30.0},\n"
        "    {\"ingredient_name\": \"Potato\", \"serving_size_description\": \"Boiled for potato masala\", \"estimated_weight_grams\": 100.0},\n"
        "    {\"ingredient_name\": \"Onion\", \"serving_size_description\": \"Chopped for potato masala\", \"estimated_weight_grams\": 40.0},\n"
        "    {\"ingredient_name\": \"Tomato\", \"serving_size_description\": \"For potato masala\", \"estimated_weight_grams\": 30.0},\n"
        "    {\"ingredient_name\": \"Green chilli\", \"serving_size_description\": \"Chopped for spice\", \"estimated_weight_grams\": 5.0},\n"
        "    {\"ingredient_name\": \"Turmeric powder\", \"serving_size_description\": \"Coloring for potato filling\", \"estimated_weight_grams\": 2.0},\n"
        "    {\"ingredient_name\": \"Mustard seeds\", \"serving_size_description\": \"Tempering\", \"estimated_weight_grams\": 2.0},\n"
        "    {\"ingredient_name\": \"Cooking oil\", \"serving_size_description\": \"Roasting and tempering\", \"estimated_weight_grams\": 10.0}\n"
        "  ]\n\n"
        "- EXAMPLE 2 ('Idli and Sambar served on a banana leaf'):\n"
        "  dish_name: 'Idli and Sambar'\n"
        "  (Banana leaf is tableware and is completely excluded)\n"
        "  ingredients: [\n"
        "    {\"ingredient_name\": \"Rice\", \"serving_size_description\": \"For steamed idlis\", \"estimated_weight_grams\": 80.0},\n"
        "    {\"ingredient_name\": \"Urad dal\", \"serving_size_description\": \"For steamed idlis\", \"estimated_weight_grams\": 25.0},\n"
        "    {\"ingredient_name\": \"Toor dal\", \"serving_size_description\": \"Pigeon pea lentil for sambar\", \"estimated_weight_grams\": 40.0},\n"
        "    {\"ingredient_name\": \"Onion\", \"serving_size_description\": \"Shallots/onion for sambar\", \"estimated_weight_grams\": 30.0},\n"
        "    {\"ingredient_name\": \"Tomato\", \"serving_size_description\": \"Chopped tomato for sambar\", \"estimated_weight_grams\": 30.0},\n"
        "    {\"ingredient_name\": \"Drumstick\", \"serving_size_description\": \"Vegetable in sambar\", \"estimated_weight_grams\": 30.0},\n"
        "    {\"ingredient_name\": \"Tamarind\", \"serving_size_description\": \"Tamarind pulp for sambar\", \"estimated_weight_grams\": 10.0},\n"
        "    {\"ingredient_name\": \"Turmeric powder\", \"serving_size_description\": \"Sambar spice\", \"estimated_weight_grams\": 2.0},\n"
        "    {\"ingredient_name\": \"Red chilli powder\", \"serving_size_description\": \"Sambar spice\", \"estimated_weight_grams\": 3.0},\n"
        "    {\"ingredient_name\": \"Mustard seeds\", \"serving_size_description\": \"Tempering\", \"estimated_weight_grams\": 2.0},\n"
        "    {\"ingredient_name\": \"Curry leaves\", \"serving_size_description\": \"Tempering\", \"estimated_weight_grams\": 2.0},\n"
        "    {\"ingredient_name\": \"Cooking oil\", \"serving_size_description\": \"Tempering oil for sambar\", \"estimated_weight_grams\": 10.0}\n"
        "  ]\n\n"
        "Respond ONLY with a single-line minified JSON object (no markdown fences, no extra spaces/newlines) matching this structure:\n"
        f"{schema_json}"
    )


# System prompt generated dynamically from the Pydantic schema
SYSTEM_PROMPT = build_system_prompt(LLMDishIngredientsResponseSchema)

MACRO_KEYS = [
    "calories_kcal",
    "protein_g",
    "carbohydrates_g",
    "dietary_fiber_g",
    "total_sugars_g",
    "added_sugars_g",
    "total_fat_g",
    "saturated_fat_g",
    "monounsaturated_fat_g",
    "polyunsaturated_fat_g",
    "unsaturated_fat_g",
    "trans_fat_g",
    "cholesterol_mg",
    "sodium_mg",
    "water_g",
]


class LlamaCppClient:
    """
    Unified LLM client for NutriGuide-AI.
    Supports two inference backends controlled by settings.INFERENCE_BACKEND:
      - 'local'  → llama-server (llama.cpp) running Gemma 4 E2B multimodal locally
      - 'gemini' → Google Gemini API via its OpenAI-compatible endpoint

    Supports text, image (base64 data URI), and voice/audio (base64 WAV/MP3) inputs.
    Identifies dish & ingredients via AI, then resolves nutrients from the database.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: Optional[float] = None,
        response_schema: Optional[Union[BaseModel, Type[BaseModel], Dict[str, Any]]] = None,
        backend: Optional[str] = None,
    ):
        self.backend = (backend or settings.INFERENCE_BACKEND).strip().lower()

        if self.backend == "gemini":
            self.base_url = base_url or settings.GEMINI_BASE_URL
            self.model_name = model_name or settings.GEMINI_MODEL_NAME
            self.timeout = timeout or getattr(settings, "GEMINI_TIMEOUT_SECONDS", 60)
            api_key = settings.GEMINI_API_KEY
            if not api_key:
                raise ValueError(
                    "GEMINI_API_KEY is not set in .env but INFERENCE_BACKEND='gemini'. "
                    "Please add your Gemini API key to .env."
                )
            self.client = OpenAI(
                base_url=self.base_url,
                api_key=api_key,
                timeout=self.timeout,
            )
        else:
            # Default: local llama-cpp server
            self.backend = "local"
            self.base_url = base_url or settings.LLAMA_SERVER_BASE_URL
            self.model_name = model_name or settings.LLAMA_MODEL_NAME
            self.timeout = timeout or settings.LLAMA_TIMEOUT_SECONDS
            self.client = OpenAI(
                base_url=self.base_url,
                api_key="llama-cpp-local",
                timeout=self.timeout,
            )

        self.response_schema = response_schema or LLMDishIngredientsResponseSchema
        self.system_prompt = build_system_prompt(self.response_schema)

    def check_health(self) -> Dict[str, Any]:
        """Checks whether the active inference backend is running and healthy."""
        if self.backend == "gemini":
            return self._check_gemini_health()
        return self._check_local_health()

    def _check_local_health(self) -> Dict[str, Any]:
        """Checks whether the local llama-server is running and healthy."""
        health_url = f"http://{settings.LLAMA_SERVER_HOST}:{settings.LLAMA_SERVER_PORT}/health"
        try:
            with httpx.Client(timeout=3.0) as http_client:
                resp = http_client.get(health_url)
                data = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                return {
                    "backend": "local",
                    "reachable": resp.status_code == 200,
                    "status": data.get("status", f"HTTP {resp.status_code}"),
                    "model_name": self.model_name,
                }
        except Exception as exc:
            return {
                "backend": "local",
                "reachable": False,
                "status": f"unreachable ({exc.__class__.__name__})",
                "model_name": self.model_name,
            }

    def _check_gemini_health(self) -> Dict[str, Any]:
        """Checks connectivity to the Google Gemini API by listing models."""
        try:
            models = self.client.models.list()
            model_ids = [m.id for m in models]
            target_available = self.model_name in model_ids
            return {
                "backend": "gemini",
                "reachable": True,
                "status": "ok" if target_available else f"ok (model '{self.model_name}' not in list, but API reachable)",
                "model_name": self.model_name,
                "models_available": len(model_ids),
                "target_model_found": target_available,
            }
        except Exception as exc:
            return {
                "backend": "gemini",
                "reachable": False,
                "status": f"unreachable ({exc.__class__.__name__})",
                "model_name": self.model_name,
            }

    def generate_structured_response(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: Type[BaseModel],
        image_base64: Optional[str] = None,
        image_mime_type: Optional[str] = "image/jpeg",
    ) -> Dict[str, Any]:
        """Generate a JSON response for a workflow-specific prompt and schema."""
        if image_base64:
            mime = image_mime_type or "image/jpeg"
            user_content: Any = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_base64}"},
                },
                {
                    "type": "text",
                    "text": user_prompt,
                },
            ]
        else:
            user_content = user_prompt

        create_kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": max(getattr(settings, "LLM_MAX_OUTPUT_TOKENS", 1800), 8192),
            "timeout": max(float(getattr(self, "timeout", 180.0) or 180.0), 600.0),
        }
        if self.backend == "gemini":
            create_kwargs["response_format"] = {"type": "json_object"}
        else:
            create_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False},
            }

        response = self.client.chat.completions.create(**create_kwargs)
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise ValueError("The AI model returned an empty meal plan.")
        validated = response_schema.model_validate(self._extract_json(content))
        return validated.model_dump(mode="json")

    def transcribe_audio(
        self,
        audio_base64: str,
        audio_format: str = "wav",
    ) -> str:
        """Return a verbatim transcript generated by the configured multimodal model."""
        fmt = audio_format.lower().lstrip(".")
        user_content = [
            {
                "type": "input_audio",
                "input_audio": {"data": audio_base64, "format": fmt},
            },
            {
                "type": "text",
                "text": (
                    "Transcribe the spoken audio verbatim in its original language. "
                    "Return only the words that were spoken. Do not summarize, translate, "
                    "identify foods, or add labels."
                ),
            },
        ]
        create_kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise speech transcription model.",
                },
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "max_tokens": 1000,
        }
        if self.backend == "local":
            create_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False},
            }

        response = self.client.chat.completions.create(**create_kwargs)
        content = response.choices[0].message.content
        if isinstance(content, list):
            transcript = " ".join(
                str(part.get("text", "")).strip()
                for part in content
                if isinstance(part, dict) and part.get("text")
            ).strip()
        else:
            transcript = str(content or "").strip()
        if not transcript:
            raise ValueError("The AI model returned an empty audio transcription.")
        return transcript

    def identify_dish_and_ingredients(
        self,
        input_text: Optional[str] = None,
        image_base64: Optional[str] = None,
        image_mime_type: Optional[str] = "image/jpeg",
        audio_base64: Optional[str] = None,
        audio_format: Optional[str] = "wav",
    ) -> Dict[str, Any]:
        """
        Sends multimodal content to the LLM to identify the dish and all ingredients used,
        strictly without hallucinating nutrient values.
        """
        user_content: List[Dict[str, Any]] = []

        if image_base64:
            mime = image_mime_type or "image/jpeg"
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_base64}"},
                }
            )

        if audio_base64:
            fmt = (audio_format or "wav").lower().lstrip(".")
            user_content.append(
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio_base64,
                        "format": fmt,
                    },
                }
            )

        prompt_parts: List[str] = []
        clean_text = (
            input_text.strip()
            if input_text and input_text.strip() and input_text.strip().lower() != "string"
            else None
        )

        if clean_text and not image_base64 and not audio_base64:
            prompt_parts.append(
                f"Identify the complete culinary recipe for '{clean_text}'. "
                f"Extract all raw, atomic cooking ingredients (grains, lentils, vegetables, spices, cooking oils) "
                f"with portion weights in grams. Do not output dish names, batters, parenthetical notes, or slashes."
            )
        elif image_base64:
            if clean_text:
                prompt_parts.append(f"User context / description: '{clean_text}'.")
            prompt_parts.append(
                "Inspect the food image closely, including all main items, gravies, curries, and accompaniments. "
                "Identify the complete dish/meal recipe. "
                "Extract all individual raw cooking ingredients (e.g., Rice, Urad dal, Toor dal, Onion, Tomato, Spices, Oil) with portion weights in grams. "
                "CRITICAL: Ignore non-edible tableware like banana leaves, plates, or bowls (NEVER list Banana leaf). "
                "Do not output dish names (like Idli or Sambar) or batters; output atomic raw ingredients only."
            )
        elif audio_base64:
            if clean_text:
                prompt_parts.append(f"User context: '{clean_text}'.")
            prompt_parts.append(
                "Listen to the voice audio. Identify the meal recipe and extract all raw cooking ingredients with portion weights in grams."
            )

        if not image_base64 and not audio_base64:
            final_user_content: Any = "\n".join(prompt_parts)
        else:
            user_content.append({"type": "text", "text": "\n".join(prompt_parts)})
            final_user_content = user_content

        create_kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": final_user_content},
            ],
            "temperature": 0.1,
            "max_tokens": getattr(settings, "LLM_MAX_OUTPUT_TOKENS", 1800),
        }
        if self.backend == "gemini":
            create_kwargs["response_format"] = {"type": "json_object"}
        # extra_body with chat_template_kwargs is only supported by local llama-server
        if self.backend == "local":
            create_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False},
            }

        initial_max_tokens = create_kwargs["max_tokens"]
        previous_attempts: List[Dict[str, Any]] = []

        for attempt in range(2):
            if attempt == 1:
                create_kwargs["max_tokens"] = max(initial_max_tokens * 2, 4096)
                logger.warning(
                    "Model response was truncated; retrying %s/%s with max_tokens=%s",
                    self.backend,
                    self.model_name,
                    create_kwargs["max_tokens"],
                )

            response = self.client.chat.completions.create(**create_kwargs)
            raw_content = response.choices[0].message.content or "{}"
            finish_reason = getattr(response.choices[0], "finish_reason", None)

            try:
                parsed_response = self._extract_json(raw_content)
            except ValueError as exc:
                error_message = str(exc)
                if attempt == 0 and finish_reason == "length":
                    previous_attempts.append({
                        "max_tokens": create_kwargs["max_tokens"],
                        "finish_reason": finish_reason,
                        "parse_error": error_message,
                        "raw_response": raw_content,
                    })
                    continue

                debug_path = getattr(
                    settings,
                    "LLM_RESPONSE_DEBUG_FILE",
                    settings.BASE_DIR / "llm_response_debug.json",
                )
                error_message = (
                    f"Model returned invalid JSON (finish_reason={finish_reason}): "
                    f"{error_message}. Raw response diagnostics: {debug_path}"
                )
                self._write_response_debug(
                    response,
                    raw_content,
                    parse_error=error_message,
                    retry_count=attempt,
                    previous_attempts=previous_attempts,
                )
                raise ValueError(error_message) from exc

            self._write_response_debug(
                response,
                raw_content,
                parsed_response=parsed_response,
                retry_count=attempt,
                previous_attempts=previous_attempts,
            )
            return parsed_response

        raise RuntimeError("Model JSON retry loop exited unexpectedly.")

    def _write_response_debug(
        self,
        response: Any,
        raw_content: str,
        parse_error: Optional[str] = None,
        parsed_response: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
        previous_attempts: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Persist the latest dish-identification completion for local inspection."""
        debug_path = Path(
            getattr(
                settings,
                "LLM_RESPONSE_DEBUG_FILE",
                settings.BASE_DIR / "llm_response_debug.json",
            )
        )
        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        if usage is not None and hasattr(usage, "model_dump"):
            usage = usage.model_dump()

        record = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "backend": self.backend,
            "model": self.model_name,
            "finish_reason": getattr(choice, "finish_reason", None),
            "usage": usage,
            "retry_count": retry_count,
            "previous_attempts": previous_attempts or [],
            "parse_error": parse_error,
            "raw_response": raw_content,
            "parsed_response": parsed_response,
        }
        try:
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except (OSError, TypeError) as exc:
            logger.warning("Could not write LLM response diagnostics to %s: %s", debug_path, exc)

    def decompose_ingredients(
        self, unmapped_items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Takes a list of ingredients that could not be resolved in the reference database,
        and asks the LLM to decompose any composite foods (e.g. batters, pastes, blends, powders)
        into their raw constituent ingredients with proportional weights.
        """
        if not unmapped_items:
            return {"decompositions": []}

        schema_json = LLMDecomposeIngredientsResponseSchema.to_compact_json()
        system_prompt = (
            "You are NutriGuide-AI, an expert culinary nutrition scientist.\n"
            "Your task is to examine ingredients that could not be found directly in the Indian Food Composition database and decompose them into raw, atomic culinary ingredients.\n\n"
            "### RULES:\n"
            "1. IF AN INGREDIENT IS A BATTER (e.g., 'Rice batter', 'Dosa batter', 'Idli batter'):\n"
            "   Decompose into:\n"
            "   - 'Rice' (75% of weight)\n"
            "   - 'Urad dal' (25% of weight)\n"
            "2. IF AN INGREDIENT HAS A SLASH OR ALTERNATIVE (e.g., 'Oil/Ghee'):\n"
            "   Choose the primary item: 'Cooking oil' (100% of weight).\n"
            "3. IF AN INGREDIENT GROUPS MULTIPLE SPICES (e.g., 'Spices (e.g., turmeric, chili powder)' 5g):\n"
            "   Unpack into separate items: 'Turmeric powder' (2g) and 'Red chilli powder' (3g).\n"
            "4. IF AN INGREDIENT GROUPS VEGETABLES (e.g., 'Vegetables (in Sambar, e.g., carrot, green beans)' 50g):\n"
            "   Unpack into separate items: 'Carrot' (25g) and 'French beans' (25g).\n"
            "5. IF AN INGREDIENT IS A PREPARED DISH NAME (e.g., 'Idli' 60g):\n"
            "   Decompose into raw ingredients: 'Rice' (45g) and 'Urad dal' (15g).\n"
            "6. IF AN INGREDIENT IS A STEW OR GRAVY (e.g., 'Sambar' 250g):\n"
            "   Decompose into: 'Toor dal' (50g), 'Onion' (40g), 'Tomato' (40g), 'Tamarind' (10g), 'Cooking oil' (10g), 'Turmeric powder' (2g), 'Red chilli powder' (3g).\n"
            "7. IF AN INGREDIENT IS NON-EDIBLE (e.g., 'Banana leaf', 'plate', 'bowl'):\n"
            "   Set can_decompose to false and sub_ingredients to an empty list.\n"
            "8. IF AN INGREDIENT IS AN ATOMIC RAW FOOD that cannot be broken down further:\n"
            "   Set can_decompose to false and sub_ingredients to an empty list.\n"
            "9. DO NOT estimate or hallucinate any nutrient numbers, calories, macronutrients, or micronutrients. Only identify ingredients and their weights in grams.\n\n"
            "Respond ONLY with a single-line minified JSON object matching this structure:\n"
            f"{schema_json}"
        )

        items_description = "\n".join(
            f"- {item.get('ingredient_name') or item.get('food_name')}: {item.get('estimated_weight_grams', 100.0)}g ({item.get('serving_size_description', '1 serving')})"
            for item in unmapped_items
        )
        user_prompt = f"Decompose the following unmapped ingredients into simpler/raw constituent ingredients:\n{items_description}"

        create_kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 800,
        }
        if self.backend == "local":
            create_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False},
            }

        response = self.client.chat.completions.create(**create_kwargs)

        raw_content = response.choices[0].message.content or "{}"
        return self._extract_json(raw_content)

    def analyze_food_multimodal(
        self,
        input_text: Optional[str] = None,
        image_base64: Optional[str] = None,
        image_mime_type: Optional[str] = "image/jpeg",
        audio_base64: Optional[str] = None,
        audio_format: Optional[str] = "wav",
    ) -> NutrientAnalysisDataSchema:
        """
        Multimodal flow:
        1. Asks AI ONLY to identify the dish and its ingredients (no AI-generated nutrients).
        2. Resolves each ingredient from the database and computes nutrients from database values only.
        3. Identifies and flags missing ingredients.
        """
        parsed_dict = self.identify_dish_and_ingredients(
            input_text=input_text,
            image_base64=image_base64,
            image_mime_type=image_mime_type,
            audio_base64=audio_base64,
            audio_format=audio_format,
        )

        # If input was a legacy full-analysis payload (e.g. from mock tests), normalize it
        if any(isinstance(item, dict) and "macronutrients" in item for item in (parsed_dict.get("items") or [])):
            normalized_dict = self._normalize_analysis_dict(parsed_dict, input_text)
            return NutrientAnalysisDataSchema.model_validate(normalized_dict)

        # Standard flow: Resolve dish ingredients against the reference database
        normalized_dish = self._normalize_dish_response(parsed_dict, input_text)
        resolved_dict = resolve_dish_nutrition_from_db(normalized_dish)
        return NutrientAnalysisDataSchema.model_validate(resolved_dict)

    @classmethod
    def _normalize_dish_response(
        cls, data: Dict[str, Any], fallback_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Normalizes AI dish and ingredients identification JSON into standard format.
        """
        if not isinstance(data, dict):
            raise ValueError("Model output JSON root must be an object.")

        dish_name = (
            data.get("dish_name")
            or data.get("meal_title")
            or fallback_text
            or "Analyzed Dish"
        )

        summary = (
            data.get("recognized_input_summary")
            or fallback_text
            or f"Identified dish: {dish_name}"
        )

        raw_ingredients = (
            data.get("ingredients")
            or data.get("items")
            or []
        )
        if not isinstance(raw_ingredients, list):
            raw_ingredients = []

        normalized_ingredients: List[Dict[str, Any]] = []
        for item in raw_ingredients:
            if not isinstance(item, dict):
                continue
            ing_name = (
                item.get("ingredient_name")
                or item.get("food_name")
                or "Unknown Ingredient"
            ).strip()
            serving_desc = item.get("serving_size_description") or "1 serving"
            try:
                weight_g = float(item.get("estimated_weight_grams") or 100.0)
            except (TypeError, ValueError):
                weight_g = 100.0
            try:
                conf = float(item.get("confidence") or 0.9)
            except (TypeError, ValueError):
                conf = 0.9

            normalized_ingredients.append({
                "ingredient_name": ing_name,
                "serving_size_description": serving_desc,
                "estimated_weight_grams": weight_g,
                "confidence": conf,
                "glycemic_index_category": item.get("glycemic_index_category"),
            })

        # Coerce dietary_tags and health_insights to lists
        dietary_tags = data.get("dietary_tags")
        if isinstance(dietary_tags, str):
            dietary_tags = [dietary_tags] if dietary_tags.strip() else []
        elif not isinstance(dietary_tags, list):
            dietary_tags = []
        else:
            dietary_tags = [str(x) for x in dietary_tags if x is not None]

        health_insights = data.get("health_insights")
        if isinstance(health_insights, str):
            health_insights = [health_insights] if health_insights.strip() else []
        elif not isinstance(health_insights, list):
            health_insights = []
        else:
            health_insights = [str(x) for x in health_insights if x is not None]

        return {
            "dish_name": dish_name,
            "recognized_input_summary": summary,
            "ingredients": normalized_ingredients,
            "dietary_tags": dietary_tags,
            "health_insights": health_insights,
        }

    @staticmethod
    def _extract_json(raw_text: str) -> Dict[str, Any]:
        """Extracts and parses JSON even if the model wraps it in thought tags or code fences."""
        cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
        cleaned = re.sub(r"<\|thought\|>.*?<\|/thought\|>", "", cleaned, flags=re.DOTALL).strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as first_error:
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError as exc:
                    raise LlamaCppClient._format_json_error(raw_text, exc) from exc
            raise LlamaCppClient._format_json_error(raw_text, first_error) from first_error

    @staticmethod
    def _format_json_error(raw_text: str, exc: json.JSONDecodeError) -> ValueError:
        position = exc.pos
        excerpt_start = max(0, position - 80)
        excerpt_end = min(len(raw_text), position + 80)
        excerpt = raw_text[excerpt_start:excerpt_end].replace("\n", "\\n")
        return ValueError(
            f"{exc.msg} at line {exc.lineno}, column {exc.colno} "
            f"(character {position}); response excerpt: {excerpt!r}"
        )

    @classmethod
    def _normalize_analysis_dict(
        cls, data: Dict[str, Any], fallback_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Normalizes LLM JSON variations (e.g., string vs list for tags/insights, missing defaults)
        and deterministically computes total_macronutrients across all items.
        """
        if not isinstance(data, dict):
            raise ValueError("Model output JSON root must be an object.")

        # Coerce string fields to lists if the model returned a single string
        for list_key in ("dietary_tags", "health_insights"):
            val = data.get(list_key)
            if isinstance(val, str):
                data[list_key] = [val] if val.strip() else []
            elif not isinstance(val, list):
                data[list_key] = []
            else:
                data[list_key] = [str(x) for x in val if x is not None]

        items = data.get("items")
        if not isinstance(items, list):
            items = []
            data["items"] = items

        totals = {k: 0.0 for k in MACRO_KEYS}

        for item in items:
            if not isinstance(item, dict):
                continue
            item.setdefault("food_name", "Unknown Food")
            item.setdefault("serving_size_description", "1 serving")
            item.setdefault("estimated_weight_grams", 100.0)
            item.setdefault("confidence", 0.9)

            macros = item.get("macronutrients")
            if not isinstance(macros, dict):
                macros = {}
                item["macronutrients"] = macros
            for k in MACRO_KEYS:
                try:
                    val = float(macros.get(k) or 0.0)
                except (TypeError, ValueError):
                    val = 0.0
                macros[k] = round(val, 2)
                totals[k] = round(totals[k] + val, 2)

            micros = item.get("micronutrients")
            if not isinstance(micros, dict):
                micros = {"vitamins": [], "minerals": []}
                item["micronutrients"] = micros
            for m_key in ("vitamins", "minerals"):
                m_list = micros.get(m_key)
                if not isinstance(m_list, list):
                    micros[m_key] = []
                else:
                    valid_micros = []
                    for entry in m_list:
                        if isinstance(entry, dict) and entry.get("name"):
                            try:
                                amt = float(entry.get("amount") or 0.0)
                            except (TypeError, ValueError):
                                amt = 0.0
                            dv = entry.get("daily_value_percent")
                            try:
                                dv_val = float(dv) if dv is not None else None
                            except (TypeError, ValueError):
                                dv_val = None
                            valid_micros.append(
                                {
                                    "name": str(entry["name"]),
                                    "amount": amt,
                                    "unit": str(entry.get("unit") or "mg"),
                                    "daily_value_percent": dv_val,
                                }
                            )
                    micros[m_key] = valid_micros

        # Use computed totals if total_macronutrients is missing or incomplete
        if not isinstance(data.get("total_macronutrients"), dict) or items:
            data["total_macronutrients"] = totals

        data.setdefault("meal_title", fallback_text or "Analyzed Meal")
        data.setdefault(
            "recognized_input_summary",
            fallback_text or ", ".join(i.get("food_name", "") for i in items) or "Analyzed input",
        )
        return data
