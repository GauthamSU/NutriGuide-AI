import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from nutrition.schemas import NutrientAnalysisDataSchema


SAMPLE_ANALYSIS_DICT = {
    "meal_title": "Boiled Eggs and Avocado Toast",
    "recognized_input_summary": "2 large boiled eggs and 1 slice of whole wheat avocado toast",
    "items": [
        {
            "food_name": "Boiled Eggs",
            "serving_size_description": "2 large eggs (100g)",
            "estimated_weight_grams": 100.0,
            "confidence": 0.96,
            "glycemic_index_category": "Low",
            "macronutrients": {
                "calories_kcal": 155.0,
                "protein_g": 12.6,
                "carbohydrates_g": 1.1,
                "dietary_fiber_g": 0.0,
                "total_sugars_g": 1.1,
                "added_sugars_g": 0.0,
                "total_fat_g": 10.6,
                "saturated_fat_g": 3.3,
                "unsaturated_fat_g": 6.2,
                "trans_fat_g": 0.0,
                "cholesterol_mg": 373.0,
                "sodium_mg": 124.0,
                "water_g": 75.0,
            },
            "micronutrients": {
                "vitamins": [
                    {"name": "Vitamin B12", "amount": 1.1, "unit": "mcg", "daily_value_percent": 46.0}
                ],
                "minerals": [
                    {"name": "Selenium", "amount": 30.8, "unit": "mcg", "daily_value_percent": 56.0}
                ],
            },
        }
    ],
    "total_macronutrients": {
        "calories_kcal": 155.0,
        "protein_g": 12.6,
        "carbohydrates_g": 1.1,
        "dietary_fiber_g": 0.0,
        "total_sugars_g": 1.1,
        "added_sugars_g": 0.0,
        "total_fat_g": 10.6,
        "saturated_fat_g": 3.3,
        "unsaturated_fat_g": 6.2,
        "trans_fat_g": 0.0,
        "cholesterol_mg": 373.0,
        "sodium_mg": 124.0,
        "water_g": 75.0,
    },
    "dietary_tags": ["High-Protein", "Vegetarian"],
    "health_insights": ["Great source of complete protein and choline."],
}


class NutritionAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from nutrition.models import (
            FattyAcidNutrient,
            Food,
            FoodGroup,
            FoodVernacularName,
            MineralNutrient,
            ProximateNutrient,
            VitaminNutrient,
        )

        grp_a, _ = FoodGroup.objects.get_or_create(code="A", defaults={"name": "Cereals and Millets"})
        grp_b, _ = FoodGroup.objects.get_or_create(code="B", defaults={"name": "Grain Legumes"})
        grp_c, _ = FoodGroup.objects.get_or_create(code="C", defaults={"name": "Green Leafy Vegetables"})
        grp_f, _ = FoodGroup.objects.get_or_create(code="F", defaults={"name": "Roots and Tubers"})
        grp_g, _ = FoodGroup.objects.get_or_create(code="G", defaults={"name": "Condiments and Spices"})
        grp_t, _ = FoodGroup.objects.get_or_create(code="T", defaults={"name": "Edible Oils and Fats"})

        # Rice A014
        f_rice = Food.objects.create(food_code="A014", group=grp_a, name="Rice, parboiled, milled")
        ProximateNutrient.objects.create(
            food=f_rice, energy_kcal=351.6, protein_g=7.81, carbohydrates_g=77.16, total_fat_g=0.55, total_fiber_g=3.74
        )
        FattyAcidNutrient.objects.create(
            food=f_rice, total_sfa_mg=150.0, total_mufa_mg=180.0, total_pufa_mg=190.0, is_cooking_oil_percent=False
        )
        MineralNutrient.objects.create(food=f_rice, iron_mg=1.19, calcium_mg=10.0, sodium_mg=5.0)
        VitaminNutrient.objects.create(food=f_rice, thiamine_b1_mg=0.17)

        # Atta A019
        f_atta = Food.objects.create(food_code="A019", group=grp_a, name="Wheat flour, atta")
        ProximateNutrient.objects.create(
            food=f_atta, energy_kcal=320.0, protein_g=10.5, carbohydrates_g=65.0, total_fat_g=1.5, total_fiber_g=11.0
        )

        # Toor dal B021
        f_toor = Food.objects.create(food_code="B021", group=grp_b, name="Red gram, dal")
        ProximateNutrient.objects.create(
            food=f_toor, energy_kcal=330.0, protein_g=22.3, carbohydrates_g=57.0, total_fat_g=1.7, total_fiber_g=9.0
        )

        # Moong dal B010
        f_moong = Food.objects.create(food_code="B010", group=grp_b, name="Green gram, dal")
        ProximateNutrient.objects.create(
            food=f_moong, energy_kcal=325.0, protein_g=24.0, carbohydrates_g=56.0, total_fat_g=1.2, total_fiber_g=8.2
        )

        # Ghee T013
        f_ghee = Food.objects.create(food_code="T013", group=grp_t, name="Ghee")
        ProximateNutrient.objects.create(
            food=f_ghee, energy_kcal=900.0, protein_g=0.0, carbohydrates_g=0.0, total_fat_g=100.0, total_fiber_g=0.0
        )
        FattyAcidNutrient.objects.create(
            food=f_ghee, total_sfa_mg=65.0, total_mufa_mg=25.0, total_pufa_mg=3.0, is_cooking_oil_percent=True
        )

        # Sunflower oil T012
        f_oil = Food.objects.create(food_code="T012", group=grp_t, name="Sunflower oil")
        ProximateNutrient.objects.create(
            food=f_oil, energy_kcal=900.0, protein_g=0.0, carbohydrates_g=0.0, total_fat_g=100.0, total_fiber_g=0.0
        )

        # Lentil dal B013
        f_lentil = Food.objects.create(food_code="B013", group=grp_b, name="Lentil dal")
        ProximateNutrient.objects.create(
            food=f_lentil, energy_kcal=330.0, protein_g=25.0, carbohydrates_g=57.0, total_fat_g=1.0, total_fiber_g=9.0
        )

        # Spinach C033
        f_palak = Food.objects.create(food_code="C033", group=grp_c, name="Spinach")
        ProximateNutrient.objects.create(
            food=f_palak, energy_kcal=26.0, protein_g=2.0, carbohydrates_g=3.0, total_fat_g=0.7, total_fiber_g=2.5
        )
        FoodVernacularName.objects.create(food=f_palak, language="Hindi", name="Palak")

        # Urad dal B003
        f_urad = Food.objects.create(food_code="B003", group=grp_b, name="Black gram, dal")
        ProximateNutrient.objects.create(
            food=f_urad, energy_kcal=341.0, protein_g=24.0, carbohydrates_g=59.6, total_fat_g=1.4, total_fiber_g=3.5
        )

        # Potato F006
        f_potato = Food.objects.create(food_code="F006", group=grp_f, name="Potato, brown skin, big")
        ProximateNutrient.objects.create(
            food=f_potato, energy_kcal=97.0, protein_g=1.6, carbohydrates_g=22.7, total_fat_g=0.1, total_fiber_g=1.7
        )

        # Onion G017
        f_onion = Food.objects.create(food_code="G017", group=grp_g, name="Onion, big")
        ProximateNutrient.objects.create(
            food=f_onion, energy_kcal=50.0, protein_g=1.2, carbohydrates_g=11.1, total_fat_g=0.1, total_fiber_g=2.3
        )

        # Turmeric powder G033
        f_turmeric = Food.objects.create(food_code="G033", group=grp_g, name="Turmeric powder")
        ProximateNutrient.objects.create(
            food=f_turmeric, energy_kcal=349.0, protein_g=7.8, carbohydrates_g=64.9, total_fat_g=9.9, total_fiber_g=21.1
        )

        # Chillies, red G022
        f_chilli = Food.objects.create(food_code="G022", group=grp_g, name="Chillies, red")
        ProximateNutrient.objects.create(
            food=f_chilli, energy_kcal=246.0, protein_g=15.0, carbohydrates_g=31.6, total_fat_g=6.2, total_fiber_g=30.2
        )

    def setUp(self):
        self.client = Client()

    def test_health_endpoint(self):
        response = self.client.get("/api/nutrition/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["api_status"], "ok")
        self.assertTrue(data["model_file_exists"])
        self.assertTrue(data["mmproj_file_exists"])
        self.assertGreaterEqual(data["database_food_count"], 5)

    @patch("nutrition.services.llama_client.LlamaCppClient.identify_dish_and_ingredients")
    def test_analyze_text_endpoint(self, mock_identify):
        mock_identify.return_value = SAMPLE_ANALYSIS_DICT
        response = self.client.post(
            "/api/nutrition/analyze/text",
            data={"text": "2 boiled eggs"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["input_modalities"], ["text"])
        self.assertEqual(body["analysis"]["meal_title"], "Boiled Eggs and Avocado Toast")

    def test_analyze_text_response_is_saved_for_debugging(self):
        final_state = {
            "request_id": "debug-request-1",
            "status": "completed",
            "input_modalities": ["text"],
            "nutrient_analysis": SAMPLE_ANALYSIS_DICT,
            "dietary_warnings": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_path = Path(temp_dir) / "api_response_debug.json"
            with override_settings(API_RESPONSE_DEBUG_FILE=debug_path):
                with patch("nutrition.api.run_nutrition_workflow", return_value=final_state):
                    response = self.client.post(
                        "/api/nutrition/analyze/text",
                        data={"text": "2 boiled eggs"},
                        content_type="application/json",
                    )

            saved_record = json.loads(debug_path.read_text(encoding="utf-8"))

        self.assertEqual(saved_record["status_code"], response.status_code)
        self.assertEqual(saved_record["response"], response.json())
        self.assertEqual(saved_record["response"]["request_id"], "debug-request-1")

    @patch("nutrition.services.llama_client.LlamaCppClient.identify_dish_and_ingredients")
    def test_analyze_multimodal_endpoint_with_image_and_voice(self, mock_identify):
        mock_identify.return_value = SAMPLE_ANALYSIS_DICT
        fake_image = SimpleUploadedFile("meal.jpg", b"\xff\xd8\xff\xe0fakejpeg", content_type="image/jpeg")
        fake_voice = SimpleUploadedFile("note.wav", b"RIFFfakewav", content_type="audio/wav")

        response = self.client.post(
            "/api/nutrition/analyze",
            data={
                "text": "My breakfast",
                "image": fake_image,
                "voice": fake_voice,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["input_modalities"], ["text", "image", "voice"])

    def test_analyze_multimodal_rejects_empty_input(self):
        response = self.client.post("/api/nutrition/analyze", data={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("At least one input modality", response.json()["detail"])

    def test_pydantic_schema_system_prompt_generation(self):
        import json
        from nutrition.schemas import LLMDishIngredientsResponseSchema, LLMNutrientResponseSchema
        from nutrition.services.llama_client import LlamaCppClient, build_system_prompt

        # Test Pydantic schema serialization
        compact_json = LLMDishIngredientsResponseSchema.to_compact_json()
        parsed = json.loads(compact_json)
        self.assertIn("dish_name", parsed)
        self.assertIn("ingredients", parsed)
        self.assertIn("dietary_tags", parsed)
        self.assertIn("health_insights", parsed)

        # Test system prompt builds with the serialized JSON and strict DB rules
        prompt = build_system_prompt(LLMDishIngredientsResponseSchema)
        self.assertIn(compact_json, prompt)
        self.assertIn("identify ALL the different ingredients", prompt)
        self.assertIn("DO NOT generate, estimate, or hallucinate any nutrient numbers", prompt)
        self.assertIn("All nutritional data must come strictly from the reference database", prompt)

        # Test client initializes with custom Pydantic schema
        client = LlamaCppClient(response_schema=LLMNutrientResponseSchema())
        self.assertIn(compact_json, client.system_prompt)

    def test_db_nutrition_service_find_food(self):
        from nutrition.services.db_nutrition_service import find_food_in_db

        # Alias lookups
        toor = find_food_in_db("toor dal")
        self.assertIsNotNone(toor)
        self.assertEqual(toor.food_code, "B021")

        atta = find_food_in_db("atta")
        self.assertIsNotNone(atta)
        self.assertEqual(atta.food_code, "A019")

        ghee = find_food_in_db("ghee")
        self.assertIsNotNone(ghee)
        self.assertEqual(ghee.food_code, "T013")

        # Vernacular lookups
        palak = find_food_in_db("palak")
        self.assertIsNotNone(palak)
        self.assertEqual(palak.name, "Spinach")

        # Unknown ingredient
        unknown = find_food_in_db("unobtainium_berry_extract_xyz")
        self.assertIsNone(unknown)

    def test_db_nutrition_service_resolution_and_missing_flags(self):
        from nutrition.services.db_nutrition_service import resolve_dish_nutrition_from_db

        dish_input = {
            "dish_name": "Moong Dal Khichdi",
            "recognized_input_summary": "Khichdi with moong dal and ghee",
            "ingredients": [
                {
                    "ingredient_name": "Rice",
                    "serving_size_description": "1/2 cup raw",
                    "estimated_weight_grams": 100.0,
                },
                {
                    "ingredient_name": "Moong dal",
                    "serving_size_description": "1/4 cup",
                    "estimated_weight_grams": 50.0,
                },
                {
                    "ingredient_name": "Ghee",
                    "serving_size_description": "1 tsp",
                    "estimated_weight_grams": 10.0,
                },
                {
                    "ingredient_name": "Mysterious Outer-space Herb",
                    "serving_size_description": "1 pinch",
                    "estimated_weight_grams": 2.0,
                },
            ],
            "dietary_tags": ["Vegetarian", "Ayurvedic"],
        }

        result = resolve_dish_nutrition_from_db(dish_input)

        self.assertEqual(result["meal_title"], "Moong Dal Khichdi")
        self.assertEqual(len(result["items"]), 4)

        # Check matched items
        rice_item = next(i for i in result["items"] if i["food_name"] == "Rice")
        self.assertTrue(rice_item["found_in_database"])
        self.assertEqual(rice_item["database_food_code"], "A014")
        self.assertGreater(rice_item["macronutrients"]["calories_kcal"], 300.0)

        # Check missing item
        missing_item = next(i for i in result["items"] if i["food_name"] == "Mysterious Outer-space Herb")
        self.assertFalse(missing_item["found_in_database"])
        self.assertIsNone(missing_item["database_food_code"])
        self.assertEqual(missing_item["macronutrients"]["calories_kcal"], 0.0)

        # Check missing ingredients array and notification
        self.assertIn("Mysterious Outer-space Herb", result["missing_ingredients"])
        self.assertTrue(
            any("Mysterious Outer-space Herb" in note for note in result["health_insights"]),
            "Should alert user to manually load missing ingredients"
        )

        # Total calories should be positive and derived from database items
        self.assertGreater(result["total_macronutrients"]["calories_kcal"], 500.0)

    @patch("nutrition.services.llama_client.LlamaCppClient.identify_dish_and_ingredients")
    def test_workflow_end_to_end_with_database_nutrients(self, mock_identify):
        from nutrition.graph.workflow import run_nutrition_workflow

        mock_identify.return_value = {
            "dish_name": "Dal Tadka with Rice",
            "recognized_input_summary": "Toor dal tadka with steamed rice",
            "ingredients": [
                {"ingredient_name": "Rice", "estimated_weight_grams": 100.0, "serving_size_description": "1 bowl"},
                {"ingredient_name": "Toor dal", "estimated_weight_grams": 50.0, "serving_size_description": "1/2 cup"},
                {"ingredient_name": "Ghee", "estimated_weight_grams": 10.0, "serving_size_description": "1 tbsp"},
                {"ingredient_name": "Special Home Spice Mix", "estimated_weight_grams": 5.0, "serving_size_description": "1 tsp"},
            ],
            "dietary_tags": ["High-Protein", "Vegetarian"],
            "health_insights": ["Wholesome traditional meal."],
        }

        final_state = run_nutrition_workflow(input_text="My lunch: dal tadka and rice")
        self.assertEqual(final_state["status"], "completed")
        self.assertEqual(final_state["dish_name"], "Dal Tadka with Rice")
        self.assertEqual(len(final_state["identified_ingredients"]), 4)
        self.assertEqual(len(final_state["detected_food_items"]), 4)
        self.assertIn("Special Home Spice Mix", final_state["missing_ingredients"])

        analysis = final_state["nutrient_analysis"]
        self.assertEqual(analysis["meal_title"], "Dal Tadka with Rice")
        self.assertEqual(len(analysis["items"]), 4)
        self.assertIn("Special Home Spice Mix", analysis["missing_ingredients"])
        self.assertTrue(any("Special Home Spice Mix" in w for w in final_state.get("dietary_warnings", [])))

    def test_food_lookup_cache_avoids_repeated_database_fetches(self):
        from nutrition.services.db_nutrition_service import (
            _FOOD_LOOKUP_CACHE,
            clear_food_lookup_cache,
            find_food_in_db,
        )
        clear_food_lookup_cache()

        # First call should hit DB and populate cache
        food1 = find_food_in_db("Rice")
        self.assertIsNotNone(food1)
        self.assertIn("rice", _FOOD_LOOKUP_CACHE)
        self.assertEqual(_FOOD_LOOKUP_CACHE["rice"].food_code, "A014")

        # Second call should return from cache without DB query
        with self.assertNumQueries(0):
            food2 = find_food_in_db("Rice")
            self.assertEqual(food2.food_code, "A014")

        # Non-existent item should cache None and not hit DB again
        unmapped1 = find_food_in_db("Unobtainium Super Spice")
        self.assertIsNone(unmapped1)
        self.assertIn("unobtainium super spice", _FOOD_LOOKUP_CACHE)

        with self.assertNumQueries(0):
            unmapped2 = find_food_in_db("Unobtainium Super Spice")
            self.assertIsNone(unmapped2)

    @patch("nutrition.services.llama_client.LlamaCppClient.decompose_ingredients")
    @patch("nutrition.services.llama_client.LlamaCppClient.identify_dish_and_ingredients")
    def test_masala_dosa_rice_batter_decomposition_loop(self, mock_identify, mock_decompose):
        from nutrition.graph.workflow import run_nutrition_workflow

        # Initial dish identification: contains 'Rice batter' which is not in DB directly
        mock_identify.return_value = {
            "dish_name": "Masala Dosa",
            "recognized_input_summary": "Crispy masala dosa with spiced potato filling",
            "ingredients": [
                {"ingredient_name": "Rice batter", "estimated_weight_grams": 100.0, "serving_size_description": "1 cup batter"},
                {"ingredient_name": "Potato", "estimated_weight_grams": 100.0, "serving_size_description": "1 medium boiled potato"},
                {"ingredient_name": "Onion", "estimated_weight_grams": 40.0, "serving_size_description": "1/2 chopped onion"},
                {"ingredient_name": "Turmeric powder", "estimated_weight_grams": 2.0, "serving_size_description": "1/2 tsp"},
                {"ingredient_name": "Red chilli powder", "estimated_weight_grams": 3.0, "serving_size_description": "1/2 tsp"},
            ],
            "dietary_tags": ["Vegetarian", "South Indian"],
            "health_insights": ["Traditional fermented crepe."],
        }

        # Decomposition AI response: breaks down 'Rice batter' into Rice and Urad dal
        mock_decompose.return_value = {
            "decompositions": [
                {
                    "original_ingredient": "Rice batter",
                    "can_decompose": True,
                    "reasoning": "Fermented dosa batter is made from 3 parts rice and 1 part urad dal.",
                    "sub_ingredients": [
                        {"ingredient_name": "Rice", "estimated_weight_grams": 75.0, "serving_size_description": "75g soaked rice"},
                        {"ingredient_name": "Urad dal", "estimated_weight_grams": 25.0, "serving_size_description": "25g black gram"},
                    ],
                }
            ]
        }

        final_state = run_nutrition_workflow(input_text="Masala Dosa")

        self.assertEqual(final_state["status"], "completed")
        self.assertEqual(final_state["dish_name"], "Masala Dosa")

        # Verify decompose node was called for Rice batter
        mock_decompose.assert_called_once()
        decomp_args = mock_decompose.call_args[0][0]
        self.assertTrue(any(i.get("ingredient_name") == "Rice batter" for i in decomp_args))

        # Check decomposition history
        history = final_state.get("decomposition_history", [])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["original_ingredient"], "Rice batter")
        self.assertEqual(len(history[0]["sub_ingredients"]), 2)

        # Check items in final nutrient analysis:
        # All items (Rice, Urad dal, Potato, Onion, Turmeric, Chilli) should be resolved in DB
        items = final_state["nutrient_analysis"]["items"]
        item_names = [i["food_name"] for i in items]
        self.assertIn("Rice", item_names)
        self.assertIn("Urad dal", item_names)
        self.assertIn("Potato", item_names)
        self.assertIn("Onion", item_names)
        self.assertIn("Turmeric powder", item_names)
        self.assertIn("Red chilli powder", item_names)

        # Every item should have found_in_database == True
        for it in items:
            self.assertTrue(it["found_in_database"], f"Item {it['food_name']} should be resolved in DB")
            self.assertIsNotNone(it["database_food_code"])

        # No missing ingredients remain
        self.assertEqual(final_state["missing_ingredients"], [])
        self.assertEqual(final_state["nutrient_analysis"]["missing_ingredients"], [])

        # Total calories should be positive and derived from database items
        total_cals = final_state["nutrient_analysis"]["total_macronutrients"]["calories_kcal"]
        self.assertGreater(total_cals, 350.0)

        # Decomposition notice should appear in dietary warnings
        warnings = final_state.get("dietary_warnings", [])
        self.assertTrue(any("Rice batter" in w for w in warnings))

    @patch("nutrition.services.llama_client.LlamaCppClient.decompose_ingredients")
    @patch("nutrition.services.llama_client.LlamaCppClient.identify_dish_and_ingredients")
    def test_decomposition_loop_handles_indivisible_item_and_stops_cleanly(self, mock_identify, mock_decompose):
        from nutrition.graph.workflow import run_nutrition_workflow

        mock_identify.return_value = {
            "dish_name": "Wild Berry Salad",
            "ingredients": [
                {"ingredient_name": "Spinach", "estimated_weight_grams": 50.0},
                {"ingredient_name": "Mystic Jungle Berry", "estimated_weight_grams": 30.0},
            ],
        }

        # Model indicates this ingredient cannot be decomposed further
        mock_decompose.return_value = {
            "decompositions": [
                {
                    "original_ingredient": "Mystic Jungle Berry",
                    "can_decompose": False,
                    "reasoning": "Single wild berry that is not divisible into other culinary ingredients.",
                    "sub_ingredients": [],
                }
            ]
        }

        final_state = run_nutrition_workflow(input_text="Wild Berry Salad")
        self.assertEqual(final_state["status"], "completed")
        self.assertIn("Mystic Jungle Berry", final_state["missing_ingredients"])
        self.assertTrue(any("Mystic Jungle Berry" in w for w in final_state.get("dietary_warnings", [])))

    def test_slash_and_parentheses_sanitization(self):
        from nutrition.services.db_nutrition_service import find_food_in_db

        # "Oil/Ghee" contains a slash, should resolve to oil (T012)
        oil_match = find_food_in_db("Oil/Ghee")
        self.assertIsNotNone(oil_match)
        self.assertEqual(oil_match.food_code, "T012")

        # "Lentils (in Sambar)" contains parentheses, should resolve to lentils (B013)
        lentil_match = find_food_in_db("Lentils (in Sambar)")
        self.assertIsNotNone(lentil_match)
        self.assertEqual(lentil_match.food_code, "B013")

    @patch("nutrition.services.llama_client.LlamaCppClient.decompose_ingredients")
    @patch("nutrition.services.llama_client.LlamaCppClient.identify_dish_and_ingredients")
    def test_non_edible_banana_leaf_tableware_ignored(self, mock_identify, mock_decompose):
        from nutrition.graph.workflow import run_nutrition_workflow

        mock_identify.return_value = {
            "dish_name": "Idli Sambar on Banana Leaf",
            "recognized_input_summary": "Two idlis served with sambar on a fresh banana leaf",
            "ingredients": [
                {"ingredient_name": "Rice", "estimated_weight_grams": 80.0},
                {"ingredient_name": "Urad dal", "estimated_weight_grams": 25.0},
                {"ingredient_name": "Banana leaf", "estimated_weight_grams": 50.0, "serving_size_description": "Serving platter"},
            ],
        }

        final_state = run_nutrition_workflow(input_text="Idli on banana leaf")
        self.assertEqual(final_state["status"], "completed")
        # Banana leaf should NOT be in missing ingredients
        self.assertNotIn("Banana leaf", final_state["missing_ingredients"])
        self.assertNotIn("Banana leaf", final_state["nutrient_analysis"]["missing_ingredients"])
        self.assertFalse(any("Banana leaf" in w for w in final_state.get("dietary_warnings", [])))

    def test_ifct_parser_numeric_and_name_helpers(self):
        from nutrition.ingestion.ifct_parser import parse_numeric_token, split_common_and_scientific_name

        # Test single float
        val, sd = parse_numeric_token("14.59")
        self.assertEqual(val, 14.59)
        self.assertIsNone(sd)

        # Test mean ± sd
        val, sd = parse_numeric_token("9.20±0.40")
        self.assertEqual(val, 9.20)
        self.assertEqual(sd, 0.40)

        # Test blanks / hyphens
        val, sd = parse_numeric_token("-")
        self.assertIsNone(val)

        # Test botanical name extraction
        common, sci = split_common_and_scientific_name("Amaranth seed, black (Amaranthus cruentus)")
        self.assertEqual(common, "Amaranth seed, black")
        self.assertEqual(sci, "Amaranthus cruentus")

    def test_ifct_database_models_relational_integrity(self):
        from nutrition.models import Food, FoodGroup, ProximateNutrient

        grp = FoodGroup.objects.create(code="Q", name="Test Category")
        food = Food.objects.create(food_code="Q001", group=grp, name="Test Item", no_of_regions=6)
        prox = ProximateNutrient.objects.create(
            food=food,
            moisture_g=10.0,
            protein_g=12.5,
            total_fat_g=4.0,
            carbohydrates_g=60.0,
            energy_kj=1400.0,
            energy_kcal=334.6,
        )

        fetched = Food.objects.select_related("group", "proximates").get(food_code="Q001")
        self.assertEqual(fetched.group.name, "Test Category")
        self.assertEqual(fetched.proximates.protein_g, 12.5)
        self.assertEqual(fetched.proximates.energy_kcal, 334.6)

    def test_ifct_all_satellite_models_relational_integrity(self):
        from nutrition.models import (
            AminoAcidNutrient,
            BioactiveNutrient,
            CarotenoidNutrient,
            FattyAcidNutrient,
            Food,
            FoodGroup,
            FoodVernacularName,
            MineralNutrient,
            OrganicAcidNutrient,
            PolyphenolNutrient,
            ProximateNutrient,
            SugarNutrient,
            VitaminNutrient,
        )

        grp = FoodGroup.objects.create(code="Z", name="Experimental Superfoods")
        food = Food.objects.create(
            food_code="Z001",
            group=grp,
            name="Ancient Wonder Grain",
            scientific_name="Mirabilis botanica",
            vernacular_names={"Hindi": "Chamatkari Anaj", "Tamil": "Arpudha Dhaniyam"},
        )

        FoodVernacularName.objects.create(food=food, language="Hindi", name="Chamatkari Anaj")
        FoodVernacularName.objects.create(food=food, language="Tamil", name="Arpudha Dhaniyam")

        ProximateNutrient.objects.create(food=food, protein_g=14.0, total_fat_g=5.5, energy_kcal=360.0)
        VitaminNutrient.objects.create(food=food, vitamin_c_mg=25.0, thiamine_b1_mg=0.45)
        CarotenoidNutrient.objects.create(food=food, beta_carotene_mcg=150.0, total_carotenoids_mcg=420.0)
        MineralNutrient.objects.create(food=food, iron_mg=4.2, calcium_mg=110.0, zinc_mg=2.8)
        SugarNutrient.objects.create(food=food, total_starch_g=52.0, total_free_sugars_g=1.2)
        FattyAcidNutrient.objects.create(food=food, total_sfa_mg=950.0, linoleic_c18_2n6_mg=1800.0, total_pufa_mg=2100.0)
        AminoAcidNutrient.objects.create(food=food, leucine_g=8.2, lysine_g=5.1, methionine_g=2.3)
        OrganicAcidNutrient.objects.create(food=food, oxalate_total_mg=35.0, citric_acid_mg=12.0)
        PolyphenolNutrient.objects.create(food=food, total_polyphenols_mg=85.0, ferulic_acid_mg=2.1)
        BioactiveNutrient.objects.create(food=food, phytate_mg=320.0, beta_sitosterol_mg=55.0)

        # Test deep situational load
        fetched = Food.objects.select_related(
            "group", "proximates", "vitamins", "carotenoids", "minerals",
            "sugars", "fatty_acids", "amino_acids", "organic_acids",
            "polyphenols", "bioactives"
        ).get(food_code="Z001")

        self.assertEqual(fetched.group.code, "Z")
        self.assertEqual(fetched.proximates.protein_g, 14.0)
        self.assertEqual(fetched.vitamins.vitamin_c_mg, 25.0)
        self.assertEqual(fetched.carotenoids.beta_carotene_mcg, 150.0)
        self.assertEqual(fetched.minerals.iron_mg, 4.2)
        self.assertEqual(fetched.sugars.total_starch_g, 52.0)
        self.assertEqual(fetched.fatty_acids.total_pufa_mg, 2100.0)
        self.assertEqual(fetched.amino_acids.lysine_g, 5.1)
        self.assertEqual(fetched.organic_acids.oxalate_total_mg, 35.0)
        self.assertEqual(fetched.polyphenols.total_polyphenols_mg, 85.0)
        self.assertEqual(fetched.bioactives.beta_sitosterol_mg, 55.0)

        # Test vernacular relational search
        hi_match = FoodVernacularName.objects.filter(name__icontains="Chamatkari").first()
        self.assertIsNotNone(hi_match)
        self.assertEqual(hi_match.food.food_code, "Z001")

        ta_match = FoodVernacularName.objects.filter(name__icontains="Arpudha").first()
        self.assertIsNotNone(ta_match)
        self.assertEqual(ta_match.language, "Tamil")


class InferenceBackendSwitchingTests(TestCase):
    """Tests for the dual inference backend (local llama-cpp vs Gemini API) switching."""

    def test_default_backend_from_settings(self):
        from django.conf import settings
        self.assertIn(settings.INFERENCE_BACKEND, ("local", "gemini"))

    def test_client_initializes_with_local_backend(self):
        from nutrition.services.llama_client import LlamaCppClient
        client = LlamaCppClient(backend="local")
        self.assertEqual(client.backend, "local")
        self.assertIn("127.0.0.1", client.base_url)
        self.assertIsNotNone(client.client)

    @override_settings(GEMINI_API_KEY="test-api-key-12345")
    def test_client_initializes_with_gemini_backend(self):
        from nutrition.services.llama_client import LlamaCppClient
        client = LlamaCppClient(backend="gemini")
        self.assertEqual(client.backend, "gemini")
        self.assertIn("generativelanguage.googleapis.com", client.base_url)
        self.assertIsNotNone(client.client)

    @override_settings(GEMINI_API_KEY="")
    def test_gemini_backend_raises_without_api_key(self):
        from nutrition.services.llama_client import LlamaCppClient
        with self.assertRaises(ValueError) as ctx:
            LlamaCppClient(backend="gemini")
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))

    def test_local_backend_health_check_structure(self):
        from nutrition.services.llama_client import LlamaCppClient
        client = LlamaCppClient(backend="local")
        health = client.check_health()
        self.assertEqual(health["backend"], "local")
        self.assertIn("reachable", health)
        self.assertIn("status", health)
        self.assertIn("model_name", health)

    @override_settings(GEMINI_API_KEY="test-api-key-12345")
    def test_gemini_backend_health_check_structure(self):
        from nutrition.services.llama_client import LlamaCppClient
        client = LlamaCppClient(backend="gemini")
        health = client.check_health()
        self.assertEqual(health["backend"], "gemini")
        self.assertIn("reachable", health)
        self.assertIn("status", health)
        self.assertIn("model_name", health)

    @override_settings(GEMINI_API_KEY="test-api-key-12345")
    def test_backend_explicit_override_ignores_settings(self):
        from nutrition.services.llama_client import LlamaCppClient
        # Even if settings say 'gemini', explicit backend='local' should work
        client_local = LlamaCppClient(backend="local")
        self.assertEqual(client_local.backend, "local")

        client_gemini = LlamaCppClient(backend="gemini")
        self.assertEqual(client_gemini.backend, "gemini")

    @override_settings(GEMINI_API_KEY="test-api-key-12345", GEMINI_MODEL_NAME="gemini-3.6-flash")
    def test_gemini_model_name_from_settings(self):
        from nutrition.services.llama_client import LlamaCppClient
        client = LlamaCppClient(backend="gemini")
        self.assertEqual(client.model_name, "gemini-3.6-flash")

    @override_settings(GEMINI_API_KEY="test-api-key-12345")
    def test_gemini_custom_model_override(self):
        from nutrition.services.llama_client import LlamaCppClient
        client = LlamaCppClient(backend="gemini", model_name="gemini-2.5-flash")
        self.assertEqual(client.model_name, "gemini-2.5-flash")

    @override_settings(GEMINI_API_KEY="test-api-key-12345")
    def test_identification_saves_malformed_raw_response_and_finish_reason(self):
        from nutrition.services.llama_client import LlamaCppClient

        raw_response = '{"dish_name":"Curd Rice","ingredients":[{"serving_size'
        completion = MagicMock()
        completion.choices[0].message.content = raw_response
        completion.choices[0].finish_reason = "length"
        completion.usage = None

        with tempfile.TemporaryDirectory() as temp_dir:
            debug_path = Path(temp_dir) / "llm_response_debug.json"
            with override_settings(LLM_RESPONSE_DEBUG_FILE=debug_path):
                client = LlamaCppClient(backend="gemini")
                with patch.object(
                    client.client.chat.completions,
                    "create",
                    return_value=completion,
                ) as mock_create:
                    with self.assertRaises(ValueError):
                        client.identify_dish_and_ingredients(input_text="Curd Rice")

            saved_record = json.loads(debug_path.read_text(encoding="utf-8"))

        self.assertEqual(saved_record["raw_response"], raw_response)
        self.assertEqual(saved_record["finish_reason"], "length")
        self.assertIn("parse_error", saved_record)
        self.assertIsNone(saved_record["parsed_response"])
        request = mock_create.call_args.kwargs
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(request["max_tokens"], 1800)

    @override_settings(GEMINI_API_KEY="test-api-key-12345")
    def test_identification_saves_parsed_json_response(self):
        from nutrition.services.llama_client import LlamaCppClient

        raw_response = json.dumps({
            "dish_name": "Curd Rice",
            "recognized_input_summary": "Curd rice",
            "ingredients": [],
        })
        completion = MagicMock()
        completion.choices[0].message.content = raw_response
        completion.choices[0].finish_reason = "stop"
        completion.usage = None

        with tempfile.TemporaryDirectory() as temp_dir:
            debug_path = Path(temp_dir) / "llm_response_debug.json"
            with override_settings(LLM_RESPONSE_DEBUG_FILE=debug_path):
                client = LlamaCppClient(backend="gemini")
                with patch.object(
                    client.client.chat.completions,
                    "create",
                    return_value=completion,
                ):
                    result = client.identify_dish_and_ingredients(input_text="Curd Rice")

            saved_record = json.loads(debug_path.read_text(encoding="utf-8"))

        self.assertEqual(saved_record["raw_response"], raw_response)
        self.assertEqual(saved_record["parsed_response"], result)
        self.assertIsNone(saved_record["parse_error"])

    @override_settings(INFERENCE_BACKEND="local")
    @patch("nutrition.services.llama_client.LlamaCppClient.identify_dish_and_ingredients")
    def test_health_endpoint_shows_local_backend(self, mock_identify):
        response = self.client.get("/api/nutrition/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["inference_backend"], "local")

    @override_settings(INFERENCE_BACKEND="gemini", GEMINI_API_KEY="test-key")
    @patch("nutrition.services.llama_client.LlamaCppClient.check_health")
    def test_health_endpoint_shows_gemini_backend(self, mock_health):
        mock_health.return_value = {
            "backend": "gemini",
            "reachable": True,
            "status": "ok",
            "model_name": "gemini-3.6-flash",
        }
        response = self.client.get("/api/nutrition/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["inference_backend"], "gemini")
