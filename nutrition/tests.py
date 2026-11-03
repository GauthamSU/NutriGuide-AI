import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings
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
    databases = {"default", "nutrition"}

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

    @patch(
        "nutrition.services.llama_client.LlamaCppClient.transcribe_audio",
        return_value="My breakfast",
    )
    @patch("nutrition.services.llama_client.LlamaCppClient.identify_dish_and_ingredients")
    def test_analyze_multimodal_endpoint_with_image_and_voice(
        self, mock_identify, mock_transcribe
    ):
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
        self.assertEqual(body["transcription"], "My breakfast")

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
                ) as mock_create:
                    with self.assertRaisesRegex(ValueError, "finish_reason=stop") as error:
                        client.identify_dish_and_ingredients(input_text="Curd Rice")

            saved_record = json.loads(debug_path.read_text(encoding="utf-8"))

        self.assertEqual(saved_record["raw_response"], raw_response)
        self.assertEqual(saved_record["finish_reason"], "stop")
        self.assertIn("parse_error", saved_record)
        self.assertIsNone(saved_record["parsed_response"])
        self.assertIn("response excerpt", str(error.exception))
        self.assertEqual(saved_record["retry_count"], 0)
        request = mock_create.call_args_list[0].kwargs
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(request["max_tokens"], 1800)

    @override_settings(GEMINI_API_KEY="test-api-key-12345")
    def test_identification_retries_truncated_response_with_larger_token_limit(self):
        from nutrition.services.llama_client import LlamaCppClient

        first_response = MagicMock()
        first_response.choices[0].message.content = '{"dish_name":"Curd Rice","ingredients":['
        first_response.choices[0].finish_reason = "length"
        first_response.usage = None
        second_response = MagicMock()
        second_response.choices[0].message.content = json.dumps({
            "dish_name": "Curd Rice",
            "recognized_input_summary": "Curd rice",
            "ingredients": [],
        })
        second_response.choices[0].finish_reason = "stop"
        second_response.usage = None

        with tempfile.TemporaryDirectory() as temp_dir:
            debug_path = Path(temp_dir) / "llm_response_debug.json"
            with override_settings(LLM_RESPONSE_DEBUG_FILE=debug_path):
                client = LlamaCppClient(backend="gemini")
                with patch.object(
                    client.client.chat.completions,
                    "create",
                    side_effect=[first_response, second_response],
                ) as mock_create:
                    result = client.identify_dish_and_ingredients(input_text="Curd Rice")

            saved_record = json.loads(debug_path.read_text(encoding="utf-8"))

        self.assertEqual(result["dish_name"], "Curd Rice")
        self.assertEqual(mock_create.call_count, 2)
        self.assertEqual(mock_create.call_args_list[0].kwargs["max_tokens"], 1800)
        self.assertEqual(mock_create.call_args_list[1].kwargs["max_tokens"], 4096)
        self.assertEqual(saved_record["retry_count"], 1)
        self.assertEqual(saved_record["previous_attempts"][0]["finish_reason"], "length")
        self.assertEqual(saved_record["parsed_response"], result)

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


class FrontendCorsTests(TestCase):
    @override_settings(CORS_ALLOWED_ORIGINS=["http://127.0.0.1:5500"])
    def test_allowed_frontend_origin_can_preflight_api_request(self):
        response = self.client.options(
            "/api/nutrition/analyze/text",
            HTTP_ORIGIN="http://127.0.0.1:5500",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["Access-Control-Allow-Origin"], "http://127.0.0.1:5500"
        )
        self.assertIn("POST", response["Access-Control-Allow-Methods"])

    @override_settings(CORS_ALLOWED_ORIGINS=["http://127.0.0.1:5500"])
    def test_unconfigured_origin_does_not_receive_cors_permission(self):
        response = self.client.get(
            "/api/nutrition/health",
            HTTP_ORIGIN="https://untrusted.example",
        )

        self.assertNotIn("Access-Control-Allow-Origin", response)


class GraphNodeOutputNormalizationTests(SimpleTestCase):
    def test_single_health_insight_string_remains_one_list_item(self):
        from nutrition.graph.nodes import _normalize_string_list

        insight = "A longer health insight should stay together."
        self.assertEqual(_normalize_string_list(insight), [insight])

    def test_insight_list_entries_are_preserved(self):
        from nutrition.graph.nodes import _normalize_string_list

        insights = ["First insight", "Second insight"]
        self.assertEqual(_normalize_string_list(insights), insights)

    @patch("nutrition.graph.nodes.LlamaCppClient")
    def test_identify_node_does_not_split_single_health_insight(self, mock_client_type):
        from nutrition.graph.nodes import identify_dish_node

        insight = "A complete health insight stays as one sentence."
        mock_client_type.return_value.identify_dish_and_ingredients.return_value = {
            "dish_name": "Lentil soup",
            "recognized_input_summary": "Lentil soup",
            "ingredients": [],
            "health_insights": insight,
        }

        node_result = identify_dish_node({"input_text": "lentil soup"})

        self.assertEqual(node_result["health_insights"], [insight])


class UserAuthAndProfileTests(TestCase):
    databases = {"default", "nutrition"}

    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.media_settings = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.client = Client()

    def test_weak_passwords_are_rejected_on_signup(self):
        for weak_pw in ("short1!", "alllowercase1!", "ALLUPPERCASE1!", "NoDigitsHere!", "NoSpecialChar123"):
            resp = self.client.post(
                "/api/auth/signup",
                data={
                    "username": "weak_pw_user",
                    "email": "weak@example.com",
                    "password": weak_pw,
                },
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 400, f"Weak password '{weak_pw}' should be rejected")
            self.assertIn("Please choose a stronger password", resp.json()["detail"])

    def test_unauthenticated_user_cannot_create_profile_or_group_even_with_owner_id(self):
        unauth_profile = self.client.post(
            "/api/profile",
            data={
                "name": "Guest Attempting Profile",
                "age": 30,
                "owner_id": "11111111-2222-3333-4444-555555555555",
            },
            content_type="application/json",
        )
        self.assertEqual(unauth_profile.status_code, 401)
        self.assertIn("log in or sign up", unauth_profile.json()["detail"].lower())

        unauth_group = self.client.post(
            "/api/groups",
            data={
                "name": "Guest Group",
                "description": "Should not be allowed",
                "is_public": True,
                "owner_id": "11111111-2222-3333-4444-555555555555",
            },
            content_type="application/json",
        )
        self.assertEqual(unauth_group.status_code, 401)
        self.assertIn("log in or sign up", unauth_group.json()["detail"].lower())

    def test_user_signup_login_and_me_flow(self):
        # 1. Signup with strong password
        signup_resp = self.client.post(
            "/api/auth/signup",
            data={
                "username": "alice_nutri",
                "email": "alice@example.com",
                "password": "SecurePassword@123",
            },
            content_type="application/json",
        )
        self.assertEqual(signup_resp.status_code, 200)
        signup_data = signup_resp.json()
        self.assertEqual(signup_data["status"], "ok")
        self.assertIn("token", signup_data)
        self.assertEqual(signup_data["user"]["username"], "alice_nutri")
        self.assertEqual(signup_data["user"]["email"], "alice@example.com")
        self.assertTrue(signup_data["user"]["owner_id"])

        # 2. Duplicate username or email rejected
        dup_user_resp = self.client.post(
            "/api/auth/signup",
            data={
                "username": "ALICE_NUTRI",
                "email": "different@example.com",
                "password": "SecurePassword@123",
            },
            content_type="application/json",
        )
        self.assertEqual(dup_user_resp.status_code, 400)
        self.assertIn("already taken", dup_user_resp.json()["detail"].lower())

        dup_email_resp = self.client.post(
            "/api/auth/signup",
            data={
                "username": "bob_nutri",
                "email": "ALICE@example.com",
                "password": "SecurePassword@123",
            },
            content_type="application/json",
        )
        self.assertEqual(dup_email_resp.status_code, 400)
        self.assertIn("already exists", dup_email_resp.json()["detail"].lower())

        # 3. Login with username or email
        login_resp = self.client.post(
            "/api/auth/login",
            data={
                "username_or_email": "alice@example.com",
                "password": "SecurePassword@123",
            },
            content_type="application/json",
        )
        self.assertEqual(login_resp.status_code, 200)
        login_data = login_resp.json()
        self.assertEqual(login_data["user"]["username"], "alice_nutri")
        token = login_data["token"]

        # 4. Fetch /api/auth/me using Bearer token
        me_resp = self.client.get(
            "/api/auth/me",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.json()["user"]["username"], "alice_nutri")

    def test_user_profile_update_with_profile_picture_and_retrieval(self):
        from chat_history.models import UserProfile

        signup_resp = self.client.post(
            "/api/auth/signup",
            data={
                "username": "profile_tester",
                "email": "profile@example.com",
                "password": "ProfilePass#1234",
            },
            content_type="application/json",
        ).json()
        token = signup_resp["token"]
        owner_id = signup_resp["user"]["owner_id"]
        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

        # Upload profile picture as a file via multipart endpoint (/api/profile/upload)
        update_resp = self.client.post(
            "/api/profile/upload",
            data={
                "name": "Aarav Sharma",
                "age": "28",
                "height_cm": "175.0",
                "weight_kg": "70.0",
                "gender": "Male",
                "allergies": "Peanuts, Shellfish",
                "bio": "Marathon runner training for a sub-4h finish, prefers South Indian meals.",
                "profile_picture_file": SimpleUploadedFile("avatar.png", png_bytes, content_type="image/png"),
            },
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(update_resp.status_code, 200)
        profile = update_resp.json()["user"]["profile"]
        expected_avatar_url = f"/api/profile/avatar/{owner_id}"
        self.assertEqual(profile["name"], "Aarav Sharma")
        self.assertEqual(profile["age"], 28)
        self.assertEqual(profile["height_cm"], 175.0)
        self.assertEqual(profile["weight_kg"], 70.0)
        self.assertEqual(profile["gender"], "Male")
        self.assertEqual(profile["allergies"], "Peanuts, Shellfish")
        self.assertIn("Marathon runner", profile["bio"])
        self.assertEqual(profile["profile_picture"], expected_avatar_url)
        self.assertTrue(profile["has_profile_picture"])
        self.assertAlmostEqual(profile["bmi"], 22.9, places=1)

        # Verify the profile image is stored as a physical file in MEDIA_ROOT/user_profiles/avatars/... inside core_app DB
        db_profile = UserProfile.objects.using("default").get(owner_id=owner_id)
        self.assertTrue(db_profile.profile_picture.name.startswith("user_profiles/avatars/"))
        with db_profile.profile_picture.open("rb") as f:
            self.assertEqual(f.read(), png_bytes)

        # Verify GET /api/profile/avatar/{owner_id} streams the stored image file
        avatar_resp = self.client.get(expected_avatar_url)
        self.assertEqual(avatar_resp.status_code, 200)
        self.assertEqual(avatar_resp["Content-Type"], "image/png")
        self.assertEqual(b"".join(avatar_resp.streaming_content), png_bytes)

        # Verify GET /api/profile returns the updated fields including profile_picture URL
        get_resp = self.client.get(
            "/api/profile",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(get_resp.status_code, 200)
        fetched_profile = get_resp.json()["user"]["profile"]
        self.assertEqual(fetched_profile["name"], "Aarav Sharma")
        self.assertEqual(fetched_profile["allergies"], "Peanuts, Shellfish")
        self.assertEqual(fetched_profile["profile_picture"], expected_avatar_url)


class NutritionGroupsTests(TestCase):
    databases = {"default", "nutrition"}

    @classmethod
    def setUpTestData(cls):
        from nutrition.models import Food, FoodGroup, ProximateNutrient
        grp_a, _ = FoodGroup.objects.get_or_create(code="A", defaults={"name": "Cereals and Millets"})
        food_rice, _ = Food.objects.get_or_create(
            food_code="A014",
            defaults={"group": grp_a, "name": "Rice, parboiled, milled"},
        )
        ProximateNutrient.objects.get_or_create(
            food=food_rice,
            defaults={
                "energy_kcal": 350.0,
                "protein_g": 8.0,
                "carbohydrates_g": 77.0,
                "total_fat_g": 0.6,
                "total_fiber_g": 3.7,
            },
        )

    def setUp(self):
        self.client = Client()
        # Create two users: Alice and Bob
        self.alice = self.client.post(
            "/api/auth/signup",
            data={"username": "alice", "email": "alice@nutri.ai", "password": "StrongPass@123"},
            content_type="application/json",
        ).json()
        self.bob = self.client.post(
            "/api/auth/signup",
            data={"username": "bob", "email": "bob@nutri.ai", "password": "StrongPass@123"},
            content_type="application/json",
        ).json()
        self.alice_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.alice['token']}"}
        self.bob_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.bob['token']}"}

    def test_public_group_requires_unique_name_and_supports_search(self):
        # Alice creates a public group "Morning Runners Club"
        pub1 = self.client.post(
            "/api/groups",
            data={
                "name": "Morning Runners Club",
                "description": "Public nutrition tracking for runners",
                "is_public": True,
            },
            content_type="application/json",
            **self.alice_headers,
        )
        self.assertEqual(pub1.status_code, 200)
        self.assertTrue(pub1.json()["group"]["is_public"])

        # Bob searches public groups by query
        search_hit = self.client.get("/api/groups?q=Runners", **self.bob_headers).json()
        self.assertEqual(len(search_hit["public_groups"]), 1)
        self.assertEqual(search_hit["public_groups"][0]["name"], "Morning Runners Club")

        search_miss = self.client.get("/api/groups?q=NonExistentClubXYZ", **self.bob_headers).json()
        self.assertEqual(len(search_miss["public_groups"]), 0)

        # Bob tries to create another PUBLIC group with the same name (case-insensitive) -> rejected
        pub_dup = self.client.post(
            "/api/groups",
            data={
                "name": "morning runners club",
                "description": "Duplicate public group",
                "is_public": True,
            },
            content_type="application/json",
            **self.bob_headers,
        )
        self.assertEqual(pub_dup.status_code, 400)
        self.assertIn("already exists", pub_dup.json()["detail"])

        # Both Alice and Bob CAN create PRIVATE groups with the same name "Family Kitchen"
        priv1 = self.client.post(
            "/api/groups",
            data={
                "name": "Family Kitchen",
                "description": "Alice's private family group",
                "is_public": False,
            },
            content_type="application/json",
            **self.alice_headers,
        )
        self.assertEqual(priv1.status_code, 200)

        priv2 = self.client.post(
            "/api/groups",
            data={
                "name": "Family Kitchen",
                "description": "Bob's private family group",
                "is_public": False,
            },
            content_type="application/json",
            **self.bob_headers,
        )
        self.assertEqual(priv2.status_code, 200)
        self.assertNotEqual(priv1.json()["group"]["id"], priv2.json()["group"]["id"])

    def test_group_membership_and_collective_nutrition_tracking(self):
        # Alice creates a private group and invites Bob by username
        create_resp = self.client.post(
            "/api/groups",
            data={
                "name": "Spartan Squad",
                "description": "Collective macro tracking",
                "is_public": False,
                "members": ["bob"],
            },
            content_type="application/json",
            **self.alice_headers,
        )
        self.assertEqual(create_resp.status_code, 200)
        group_id = create_resp.json()["group"]["id"]
        # Alice is the only active member initially; Bob has a pending invitation
        self.assertEqual(create_resp.json()["group"]["member_count"], 1)

        # Bob views his notifications to find the pending invitation
        bob_notifs = self.client.get(
            "/api/groups/notifications",
            **self.bob_headers,
        )
        self.assertEqual(bob_notifs.status_code, 200)
        invitations = bob_notifs.json().get("pending_invitations", [])
        self.assertEqual(len(invitations), 1)
        req_id = invitations[0]["id"]
        self.assertEqual(invitations[0]["group_name"], "Spartan Squad")

        # Bob accepts the invitation
        accept_resp = self.client.post(
            f"/api/groups/requests/{req_id}/respond",
            data={"action": "accept"},
            content_type="application/json",
            **self.bob_headers,
        )
        self.assertEqual(accept_resp.status_code, 200)
        self.assertEqual(accept_resp.json()["status"], "accepted")

        # Now Bob is an active member
        detail_after_accept = self.client.get(f"/api/groups/{group_id}", **self.bob_headers)
        self.assertEqual(detail_after_accept.status_code, 200)
        self.assertEqual(detail_after_accept.json()["group"]["member_count"], 2)

        # Alice logs a meal with explicit macros
        meal1 = self.client.post(
            f"/api/groups/{group_id}/meals",
            data={
                "meal_title": "Post-Workout Protein Shake",
                "calories_kcal": 400.0,
                "protein_g": 35.0,
                "carbohydrates_g": 42.0,
                "fat_g": 8.0,
                "fiber_g": 5.0,
            },
            content_type="application/json",
            **self.alice_headers,
        )
        self.assertEqual(meal1.status_code, 200)

        # Bob logs a meal with 0 calories so it auto-resolves "Rice" from IFCT DB (350 kcal / 100g -> 700 kcal for 200g)
        meal2 = self.client.post(
            f"/api/groups/{group_id}/meals",
            data={
                "meal_title": "Rice",
                "serving_grams": 200.0,
            },
            content_type="application/json",
            **self.bob_headers,
        )
        self.assertEqual(meal2.status_code, 200)

        # Fetch group detail to verify collective nutrition totals and per-member breakdown
        detail_resp = self.client.get(
            f"/api/groups/{group_id}",
            **self.alice_headers,
        )
        self.assertEqual(detail_resp.status_code, 200)
        group_data = detail_resp.json()["group"]
        collective = group_data["collective_nutrition"]
        self.assertEqual(collective["total_meals_logged"], 2)
        self.assertAlmostEqual(collective["total_calories_kcal"], 1100.0, places=0)
        self.assertAlmostEqual(collective["total_protein_g"], 51.0, places=0)
        self.assertEqual(len(group_data["member_breakdown"]), 2)

    def test_group_invitation_rejection(self):
        # Alice creates a group and invites Bob
        create_resp = self.client.post(
            "/api/groups",
            data={
                "name": "Invited Only Club",
                "is_public": False,
            },
            content_type="application/json",
            **self.alice_headers,
        )
        group_id = create_resp.json()["group"]["id"]

        # Alice invites Bob via members endpoint
        inv_resp = self.client.post(
            f"/api/groups/{group_id}/members",
            data={"identifier": "bob"},
            content_type="application/json",
            **self.alice_headers,
        )
        self.assertEqual(inv_resp.status_code, 200)

        # Bob checks notifications
        bob_notifs = self.client.get("/api/groups/notifications", **self.bob_headers).json()
        self.assertEqual(len(bob_notifs["pending_invitations"]), 1)
        req_id = bob_notifs["pending_invitations"][0]["id"]

        # Bob rejects the invitation
        rej_resp = self.client.post(
            f"/api/groups/requests/{req_id}/respond",
            data={"action": "reject"},
            content_type="application/json",
            **self.bob_headers,
        )
        self.assertEqual(rej_resp.status_code, 200)
        self.assertEqual(rej_resp.json()["status"], "rejected")

        # Verify Bob is NOT a member
        detail_resp = self.client.get(f"/api/groups/{group_id}", **self.alice_headers).json()
        self.assertEqual(detail_resp["group"]["member_count"], 1)

    def test_user_join_request_and_admin_approval(self):
        # Alice creates a public group
        create_resp = self.client.post(
            "/api/groups",
            data={
                "name": "Bangalore Runners Community",
                "description": "Public runners tracking",
                "is_public": True,
            },
            content_type="application/json",
            **self.alice_headers,
        )
        self.assertEqual(create_resp.status_code, 200)
        group_id = create_resp.json()["group"]["id"]

        # Bob sends a join request to this public group
        join_resp = self.client.post(
            f"/api/groups/{group_id}/join",
            **self.bob_headers,
        )
        self.assertEqual(join_resp.status_code, 200)
        self.assertTrue(join_resp.json()["group"]["has_pending_join_request"])
        self.assertFalse(join_resp.json()["group"]["is_member"])

        # Alice checks her admin notifications
        alice_notifs = self.client.get("/api/groups/notifications", **self.alice_headers).json()
        admin_reqs = alice_notifs["admin_pending_requests"]
        self.assertEqual(len(admin_reqs), 1)
        self.assertEqual(admin_reqs[0]["username"], "bob")
        req_id = admin_reqs[0]["id"]

        # Alice approves Bob's join request
        approve_resp = self.client.post(
            f"/api/groups/requests/{req_id}/respond",
            data={"action": "approve"},
            content_type="application/json",
            **self.alice_headers,
        )
        self.assertEqual(approve_resp.status_code, 200)
        self.assertEqual(approve_resp.json()["status"], "accepted")

        # Now Bob is an active member of the group
        bob_detail = self.client.get(f"/api/groups/{group_id}", **self.bob_headers).json()
        self.assertTrue(bob_detail["group"]["is_member"])
        self.assertEqual(bob_detail["group"]["member_count"], 2)

    def test_user_join_request_and_admin_rejection(self):
        # Alice creates a public group
        create_resp = self.client.post(
            "/api/groups",
            data={
                "name": "Strict Fitness Cohort",
                "is_public": True,
            },
            content_type="application/json",
            **self.alice_headers,
        )
        group_id = create_resp.json()["group"]["id"]

        # Bob requests to join
        self.client.post(f"/api/groups/{group_id}/join", **self.bob_headers)

        # Alice rejects
        alice_notifs = self.client.get("/api/groups/notifications", **self.alice_headers).json()
        req_id = alice_notifs["admin_pending_requests"][0]["id"]
        rej_resp = self.client.post(
            f"/api/groups/requests/{req_id}/respond",
            data={"action": "reject"},
            content_type="application/json",
            **self.alice_headers,
        )
        self.assertEqual(rej_resp.status_code, 200)
        self.assertEqual(rej_resp.json()["status"], "rejected")

        # Bob is NOT a member
        bob_detail = self.client.get(f"/api/groups/{group_id}", **self.bob_headers).json()
        self.assertFalse(bob_detail["group"]["is_member"])


class ExplicitTrackerAndDeletionTests(TestCase):
    databases = {"default", "nutrition"}

    @classmethod
    def setUpTestData(cls):
        from nutrition.models import Food, FoodGroup, MineralNutrient, ProximateNutrient, VitaminNutrient
        grp_a, _ = FoodGroup.objects.get_or_create(code="A", defaults={"name": "Cereals and Millets"})
        food_rice, _ = Food.objects.get_or_create(
            food_code="A014",
            defaults={"group": grp_a, "name": "Rice, parboiled, milled"},
        )
        ProximateNutrient.objects.get_or_create(
            food=food_rice,
            defaults={
                "energy_kcal": 350.0,
                "protein_g": 8.0,
                "carbohydrates_g": 77.0,
                "total_fat_g": 0.6,
                "total_fiber_g": 3.7,
            },
        )
        VitaminNutrient.objects.get_or_create(food=food_rice, defaults={"thiamine_b1_mg": 0.25})
        MineralNutrient.objects.get_or_create(food=food_rice, defaults={"iron_mg": 1.5, "calcium_mg": 12.0})

    def setUp(self):
        self.client = Client()
        self.owner_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        self.conversation_id = "11111111-2222-4333-8444-555555555555"

    @patch("nutrition.services.llama_client.LlamaCppClient.identify_dish_and_ingredients")
    def test_chat_does_not_auto_log_to_tracker_unless_explicit_or_button_clicked(self, mock_identify):
        mock_identify.return_value = {
            "dish_name": "Steamed Rice Bowl",
            "recognized_input_summary": "100g steamed rice",
            "ingredients": [
                {"ingredient_name": "Rice", "estimated_weight_grams": 100.0, "serving_size_description": "1 bowl"}
            ],
            "dietary_tags": ["Vegetarian"],
            "health_insights": ["Good source of energy."],
        }

        # 1. Normal chat query about a food product -> NOT logged to tracker
        chat_resp = self.client.post(
            "/api/nutrition/analyze/text",
            data={
                "text": "What are the nutrients in a bowl of steamed rice?",
                "owner_id": self.owner_id,
                "conversation_id": self.conversation_id,
            },
            content_type="application/json",
        )
        self.assertEqual(chat_resp.status_code, 200)
        chat_data = chat_resp.json()
        self.assertFalse(chat_data["logged_to_tracker"])
        self.assertIsNone(chat_data["tracker_log_id"])
        msg1_id = chat_data["message_id"]
        self.assertIsNotNone(msg1_id)

        # Verify tracker is still empty (0 meals)
        tracker_empty = self.client.get(f"/api/tracker?owner_id={self.owner_id}").json()
        self.assertEqual(tracker_empty["periods"]["daily"]["meals_count"], 0)
        self.assertEqual(tracker_empty["periods"]["daily"]["macronutrients"]["calories_kcal"], 0.0)

        # 2. User clicks "Log to Tracker" button on msg1_id -> logged to tracker!
        btn_log_resp = self.client.post(
            "/api/tracker/log",
            data={
                "owner_id": self.owner_id,
                "conversation_id": self.conversation_id,
                "message_id": msg1_id,
            },
            content_type="application/json",
        )
        self.assertEqual(btn_log_resp.status_code, 200)
        btn_log_data = btn_log_resp.json()
        self.assertEqual(btn_log_data["meal"]["logged_via"], "chat_button")
        first_log_id = btn_log_data["meal"]["id"]

        tracker_after_btn = self.client.get(f"/api/tracker?owner_id={self.owner_id}").json()
        self.assertEqual(tracker_after_btn["periods"]["daily"]["meals_count"], 1)
        self.assertGreater(tracker_after_btn["periods"]["daily"]["macronutrients"]["calories_kcal"], 300.0)
        self.assertGreaterEqual(len(tracker_after_btn["periods"]["daily"]["micronutrients"]["vitamins"]), 1)
        self.assertGreaterEqual(len(tracker_after_btn["periods"]["daily"]["micronutrients"]["minerals"]), 1)

        # 3. User sends explicit chat intent ("Please log this rice bowl to my tracker") -> auto-logged!
        explicit_resp = self.client.post(
            "/api/nutrition/analyze/text",
            data={
                "text": "Please log this steamed rice bowl to my tracker",
                "owner_id": self.owner_id,
                "conversation_id": self.conversation_id,
            },
            content_type="application/json",
        )
        self.assertEqual(explicit_resp.status_code, 200)
        explicit_data = explicit_resp.json()
        self.assertTrue(explicit_data["logged_to_tracker"])
        self.assertIsNotNone(explicit_data["tracker_log_id"])

        # Verify daily, weekly, and monthly periods all reflect 2 logged meals
        tracker_two = self.client.get(f"/api/tracker?owner_id={self.owner_id}").json()
        for period_name in ("daily", "weekly", "monthly"):
            self.assertEqual(tracker_two["periods"][period_name]["meals_count"], 2)
            self.assertGreater(tracker_two["periods"][period_name]["macronutrients"]["calories_kcal"], 600.0)

        # 4. Delete a tracked meal from the tracker
        del_track_resp = self.client.post(
            f"/api/tracker/meals/{first_log_id}/delete?owner_id={self.owner_id}"
        )
        self.assertEqual(del_track_resp.status_code, 200)
        tracker_after_del = self.client.get(f"/api/tracker?owner_id={self.owner_id}").json()
        self.assertEqual(tracker_after_del["periods"]["daily"]["meals_count"], 1)

    def test_delete_individual_chat_message_conversation_and_meal_plan(self):
        from chat_history.services import save_chat_message, save_meal_plan

        # Save 2 chat messages in a conversation
        m1 = save_chat_message(
            owner_id=self.owner_id,
            conversation_id=self.conversation_id,
            user_query="Product 1: Almond Milk",
            transcription="",
            modalities=["text"],
            ai_response={"dish_name": "Almond Milk", "ingredients": []},
        )
        m2 = save_chat_message(
            owner_id=self.owner_id,
            conversation_id=self.conversation_id,
            user_query="Product 2: Greek Yogurt",
            transcription="",
            modalities=["text"],
            ai_response={"dish_name": "Greek Yogurt", "ingredients": []},
        )

        # Delete individual chat message m1
        del_msg_resp = self.client.delete(
            f"/api/chat-history/conversations/{self.conversation_id}/messages/{m1.id}?owner_id={self.owner_id}"
        )
        self.assertEqual(del_msg_resp.status_code, 200)
        self.assertFalse(del_msg_resp.json()["conversation_deleted"])

        conv_after = self.client.get(
            f"/api/chat-history/conversations/{self.conversation_id}?owner_id={self.owner_id}"
        ).json()
        self.assertEqual(len(conv_after["messages"]), 1)
        self.assertEqual(conv_after["messages"][0]["id"], str(m2.id))

        # Delete entire chat conversation
        del_conv_resp = self.client.delete(
            f"/api/chat-history/conversations/{self.conversation_id}?owner_id={self.owner_id}"
        )
        self.assertEqual(del_conv_resp.status_code, 200)
        convs_list = self.client.get(f"/api/chat-history/conversations?owner_id={self.owner_id}").json()
        self.assertEqual(len(convs_list), 0)

        # Save & delete a meal plan
        saved_plan = save_meal_plan(
            owner_id=self.owner_id,
            preferences=["High-protein"],
            custom_request="Test plan",
            plan={"summary": "Test", "breakfast": {"options": []}},
        )
        del_plan_resp = self.client.delete(
            f"/api/chat-history/meal-plans/{saved_plan['id']}?owner_id={self.owner_id}"
        )
        self.assertEqual(del_plan_resp.status_code, 200)
        plans_after = self.client.get(f"/api/chat-history/meal-plans?owner_id={self.owner_id}").json()
        self.assertEqual(len(plans_after), 0)


class EnhancedMealPlanTests(TestCase):
    databases = {"default", "nutrition"}

    def setUp(self):
        self.client = Client()

    @patch("nutrition.services.llama_client.LlamaCppClient.generate_structured_response")
    def test_meal_plan_duration_diet_type_and_profile_context(self, mock_gen):
        mock_gen.return_value = {
            "summary": "Weekly Vegan High-Protein Plan",
            "breakfast": {"options": [{"name": "Ragi Porridge", "details": "1 bowl", "why_it_fits": "High calcium"}]},
            "lunch": {"options": [{"name": "Chana Masala & Brown Rice", "details": "1 plate", "why_it_fits": "Complete protein"}]},
            "snacks": {"options": [{"name": "Roasted Makhana", "details": "1 cup", "why_it_fits": "Low calorie"}]},
            "dinner": {"options": [{"name": "Dal Khichdi with Palak", "details": "1 bowl", "why_it_fits": "Easy digestion"}]},
        }

        # Create user & profile to verify profile context is passed to AI
        signup = self.client.post(
            "/api/auth/signup",
            data={"username": "vegan_athlete", "email": "vegan@nutri.ai", "password": "VeganPass@123"},
            content_type="application/json",
        ).json()
        user_id = signup["user"]["id"]
        owner_id = signup["user"]["owner_id"]
        token = signup["token"]

        self.client.post(
            "/api/profile",
            data={"name": "Priya", "age": 25, "allergies": "Soy", "bio": "Endurance cyclist"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        resp = self.client.post(
            "/api/nutrition/meal-plans/generate",
            data={
                "preferences": ["High-protein", "Blood-sugar conscious"],
                "duration": "weekly",
                "diet_type": "vegan",
                "custom_request": "Include South Indian breakfast options",
                "owner_id": owner_id,
                "user_id": user_id,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["duration"], "weekly")
        self.assertEqual(body["diet_type"], "vegan")
        self.assertEqual(body["plan"]["duration"], "weekly")
        self.assertEqual(body["plan"]["diet_type"], "vegan")
        for sec in ("breakfast", "lunch", "snacks", "dinner"):
            self.assertGreaterEqual(len(body["plan"][sec]["options"]), 5)

        # Verify prompt sent to LLM included duration, diet_type, and user profile allergies
        call_kwargs = mock_gen.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("7-day", user_prompt)
        self.assertIn("100% Vegan", user_prompt)
        self.assertIn("Soy", user_prompt)

    @patch("nutrition.services.llama_client.LlamaCppClient.transcribe_audio", return_value="I want a monthly eggetarian diet for muscle gain")
    @patch("nutrition.services.llama_client.LlamaCppClient.generate_structured_response")
    def test_meal_plan_multimodal_upload_endpoint_with_voice_and_image(self, mock_gen, mock_transcribe):
        mock_gen.return_value = {
            "summary": "Monthly Eggetarian Plan",
            "breakfast": {"options": [{"name": "Masala Omelette", "details": "3 eggs", "why_it_fits": "High protein"}]},
            "lunch": {"options": [{"name": "Egg Curry & Roti", "details": "2 eggs, 2 rotis", "why_it_fits": "Balanced macros"}]},
            "snacks": {"options": [{"name": "Boiled Egg Whites", "details": "3 whites", "why_it_fits": "Lean protein"}]},
            "dinner": {"options": [{"name": "Bhurji & Dal", "details": "1 bowl", "why_it_fits": "Sustained release"}]},
        }

        fake_image = SimpleUploadedFile("fridge.jpg", b"\xff\xd8\xff\xe0fakejpeg", content_type="image/jpeg")
        fake_voice = SimpleUploadedFile("request.wav", b"RIFFfakewav", content_type="audio/wav")

        resp = self.client.post(
            "/api/nutrition/meal-plans/generate/upload",
            data={
                "preferences": json.dumps(["High-protein"]),
                "duration": "monthly",
                "diet_type": "egg",
                "custom_request": "Use ingredients in photo",
                "image": fake_image,
                "voice": fake_voice,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["duration"], "monthly")
        self.assertEqual(data["diet_type"], "egg")
        self.assertEqual(data["transcription"], "I want a monthly eggetarian diet for muscle gain")
        self.assertEqual(data["plan"]["has_image"], True)
        for sec in ("breakfast", "lunch", "snacks", "dinner"):
            self.assertGreaterEqual(len(data["plan"][sec]["options"]), 10)


class WebFrontendTemplatesTests(SimpleTestCase):
    def test_frontend_templates_render_all_upgraded_views(self):
        from web_frontend.server import build_page_context, render_template

        # 1. Auth page (Login / Signup + Strong Password Meter)
        auth_ctx = build_page_context("/login", auth_mode="login")
        auth_html = render_template("pages/auth.html", auth_ctx)
        self.assertIn("Create Account", auth_html)
        self.assertIn("login-form", auth_html)
        self.assertIn("signup-form", auth_html)
        self.assertIn("password-strength-bars", auth_html)
        self.assertIn("generate-strong-password-btn", auth_html)

        # 2. Unauthenticated Profile & Groups pages show Auth Gate and disable submission
        unauth_profile_html = render_template("pages/profile.html", build_page_context("/profile"))
        self.assertIn("profile-auth-gate", unauth_profile_html)
        self.assertIn("Please log in or sign up to create your profile", unauth_profile_html)
        self.assertNotIn('id="profile-save-btn"', unauth_profile_html)

        unauth_groups_html = render_template("pages/groups.html", build_page_context("/groups"))
        self.assertIn("groups-auth-gate", unauth_groups_html)
        self.assertIn("Log in or sign up to create or join a nutrition group", unauth_groups_html)
        self.assertIn('id="open-create-group-modal-btn"', unauth_groups_html)
        self.assertIn('disabled', unauth_groups_html)
        self.assertIn('cursor-not-allowed', unauth_groups_html)
        self.assertIn('Log in or sign up to create a group', unauth_groups_html)

        # 3. Authenticated Profile & Groups pages show Profile Picture Upload + Group Modals
        mock_user = {"username": "alice", "email": "alice@nutri.ai", "profile": {"name": "Alice"}}
        profile_ctx = build_page_context("/profile", current_user=mock_user)
        profile_html = render_template("pages/profile.html", profile_ctx)
        self.assertIn("profile-avatar-file", profile_html)
        self.assertIn("allergies", profile_html)
        self.assertIn("height", profile_html)
        self.assertIn("weight", profile_html)
        self.assertIn("gender", profile_html)

        groups_ctx = build_page_context("/groups", current_user=mock_user)
        groups_html = render_template("pages/groups.html", groups_ctx)
        self.assertIn("create-group-modal", groups_html)
        self.assertIn("public-groups-search", groups_html)

        group_detail_ctx = build_page_context("/groups/test-grp-1", current_user=mock_user)
        group_detail_ctx["group"] = {"id": "test-grp-1", "name": "Runners", "collective": {}, "recent_meals": [], "members": []}
        group_detail_html = render_template("pages/group_detail.html", group_detail_ctx)
        self.assertIn("group-page-log-meal-form", group_detail_html)

        # 4. Tracker page (Daily / Weekly / Monthly tabs + Complete Nutrient Breakdown)
        tracker_ctx = build_page_context("/tracker", current_user=mock_user)
        tracker_html = render_template("pages/tracker.html", tracker_ctx)
        self.assertIn('data-tracker-tab="daily"', tracker_html)
        self.assertIn('data-tracker-tab="weekly"', tracker_html)
        self.assertIn('data-tracker-tab="monthly"', tracker_html)
        self.assertIn("Macronutrients", tracker_html)
        self.assertIn("Vitamins", tracker_html)
        self.assertIn("Minerals", tracker_html)

        # 5. Meal Plan page
        meal_ctx = build_page_context("/meal-plan", current_user=mock_user)
        meal_html = render_template("pages/meal_plan.html", meal_ctx)
        for duration_val in ("daily", "weekly", "monthly"):
            self.assertIn(f'value="{duration_val}"', meal_html)
        for diet_val in ("veg", "non-veg", "vegan", "egg"):
            self.assertIn(f'value="{diet_val}"', meal_html)
        self.assertIn("meal-plan-mic-btn", meal_html)
        self.assertIn("meal-plan-image", meal_html)
        self.assertIn("meal-plan-voice", meal_html)
        self.assertIn("meal-section-card", meal_html)


