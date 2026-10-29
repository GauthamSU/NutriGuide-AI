import logging
import re
from typing import Any, Dict, List
from nutrition.graph.state import NutriGuideState
from nutrition.services.db_nutrition_service import (
    NON_EDIBLE_ITEMS,
    _FOOD_LOOKUP_CACHE,
    find_food_in_db,
    resolve_dish_nutrition_from_db,
    resolve_single_ingredient_from_db,
)
from nutrition.services.llama_client import LlamaCppClient

logger = logging.getLogger(__name__)


def validate_input_node(state: NutriGuideState) -> Dict[str, Any]:
    """
    Node 1: Validates incoming multimodal inputs (text, image, voice) and
    initializes state tracking fields.
    """
    modalities: List[str] = []
    if state.get("input_text") and state["input_text"].strip():
        modalities.append("text")
    if state.get("image_base64"):
        modalities.append("image")
    if state.get("audio_base64"):
        modalities.append("voice")

    errors = list(state.get("errors") or [])
    if not modalities:
        errors.append("At least one input modality (text, image, or voice) must be provided.")
        return {
            "input_modalities": [],
            "status": "failed",
            "errors": errors,
        }

    return {
        "input_modalities": modalities,
        "status": "processing",
        "errors": errors,
        "dietary_warnings": list(state.get("dietary_warnings") or []),
        "meal_recommendations": list(state.get("meal_recommendations") or []),
        "metadata": dict(state.get("metadata") or {}),
    }


def identify_dish_node(state: NutriGuideState) -> Dict[str, Any]:
    """
    Node 2 (AI Culinary Perception):
    Invokes local Gemma 4 via llama-server to identify the dish and its constituent
    ingredients with portion weights. Strictly does NOT estimate or hallucinate nutrients.
    """
    client = LlamaCppClient()
    errors = list(state.get("errors") or [])

    try:
        raw_result = client.identify_dish_and_ingredients(
            input_text=state.get("input_text"),
            image_base64=state.get("image_base64"),
            image_mime_type=state.get("image_mime_type") or "image/jpeg",
            audio_base64=state.get("audio_base64"),
            audio_format=state.get("audio_format") or "wav",
        )

        dish_name = (
            raw_result.get("dish_name")
            or raw_result.get("meal_title")
            or state.get("input_text")
            or "Identified Dish"
        )
        summary = (
            raw_result.get("recognized_input_summary")
            or state.get("input_text")
            or f"Identified dish: {dish_name}"
        )

        raw_ingredients = raw_result.get("ingredients") or raw_result.get("items") or []
        if not isinstance(raw_ingredients, list):
            raw_ingredients = []

        normalized_ingredients: List[Dict[str, Any]] = []
        for item in raw_ingredients:
            if not isinstance(item, dict):
                continue
            normalized_ingredients.append({
                "ingredient_name": (
                    item.get("ingredient_name") or item.get("food_name") or "Unknown Ingredient"
                ).strip(),
                "serving_size_description": str(item.get("serving_size_description") or "1 serving"),
                "estimated_weight_grams": float(item.get("estimated_weight_grams") or 100.0),
                "confidence": float(item.get("confidence") or 0.95),
                "glycemic_index_category": item.get("glycemic_index_category"),
                # Preserve any pre-computed nutrient fields if provided in mock payloads
                "macronutrients": item.get("macronutrients"),
                "micronutrients": item.get("micronutrients"),
                "found_in_database": item.get("found_in_database"),
                "database_food_code": item.get("database_food_code"),
                "database_food_name": item.get("database_food_name"),
            })

        dietary_tags = list(raw_result.get("dietary_tags") or [])
        health_insights = list(raw_result.get("health_insights") or [])

        # If input was already a pre-computed full analysis dict (e.g. legacy tests)
        already_analyzed = None
        if "total_macronutrients" in raw_result and any("macronutrients" in i for i in normalized_ingredients):
            already_analyzed = raw_result

        return {
            "dish_name": dish_name,
            "recognized_input_summary": summary,
            "identified_ingredients": normalized_ingredients,
            "pending_ingredients": normalized_ingredients,
            "resolved_items": [],
            "unresolved_ingredients": [],
            "attempted_ingredients": [],
            "decomposition_round": 0,
            "max_decomposition_rounds": 2,
            "decomposition_history": [],
            "dietary_tags": dietary_tags,
            "health_insights": health_insights,
            "nutrient_analysis": already_analyzed,
            "status": "processing",
        }
    except Exception as exc:
        logger.exception("AI dish and ingredient identification failed")
        errors.append(f"AI dish identification failed: {str(exc)}")
        return {
            "status": "failed",
            "errors": errors,
        }


def resolve_database_nutrients_node(state: NutriGuideState) -> Dict[str, Any]:
    """
    Node 3 (Database Nutrient Resolution with Query Caching):
    Resolves pending ingredients against the authoritative IFCT reference database.
    Checks in-memory cache to guarantee that database queries are never repeated for identical items.
    If composite/unmapped ingredients are found and decomposition rounds remain, sets them in
    unresolved_ingredients so the router can trigger AI decomposition.
    When all items are resolved or maximum rounds are exhausted, computes the final aggregated
    nutrient analysis.
    """
    errors = list(state.get("errors") or [])

    # If nutrient analysis was already completed in Stage 1 (e.g. mock test payload)
    existing_analysis = state.get("nutrient_analysis")
    if existing_analysis and isinstance(existing_analysis, dict) and "total_macronutrients" in existing_analysis:
        return {
            "detected_food_items": existing_analysis.get("items", []),
            "nutrient_analysis": existing_analysis,
            "missing_ingredients": existing_analysis.get("missing_ingredients", []),
            "status": "completed",
        }

    try:
        pending = state.get("pending_ingredients")
        if pending is None:
            pending = list(state.get("identified_ingredients") or [])

        resolved_items = list(state.get("resolved_items") or [])
        attempted_ingredients = set(state.get("attempted_ingredients") or [])
        decomposition_history = list(state.get("decomposition_history") or [])
        current_round = int(state.get("decomposition_round") or 0)
        max_rounds = int(state.get("max_decomposition_rounds") or 2)
        permanent_unresolved = list(state.get("unresolved_ingredients") or [])

        current_unresolved: List[Dict[str, Any]] = []

        for item in pending:
            if not isinstance(item, dict):
                continue
            ing_name = (
                item.get("ingredient_name") or item.get("food_name") or "Unknown Ingredient"
            ).strip()
            norm_key = ing_name.lower()
            attempted_ingredients.add(norm_key)

            resolved_item, is_found = resolve_single_ingredient_from_db(item)
            if is_found:
                resolved_items.append(resolved_item)
            else:
                current_unresolved.append(item)

        # Trigger decomposition loop if current_unresolved is non-empty AND current_round < max_rounds
        if current_unresolved and current_round < max_rounds:
            return {
                "resolved_items": resolved_items,
                "unresolved_ingredients": current_unresolved,
                "attempted_ingredients": list(attempted_ingredients),
                "pending_ingredients": [],
                "status": "processing",
            }

        # Finalize! Combine resolved items and any remaining unresolved items
        all_final_unresolved = permanent_unresolved + current_unresolved
        unresolved_names = sorted(list(set(
            (i.get("ingredient_name") or i.get("food_name") or "").strip()
            for i in all_final_unresolved
            if (i.get("ingredient_name") or i.get("food_name"))
            and (i.get("ingredient_name") or i.get("food_name")).strip().lower() not in NON_EDIBLE_ITEMS
            and "banana leaf" not in (i.get("ingredient_name") or i.get("food_name")).strip().lower()
        )))

        # Also add dummy entries for final unmapped items so they appear in items list
        final_items = list(resolved_items)
        macro_keys = [
            "calories_kcal", "protein_g", "carbohydrates_g", "dietary_fiber_g",
            "total_sugars_g", "added_sugars_g", "total_fat_g", "saturated_fat_g",
            "unsaturated_fat_g", "trans_fat_g", "cholesterol_mg", "sodium_mg", "water_g"
        ]
        for missing_item in all_final_unresolved:
            m_name = (missing_item.get("ingredient_name") or missing_item.get("food_name") or "Unknown").strip()
            if m_name.lower() in NON_EDIBLE_ITEMS or "banana leaf" in m_name.lower():
                continue
            if any(it["food_name"] == m_name for it in final_items):
                continue
            final_items.append({
                "food_name": m_name,
                "serving_size_description": str(missing_item.get("serving_size_description") or "1 serving"),
                "estimated_weight_grams": float(missing_item.get("estimated_weight_grams") or 100.0),
                "confidence": float(missing_item.get("confidence") or 0.9),
                "glycemic_index_category": None,
                "found_in_database": False,
                "database_food_code": None,
                "database_food_name": None,
                "macronutrients": {k: 0.0 for k in macro_keys},
                "micronutrients": {"vitamins": [], "minerals": []},
            })

        # Calculate totals across all resolved items
        total_macros = {k: 0.0 for k in macro_keys}
        for it in resolved_items:
            macros = it.get("macronutrients") or {}
            for k in macro_keys:
                total_macros[k] = round(total_macros[k] + macros.get(k, 0.0), 2)

        dietary_warnings = list(state.get("dietary_warnings") or [])
        health_insights = list(state.get("health_insights") or [])

        # Add decomposition history alerts
        for decomp in decomposition_history:
            subs = decomp.get("sub_ingredients") or []
            sub_strs = [
                f"{s.get('ingredient_name')} ({s.get('estimated_weight_grams')}g)"
                for s in subs
            ]
            note = (
                f"Decomposed composite ingredient '{decomp.get('original_ingredient')}' "
                f"({decomp.get('original_weight_grams')}g) into: {', '.join(sub_strs)} "
                f"for exact reference database nutrient resolution."
            )
            dietary_warnings.append(note)
            health_insights.append(note)

        # Add missing database nutrient warnings if any permanent unmapped ingredients remain
        if unresolved_names:
            dietary_warnings.append(
                f"Missing database nutrients for: {', '.join(unresolved_names)}. "
                f"Please load these ingredients manually to the database."
            )
            health_insights.append(
                f"The following ingredient(s) could not be found in the reference database: "
                f"{', '.join(unresolved_names)}. Their nutrients are currently excluded from total calculations."
            )

        dish_name = state.get("dish_name") or "Identified Dish"
        summary = state.get("recognized_input_summary") or f"Identified dish: {dish_name}"

        final_analysis = {
            "meal_title": dish_name,
            "recognized_input_summary": summary,
            "items": final_items,
            "total_macronutrients": total_macros,
            "dietary_tags": list(state.get("dietary_tags") or []),
            "health_insights": health_insights,
            "missing_ingredients": unresolved_names,
        }

        return {
            "detected_food_items": final_items,
            "nutrient_analysis": final_analysis,
            "missing_ingredients": unresolved_names,
            "dietary_warnings": dietary_warnings,
            "health_insights": health_insights,
            "resolved_items": resolved_items,
            "unresolved_ingredients": [],
            "pending_ingredients": [],
            "attempted_ingredients": list(attempted_ingredients),
            "status": "completed",
        }
    except Exception as exc:
        logger.exception("Database nutrient resolution failed")
        errors.append(f"Database nutrient resolution failed: {str(exc)}")
        return {
            "status": "failed",
            "errors": errors,
        }


def decompose_ingredients_node(state: NutriGuideState) -> Dict[str, Any]:
    """
    Node 4 (Ingredient Decomposition via AI):
    Takes unmapped ingredients from resolve_database_nutrients_node and queries the AI
    to break down composite foods (e.g., rice batter -> rice + urad dal, chilli powder -> red chillies)
    into constituent raw ingredients.
    Strictly avoids re-fetching already attempted or failed ingredients.
    """
    unresolved = list(state.get("unresolved_ingredients") or [])
    current_round = int(state.get("decomposition_round") or 0)
    max_rounds = int(state.get("max_decomposition_rounds") or 2)
    attempted_ingredients = set(state.get("attempted_ingredients") or [])
    decomposition_history = list(state.get("decomposition_history") or [])

    if not unresolved or current_round >= max_rounds:
        return {
            "decomposition_round": max_rounds,
            "pending_ingredients": [],
            "status": "processing",
        }

    client = LlamaCppClient()
    try:
        decomp_result = client.decompose_ingredients(unresolved)
        decompositions = decomp_result.get("decompositions") or []
    except Exception as exc:
        logger.warning(f"Ingredient decomposition call failed: {exc}")
        return {
            "decomposition_round": max_rounds,
            "pending_ingredients": [],
            "status": "processing",
        }

    decomp_map: Dict[str, Dict[str, Any]] = {}
    for d in decompositions:
        if isinstance(d, dict) and d.get("original_ingredient"):
            orig_k = d["original_ingredient"].strip().lower()
            decomp_map[orig_k] = d
            stripped_k = re.sub(r"\(.*?\)", "", orig_k).strip()
            if stripped_k:
                decomp_map[stripped_k] = d

    new_pending: List[Dict[str, Any]] = []
    permanent_unresolved: List[Dict[str, Any]] = []

    for unmapped_item in unresolved:
        raw_name = (
            unmapped_item.get("ingredient_name") or unmapped_item.get("food_name") or ""
        ).strip()
        key = raw_name.lower()

        # Ignore non-edible tableware like banana leaf
        if key in NON_EDIBLE_ITEMS or "banana leaf" in key:
            continue

        # Look up decomposition in decomp_map (exact, stripped parentheses, or containment)
        d_info = decomp_map.get(key)
        if not d_info:
            clean_k = re.sub(r"\(.*?\)", "", key).strip()
            d_info = decomp_map.get(clean_k)
        if not d_info:
            for dk, dv in decomp_map.items():
                if dk in key or key in dk:
                    d_info = dv
                    break

        if d_info and d_info.get("can_decompose") and d_info.get("sub_ingredients"):
            sub_items = d_info.get("sub_ingredients") or []
            valid_subs: List[Dict[str, Any]] = []

            for sub in sub_items:
                if not isinstance(sub, dict):
                    continue
                sub_name = (sub.get("ingredient_name") or "").strip()
                if not sub_name:
                    continue
                sub_key = sub_name.lower()

                # Guard against tableware or already failed lookups
                if sub_key in NON_EDIBLE_ITEMS or "banana leaf" in sub_key:
                    continue

                if sub_key in attempted_ingredients and _FOOD_LOOKUP_CACHE.get(sub_key) is None:
                    continue

                sub_weight = float(sub.get("estimated_weight_grams") or 50.0)
                sub_dict = {
                    "ingredient_name": sub_name,
                    "serving_size_description": str(sub.get("serving_size_description") or "1 serving"),
                    "estimated_weight_grams": sub_weight,
                    "confidence": float(sub.get("confidence") or 0.9),
                }
                valid_subs.append(sub_dict)
                new_pending.append(sub_dict)

            if valid_subs:
                decomposition_history.append({
                    "original_ingredient": raw_name,
                    "original_weight_grams": float(unmapped_item.get("estimated_weight_grams") or 100.0),
                    "sub_ingredients": valid_subs,
                    "reasoning": d_info.get("reasoning"),
                })
            else:
                permanent_unresolved.append(unmapped_item)
        else:
            # Atomic raw ingredient or un-decomposable item
            permanent_unresolved.append(unmapped_item)

    next_round = current_round + 1
    if not new_pending:
        next_round = max_rounds

    return {
        "pending_ingredients": new_pending,
        "unresolved_ingredients": permanent_unresolved,
        "decomposition_round": next_round,
        "decomposition_history": decomposition_history,
        "status": "processing",
    }


# Backward compatibility alias
def analyze_nutrients_node(state: NutriGuideState) -> Dict[str, Any]:
    """Legacy 1-shot node retained for backward compatibility."""
    stage1 = identify_dish_node(state)
    if stage1.get("status") == "failed":
        return stage1
    combined_state = dict(state)
    combined_state.update(stage1)
    stage2 = resolve_database_nutrients_node(combined_state)
    stage1.update(stage2)
    return stage1
