from typing import Annotated, Any, Dict, List, Optional, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class NutriGuideState(TypedDict, total=False):
    """
    Central LangGraph State for NutriGuide-AI.

    Coordinates the multi-stage multimodal nutrition analysis pipeline:
    1. Validation: Inspects text, image, and voice inputs.
    2. AI Culinary Perception: Local Gemma 4 identifies dish and constituent ingredients.
    3. Database Nutrient Resolution: IFCT reference tables calculate ground-truth nutrition.
    4. Diagnostics & Extensions: Missing ingredient alerts, safety warnings, user profile.
    """

    # --- 1. Request & Session Context ---
    request_id: str
    user_id: Optional[str]
    input_modalities: List[str]  # e.g., ["text"], ["image"], ["voice"], or combinations

    # --- 2. Multimodal Raw Inputs ---
    input_text: Optional[str]
    image_base64: Optional[str]
    image_mime_type: Optional[str]  # e.g., "image/jpeg", "image/png", "image/webp"
    audio_base64: Optional[str]
    audio_format: Optional[str]  # e.g., "wav", "mp3"

    # --- 3. Stage 1: AI Dish & Ingredient Perception Output ---
    dish_name: Optional[str]
    recognized_input_summary: Optional[str]
    ai_generated_response: Optional[Dict[str, Any]]
    identified_ingredients: List[Dict[str, Any]]
    dietary_tags: List[str]
    health_insights: List[str]

    # --- 4. Stage 2: Database Nutrient Resolution Output ---
    detected_food_items: List[Dict[str, Any]]
    nutrient_analysis: Optional[Dict[str, Any]]  # Matches NutrientAnalysisDataSchema
    missing_ingredients: List[str]

    # --- 5. Iterative Decomposition Loop Fields ---
    pending_ingredients: List[Dict[str, Any]]
    resolved_items: List[Dict[str, Any]]
    unresolved_ingredients: List[Dict[str, Any]]
    attempted_ingredients: List[str]
    decomposition_round: int
    max_decomposition_rounds: int
    decomposition_history: List[Dict[str, Any]]

    # --- 6. Extensible Safety, Warnings & Guidance ---
    # User profile & health goals (e.g., calorie target, allergies, medical conditions)
    user_profile: Optional[Dict[str, Any]]
    # Allergen, medical, or missing-ingredient warnings generated during execution
    dietary_warnings: List[str]
    # Personalized healthier swaps or portion adjustments
    meal_recommendations: List[str]
    # Daily intake aggregation & remaining macro budget
    daily_log_summary: Optional[Dict[str, Any]]
    # Conversation history for multi-turn nutrition coaching
    messages: Annotated[List[AnyMessage], add_messages]

    # --- 6. Execution & Diagnostics ---
    status: str  # "pending" | "processing" | "completed" | "failed"
    errors: List[str]
    metadata: Dict[str, Any]
