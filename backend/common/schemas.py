import json
from typing import Any, List, Optional
from ninja import Schema
from pydantic import Field, model_validator


MEAL_PLAN_PREFERENCES = (
    "Blood-sugar conscious",
    "Heart-healthy",
    "Weight management",
    "Healthy weight gain",
    "Plant-forward",
    "High-protein",
    "Gluten-free",
    "Dairy-free",
)

MEAL_PLAN_DURATIONS = (
    "daily",
    "weekly",
    "monthly",
)

MEAL_PLAN_DIET_TYPES = (
    "veg",
    "non-veg",
    "vegan",
    "egg",
)


class MicronutrientItemSchema(Schema):
    name: str = Field(..., description="Name of the vitamin or mineral (e.g., Vitamin C, Iron, Potassium)")
    amount: float = Field(..., description="Numeric amount of the micronutrient")
    unit: str = Field(..., description="Measurement unit (e.g., mg, mcg, IU)")
    daily_value_percent: Optional[float] = Field(
        None, description="Estimated percentage of recommended Daily Value (%DV)"
    )


class MacronutrientsSchema(Schema):
    calories_kcal: float = Field(..., description="Total energy in kilocalories (kcal)")
    protein_g: float = Field(..., description="Protein in grams")
    carbohydrates_g: float = Field(..., description="Total carbohydrates in grams")
    dietary_fiber_g: float = Field(0.0, description="Dietary fiber in grams")
    total_sugars_g: float = Field(0.0, description="Total sugars in grams")
    added_sugars_g: float = Field(0.0, description="Added sugars in grams")
    total_fat_g: float = Field(..., description="Total fat in grams")
    saturated_fat_g: float = Field(0.0, description="Saturated fat in grams")
    unsaturated_fat_g: float = Field(0.0, description="Monounsaturated + polyunsaturated fat in grams")
    trans_fat_g: float = Field(0.0, description="Trans fat in grams")
    cholesterol_mg: float = Field(0.0, description="Cholesterol in milligrams")
    sodium_mg: float = Field(0.0, description="Sodium in milligrams")
    water_g: Optional[float] = Field(None, description="Estimated water content in grams")


class MicronutrientsSchema(Schema):
    vitamins: List[MicronutrientItemSchema] = Field(
        default_factory=list,
        description="Key vitamins present in the food item",
    )
    minerals: List[MicronutrientItemSchema] = Field(
        default_factory=list,
        description="Key minerals present in the food item",
    )


class FoodItemNutrientSchema(Schema):
    food_name: str = Field(..., description="Identified name of the food item")
    serving_size_description: str = Field(
        ..., description="Human-readable serving size (e.g., '1 medium bowl', '2 large eggs')"
    )
    estimated_weight_grams: float = Field(
        ..., description="Estimated edible weight in grams for the serving"
    )
    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Model confidence score (0.0 to 1.0) in identifying the food and portion",
    )
    glycemic_index_category: Optional[str] = Field(
        default=None,
        description="Estimated glycemic index category: Low, Medium, High, or N/A",
    )
    macronutrients: MacronutrientsSchema
    micronutrients: MicronutrientsSchema
    database_food_code: Optional[str] = Field(
        default=None,
        description="IFCT reference food code resolved from database, or None if unmapped",
    )
    database_food_name: Optional[str] = Field(
        default=None,
        description="IFCT reference food item name from database",
    )
    found_in_database: bool = Field(
        default=True,
        description="True if nutrient profile was found and calculated from reference database",
    )


class NutrientAnalysisDataSchema(Schema):
    meal_title: str = Field(..., description="Short descriptive title of the analyzed meal or food")
    recognized_input_summary: str = Field(
        ...,
        description="What the model recognized or transcribed from the user's text, image, or voice input",
    )
    items: List[FoodItemNutrientSchema] = Field(
        ..., description="Per-item breakdown of all detected foods/ingredients and their database nutrients"
    )
    total_macronutrients: MacronutrientsSchema = Field(
        ..., description="Aggregated macronutrients calculated strictly from database across all items"
    )
    dietary_tags: List[str] = Field(
        default_factory=list,
        description="Relevant dietary tags (e.g., High-Protein, Vegetarian, Gluten-Free, Low-Carb)",
    )
    health_insights: List[str] = Field(
        default_factory=list,
        description="Brief nutritional highlights, balanced meal tips, and notes on missing ingredients",
    )
    missing_ingredients: List[str] = Field(
        default_factory=list,
        description="Identified ingredients that could not be found in reference database and require manual entry",
    )


class LLMIngredientItemSchema(Schema):
    ingredient_name: str = "str"
    serving_size_description: str = "str"
    estimated_weight_grams: float = 100.0
    confidence: float = 0.95


class LLMDishIngredientsResponseSchema(Schema):
    """
    Pydantic schema representing the expected LLM response structure for dish and
    ingredient identification.
    Strictly excludes nutrient figures; all nutritional profiles are computed from
    the reference database.
    """
    dish_name: str = "str"
    recognized_input_summary: str = "str"
    ingredients: List[LLMIngredientItemSchema] = Field(
        default_factory=lambda: [LLMIngredientItemSchema()]
    )
    dietary_tags: List[str] = Field(default_factory=lambda: ["str"])
    health_insights: List[str] = Field(default_factory=lambda: ["str"])

    @classmethod
    def to_compact_json(cls) -> str:
        """Returns the single-line minified JSON string of the schema structure."""
        return cls().model_dump_json()

    @classmethod
    def to_json_object(cls) -> dict:
        """Returns the schema structure as a Python dictionary (JSON object)."""
        return cls().model_dump()


class DecomposedIngredientSubItemSchema(Schema):
    ingredient_name: str = "str"
    serving_size_description: str = "str"
    estimated_weight_grams: float = 50.0
    confidence: float = 0.95


class IngredientDecompositionItemSchema(Schema):
    original_ingredient: str = "str"
    can_decompose: bool = True
    sub_ingredients: List[DecomposedIngredientSubItemSchema] = Field(default_factory=list)
    reasoning: Optional[str] = None


class LLMDecomposeIngredientsResponseSchema(Schema):
    """
    Pydantic schema for requesting the LLM to break down unmapped/composite ingredients
    (e.g., rice batter, chilli powder, spice mix) into constituent raw ingredients.
    """
    decompositions: List[IngredientDecompositionItemSchema] = Field(
        default_factory=lambda: [IngredientDecompositionItemSchema()]
    )

    @classmethod
    def to_compact_json(cls) -> str:
        return cls().model_dump_json()

    @classmethod
    def to_json_object(cls) -> dict:
        return cls().model_dump()


# Legacy alias so existing imports continue to resolve cleanly
LLMNutrientResponseSchema = LLMDishIngredientsResponseSchema


class TextAnalyzeRequestSchema(Schema):
    text: str = Field(
        ...,
        min_length=1,
        description="Description of the food/meal (e.g., '2 boiled eggs, 100g oats, and 1 banana')",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Optional user identifier for future personalization nodes in LangGraph",
    )
    owner_id: Optional[str] = None
    conversation_id: Optional[str] = None


class NutrientAnalysisResponseSchema(Schema):
    request_id: str
    status: str
    input_modalities: List[str]
    analysis: NutrientAnalysisDataSchema
    dietary_warnings: List[str] = Field(
        default_factory=list,
        description="Actionable dietary alerts, allergen notices, or missing database ingredient warnings",
    )
    transcription: Optional[str] = None
    message_id: Optional[str] = None
    logged_to_tracker: bool = False
    tracker_log_id: Optional[str] = None


class ErrorResponseSchema(Schema):
    detail: str
    errors: Optional[List[str]] = None


class MealPlanRequestSchema(Schema):
    preferences: List[str] = Field(default_factory=list, max_length=8)
    custom_request: str = Field(default="", max_length=2000)
    owner_id: Optional[str] = Field(default=None, max_length=64)
    duration: str = Field(default="daily", max_length=32)
    diet_type: str = Field(default="", max_length=32)
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None
    image_name: Optional[str] = None
    audio_base64: Optional[str] = None
    audio_format: Optional[str] = None
    audio_name: Optional[str] = None
    user_id: Optional[Any] = None


class SignupRequestSchema(Schema):
    username: str = Field(..., min_length=1, max_length=150)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=256)
    name: Optional[str] = Field(default="", max_length=150)
    full_name: Optional[str] = Field(default="", max_length=150)
    owner_id: Optional[str] = None


class LoginRequestSchema(Schema):
    identifier: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    username_or_email: Optional[str] = None
    password: str = Field(..., min_length=1, max_length=256)


class UserProfileUpdateSchema(Schema):
    name: Optional[str] = None
    age: Optional[Any] = None
    height: Optional[Any] = None
    height_cm: Optional[Any] = None
    weight: Optional[Any] = None
    weight_kg: Optional[Any] = None
    gender: Optional[str] = None
    allergies: Optional[str] = None
    bio: Optional[str] = None
    email: Optional[str] = None
    profile_picture: Optional[str] = None
    avatar_url: Optional[str] = None
    owner_id: Optional[str] = None
    token: Optional[str] = None


class TrackerLogRequestSchema(Schema):
    owner_id: Optional[str] = None
    token: Optional[str] = None
    message_id: Optional[str] = None
    conversation_id: Optional[str] = None
    meal_title: Optional[str] = None
    meal_type: str = Field(default="Meal", max_length=32)
    recognized_summary: str = Field(default="", max_length=2000)
    analysis: Optional[dict] = None
    logged_via: Optional[str] = Field(default=None, max_length=32)
    consumed_at: Optional[str] = None
    time_option: Optional[str] = Field(default="now", max_length=16)
    calories_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    carbohydrates_g: Optional[float] = None
    total_fat_g: Optional[float] = None
    dietary_fiber_g: Optional[float] = None
    total_sugars_g: Optional[float] = None



class GroupCreateRequestSchema(Schema):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    is_public: Optional[bool] = None
    visibility: Optional[str] = None
    member_identifiers: Optional[List[str]] = None
    members: Optional[List[str]] = None
    owner_id: Optional[str] = None
    token: Optional[str] = None


class GroupAddMemberRequestSchema(Schema):
    identifier: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    owner_id: Optional[str] = None
    token: Optional[str] = None


class GroupRequestRespondSchema(Schema):
    action: str = Field(..., description="'accept' or 'reject' (or 'cancel')")
    owner_id: Optional[str] = None
    token: Optional[str] = None


class GroupMealLogRequestSchema(Schema):
    meal_title: str = Field(..., min_length=1, max_length=200)
    meal_type: str = Field(default="Meal", max_length=32)
    calories_kcal: Optional[float] = None
    protein_g: Optional[float] = None
    carbohydrates_g: Optional[float] = None
    total_fat_g: Optional[float] = None
    fat_g: Optional[float] = None
    dietary_fiber_g: Optional[float] = None
    fiber_g: Optional[float] = None
    serving_grams: Optional[float] = None
    serving_notes: str = Field(default="", max_length=1000)
    owner_id: Optional[str] = None
    token: Optional[str] = None


class MealPlanOptionSchema(Schema):
    name: str
    details: str
    why_it_fits: str


class MealPlanSectionSchema(Schema):
    options: List[MealPlanOptionSchema] = Field(..., min_length=1, max_length=25)

    @model_validator(mode="before")
    @classmethod
    def normalize_options(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"options": data}
        return data


class MealPlanResponseSchema(Schema):
    summary: str
    breakfast: MealPlanSectionSchema
    lunch: MealPlanSectionSchema
    snacks: MealPlanSectionSchema
    dinner: MealPlanSectionSchema

    @classmethod
    def to_compact_json(cls) -> str:
        return json.dumps(
            cls.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @model_validator(mode="before")
    @classmethod
    def normalize_root(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "summary" not in data or not data.get("summary"):
                for key in ("plan_summary", "overview", "description", "title"):
                    if data.get(key):
                        data["summary"] = data[key]
                        break
                else:
                    data["summary"] = "Personalized meal plan tailored to your preferences."
        return data


class HealthCheckResponseSchema(Schema):
    api_status: str
    inference_backend: str = Field(
        default="local",
        description="Active inference backend: 'local' (llama-cpp) or 'gemini' (Google Gemini API)",
    )
    llama_server_url: str
    llama_server_reachable: bool
    llama_server_status: str
    model_name: str = Field(
        default="",
        description="Name of the active model being used for inference",
    )
    model_file_exists: bool
    mmproj_file_exists: bool
    startup_command_hint: str
    database_food_count: Optional[int] = Field(
        None, description="Number of reference food items currently loaded in the database"
    )


class IngredientCustomizationItemSchema(Schema):
    food_name: str = Field(..., description="Name of ingredient/food item")
    estimated_weight_grams: float = Field(..., description="Weight in grams")
    serving_size_description: Optional[str] = Field("1 serving", description="Portion description")
    confidence: Optional[float] = Field(1.0, description="Confidence")


class CustomizeRecipeRequestSchema(Schema):
    owner_id: str = Field(..., description="User owner identifier")
    ingredients: List[IngredientCustomizationItemSchema] = Field(..., description="Customized ingredients list")
    dish_name: Optional[str] = Field(None, description="Standardized or customized dish title")
    description: Optional[str] = Field(None, description="User customized dish description / summary")
    notes: Optional[str] = Field("", description="Household culinary notes")

