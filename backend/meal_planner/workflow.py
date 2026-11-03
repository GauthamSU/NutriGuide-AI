import copy
import json
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from nutrition.schemas import MealPlanResponseSchema
from nutrition.services.llama_client import LlamaCppClient


class MealPlanState(TypedDict, total=False):
    preferences: list[str]
    custom_request: str
    duration: str
    diet_type: str
    image_base64: Optional[str]
    image_mime_type: Optional[str]
    transcription: Optional[str]
    user_profile_context: Optional[str]
    meal_plan: dict[str, Any]


DIET_TYPE_INSTRUCTIONS = {
    "veg": (
        "Strictly Vegetarian (Lacto-Vegetarian): Include plant-based foods and dairy "
        "(milk, curd/yogurt, paneer, ghee). NEVER include meat, poultry, fish, seafood, or eggs."
    ),
    "non-veg": (
        "Non-Vegetarian: Include balanced non-vegetarian protein sources (chicken, fish, eggs, "
        "lean meats) alongside wholesome grains, legumes, and vegetables."
    ),
    "vegan": (
        "Strictly 100% Vegan (Plant-Based): NEVER include meat, poultry, fish, eggs, dairy "
        "(milk, curd, paneer, cheese, butter, ghee), or honey. Use plant proteins (tofu, tempeh, "
        "lentils, chickpeas, nuts, seeds, soy/almond/coconut milk)."
    ),
    "egg": (
        "Eggetarian (Ovo-Lacto Vegetarian): Include eggs, dairy, and plant-based foods. "
        "NEVER include meat, poultry, fish, or seafood."
    ),
}

DURATION_MIN_OPTIONS = {
    "daily": 3,
    "weekly": 5,
    "monthly": 10,
}

DURATION_INSTRUCTIONS = {
    "daily": (
        "Create a 1-day (Daily) meal plan. Provide AT LEAST 3 distinct, practical options in each "
        "section (breakfast, lunch, snacks, dinner). Keep 'details' and 'why_it_fits' concise (1 short sentence each)."
    ),
    "weekly": (
        "Create a 7-day (Weekly) meal plan rotation. In EACH section (breakfast, lunch, snacks, dinner), "
        "you MUST provide AT LEAST 5 to 7 distinct options covering the week (e.g., 'Day 1 (Mon): ...', "
        "'Day 2 (Tue): ...', 'Day 3 (Wed): ...', 'Day 4 (Thu): ...', 'Day 5 (Fri): ...', 'Days 6–7 (Weekend): ...'). "
        "Keep 'details' and 'why_it_fits' concise (1 short sentence each)."
    ),
    "monthly": (
        "Create a 4-week (Monthly) meal plan blueprint. In EACH section (breakfast, lunch, snacks, dinner), "
        "you MUST provide AT LEAST 10 distinct options rotating across the month (e.g., 'Option 1 (Days 1–3): ...' "
        "through 'Option 10 (Days 28–30): ...'). Keep 'details' and 'why_it_fits' concise (1 short sentence each) "
        "so all 10+ options in every section generate completely."
    ),
}

# Diet-aware fallback pools used only if a smaller local model returns fewer than the required minimum options
FALLBACK_MEAL_POOL: dict[str, dict[str, list[dict[str, str]]]] = {
    "veg": {
        "breakfast": [
            {"name": "Moong Dal Chilla with Mint Curd", "details": "2 savoury green gram pancakes served with 1/2 cup fresh curd.", "why_it_fits": "High plant protein and slow-digesting complex carbohydrates."},
            {"name": "Vegetable Poha with Roasted Peanuts & Lemon", "details": "1 bowl flattened rice cooked with peas, carrots, turmeric, and curry leaves.", "why_it_fits": "Light, iron-rich morning meal with healthy fats."},
            {"name": "Ragi Malt & Steamed Idli Sambar", "details": "2 soft idlis with vegetable sambar and 1 glass finger millet porridge.", "why_it_fits": "Fermented gut-friendly grains paired with calcium-rich ragi."},
            {"name": "Paneer Bhurji on Multigrain Toast", "details": "100g crumbled spiced cottage cheese with bell peppers and 2 multigrain slices.", "why_it_fits": "Rich vegetarian protein to keep morning hunger away."},
            {"name": "Overnight Oats with Chia, Almonds & Pomegranate", "details": "1/2 cup rolled oats soaked in milk with 1 tbsp chia seeds and fresh fruit.", "why_it_fits": "Soluble beta-glucan fiber for steady morning energy."},
            {"name": "Vegetable Upma with Coconut Chutney", "details": "1 bowl roasted semolina/millets cooked with beans, carrots, and mustard seeds.", "why_it_fits": "Wholesome warm breakfast with balanced micronutrients."},
            {"name": "Besan Methi Paratha with Low-Fat Curd", "details": "2 whole-wheat & chickpea flour flatbreads with fenugreek leaves.", "why_it_fits": "Lower glycemic load with extra fiber and protein."},
            {"name": "Sprouted Moong & Pomegranate Salad Bowl", "details": "1 cup steamed moong sprouts tossed with cucumber, tomato, and lemon.", "why_it_fits": "Enzyme-rich, high-fiber start with vitamin C."},
            {"name": "Millet Pongal with Pepper-Cumin Tempering", "details": "1 bowl foxtail millet and moong dal pongal with ginger and black pepper.", "why_it_fits": "Comforting, easy-to-digest complete amino acid profile."},
            {"name": "Dalia (Broken Wheat) Vegetable Khichdi", "details": "1 bowl cracked wheat cooked with moong dal, spinach, and mild spices.", "why_it_fits": "Sustained energy release and rich B-vitamins."},
        ],
        "lunch": [
            {"name": "Rajma Masala with Brown Rice & Kachumber Salad", "details": "1 cup kidney bean curry, 1 cup brown rice, and cucumber-tomato salad.", "why_it_fits": "Classic complete protein combination rich in soluble fiber."},
            {"name": "Palak Paneer with 2 Whole-Wheat Rotis & Dal", "details": "1 cup spinach-paneer gravy, 2 phulkas, and 1/2 cup yellow toor dal.", "why_it_fits": "Combines iron-rich leafy greens with calcium and protein."},
            {"name": "Chole (Chickpea Curry) with Quinoa / Millet Pilaf", "details": "1 cup spiced garbanzo beans with 1 cup fluffy millet rice and beet salad.", "why_it_fits": "High-fiber legumes support satiety and steady glucose."},
            {"name": "South Indian Sambar Rice with Bhindi Poriyal & Curd", "details": "1 bowl toor dal vegetable sambar with parboiled rice and stir-fried okra.", "why_it_fits": "Balanced macros with probiotic curd and vegetable fiber."},
            {"name": "Baingan Bharta, Panchmel Dal & Jowar Roti", "details": "Roasted mashed brinjal, 1 bowl mixed five-lentil dal, and 2 sorghum rotis.", "why_it_fits": "Gluten-free millet paired with diverse lentil proteins."},
            {"name": "Curd Rice with Pomegranate & Masoor Dal Tadka", "details": "1 bowl tempered yogurt rice with 1 cup red lentil dal and carrot kosambari.", "why_it_fits": "Cooling, gut-soothing midday meal with balanced protein."},
            {"name": "Methi Matar Malai (Light) with Missi Roti", "details": "Fenugreek and green peas curry served with 2 gram-flour wheat rotis.", "why_it_fits": "Phytonutrient-dense greens with high-protein flatbread."},
            {"name": "Vegetable Pulao with Boondi Raita & Kala Chana", "details": "1 bowl spiced vegetable rice with 1 cup black chickpea gravy and raita.", "why_it_fits": "Iron- and protein-dense black chickpeas sustain afternoon focus."},
            {"name": "Lauki Chana Dal with Bajra Roti & Green Salad", "details": "1 bowl bottle gourd and split Bengal gram curry with 2 pearl millet rotis.", "why_it_fits": "Hydrating vegetables with mineral-rich pearl millet."},
            {"name": "Mixed Sprouts Usal with Chapati & Buttermilk", "details": "1 cup Maharashtrian spiced mixed sprouts curry, 2 chapatis, and chaas.", "why_it_fits": "High bioavailability of micronutrients from sprouted legumes."},
        ],
        "snacks": [
            {"name": "Roasted Makhana (Fox Nuts) with Turmeric & Pepper", "details": "1.5 cups dry-roasted lotus seeds with a pinch of rock salt and ghee.", "why_it_fits": "Low-calorie, crunchy mineral boost between meals."},
            {"name": "Roasted Chana & Mixed Walnuts/Almonds", "details": "1/3 cup crunchy roasted Bengal gram with 6 almonds and 3 walnut halves.", "why_it_fits": "Combines plant protein with omega-3 healthy fats."},
            {"name": "Spiced Masala Chaas & Cucumber Sticks", "details": "1 tall glass buttermilk with roasted cumin, mint, and sliced cucumber.", "why_it_fits": "Hydrating probiotic drink that curbs afternoon cravings."},
            {"name": "Steamed Corn & Bell Pepper Chaat", "details": "1 cup sweet corn tossed with chopped onions, coriander, and lemon juice.", "why_it_fits": "Antioxidant lutein and fiber without deep frying."},
            {"name": "Apple Slices with Homemade Peanut Butter", "details": "1 medium apple sliced with 1 tbsp unsweetened natural peanut butter.", "why_it_fits": "Pectin fiber paired with monounsaturated fats."},
            {"name": "Dhokla (Steamed Fermented Chickpea Cake)", "details": "3 pieces spongy khaman dhokla with coriander-mint chutney.", "why_it_fits": "Steamed, fermented, low-oil protein snack."},
            {"name": "Paneer Tikka Skewers (Grilled)", "details": "80g cubed cottage cheese marinated in hung curd and grilled with capsicum.", "why_it_fits": "High-protein evening bridge to prevent dinner overeating."},
            {"name": "Guava with Chaat Masala & Pumpkin Seeds", "details": "1 ripe guava with 1 tbsp roasted pumpkin and sunflower seeds.", "why_it_fits": "Exceptionally high vitamin C with zinc and magnesium."},
            {"name": "Ragda / Boiled Kala Chana Sundal", "details": "1/2 cup boiled black chickpeas tempered with mustard, curry leaves, and coconut.", "why_it_fits": "Traditional South Indian high-fiber protein snack."},
            {"name": "Greek Yogurt / Hung Curd Berry Parfait", "details": "1/2 cup thick curd topped with flaxseeds and seasonal fruit.", "why_it_fits": "Casein protein and probiotics for digestive health."},
        ],
        "dinner": [
            {"name": "Moong Dal Palak Khichdi with Roasted Papad", "details": "1 comforting bowl yellow moong dal, rice, and spinach khichdi.", "why_it_fits": "Light on evening digestion while providing complete protein."},
            {"name": "Grilled Paneer & Sautéed Broccoli-Mushroom Bowl", "details": "100g herb-grilled paneer with garlic-sautéed broccoli, beans, and carrots.", "why_it_fits": "Low-carb, high-protein restorative evening meal."},
            {"name": "Masoor Dal Soup with 2 Multigrain Phulkas & Bhindi", "details": "1 bowl red lentil soup, 2 soft rotis, and dry-roasted okra sabzi.", "why_it_fits": "High fiber and lean plant protein for overnight recovery."},
            {"name": "Tofu/Paneer Tikka Salad with Quinoa", "details": "1 bowl warm quinoa tossed with grilled paneer, greens, and lemon-olive dressing.", "why_it_fits": "Nutrient-dense, light dinner that supports restful sleep."},
            {"name": "Vegetable Dalia Upma with Yellow Dal Tadka", "details": "1 cup broken wheat vegetable upma served with 1/2 cup tempered dal.", "why_it_fits": "Complex carbohydrates with minimal evening glycemic spike."},
            {"name": "Methi Thepla with Lauki Raita & Green Moong Dal", "details": "2 thin fenugreek flatbreads with bottle gourd raita and whole green gram.", "why_it_fits": "Balanced fiber, probiotics, and plant protein."},
            {"name": "Tomato-Lentil Rasam with Millet Rice & Beans Thoran", "details": "1 small bowl millet rice with warm pepper rasam and cabbage-beans stir-fry.", "why_it_fits": "Soothing digestive spices with high vegetable volume."},
            {"name": "Palak Chana Dal with 1 Jowar Roti & Cucumber Salad", "details": "1 cup spinach split-gram curry with gluten-free sorghum flatbread.", "why_it_fits": "Rich in folate, iron, and slow-release energy."},
            {"name": "Stuffed Capsicum with Spiced Cottage Cheese & Dal", "details": "2 baked bell peppers stuffed with paneer-pea mash and 1 bowl clear dal.", "why_it_fits": "Portion-controlled, vitamin-C rich dinner."},
            {"name": "Oats & Vegetable Oats Uttapam with Tomato Chutney", "details": "2 savoury rolled-oats uttapams topped with onions, tomatoes, and coriander.", "why_it_fits": "Quick, light, beta-glucan rich evening option."},
        ],
    },
}

# Build vegan, egg, and non-veg fallback pools so every diet_type has 10+ authentic options
FALLBACK_MEAL_POOL["vegan"] = {
    "breakfast": [
        {"name": "Tofu Bhurji with Multigrain Toast", "details": "120g scrambled spiced firm tofu with spinach, tomatoes, and 2 toast slices.", "why_it_fits": "100% plant-based complete soy protein with zero cholesterol."},
        {"name": "Moong Dal Chilla with Coriander-Mint Chutney", "details": "2 savoury green gram crepes cooked with minimal cold-pressed oil.", "why_it_fits": "High plant protein and iron without dairy."},
        {"name": "Almond-Milk Chia Overnight Oats with Berries", "details": "1/2 cup rolled oats soaked in almond milk with chia, flax, and fruit.", "why_it_fits": "Omega-3 fatty acids and soluble fiber for steady energy."},
        {"name": "Vegetable Poha with Peanuts & Sprouts", "details": "1 bowl flattened rice topped with steamed moong sprouts and lemon juice.", "why_it_fits": "Vitamin C boosts plant-iron absorption."},
        {"name": "Steamed Idli with Drumstick Vegetable Sambar", "details": "3 fermented rice-lentil idlis with hearty lentil-vegetable sambar.", "why_it_fits": "Naturally vegan, gut-friendly fermented breakfast."},
        {"name": "Ragi Porridge Made with Coconut Milk & Nuts", "details": "1 bowl finger millet porridge cooked with light coconut milk and almonds.", "why_it_fits": "Dairy-free calcium and sustained complex carbs."},
        {"name": "Besan-Spinach Cheela with Tomato Garlic Chutney", "details": "2 chickpea flour pancakes packed with chopped baby spinach.", "why_it_fits": "Low-glycemic vegan breakfast rich in folate."},
        {"name": "Foxtail Millet Upma with Green Peas & Cashews", "details": "1 bowl savoury millet upma with carrots, peas, and curry leaves.", "why_it_fits": "High-fiber gluten-free and dairy-free morning fuel."},
        {"name": "Peanut Butter & Banana Whole-Grain Wrap", "details": "1 whole-wheat tortilla with 1.5 tbsp natural peanut butter, banana, and hemp seeds.", "why_it_fits": "Potassium and plant protein for active mornings."},
        {"name": "Sprouted Moth & Moong Salad with Lemon-Tahini", "details": "1.5 cups warm steamed sprouts with cucumber, pomegranate, and sesame dressing.", "why_it_fits": "Rich in plant enzymes, calcium, and protein."},
    ],
    "lunch": [
        {"name": "Chana Masala with Brown Rice & Cucumber Salad", "details": "1 cup spiced chickpea curry, 1 cup brown basmati rice, and lemon salad.", "why_it_fits": "Complete amino acid profile from legumes and whole grain."},
        {"name": "Palak Tofu Curry with 2 Whole-Wheat Rotis", "details": "1 cup iron-rich spinach gravy with cubed firm tofu and 2 oil-free phulkas.", "why_it_fits": "Dairy-free alternative to palak paneer with high calcium and iron."},
        {"name": "Rajma Chawal with Beetroot-Carrot Koshimbir", "details": "1 cup red kidney beans in tomato-onion gravy with steamed red rice.", "why_it_fits": "Antioxidant-rich kidney beans support heart and gut health."},
        {"name": "South Indian Sambar, Millet Rice & Cabbage Thoran", "details": "1 bowl toor dal sambar with foxtail millet and coconut-tempered cabbage.", "why_it_fits": "Naturally vegan South Indian thali with high vegetable fiber."},
        {"name": "kala Chana & Sweet Potato Quinoa Bowl", "details": "1 cup black chickpeas, roasted sweet potato, spinach, and quinoa.", "why_it_fits": "Complex carbs and slow-digesting legume protein."},
        {"name": "Masoor Dal Tadka (Oil-Tempered) with Jowar Bhakri", "details": "1 bowl red lentil dal tempered with cumin-garlic and 2 sorghum flatbreads.", "why_it_fits": "High-iron lentils paired with gluten-free millet."},
        {"name": "Baingan Bharta, Moong Dal & 2 Multigrain Rotis", "details": "Smoky roasted eggplant mash with yellow moong dal and rotis.", "why_it_fits": "Low-calorie, high-satiety plant-forward midday meal."},
        {"name": "Mixed Vegetable & Soy Chunk Pulao with Kachumber", "details": "1.5 cups high-protein soya chunk and vegetable brown rice pilaf.", "why_it_fits": "Delivers over 20g of vegan protein in a single bowl."},
        {"name": "Lobia (Black-Eyed Peas) Curry with Bajra Roti", "details": "1 cup spiced black-eyed peas curry with 2 pearl millet rotis.", "why_it_fits": "Rich in folate, potassium, and soluble fiber."},
        {"name": "Green Moong Whole Usal with Steamed Rice & Salad", "details": "1 cup whole green gram curry with lemon wedges and steamed rice.", "why_it_fits": "Wholesome plant protein that keeps afternoon energy stable."},
    ],
    "snacks": [
        {"name": "Roasted Makhana with Nutritional Yeast & Herbs", "details": "1.5 cups dry-roasted fox nuts tossed with turmeric, pepper, and rock salt.", "why_it_fits": "Crunchy, low-calorie plant snack."},
        {"name": "Hummus with Carrot, Cucumber & Bell Pepper Sticks", "details": "1/3 cup chickpea-tahini hummus with fresh crunchy crudités.", "why_it_fits": "Healthy sesame fats and chickpea fiber."},
        {"name": "Roasted Chana & Trail Mix (Almonds, Walnuts, Seeds)", "details": "1/3 cup roasted Bengal gram with pumpkin seeds and walnuts.", "why_it_fits": "High plant protein and plant omega-3s."},
        {"name": "Steamed Khaman Dhokla with Green Chutney", "details": "3 pieces fermented chickpea cake topped with sesame and coriander.", "why_it_fits": "Light, steamed, probiotic-friendly vegan snack."},
        {"name": "Boiled Kala Chana Sundal with Grated Coconut", "details": "1/2 cup spiced black chickpeas with curry leaves and fresh coconut.", "why_it_fits": "Sustained afternoon energy without blood-sugar spikes."},
        {"name": "Apple Slices with Almond Butter & Chia Seeds", "details": "1 crisp apple with 1 tbsp unsweetened almond butter.", "why_it_fits": "Balanced fiber and vitamin E."},
        {"name": "Grilled Herbed Tofu Cubes with Mint Dip", "details": "100g pan-seared spiced tofu cubes with pudina chutney.", "why_it_fits": "Lean plant protein boost before evening workouts."},
        {"name": "Sweet Corn & Pomegranate Bhel (Oil-Free)", "details": "1 cup steamed corn, puffed rice, onion, tomato, and tamarind-mint dressing.", "why_it_fits": "Refreshing antioxidant-rich evening snack."},
        {"name": "Edamame / Steamed Green Soybeans with Sea Salt", "details": "1 cup steamed edamame pods with lemon and chili flakes.", "why_it_fits": "Complete plant protein and dietary fiber."},
        {"name": "Guava & Roasted Sunflower-Flax Seed Mix", "details": "1 medium guava paired with 1 tbsp mixed roasted seeds.", "why_it_fits": "High vitamin C and essential minerals."},
    ],
    "dinner": [
        {"name": "Spinach Moong Dal Khichdi (Tempered with Sesame Oil)", "details": "1 warm bowl yellow moong dal, brown rice, and palak khichdi.", "why_it_fits": "Gentle on digestion and rich in plant amino acids."},
        {"name": "Grilled Tofu & Stir-Fried Broccoli, Beans & Peppers", "details": "120g firm tofu tossed with colourful vegetables in ginger-garlic sauce.", "why_it_fits": "High-protein, low-glycemic vegan dinner."},
        {"name": "Red Lentil & Vegetable Soup with 1 Multigrain Roti", "details": "1 hearty bowl masoor dal vegetable soup with 1 whole-grain phulka.", "why_it_fits": "Warm, restorative, and fiber-rich evening meal."},
        {"name": "Quinoa Vegetable Pulao with Dal Fry", "details": "1 cup fluffy vegetable quinoa served with 1/2 cup yellow toor dal.", "why_it_fits": "Complete plant protein with magnesium for sleep support."},
        {"name": "Methi Roti with Chana Dal Lauki Sabzi", "details": "2 fenugreek rotis with bottle gourd and split Bengal gram curry.", "why_it_fits": "Easy to digest and supports overnight blood-sugar balance."},
        {"name": "Soya Granule Matar Keema with 2 Phulkas", "details": "1 cup spiced soya mince and green peas curry with whole-wheat rotis.", "why_it_fits": "Packed with lean plant protein for muscle recovery."},
        {"name": "Millet Bisibelebath (Dairy-Free) with Cucumber Kosambari", "details": "1 bowl lentil-vegetable millet stew with fresh cucumber-moong salad.", "why_it_fits": "One-pot balanced macro and micronutrient profile."},
        {"name": "Chickpea & Spinach Coconut Curry with Red Rice", "details": "1 cup chickpeas and spinach in light coconut-tomato gravy with 1/2 cup rice.", "why_it_fits": "Iron-rich greens with satisfying healthy fats."},
        {"name": "Oats & Lentil Adai Dosa with Tomato-Onion Chutney", "details": "2 protein-rich mixed lentil and oats dosas with tangential chutney.", "why_it_fits": "High-protein fermented crepe for a light dinner."},
        {"name": "Stuffed Bell Peppers with Quinoa & Black Beans", "details": "2 roasted capsicums filled with spiced quinoa, corn, and beans.", "why_it_fits": "Nutrient-dense, colourful, portion-controlled dinner."},
    ],
}

FALLBACK_MEAL_POOL["egg"] = {
    "breakfast": [
        {"name": "Masala Vegetable Omelette with 2 Multigrain Toasts", "details": "2 whole eggs + 1 egg white whisked with onion, tomato, spinach, and coriander.", "why_it_fits": "High biological-value protein and choline for morning focus."},
        {"name": "Boiled Eggs & Avocado/Mint Chutney Whole-Wheat Toast", "details": "2 hard-boiled eggs sliced over 2 multigrain toasts with herb chutney.", "why_it_fits": "Sustained satiety with healthy fats and complete amino acids."},
        {"name": "Egg Bhurji (Spiced Scramble) with 2 Soft Phulkas", "details": "2 eggs scrambled with tomatoes, green chillies, and turmeric.", "why_it_fits": "Warm traditional high-protein Indian breakfast."},
        {"name": "Poached Eggs on Sautéed Spinach & Ragi Toast", "details": "2 poached eggs over wilted garlic spinach and multigrain bread.", "why_it_fits": "Combines iron-rich greens with vitamin B12 and D from eggs."},
        {"name": "Moong Dal Chilla Topped with Egg White Omelette", "details": "1 green gram crepe layered with a spiced egg-white omelette.", "why_it_fits": "Doubles up plant and egg protein with complex carbs."},
        {"name": "Shakshuka (Eggs Poached in Spiced Tomato-Pepper Sauce)", "details": "2 eggs simmered in tomato-bell pepper gravy with 1 whole-wheat pita/roti.", "why_it_fits": "Lycopene-rich vegetables paired with complete protein."},
        {"name": "Oats Porridge with 2 Side Boiled Eggs", "details": "1 bowl warm cinnamon oats with almonds alongside 2 boiled eggs.", "why_it_fits": "Soluble fiber from oats plus 12g protein from eggs."},
        {"name": "Egg Dosa with Coconut Chutney & Sambar", "details": "1 fermented crepe roasted with 1 egg spread on top and vegetable sambar.", "why_it_fits": "Balanced South Indian breakfast with boosted protein."},
        {"name": "Spinach & Mushroom Frittata Muffins", "details": "3 baked egg muffins loaded with mushrooms, bell peppers, and herbs.", "why_it_fits": "Low-carb, portable, nutrient-dense morning option."},
        {"name": "Vegetable Upma with 2 Masala Boiled Eggs", "details": "1 bowl semolina vegetable upma paired with pepper-spiced boiled eggs.", "why_it_fits": "Balances quick morning energy with lasting protein."},
    ],
    "lunch": [
        {"name": "Home-Style Egg Curry with Brown Rice & Cucumber Salad", "details": "2 boiled eggs in onion-tomato masala gravy with 1 cup brown rice.", "why_it_fits": "Balanced carbohydrates and complete protein for midday fuel."},
        {"name": "Egg Bhurji Roll in Whole-Wheat Roti with Mint Curd", "details": "2 whole-wheat kathi rolls filled with spiced egg scramble and crunchy onions.", "why_it_fits": "High-protein, portable lunch with probiotic yogurt."},
        {"name": "Palak Egg Curry with 2 Multigrain Rotis & Dal", "details": "2 eggs simmered in iron-rich spinach puree with 2 phulkas.", "why_it_fits": "Pairs folate and iron from spinach with high-protein eggs."},
        {"name": "Quinoa & Boiled Egg Mediterranean/Indian Salad Bowl", "details": "1 cup quinoa, 2 boiled eggs, chickpeas, cucumber, and lemon dressing.", "why_it_fits": "Fiber-rich grain + legume + egg trio for steady afternoon energy."},
        {"name": "South Indian Egg Roast with Appam / Millet Rice & Thoran", "details": "2 eggs in caramelized onion-pepper masala with millet rice and cabbage stir-fry.", "why_it_fits": "Wholesome regional meal with high vegetable content."},
        {"name": "Dal Tadka, 2 Egg-White Omelette Strips & Jeera Rice", "details": "1 bowl yellow toor dal, cumin rice, and herbed egg strips.", "why_it_fits": "Combines lentil fiber with lean egg-white albumin."},
        {"name": "Egg & Vegetable Millet Fried Rice with Raita", "details": "1.5 cups foxtail millet stir-fried with 2 eggs, carrots, beans, and spring onions.", "why_it_fits": "Low-glycemic millet grain with high protein and vegetables."},
        {"name": "Chana Masala, 1 Boiled Egg & 2 Whole-Wheat Phulkas", "details": "1 cup chickpea curry topped with a sliced boiled egg and 2 rotis.", "why_it_fits": "High fiber and over 22g protein to prevent afternoon slumps."},
        {"name": "Egg Drop Sweet Corn & Lentil Soup with Multigrain Bread", "details": "1 large bowl protein-rich egg-lentil soup with sautéed greens.", "why_it_fits": "Light yet deeply nourishing midday option."},
        {"name": "Paneer & Egg White Stir-Fry with Jowar Roti", "details": "80g paneer and 3 egg whites tossed with bell peppers and 2 sorghum rotis.", "why_it_fits": "Dual vegetarian/eggetarian protein sources."},
    ],
    "snacks": [
        {"name": "2 Spiced Boiled Egg Whites & 1 Whole Egg with Pepper", "details": "Sliced hard-boiled eggs sprinkled with roasted cumin, black salt, and coriander.", "why_it_fits": "Pure, high-satiety protein snack under 150 kcal."},
        {"name": "Egg Chaat with Onion, Tomato, Coriander & Lemon", "details": "2 boiled eggs cubed and tossed with crunchy vegetables and chaat masala.", "why_it_fits": "Tangy, protein-packed alternative to fried snacks."},
        {"name": "Roasted Makhana & 1 Boiled Egg", "details": "1 cup roasted fox nuts paired with 1 hard-boiled egg.", "why_it_fits": "Crunchy carbohydrates balanced with complete protein."},
        {"name": "Mini Besan-Egg Omelette Toast", "details": "1 egg whisked with 1 tbsp gram flour and herbs on 1 multigrain slice.", "why_it_fits": "Extra fiber and protein for pre-workout fuel."},
        {"name": "Masala Buttermilk (Chaas) & Mixed Nuts", "details": "1 glass spiced buttermilk with 6 almonds and 3 walnuts.", "why_it_fits": "Probiotics and omega-3 fats for afternoon refreshment."},
        {"name": "Avocado / Guacamole Deviled Eggs", "details": "2 boiled eggs stuffed with mashed avocado, lime, and black pepper.", "why_it_fits": "Heart-healthy monounsaturated fats and protein."},
        {"name": "Sprouted Moong Salad Topped with Grated Boiled Egg", "details": "1 cup steamed sprouts topped with 1 grated boiled egg and lemon.", "why_it_fits": "High-fiber legumes + high-protein egg."},
        {"name": "Greek Yogurt / Hung Curd with Chia & Pomegranate", "details": "1/2 cup thick curd with 1 tsp chia seeds and fresh pomegranate arils.", "why_it_fits": "Calcium, probiotics, and antioxidants."},
        {"name": "Steamed Egg Custard (Savoury) with Herbs", "details": "1 ramekin silky steamed egg with spring onions and sesame oil.", "why_it_fits": "Gentle, high-protein, zero-fry snack."},
        {"name": "Roasted Chana & Apple Slices", "details": "1/3 cup roasted Bengal gram with 1 sliced apple.", "why_it_fits": "Steady fiber and plant protein."},
    ],
    "dinner": [
        {"name": "2-Egg Vegetable Omelette with Sautéed Broccoli & Soup", "details": "Fluffy vegetable omelette served with garlic broccoli and clear tomato soup.", "why_it_fits": "Light, low-carb, high-protein evening meal for overnight recovery."},
        {"name": "Egg Tadka Dal with 2 Whole-Wheat Phulkas", "details": "1 bowl yellow moong/masoor dal tempered with 1 scrambled egg and spices.", "why_it_fits": "Comforting high-protein dhaba-style dinner with minimal oil."},
        {"name": "Grilled Vegetable & Boiled Egg Salad with Quinoa", "details": "2 boiled eggs over warm quinoa, zucchini, bell peppers, and olive-lemon dressing.", "why_it_fits": "Complete amino acids and magnesium for restorative sleep."},
        {"name": "Moong Dal Khichdi with 1 Masala Omelette on the Side", "details": "1 small bowl soothing dal khichdi paired with a 1-egg herb omelette.", "why_it_fits": "Easy to digest while keeping evening protein intake strong."},
        {"name": "Egg & Spinach Curry with 1 Jowar Roti", "details": "2 eggs in light palak gravy served with 1 gluten-free sorghum roti.", "why_it_fits": "Micronutrient-rich greens with lean protein."},
        {"name": "Egg Bhurji Lettuce/Roti Wraps with Cucumber Raita", "details": "2 eggs scrambled with capsicum and onions wrapped in 1 thin phulka.", "why_it_fits": "Portion-controlled, protein-dense dinner."},
        {"name": "Clear Egg Drop & Mushroom Vegetable Soup", "details": "1 large bowl warm broth with ribbons of egg, mushrooms, bok choy/spinach, and tofu.", "why_it_fits": "Hydrating, low-calorie, high-protein evening option."},
        {"name": "Oats Uttapam Topped with Grated Boiled Egg & Chutney", "details": "2 savoury oats uttapams topped with 1 grated boiled egg and coriander.", "why_it_fits": "Soluble fiber + complete protein."},
        {"name": "Poached Eggs over Garlic-Sautéed French Beans & Carrots", "details": "2 poached eggs served over 1.5 cups crunchy sautéed vegetables and 1 toast.", "why_it_fits": "High vegetable volume with bioavailable nutrients."},
        {"name": "Methi Egg Curry with Millet Rice", "details": "2 boiled eggs simmered with fresh fenugreek leaves and 1/2 cup millet rice.", "why_it_fits": "Blood-sugar friendly fenugreek paired with protein."},
    ],
}

FALLBACK_MEAL_POOL["non-veg"] = {
    "breakfast": [
        {"name": "Masala Omelette (2 Eggs) with Multigrain Toast & Fruit", "details": "2-egg vegetable omelette with 2 whole-grain toasts and papaya slices.", "why_it_fits": "Complete protein and digestive enzymes to kickstart metabolism."},
        {"name": "Chicken Keema Paratha (Light) with Mint Curd", "details": "1 whole-wheat flatbread stuffed with lean minced chicken and 1/2 cup curd.", "why_it_fits": "High lean protein and complex carbs for sustained morning stamina."},
        {"name": "Boiled Eggs & Smoked Chicken/Grilled Chicken Salad Toast", "details": "2 boiled eggs and 50g shredded grilled chicken on multigrain toast.", "why_it_fits": "Over 25g of lean morning protein."},
        {"name": "Idli with Chicken/Mutton Bone Broth Sambar or Egg Roast", "details": "2 steamed idlis with protein-rich stew and 1 boiled egg.", "why_it_fits": "Easy-to-digest fermented grains with high-protein accompaniment."},
        {"name": "Scrambled Eggs with Sautéed Spinach & Mushrooms", "details": "2 eggs scrambled with garlic mushrooms, baby spinach, and 1 toast.", "why_it_fits": "Rich in vitamin D, B12, iron, and choline."},
        {"name": "Oats Porridge with Almonds & 2 Side Boiled Eggs", "details": "1 bowl rolled oats cooked in milk alongside 2 hard-boiled eggs.", "why_it_fits": "Combines heart-healthy beta-glucan fiber with complete protein."},
        {"name": "Moong Dal Chilla with Spiced Chicken Tikka Filling", "details": "2 green gram crepes filled with 60g diced grilled chicken breast.", "why_it_fits": "Low-glycemic lentil wrap with lean poultry protein."},
        {"name": "Poached Eggs & Herb Grilled Chicken Breast Medallions", "details": "2 poached eggs, 60g herb chicken, and sliced tomatoes.", "why_it_fits": "High-satiety, low-carb morning plate."},
        {"name": "Ragi Dosa with Egg Bhurji & Coconut Chutney", "details": "1 crispy finger-millet dosa served with 2-egg spiced bhurji.", "why_it_fits": "Calcium-rich millet paired with complete protein."},
        {"name": "Shakshuka with Lean Chicken Sausage / Mince", "details": "2 eggs poached in spiced tomato-bell pepper sauce with lean chicken.", "why_it_fits": "Antioxidant-rich lycopene and high protein."},
    ],
    "lunch": [
        {"name": "Grilled Chicken Tikka Breast with Brown Rice & Dal", "details": "150g tandoori/grilled chicken breast, 1 cup brown rice, 1/2 cup dal, and salad.", "why_it_fits": "High lean protein (~35g) with slow-release complex carbohydrates."},
        {"name": "Home-Style Fish Curry (Rohu/Surmai/Salmon) with Parboiled Rice", "details": "150g fish simmered in turmeric-tamarind gravy with 1 cup rice and beans thoran.", "why_it_fits": "Rich in anti-inflammatory omega-3 fatty acids and lean protein."},
        {"name": "Palak Chicken (Spinach Chicken) with 2 Whole-Wheat Rotis", "details": "150g chicken breast cooked in iron-rich spinach puree with 2 phulkas.", "why_it_fits": "Combines heme iron, vitamin C, and leafy greens."},
        {"name": "Chicken & Quinoa Power Bowl with Cucumber Raita", "details": "120g herb-grilled chicken, 1 cup quinoa, roasted bell peppers, and yogurt dip.", "why_it_fits": "Balanced macro bowl that prevents afternoon fatigue."},
        {"name": "Egg & Chicken Keema Matar with 2 Multigrain Rotis", "details": "1 cup lean minced chicken and green peas curry topped with 1 boiled egg.", "why_it_fits": "High protein and zinc for immunity and muscle maintenance."},
        {"name": "Grilled Fish Fillet with Millet Pilaf & Sautéed Greens", "details": "150g lemon-pepper fish with 1 cup foxtail millet and garlic spinach.", "why_it_fits": "Light, heart-healthy midday meal with gluten-free millet."},
        {"name": "Dahi Chicken (Yogurt-Marinated Curry) with Jeera Rice & Salad", "details": "150g chicken cooked in spiced yogurt gravy with cumin rice and kachumber.", "why_it_fits": "Tender probiotic-marinated poultry without heavy cream."},
        {"name": "South Indian Pepper Chicken with Red Rice & Rasam", "details": "120g black-pepper chicken stir-fry with 1 cup red rice and tomato rasam.", "why_it_fits": "Metabolism-supporting piperine and wholesome unpolished rice."},
        {"name": "Prawn / Fish Masala with 2 Jowar Bhakris & Solkadhi", "details": "120g spiced seafood with sorghum flatbreads and digestive kokum drink.", "why_it_fits": "High selenium, iodine, and lean marine protein."},
        {"name": "Chicken Kathi Roll in Whole-Wheat Roti with Mint Chutney", "details": "2 whole-wheat wraps with grilled chicken strips, egg wash, onions, and lime.", "why_it_fits": "Balanced, high-protein portable lunch."},
    ],
    "snacks": [
        {"name": "Grilled Chicken Tikka Skewers (4 Pieces) with Mint Dip", "details": "100g yogurt-and-spice marinated grilled chicken cubes with pudina chutney.", "why_it_fits": "Lean protein boost that keeps evening hunger in check."},
        {"name": "2 Boiled Eggs with Black Pepper & Roasted Cumin", "details": "2 hard-boiled eggs halved with a pinch of rock salt and jeera.", "why_it_fits": "Quick 12g complete protein with essential vitamins."},
        {"name": "Clear Chicken & Sweet Corn Soup", "details": "1 warm bowl shredded chicken breast and corn broth with spring onions.", "why_it_fits": "Hydrating, low-calorie, high-satiety afternoon bridge."},
        {"name": "Shredded Chicken & Cucumber Lettuce Cups", "details": "80g boiled/grilled chicken tossed with hung curd, pepper, and crunchy cucumber.", "why_it_fits": "Ultra-lean protein with refreshing hydration."},
        {"name": "Roasted Makhana & Almonds with Masala Chaas", "details": "1 cup roasted fox nuts, 6 almonds, and 1 glass spiced buttermilk.", "why_it_fits": "Probiotics and minerals for steady afternoon energy."},
        {"name": "Pan-Seared Fish / Chicken Bites with Lemon-Garlic", "details": "80g bite-sized fish or chicken breast seared with curry leaves and lemon.", "why_it_fits": "High protein with zero deep-frying."},
        {"name": "Egg White & Vegetable Omelette Roll-Up", "details": "3 egg whites cooked thin with spinach and rolled up.", "why_it_fits": "Pure albumin protein with negligible fat."},
        {"name": "Greek Yogurt / Hung Curd with Walnuts & Berries", "details": "1/2 cup thick curd topped with 4 walnut halves and seasonal fruit.", "why_it_fits": "Gut-friendly probiotics and omega-3 fats."},
        {"name": "Chicken Salad Stuffed Whole-Wheat Pita Pocket", "details": "1 small whole-wheat pocket with 60g diced chicken, celery, and curd dressing.", "why_it_fits": "Balanced pre-workout carb and protein pairing."},
        {"name": "Roasted Chana & 1 Boiled Egg", "details": "1/4 cup crunchy roasted Bengal gram alongside 1 boiled egg.", "why_it_fits": "Combines plant fiber with high-biological-value egg protein."},
    ],
    "dinner": [
        {"name": "Herb-Grilled Chicken Breast with Steamed Broccoli & Quinoa", "details": "140g grilled chicken breast, 1 cup steamed broccoli-carrots, and 1/2 cup quinoa.", "why_it_fits": "Lean overnight muscle recovery with low evening glycemic load."},
        {"name": "Baked/Pan-Grilled Fish Fillet with Garlic Spinach & Lentil Soup", "details": "150g fish fillet with sautéed palak and 1 small bowl clear masoor dal.", "why_it_fits": "Easy-to-digest marine protein and omega-3s support restful sleep."},
        {"name": "Chicken Clear Vegetable Stew with 1 Appam / Multigrain Roti", "details": "1 bowl light ginger-pepper chicken stew with carrots, beans, and 1 roti.", "why_it_fits": "Soothing, nutrient-rich broth that is light on the stomach."},
        {"name": "Chicken Dal Khichdi with Cucumber Raita", "details": "1 comforting bowl moong dal and rice khichdi cooked with 100g shredded chicken.", "why_it_fits": "One-pot high-protein recovery meal."},
        {"name": "2-Egg Omelette & Grilled Chicken Warm Salad Bowl", "details": "100g grilled chicken and 1-egg omelette over mixed greens, tomatoes, and seeds.", "why_it_fits": "High-protein, low-carbohydrate evening plate."},
        {"name": "Methi Chicken (Low-Oil) with 1 Jowar Roti & Salad", "details": "130g chicken cooked with fresh fenugreek leaves and 1 sorghum flatbread.", "why_it_fits": "Fiber-rich fenugreek greens paired with lean poultry."},
        {"name": "Fish Tikka (Grilled) with Mint Chutney & Sautéed Beans", "details": "140g grilled fish tikka served with 1.5 cups garlic-sautéed green beans.", "why_it_fits": "High protein and micronutrients with minimal evening carbs."},
        {"name": "Lean Chicken Keema with Lauki (Bottle Gourd) & 1 Phulka", "details": "120g chicken mince simmered with diced bottle gourd and 1 whole-wheat roti.", "why_it_fits": "Adding bottle gourd keeps the keema light, hydrating, and fiber-rich."},
        {"name": "Egg & Shrimp/Chicken Stir-Fry with Bell Peppers & Brown Rice", "details": "120g lean protein stir-fried with tri-colour capsicum and 1/2 cup brown rice.", "why_it_fits": "Vitamin-C rich bell peppers and lean protein."},
        {"name": "Warm Lemon-Coriander Chicken Soup with Tofu & Greens", "details": "1 large bowl shredded chicken, bok choy/spinach, and mushrooms in lemon broth.", "why_it_fits": "Light, anti-inflammatory evening meal."},
    ],
}


MEAL_PLAN_SYSTEM_PROMPT = (
    "You are NutriGuide, a thoughtful meal-planning assistant. Create a practical, "
    "varied meal plan that follows the user's selected duration (daily, weekly, or monthly), "
    "dietary category (veg, non-veg, vegan, or egg), health preferences, and request. "
    "Do not diagnose, promise treatment, or describe foods as curing a condition. "
    "For blood-sugar-conscious plans, favor balanced meals with fiber, protein, and "
    "minimally processed carbohydrates; do not make medical or glucose-control guarantees. "
    "For weight goals, avoid extreme restriction or unsafe bulking advice. Respect stated "
    "allergies and dietary restrictions, and never include a restricted ingredient. "
    "Use accessible ingredients and provide realistic serving guidance. Do not invent "
    "precise calorie or nutrient counts. Include distinct options in each "
    "meal section: breakfast, lunch, snacks, and dinner. Each option must have a concise "
    "name, practical serving/preparation details, and a specific explanation of why it "
    "fits the request. The summary should briefly explain the overall approach. This is "
    "general food-planning information, not a substitute for individualized medical advice. "
    "Respond only with a valid JSON object matching this schema:\n"
)


def _build_duration_schema_json(duration: str, is_local_backend: bool = False) -> str:
    """Build compact JSON schema with minItems tailored to backend speed and duration."""
    schema_dict = copy.deepcopy(MealPlanResponseSchema.model_json_schema())
    min_items = 1 if is_local_backend else DURATION_MIN_OPTIONS.get(duration, 3)
    defs = schema_dict.get("$defs") or schema_dict.get("definitions") or {}
    section_def = defs.get("MealPlanSectionSchema")
    if isinstance(section_def, dict):
        props = section_def.get("properties") or {}
        if isinstance(props.get("options"), dict):
            props["options"]["minItems"] = min_items
            if is_local_backend:
                props["options"]["maxItems"] = 1
    return json.dumps(schema_dict, ensure_ascii=False, separators=(",", ":"))


def _ensure_minimum_section_options(
    meal_plan: dict[str, Any],
    duration: str,
    diet_type: str,
) -> dict[str, Any]:
    """
    Guarantee that each meal section has at least:
    - 3 options for daily plans
    - 5 options for weekly plans
    - 10 options for monthly plans
    If the LLM returned fewer options in any section, top up from the diet-matched pool.
    """
    min_required = DURATION_MIN_OPTIONS.get(duration, 3)

    pool_key = diet_type if diet_type in FALLBACK_MEAL_POOL else "veg"
    diet_pool = FALLBACK_MEAL_POOL[pool_key]

    weekly_prefixes = [
        "Day 1 (Mon)",
        "Day 2 (Tue)",
        "Day 3 (Wed)",
        "Day 4 (Thu)",
        "Day 5 (Fri)",
        "Day 6 (Sat)",
        "Day 7 (Sun)",
    ]
    monthly_prefixes = [
        "Days 1–3",
        "Days 4–6",
        "Days 7–9",
        "Days 10–12",
        "Days 13–15",
        "Days 16–18",
        "Days 19–21",
        "Days 22–24",
        "Days 25–27",
        "Days 28–30",
    ]
    prefixes = (
        weekly_prefixes
        if duration == "weekly"
        else (monthly_prefixes if duration == "monthly" else ["Option 1", "Option 2", "Option 3"])
    )

    result = copy.deepcopy(meal_plan)
    for section_key in ("breakfast", "lunch", "snacks", "dinner"):
        section = result.get(section_key)
        if not isinstance(section, dict):
            section = {"options": []}
            result[section_key] = section
        raw_options = list(section.get("options") or [])
        options: list[dict[str, Any]] = []
        existing_names: set[str] = set()

        for i, opt in enumerate(raw_options):
            if not isinstance(opt, dict):
                continue
            raw_name = str(opt.get("name", "")).strip()
            if duration in {"weekly", "monthly"} and i < len(prefixes):
                expected_prefix = prefixes[i]
                if not any(
                    raw_name.lower().startswith(tok)
                    for tok in ("day ", "days ", "week ", "mon", "tue", "wed", "thu", "fri", "sat", "sun", "option ")
                ):
                    raw_name = f"{expected_prefix}: {raw_name}"
            normalized_opt = dict(opt, name=raw_name)
            options.append(normalized_opt)
            existing_names.add(raw_name.lower())
            if ":" in raw_name:
                existing_names.add(raw_name.split(":", 1)[1].strip().lower())

        candidates = diet_pool.get(section_key, [])
        idx = 0
        while len(options) < min_required and idx < len(candidates):
            cand = candidates[idx]
            idx += 1
            slot_num = len(options)
            prefix = prefixes[slot_num] if slot_num < len(prefixes) else f"Option {slot_num + 1}"
            candidate_name = (
                f"{prefix}: {cand['name']}"
                if duration in {"weekly", "monthly"}
                else cand["name"]
            )
            if cand["name"].lower() in existing_names or candidate_name.lower() in existing_names:
                continue
            options.append({
                "name": candidate_name,
                "details": cand["details"],
                "why_it_fits": cand["why_it_fits"],
            })
            existing_names.add(candidate_name.lower())
            existing_names.add(cand["name"].lower())

        section["options"] = options

    return result


def generate_meal_plan_node(state: MealPlanState) -> dict[str, Any]:
    duration = (state.get("duration") or "daily").strip().lower()
    diet_type = (state.get("diet_type") or "").strip().lower()
    client = LlamaCppClient(response_schema=MealPlanResponseSchema)
    is_local = getattr(client, "backend", "local") == "local"
    schema_json = _build_duration_schema_json(duration, is_local_backend=is_local)
    if is_local:
        duration_guide = (
            f"Create a {duration} ({'7-day Weekly' if duration == 'weekly' else ('4-week Monthly' if duration == 'monthly' else '1-day Daily')}) "
            "meal plan foundation. Provide EXACTLY 1 ultra-concise signature option in each section "
            "(breakfast, lunch, snacks, dinner) with 'details' and 'why_it_fits' under 12 words each."
        )
    else:
        duration_guide = DURATION_INSTRUCTIONS.get(duration, DURATION_INSTRUCTIONS["daily"])
    diet_guide = DIET_TYPE_INSTRUCTIONS.get(diet_type, "Follow the user's stated dietary preferences.")

    prompt_lines = [
        f"Plan Duration: {duration.upper()} — {duration_guide}",
        f"Dietary Mode: {diet_type.upper() if diet_type else 'General'} — {diet_guide}",
        "Selected meal-planning preferences: "
        + (", ".join(state.get("preferences") or []) or "No predefined preferences"),
        "Additional user request: " + (state.get("custom_request") or "None"),
    ]
    if state.get("transcription"):
        prompt_lines.append(f"Spoken voice note transcription: {state['transcription']}")
    if state.get("user_profile_context"):
        prompt_lines.append(f"User profile & allergy context: {state['user_profile_context']}")
    if state.get("image_base64"):
        prompt_lines.append(
            "An image is attached. Inspect the ingredients, foods, or dietary notes visible in "
            "the image and incorporate them thoughtfully into the meal plan."
        )

    prompt = "\n".join(prompt_lines)
    generate_kwargs: dict[str, Any] = {
        "system_prompt": MEAL_PLAN_SYSTEM_PROMPT + schema_json,
        "user_prompt": prompt,
        "response_schema": MealPlanResponseSchema,
    }
    if state.get("image_base64"):
        generate_kwargs["image_base64"] = state["image_base64"]
        generate_kwargs["image_mime_type"] = state.get("image_mime_type") or "image/jpeg"

    meal_plan = client.generate_structured_response(**generate_kwargs)
    meal_plan = _ensure_minimum_section_options(meal_plan, duration=duration, diet_type=diet_type)
    return {"meal_plan": meal_plan}


def build_meal_plan_graph():
    builder = StateGraph(MealPlanState)
    builder.add_node("generate_meal_plan", generate_meal_plan_node)
    builder.add_edge(START, "generate_meal_plan")
    builder.add_edge("generate_meal_plan", END)
    return builder.compile()


meal_plan_graph = build_meal_plan_graph()


def run_meal_plan_workflow(
    preferences: list[str],
    custom_request: str = "",
    *,
    duration: str = "daily",
    diet_type: str = "",
    image_base64: Optional[str] = None,
    image_mime_type: Optional[str] = None,
    transcription: Optional[str] = None,
    user_profile_context: Optional[str] = None,
) -> dict[str, Any]:
    result = meal_plan_graph.invoke(
        {
            "preferences": preferences,
            "custom_request": custom_request,
            "duration": duration,
            "diet_type": diet_type,
            "image_base64": image_base64,
            "image_mime_type": image_mime_type,
            "transcription": transcription,
            "user_profile_context": user_profile_context,
        }
    )
    return result["meal_plan"]
