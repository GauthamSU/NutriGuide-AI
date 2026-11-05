import re
from typing import Any, Dict, List, Optional, Tuple
from django.db.models import Q

from nutrition.models import (
    Food,
    FoodVernacularName,
    ProximateNutrient,
    VitaminNutrient,
    CarotenoidNutrient,
    MineralNutrient,
    SugarNutrient,
    FattyAcidNutrient,
)

# Reference Daily Values (FDA / ICMR standards for adult daily reference intake)
DAILY_VALUES: Dict[str, Tuple[float, str]] = {
    # Vitamins
    "Vitamin C": (90.0, "mg"),
    "Thiamine (B1)": (1.2, "mg"),
    "Riboflavin (B2)": (1.3, "mg"),
    "Niacin (B3)": (16.0, "mg"),
    "Pantothenic Acid (B5)": (5.0, "mg"),
    "Vitamin B6": (1.7, "mg"),
    "Biotin (B7)": (30.0, "mcg"),
    "Folate (B9)": (400.0, "mcg"),
    "Vitamin D": (20.0, "mcg"),
    "Vitamin E": (15.0, "mg"),
    "Vitamin K1": (120.0, "mcg"),
    "Beta-Carotene": (900.0, "mcg"),
    # Minerals
    "Calcium": (1000.0, "mg"),
    "Iron": (18.0, "mg"),
    "Magnesium": (420.0, "mg"),
    "Phosphorus": (1250.0, "mg"),
    "Potassium": (4700.0, "mg"),
    "Sodium": (2300.0, "mg"),
    "Zinc": (11.0, "mg"),
    "Copper": (0.9, "mg"),
    "Manganese": (2.3, "mg"),
    "Selenium": (55.0, "mcg"),
}

# In-memory lookup cache to guarantee we never repeat queries for the same ingredient
_FOOD_LOOKUP_CACHE: Dict[str, Optional[Food]] = {}


def clear_food_lookup_cache() -> None:
    """Clears the in-memory database lookup cache (useful for testing or cache resets)."""
    _FOOD_LOOKUP_CACHE.clear()


# Common culinary aliases mapped directly to IFCT food codes for instant, high-precision matching
COMMON_CULINARY_ALIASES: Dict[str, str] = {
    # Cereals & Grains
    "rice": "A014",
    "white rice": "A015",
    "brown rice": "A013",
    "raw rice": "A015",
    "parboiled rice": "A014",
    "basmati rice": "A014",
    "cooked rice": "A014",
    "steamed rice": "A014",
    "boiled rice": "A014",
    "rice flour": "A014",
    "rice powder": "A014",
    "idli rice": "A014",
    "idli rava": "A014",
    "poha": "A011",
    "rice flakes": "A011",
    "flattened rice": "A011",
    "puffed rice": "A012",
    "murmura": "A012",
    "wheat": "A020",
    "wheat flour": "A019",
    "atta": "A019",
    "whole wheat flour": "A019",
    "maida": "A018",
    "all purpose flour": "A018",
    "refined wheat flour": "A018",
    "sooji": "A022",
    "suji": "A022",
    "rava": "A022",
    "semolina": "A022",
    "dalia": "A021",
    "broken wheat": "A021",
    "ragi": "A010",
    "finger millet": "A010",
    "bajra": "A003",
    "pearl millet": "A003",
    "jowar": "A005",
    "sorghum": "A005",
    "oats": "A009",
    "quinoa": "A009",
    "barley": "A004",
    "corn": "A006",
    "maize": "A006",

    # Pulses & Legumes
    "toor dal": "B021",
    "tuvar dal": "B021",
    "tur dal": "B021",
    "arhar dal": "B021",
    "pigeon pea": "B021",
    "red gram dal": "B021",
    "red gram": "B021",
    "chana dal": "B001",
    "bengal gram dal": "B001",
    "bengal gram": "B001",
    "besan": "B001",
    "gram flour": "B001",
    "kala chana": "B002",
    "black chana": "B002",
    "chickpeas": "B002",
    "kabuli chana": "B002",
    "urad dal": "B003",
    "black gram dal": "B003",
    "black gram": "B003",
    "ulutham paruppu": "B003",
    "moong dal": "B010",
    "mung dal": "B010",
    "green gram dal": "B010",
    "green gram": "B011",
    "hari moong": "B011",
    "masoor dal": "B013",
    "red lentil": "B013",
    "lentil": "B013",
    "rajma": "B020",
    "red kidney beans": "B020",
    "kidney beans": "B020",
    "cowpea": "B005",
    "lobia": "B005",
    "soya bean": "B025",
    "soyabean": "B025",
    "soybean": "B025",
    "green peas": "B017",
    "dry peas": "B017",

    # Vegetables
    "onion": "G017",
    "onions": "G017",
    "big onion": "G017",
    "pyaz": "G017",
    "vengayam": "G017",
    "shallot": "G018",
    "small onion": "G018",
    "sambhar onion": "G018",
    "tomato": "D075",
    "tomatoes": "D075",
    "tamatar": "D075",
    "thakkali": "D075",
    "green tomato": "D074",
    "potato": "F006",
    "potatoes": "F006",
    "aloo": "F006",
    "urulaikizhangu": "F006",
    "garlic": "G011",
    "lahsun": "G011",
    "poondu": "G011",
    "ginger": "G014",
    "adrak": "G014",
    "inji": "G014",
    "green chilli": "G008",
    "green chili": "G008",
    "green chillies": "G008",
    "hari mirch": "G008",
    "pachai milagai": "G008",
    "capsicum": "D033",
    "bell pepper": "D033",
    "shimla mirch": "D033",
    "green capsicum": "D033",
    "red capsicum": "D034",
    "yellow capsicum": "D035",
    "carrot": "F002",
    "gajar": "F002",
    "cauliflower": "D036",
    "gobi": "D036",
    "cabbage": "C015",
    "patta gobi": "C015",
    "spinach": "C033",
    "palak": "C033",
    "coriander leaves": "G009",
    "fresh coriander": "G009",
    "cilantro": "G009",
    "dhaniya patta": "G009",
    "kothamalli": "G009",
    "curry leaves": "G010",
    "kadi patta": "G010",
    "kariveppilai": "G010",
    "fenugreek leaves": "C020",
    "methi leaves": "C020",
    "mint leaves": "G016",
    "pudina": "G016",
    "cucumber": "D043",
    "kheera": "D043",
    "brinjal": "D010",
    "eggplant": "D010",
    "baingan": "D010",
    "kathirikai": "D010",
    "ladies finger": "D056",
    "lady finger": "D056",
    "okra": "D056",
    "bhindi": "D056",
    "vendakkai": "D056",
    "bottle gourd": "D007",
    "lauki": "D007",
    "bitter gourd": "D004",
    "karela": "D004",
    "beetroot": "F001",
    "beet root": "F001",
    "radish": "F009",
    "mooli": "F009",
    "mullangi": "F009",
    "drumstick": "D046",
    "murungakkai": "D046",
    "mushroom": "J001",
    "button mushroom": "J001",

    # Spices & Condiments
    "cumin": "G025",
    "cumin seeds": "G025",
    "jeera": "G025",
    "seeragam": "G025",
    "mustard seeds": "H013",
    "mustard": "H013",
    "rai": "H013",
    "kadugu": "H013",
    "turmeric": "G033",
    "turmeric powder": "G033",
    "haldi": "G033",
    "manjal": "G033",
    "black pepper": "G031",
    "black pepper powder": "G031",
    "kali mirch": "G031",
    "milagu": "G031",
    "red chilli powder": "G022",
    "chilli powder": "G022",
    "chili powder": "G022",
    "lal mirch powder": "G022",
    "red chillies": "G022",
    "red chilli": "G022",
    "dry red chilli": "G022",
    "dry red chillies": "G022",
    "fenugreek seeds": "G026",
    "methi seeds": "G026",
    "vendhayam": "G026",
    "coriander seeds": "G024",
    "dhaniya": "G024",
    "cardamom": "G020",
    "elaichi": "G020",
    "cloves": "G023",
    "laung": "G023",
    "tamarind": "E064",
    "tamarind pulp": "E064",
    "imli": "E064",
    "puli": "E064",
    "asafoetida": "G019",
    "hing": "G019",
    "perungayam": "G019",

    # Dairy & Poultry & Meats
    "milk": "L002",
    "cow milk": "L002",
    "buffalo milk": "L001",
    "paneer": "L003",
    "cottage cheese": "L003",
    "khoa": "L004",
    "curd": "L002",
    "yogurt": "L002",
    "dahi": "L002",
    "egg": "M001",
    "eggs": "M001",
    "whole egg": "M001",
    "raw egg": "M001",
    "egg white": "M002",
    "egg yolk": "M003",
    "boiled egg": "M004",
    "chicken": "N003",
    "chicken breast": "N003",
    "chicken leg": "N001",
    "chicken thigh": "N002",
    "chicken wing": "N004",
    "mutton": "O001",
    "goat meat": "O001",

    # Oils & Fats
    "oil": "T012",
    "cooking oil": "T012",
    "vegetable oil": "T012",
    "sunflower oil": "T012",
    "ghee": "T013",
    "clarified butter": "T013",
    "desi ghee": "T013",
    "mustard oil": "T006",
    "coconut oil": "T001",
    "groundnut oil": "T005",
    "peanut oil": "T005",
    "sesame oil": "T004",
    "gingelly oil": "T004",
    "til oil": "T004",
    "palm oil": "T007",
    "rice bran oil": "T008",
    "vanaspati": "T014",

    # Nuts & Oilseeds
    "peanut": "H012",
    "peanuts": "H012",
    "groundnut": "H012",
    "groundnuts": "H012",
    "ground nut": "H012",
    "moongphali": "H012",
    "cashew": "H005",
    "cashews": "H005",
    "cashew nut": "H005",
    "kaju": "H005",
    "almond": "H001",
    "almonds": "H001",
    "badam": "H001",
    "mustard seeds": "H013",
    "mustard seed": "H013",
    "rai": "H013",
    "sarson": "H013",

    # Sweeteners & Coconut
    "coconut": "H007",
    "fresh coconut": "H007",
    "grated coconut": "H007",
    "dry coconut": "H006",
    "copra": "H006",
    "coconut water": "K002",
    "jaggery": "I001",
    "cane jaggery": "I001",
    "gur": "I001",
    "vellam": "I001",
    "sugar cane juice": "I002",

    # Beans and legumes fallbacks
    "lentils": "B013",
    "lentil": "B013",
    "dal": "B021",
    "french beans": "D049",
    "green beans": "D049",
    "beans": "D049",
    "spices": "G033",
}

# Non-edible tableware, platters, and garnishes that must never be treated as food nutrients
NON_EDIBLE_ITEMS = {
    "banana leaf", "banana leaves", "banana leaf plate", "banana leaf platter",
    "leaf", "plate", "bowl", "platter", "serving leaf", "cutlery", "spoon", "fork"
}

# Modifiers / noise words stripped when looking up ingredients
COMMON_NOISE_WORDS = {
    "fresh", "raw", "cooked", "boiled", "fried", "steamed", "chopped", "sliced",
    "diced", "grated", "crushed", "powder", "powdered", "roasted", "dry", "dried",
    "organic", "teaspoon", "tablespoon", "tsp", "tbsp", "cup", "cups", "pinch",
    "pinch of", "piece", "pieces", "gram", "grams", "handful", "small", "medium",
    "large", "local", "hybrid", "ripe", "unripe", "tender", "skinless", "boneless",
    "pure", "clean", "refined", "peeled", "seeded"
}


def clean_ingredient_query(text: str) -> str:
    """Normalizes ingredient string by stripping punctuation and known cooking noise words."""
    cleaned = text.lower().strip()
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    tokens = [w for w in cleaned.split() if w and w not in COMMON_NOISE_WORDS]
    return " ".join(tokens)


def find_food_in_db(
    ingredient_name: str, cache: Optional[Dict[str, Optional[Food]]] = None
) -> Optional[Food]:
    """
    Resolves an ingredient name to a database Food entity using a multi-tiered search:
    0. Lookup Cache check: avoids redundant DB queries if the ingredient was already evaluated.
    1. Direct alias dictionary lookup (common English, Hindi, Tamil terms).
    2. Exact Food name match.
    3. Exact FoodVernacularName match.
    4. Cleaned query in alias dictionary.
    5. Food name starts with or contains.
    6. FoodVernacularName starts with or contains.
    7. Multi-word token overlap search.

    Returns the best matching Food instance, or None if unmapped.
    """
    if not ingredient_name or not ingredient_name.strip():
        return None

    raw_query = ingredient_name.strip().lower()

    # Ignore non-edible tableware
    if raw_query in NON_EDIBLE_ITEMS or "banana leaf" in raw_query:
        return None

    # Step 0: Check lookup cache first to prevent repeated DB fetches
    if cache is not None and raw_query in cache:
        return cache[raw_query]
    if raw_query in _FOOD_LOOKUP_CACHE:
        return _FOOD_LOOKUP_CACHE[raw_query]

    def _cache_and_return(match_food: Optional[Food]) -> Optional[Food]:
        _FOOD_LOOKUP_CACHE[raw_query] = match_food
        if cache is not None:
            cache[raw_query] = match_food
        return match_food

    # Handle slashes like "Oil/Ghee" -> try each alternative
    if "/" in raw_query:
        parts = [p.strip() for p in raw_query.split("/") if p.strip()]
        for p in parts:
            found = find_food_in_db(p, cache=cache)
            if found:
                return _cache_and_return(found)

    # Handle parenthetical descriptions like "Lentils (in Sambar)" or "Sambar (lentil and vegetable stew)"
    if "(" in raw_query and ")" in raw_query:
        stripped_paren = re.sub(r"\(.*?\)", "", raw_query).strip()
        if stripped_paren:
            found = find_food_in_db(stripped_paren, cache=cache)
            if found:
                return _cache_and_return(found)

    # Tier 1: Direct Alias Lookup
    if raw_query in COMMON_CULINARY_ALIASES:
        code = COMMON_CULINARY_ALIASES[raw_query]
        food = Food.objects.filter(food_code=code).first()
        if food:
            return _cache_and_return(food)

    # Tier 2: Exact match on Food name
    match = Food.objects.filter(name__iexact=raw_query).first()
    if match:
        return _cache_and_return(match)

    # Tier 3: Exact match on Vernacular names
    v_match = FoodVernacularName.objects.filter(name__iexact=raw_query).select_related("food").first()
    if v_match:
        return _cache_and_return(v_match.food)

    # Tier 4: Cleaned query alias lookup
    cleaned_query = clean_ingredient_query(raw_query)
    if cleaned_query and cleaned_query in COMMON_CULINARY_ALIASES:
        code = COMMON_CULINARY_ALIASES[cleaned_query]
        food = Food.objects.filter(food_code=code).first()
        if food:
            return _cache_and_return(food)

    # Tier 5: Food name starts with or contains
    # Prefer exact prefix matches, then shortest overall matching name
    candidates = Food.objects.filter(name__istartswith=raw_query)
    if candidates.exists():
        return _cache_and_return(min(candidates, key=lambda f: len(f.name)))

    candidates = Food.objects.filter(name__icontains=raw_query)
    if candidates.exists():
        # Avoid picking "Chicken mushroom" when querying "Chicken"
        # Prioritize foods where query is a full word
        word_boundary_pattern = rf"\b{re.escape(raw_query)}\b"
        exact_word_matches = [f for f in candidates if re.search(word_boundary_pattern, f.name, re.IGNORECASE)]
        if exact_word_matches:
            return _cache_and_return(min(exact_word_matches, key=lambda f: len(f.name)))
        return _cache_and_return(min(candidates, key=lambda f: len(f.name)))

    # Tier 6: Vernacular name starts with or contains
    v_candidates = FoodVernacularName.objects.filter(name__istartswith=raw_query).select_related("food")
    if v_candidates.exists():
        return _cache_and_return(v_candidates.first().food)

    v_candidates = FoodVernacularName.objects.filter(name__icontains=raw_query).select_related("food")
    if v_candidates.exists():
        return _cache_and_return(v_candidates.first().food)

    # Tier 7: Try cleaned query if distinct from raw query
    if cleaned_query and cleaned_query != raw_query:
        candidates = Food.objects.filter(name__icontains=cleaned_query)
        if candidates.exists():
            word_boundary_pattern = rf"\b{re.escape(cleaned_query)}\b"
            exact_word_matches = [f for f in candidates if re.search(word_boundary_pattern, f.name, re.IGNORECASE)]
            if exact_word_matches:
                return _cache_and_return(min(exact_word_matches, key=lambda f: len(f.name)))
            return _cache_and_return(min(candidates, key=lambda f: len(f.name)))

        v_candidates = FoodVernacularName.objects.filter(name__icontains=cleaned_query).select_related("food")
        if v_candidates.exists():
            return _cache_and_return(v_candidates.first().food)

    return _cache_and_return(None)


def calculate_ingredient_nutrients(
    food: Food, weight_grams: float
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Calculates macronutrients and micronutrients scaled from the 100g database values
    to the estimated ingredient weight.
    """
    scale = max(weight_grams, 0.0) / 100.0

    proximates: Optional[ProximateNutrient] = getattr(food, "proximates", None)
    vitamins: Optional[VitaminNutrient] = getattr(food, "vitamins", None)
    carotenoids: Optional[CarotenoidNutrient] = getattr(food, "carotenoids", None)
    minerals: Optional[MineralNutrient] = getattr(food, "minerals", None)
    sugars: Optional[SugarNutrient] = getattr(food, "sugars", None)
    fatty_acids: Optional[FattyAcidNutrient] = getattr(food, "fatty_acids", None)

    # --- Macronutrients ---
    energy_kcal = round((proximates.energy_kcal or 0.0) * scale, 2) if proximates else 0.0
    protein_g = round((proximates.protein_g or 0.0) * scale, 2) if proximates else 0.0
    carbs_g = round((proximates.carbohydrates_g or 0.0) * scale, 2) if proximates else 0.0
    fiber_g = round((proximates.total_fiber_g or 0.0) * scale, 2) if proximates else 0.0
    total_fat_g = round((proximates.total_fat_g or 0.0) * scale, 2) if proximates else 0.0
    water_g = round((proximates.moisture_g or 0.0) * scale, 2) if proximates else 0.0
    sugars_g = round((sugars.total_free_sugars_g or 0.0) * scale, 2) if sugars else 0.0

    # Saturated, Unsaturated (MUFA, PUFA), and Trans Fats
    saturated_fat_g = 0.0
    monounsaturated_fat_g = 0.0
    polyunsaturated_fat_g = 0.0
    unsaturated_fat_g = 0.0
    trans_fat_g = 0.0
    cholesterol_mg = 0.0

    if fatty_acids:
        if fatty_acids.is_cooking_oil_percent:
            sfa_pct = (fatty_acids.total_sfa_mg or 0.0) / 100.0
            saturated_fat_g = round(sfa_pct * total_fat_g, 2)
            mufa_pct = (fatty_acids.total_mufa_mg or 0.0) / 100.0
            monounsaturated_fat_g = round(mufa_pct * total_fat_g, 2)
            pufa_pct = (fatty_acids.total_pufa_mg or 0.0) / 100.0
            polyunsaturated_fat_g = round(pufa_pct * total_fat_g, 2)
            unsaturated_fat_g = round(monounsaturated_fat_g + polyunsaturated_fat_g, 2)
        else:
            saturated_fat_g = round(((fatty_acids.total_sfa_mg or 0.0) / 1000.0) * scale, 2)
            monounsaturated_fat_g = round(((fatty_acids.total_mufa_mg or 0.0) / 1000.0) * scale, 2)
            polyunsaturated_fat_g = round(((fatty_acids.total_pufa_mg or 0.0) / 1000.0) * scale, 2)
            unsaturated_fat_g = round(monounsaturated_fat_g + polyunsaturated_fat_g, 2)

        trans_fat_g = round(((fatty_acids.elaidic_c18_1n9t_mg or 0.0) / 1000.0) * scale, 2)
        cholesterol_mg = round((fatty_acids.cholesterol_mg or 0.0) * scale, 2)

    sodium_mg = round((minerals.sodium_mg or 0.0) * scale, 2) if minerals else 0.0

    macronutrients = {
        "calories_kcal": energy_kcal,
        "protein_g": protein_g,
        "carbohydrates_g": carbs_g,
        "dietary_fiber_g": fiber_g,
        "total_sugars_g": sugars_g,
        "added_sugars_g": 0.0,
        "total_fat_g": total_fat_g,
        "saturated_fat_g": saturated_fat_g,
        "monounsaturated_fat_g": monounsaturated_fat_g,
        "polyunsaturated_fat_g": polyunsaturated_fat_g,
        "unsaturated_fat_g": unsaturated_fat_g,
        "trans_fat_g": trans_fat_g,
        "cholesterol_mg": cholesterol_mg,
        "sodium_mg": sodium_mg,
        "water_g": water_g,
    }

    # --- Micronutrients (Vitamins & Minerals) ---
    vitamin_list: List[Dict[str, Any]] = []
    mineral_list: List[Dict[str, Any]] = []

    def _add_micro(target_list: List[Dict[str, Any]], name: str, raw_amt: Optional[float], unit: str):
        if raw_amt is not None and raw_amt > 0:
            scaled_amt = round(raw_amt * scale, 3)
            if scaled_amt > 0:
                ref_dv, _ = DAILY_VALUES.get(name, (0.0, unit))
                dv_pct = round((scaled_amt / ref_dv) * 100.0, 1) if ref_dv > 0 else None
                target_list.append({
                    "name": name,
                    "amount": round(scaled_amt, 2) if unit == "mg" else round(scaled_amt, 1),
                    "unit": unit,
                    "daily_value_percent": dv_pct,
                })

    if vitamins:
        _add_micro(vitamin_list, "Vitamin C", vitamins.vitamin_c_mg, "mg")
        _add_micro(vitamin_list, "Thiamine (B1)", vitamins.thiamine_b1_mg, "mg")
        _add_micro(vitamin_list, "Riboflavin (B2)", vitamins.riboflavin_b2_mg, "mg")
        _add_micro(vitamin_list, "Niacin (B3)", vitamins.niacin_b3_mg, "mg")
        _add_micro(vitamin_list, "Pantothenic Acid (B5)", vitamins.pantothenic_acid_b5_mg, "mg")
        _add_micro(vitamin_list, "Vitamin B6", vitamins.vitamin_b6_mg, "mg")
        _add_micro(vitamin_list, "Biotin (B7)", vitamins.biotin_b7_mcg, "mcg")
        _add_micro(vitamin_list, "Folate (B9)", vitamins.folates_b9_mcg, "mcg")
        _add_micro(vitamin_list, "Vitamin D", vitamins.ergocalciferol_d2_mcg, "mcg")
        _add_micro(vitamin_list, "Vitamin E", vitamins.vitamin_e_mg, "mg")
        _add_micro(vitamin_list, "Vitamin K1", vitamins.vitamin_k1_mcg, "mcg")

    if carotenoids:
        _add_micro(vitamin_list, "Beta-Carotene", carotenoids.beta_carotene_mcg, "mcg")

    if minerals:
        _add_micro(mineral_list, "Calcium", minerals.calcium_mg, "mg")
        _add_micro(mineral_list, "Iron", minerals.iron_mg, "mg")
        _add_micro(mineral_list, "Magnesium", minerals.magnesium_mg, "mg")
        _add_micro(mineral_list, "Phosphorus", minerals.phosphorus_mg, "mg")
        _add_micro(mineral_list, "Potassium", minerals.potassium_mg, "mg")
        _add_micro(mineral_list, "Sodium", minerals.sodium_mg, "mg")
        _add_micro(mineral_list, "Zinc", minerals.zinc_mg, "mg")
        _add_micro(mineral_list, "Copper", minerals.copper_mg, "mg")
        _add_micro(mineral_list, "Manganese", minerals.manganese_mg, "mg")
        _add_micro(mineral_list, "Selenium", minerals.selenium_mcg, "mcg")

    micronutrients = {
        "vitamins": vitamin_list,
        "minerals": mineral_list,
    }

    return macronutrients, micronutrients


def resolve_single_ingredient_from_db(
    item: Dict[str, Any],
    cache: Optional[Dict[str, Optional[Food]]] = None,
) -> Tuple[Dict[str, Any], bool]:
    """
    Resolves a single ingredient dict against the database.
    Returns (resolved_item_dict, is_found).
    If is_found is True: ground-truth macros/micros calculated from satellite tables.
    If is_found is False: zero macros, found_in_database=False.
    Guarantees no repeated DB queries by checking the lookup cache.
    """
    macro_keys = [
        "calories_kcal", "protein_g", "carbohydrates_g", "dietary_fiber_g",
        "total_sugars_g", "added_sugars_g", "total_fat_g", "saturated_fat_g",
        "monounsaturated_fat_g", "polyunsaturated_fat_g",
        "unsaturated_fat_g", "trans_fat_g", "cholesterol_mg", "sodium_mg", "water_g"
    ]

    ing_name = (
        item.get("ingredient_name")
        or item.get("food_name")
        or "Unknown Ingredient"
    ).strip()

    # Check if item is non-edible tableware/serving base (e.g. Banana leaf)
    raw_lower = ing_name.lower()
    if raw_lower in NON_EDIBLE_ITEMS or "banana leaf" in raw_lower:
        return {
            "food_name": ing_name,
            "serving_size_description": str(item.get("serving_size_description") or "Serving base/Platter"),
            "estimated_weight_grams": float(item.get("estimated_weight_grams") or 0.0),
            "confidence": 1.0,
            "glycemic_index_category": None,
            "found_in_database": True,
            "database_food_code": "TABLEWARE",
            "database_food_name": "Non-edible serving base",
            "macronutrients": {k: 0.0 for k in macro_keys},
            "micronutrients": {"vitamins": [], "minerals": []},
        }, True

    serving_desc = str(item.get("serving_size_description") or "1 serving")
    try:
        weight_grams = float(item.get("estimated_weight_grams") or 100.0)
    except (TypeError, ValueError):
        weight_grams = 100.0

    try:
        confidence = float(item.get("confidence") or 0.9)
    except (TypeError, ValueError):
        confidence = 0.9

    food = find_food_in_db(ing_name, cache=cache)

    if food is not None:
        food_with_satellites = Food.objects.select_related(
            "proximates", "vitamins", "carotenoids", "minerals", "sugars", "fatty_acids"
        ).get(food_code=food.food_code)

        macros, micros = calculate_ingredient_nutrients(food_with_satellites, weight_grams)

        return {
            "food_name": ing_name,
            "serving_size_description": serving_desc,
            "estimated_weight_grams": weight_grams,
            "confidence": confidence,
            "glycemic_index_category": item.get("glycemic_index_category"),
            "found_in_database": True,
            "database_food_code": food.food_code,
            "database_food_name": food.name,
            "macronutrients": macros,
            "micronutrients": micros,
        }, True

    return {
        "food_name": ing_name,
        "serving_size_description": serving_desc,
        "estimated_weight_grams": weight_grams,
        "confidence": confidence,
        "glycemic_index_category": None,
        "found_in_database": False,
        "database_food_code": None,
        "database_food_name": None,
        "macronutrients": {k: 0.0 for k in macro_keys},
        "micronutrients": {"vitamins": [], "minerals": []},
    }, False


def resolve_dish_nutrition_from_db(
    dish_data: Dict[str, Any],
    cache: Optional[Dict[str, Optional[Food]]] = None,
) -> Dict[str, Any]:
    """
    Takes AI-identified dish and ingredients data, resolves every ingredient from the
    authoritative reference database, strictly computes nutritional values from database records,
    and explicitly flags any ingredients not found in the database.
    """
    dish_title = (
        dish_data.get("dish_name")
        or dish_data.get("meal_title")
        or "Identified Dish"
    )
    summary = (
        dish_data.get("recognized_input_summary")
        or f"Identified dish: {dish_title}"
    )

    raw_ingredients = (
        dish_data.get("ingredients")
        or dish_data.get("items")
        or []
    )

    resolved_items: List[Dict[str, Any]] = []
    missing_ingredients: List[str] = []

    macro_keys = [
        "calories_kcal", "protein_g", "carbohydrates_g", "dietary_fiber_g",
        "total_sugars_g", "added_sugars_g", "total_fat_g", "saturated_fat_g",
        "monounsaturated_fat_g", "polyunsaturated_fat_g",
        "unsaturated_fat_g", "trans_fat_g", "cholesterol_mg", "sodium_mg", "water_g"
    ]
    total_macros = {k: 0.0 for k in macro_keys}

    for item in raw_ingredients:
        if not isinstance(item, dict):
            continue

        resolved_item, is_found = resolve_single_ingredient_from_db(item, cache=cache)
        resolved_items.append(resolved_item)

        if is_found:
            for k in macro_keys:
                total_macros[k] = round(total_macros[k] + resolved_item["macronutrients"].get(k, 0.0), 2)
        else:
            missing_ingredients.append(resolved_item["food_name"])

    dietary_tags = list(dish_data.get("dietary_tags") or [])
    health_insights = list(dish_data.get("health_insights") or [])

    # Aggregate total micronutrients (vitamins & minerals) across resolved items
    micro_totals: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {
        "vitamins": {},
        "minerals": {},
    }
    for resolved_item in resolved_items:
        item_micros = resolved_item.get("micronutrients") or {}
        for category in ("vitamins", "minerals"):
            for micro in item_micros.get(category) or []:
                m_name = str(micro.get("name") or "Unknown")
                m_unit = str(micro.get("unit") or "")
                m_key = (m_name, m_unit)
                entry = micro_totals[category].setdefault(
                    m_key,
                    {"name": m_name, "unit": m_unit, "amount": 0.0, "daily_value_percent": 0.0},
                )
                entry["amount"] += float(micro.get("amount") or 0.0)
                entry["daily_value_percent"] += float(micro.get("daily_value_percent") or 0.0)

    total_micros = {
        category: [
            {
                "name": item["name"],
                "unit": item["unit"],
                "amount": round(item["amount"], 2),
                "daily_value_percent": round(item["daily_value_percent"], 1),
            }
            for item in sorted(cat_map.values(), key=lambda x: (-x["daily_value_percent"], x["name"]))
        ]
        for category, cat_map in micro_totals.items()
    }

    # Explicitly highlight missing ingredients if any
    if missing_ingredients:
        unique_missing = sorted(list(set(missing_ingredients)))
        note = (
            f"The following ingredient(s) could not be found in the reference database: "
            f"{', '.join(unique_missing)}. "
            f"Their nutrients are currently excluded from total calculations. "
            f"Please record and load their nutrient details manually into the database."
        )
        health_insights.append(note)

    return {
        "meal_title": dish_title,
        "recognized_input_summary": summary,
        "items": resolved_items,
        "total_macronutrients": total_macros,
        "total_micronutrients": total_micros,
        "dietary_tags": dietary_tags,
        "health_insights": health_insights,
        "missing_ingredients": missing_ingredients,
    }
