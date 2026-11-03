import uuid
from typing import Optional
from langgraph.graph import END, START, StateGraph
from nutrition.graph.nodes import (
    decompose_ingredients_node,
    identify_dish_node,
    resolve_database_nutrients_node,
    validate_input_node,
)
from nutrition.graph.state import NutriGuideState


def _route_after_validation(state: NutriGuideState) -> str:
    if state.get("status") == "failed":
        return END
    return "identify_dish"


def _route_after_identification(state: NutriGuideState) -> str:
    if state.get("status") == "failed":
        return END
    return "resolve_nutrients"


def _route_after_resolution(state: NutriGuideState) -> str:
    """
    Evaluates whether unmapped/composite ingredients require AI decomposition.
    Loops back to decompose_ingredients until all ingredients resolve or maximum
    decomposition iterations are reached.
    """
    if state.get("status") == "failed":
        return END
    unresolved = state.get("unresolved_ingredients") or []
    current_round = int(state.get("decomposition_round") or 0)
    max_rounds = int(state.get("max_decomposition_rounds") or 2)
    if unresolved and current_round < max_rounds:
        return "decompose_ingredients"
    return END


def build_nutrition_graph():
    """
    Constructs and compiles the multi-stage LangGraph workflow for NutriGuide-AI:
    START -> validate_input -> identify_dish -> resolve_nutrients <-> decompose_ingredients -> END

    Separates AI multimodal perception (identifying dish and constituent ingredients)
    from deterministic nutrient calculation (querying the IFCT 2017 relational database).
    Features an Agentic AI Decomposition Loop that breaks down composite ingredients
    (e.g., rice batter, chilli powder) into raw database-backed constituents without repeated fetches.
    """
    builder = StateGraph(NutriGuideState)

    builder.add_node("validate_input", validate_input_node)
    builder.add_node("identify_dish", identify_dish_node)
    builder.add_node("resolve_nutrients", resolve_database_nutrients_node)
    builder.add_node("decompose_ingredients", decompose_ingredients_node)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        _route_after_validation,
        {
            "identify_dish": "identify_dish",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "identify_dish",
        _route_after_identification,
        {
            "resolve_nutrients": "resolve_nutrients",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "resolve_nutrients",
        _route_after_resolution,
        {
            "decompose_ingredients": "decompose_ingredients",
            END: END,
        },
    )
    builder.add_edge("decompose_ingredients", "resolve_nutrients")

    return builder.compile()


nutrition_graph = build_nutrition_graph()


def run_nutrition_workflow(
    input_text: Optional[str] = None,
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
    audio_base64: Optional[str] = None,
    audio_format: Optional[str] = None,
    user_id: Optional[str] = None,
) -> NutriGuideState:
    """Executes the compiled multi-stage LangGraph workflow and returns the final NutriGuideState."""
    initial_state: NutriGuideState = {
        "request_id": str(uuid.uuid4()),
        "user_id": user_id,
        "input_text": input_text,
        "image_base64": image_base64,
        "image_mime_type": image_mime_type,
        "audio_base64": audio_base64,
        "audio_format": audio_format,
        "dish_name": None,
        "recognized_input_summary": None,
        "ai_generated_response": None,
        "identified_ingredients": [],
        "detected_food_items": [],
        "nutrient_analysis": None,
        "missing_ingredients": [],
        "pending_ingredients": [],
        "resolved_items": [],
        "unresolved_ingredients": [],
        "attempted_ingredients": [],
        "decomposition_round": 0,
        "max_decomposition_rounds": 2,
        "decomposition_history": [],
        "dietary_tags": [],
        "dietary_warnings": [],
        "health_insights": [],
        "meal_recommendations": [],
        "user_profile": None,
        "status": "pending",
        "errors": [],
        "metadata": {},
    }
    return nutrition_graph.invoke(initial_state)
