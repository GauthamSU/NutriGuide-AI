import tempfile
import uuid
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from chat_history.models import (
    ChatConversation,
    ChatMessage,
    GroupMealLog,
    MealPlanHistory,
    NutritionGroup,
    TrackedMeal,
    UserCustomRecipe,
)
from chat_history.services import (
    customize_dish_recipe,
    delete_chat_message,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_meal_plans,
    reset_dish_recipe,
    save_chat_message,
    save_meal_plan,
)
from nutrition.services.llama_client import LlamaCppClient


class ChatHistoryTests(TestCase):
    databases = {"default", "nutrition"}

    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.media_settings = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.owner_id = str(uuid.uuid4())
        self.conversation_id = str(uuid.uuid4())

    def save_message(self):
        save_chat_message(
            owner_id=self.owner_id,
            conversation_id=self.conversation_id,
            user_query="A bowl of lentil soup",
            transcription="",
            modalities=["text", "image", "voice"],
            ai_response={
                "dish_name": "Lentil soup",
                "recognized_input_summary": "A bowl of lentil soup",
                "ingredients": [
                    {
                        "ingredient_name": "Lentils",
                        "serving_size_description": "1 bowl",
                        "estimated_weight_grams": 250,
                        "confidence": 0.94,
                    }
                ],
                "dietary_tags": ["Vegetarian"],
                "health_insights": ["A filling meal."],
                "total_macronutrients": {"calories_kcal": 300},
            },
            image_data=b"image-bytes",
            image_name="meal.png",
            image_content_type="image/png",
            audio_data=b"audio-bytes",
            audio_name="voice.wav",
            audio_content_type="audio/wav",
        )

    def test_saves_modalities_and_ai_only_response_separately_from_nutrients(self):
        self.save_message()
        message = ChatMessage.objects.using("default").get()

        self.assertEqual(message.user_query, "A bowl of lentil soup")
        self.assertEqual(message.input_modalities, ["text", "image", "voice"])
        self.assertEqual(message.image_name, "meal.png")
        self.assertEqual(message.audio_name, "voice.wav")
        self.assertNotIn("total_macronutrients", message.ai_response)
        self.assertNotIn("macronutrients", message.ai_response["ingredients"][0])
        with message.image.open("rb") as image_file:
            self.assertEqual(image_file.read(), b"image-bytes")
        with message.audio.open("rb") as audio_file:
            self.assertEqual(audio_file.read(), b"audio-bytes")

    @patch("chat_history.services.resolve_dish_nutrition_from_db")
    def test_history_is_owner_scoped_and_reloads_nutrients_from_reference_data(
        self, resolve_nutrients
    ):
        self.save_message()
        resolve_nutrients.return_value = {
            "meal_title": "Lentil soup",
            "recognized_input_summary": "A bowl of lentil soup",
            "items": [],
            "total_macronutrients": {},
            "dietary_tags": ["Vegetarian"],
            "health_insights": [],
            "missing_ingredients": [],
        }

        chats = list_conversations(self.owner_id)
        conversation = get_conversation(self.owner_id, self.conversation_id)

        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0]["id"], self.conversation_id)
        self.assertEqual(conversation["messages"][0]["user_query"], "A bowl of lentil soup")
        self.assertEqual(
            resolve_nutrients.call_args.args[0]["ingredients"][0]["ingredient_name"],
            "Lentils",
        )
        self.assertEqual(
            list_conversations(str(uuid.uuid4())),
            [],
        )

    def test_history_api_serves_saved_audio_for_its_owner(self):
        self.save_message()
        message = ChatMessage.objects.using("default").get()
        response = self.client.get(
            f"/api/chat-history/conversations/{self.conversation_id}/"
            f"messages/{message.id}/audio",
            {"owner_id": self.owner_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"audio-bytes")
        self.assertEqual(response["Content-Type"], "audio/wav")

    def test_invalid_owner_id_is_rejected(self):
        response = self.client.get(
            "/api/chat-history/conversations",
            {"owner_id": "not-a-uuid"},
        )
        self.assertEqual(response.status_code, 400)

    @patch("nutrition.api._write_api_response_debug")
    @patch("nutrition.api.run_nutrition_workflow")
    @patch("nutrition.api.LlamaCppClient")
    def test_audio_submission_returns_and_persists_model_transcription(
        self, mock_client_type, mock_workflow, _write_debug
    ):
        transcript = "Rice with lentils."
        mock_client_type.return_value.transcribe_audio.return_value = transcript
        macros = {
            "calories_kcal": 0,
            "protein_g": 0,
            "carbohydrates_g": 0,
            "dietary_fiber_g": 0,
            "total_sugars_g": 0,
            "added_sugars_g": 0,
            "total_fat_g": 0,
            "saturated_fat_g": 0,
            "unsaturated_fat_g": 0,
            "trans_fat_g": 0,
            "cholesterol_mg": 0,
            "sodium_mg": 0,
            "water_g": 0,
        }
        mock_workflow.return_value = {
            "status": "completed",
            "request_id": str(uuid.uuid4()),
            "input_modalities": ["voice"],
            "nutrient_analysis": {
                "meal_title": "Lentils and rice",
                "recognized_input_summary": transcript,
                "items": [],
                "total_macronutrients": macros,
                "dietary_tags": [],
                "health_insights": [],
                "missing_ingredients": [],
            },
            "dietary_tags": [],
            "dietary_warnings": [],
            "ai_generated_response": {
                "dish_name": "Lentils and rice",
                "recognized_input_summary": transcript,
                "ingredients": [],
                "dietary_tags": [],
                "health_insights": [],
            },
        }

        response = self.client.post(
            "/api/nutrition/analyze",
            {
                "owner_id": self.owner_id,
                "conversation_id": self.conversation_id,
                "voice": SimpleUploadedFile(
                    "voice.wav", b"wav-audio", content_type="audio/wav"
                ),
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["transcription"], transcript)
        message = ChatMessage.objects.using("default").get()
        self.assertEqual(message.transcription, transcript)
        self.assertEqual(message.audio_name, "voice.wav")
        self.assertEqual(message.input_modalities, ["voice"])
        conversations = self.client.get(
            "/api/chat-history/conversations",
            {"owner_id": self.owner_id},
        )
        self.assertEqual(conversations.status_code, 200)
        self.assertEqual(len(conversations.json()), 1)
        self.assertEqual(conversations.json()[0]["id"], self.conversation_id)

    def test_delete_single_message_deletes_conversation_and_cascades_tracker(self):
        """Deleting the only message in a conversation deletes the conversation and cascades to TrackedMeal."""
        self.save_message()
        msg = ChatMessage.objects.using("default").get()
        conv_id = str(msg.conversation_id)
        msg_id = str(msg.id)

        # Log a meal linked to this chat message turn
        tracked = TrackedMeal.objects.create(
            owner_id=self.owner_id,
            conversation_id=conv_id,
            source_message_id=msg_id,
            meal_title="Lentil soup",
            macronutrients={"calories_kcal": 300},
        )
        # Update message with tracker log id
        msg.ai_response = {"dish_name": "Lentil soup", "tracker_log_id": str(tracked.id)}
        msg.save(using="default", update_fields=["ai_response"])

        self.assertEqual(TrackedMeal.objects.filter(id=tracked.id).count(), 1)
        self.assertEqual(ChatConversation.objects.filter(id=conv_id).count(), 1)

        result = delete_chat_message(self.owner_id, conv_id, msg_id)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["remaining_messages"], 0)
        self.assertTrue(result["conversation_deleted"])

        # Conversation should be deleted
        self.assertEqual(ChatConversation.objects.filter(id=conv_id).count(), 0)
        # Message should be deleted
        self.assertEqual(ChatMessage.objects.filter(id=msg_id).count(), 0)
        # TrackedMeal should be cascaded and deleted
        self.assertEqual(TrackedMeal.objects.filter(id=tracked.id).count(), 0)

    def test_delete_message_with_multiple_messages_only_deletes_turn_and_cascades_meal(self):
        """Deleting one message in a multi-turn conversation deletes only that turn and its tracked meal."""
        self.save_message()
        msg1 = ChatMessage.objects.using("default").get()
        conv = msg1.conversation

        # Add second message to same conversation
        msg2 = ChatMessage.objects.using("default").create(
            conversation=conv,
            user_query="Second dish query",
            ai_response={"meal_title": "Second Dish", "tracker_log_id": ""},
        )

        tracked1 = TrackedMeal.objects.create(
            owner_id=self.owner_id,
            conversation_id=str(conv.id),
            source_message_id=str(msg1.id),
            meal_title="Lentil soup",
        )
        msg1.ai_response = {"dish_name": "Lentil soup", "tracker_log_id": str(tracked1.id)}
        msg1.save(using="default", update_fields=["ai_response"])

        result = delete_chat_message(self.owner_id, str(conv.id), str(msg1.id))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["remaining_messages"], 1)
        self.assertFalse(result["conversation_deleted"])

        # Conversation still exists with msg2
        self.assertEqual(ChatConversation.objects.filter(id=conv.id).count(), 1)
        self.assertEqual(ChatMessage.objects.filter(id=msg1.id).count(), 0)
        self.assertEqual(ChatMessage.objects.filter(id=msg2.id).count(), 1)
        # Tracked meal for msg1 is cascaded and deleted
        self.assertEqual(TrackedMeal.objects.filter(id=tracked1.id).count(), 0)

    def test_delete_conversation_cascades_all_tracked_meals_and_group_logs(self):
        """Deleting a conversation deletes all associated TrackedMeals and GroupMealLogs."""
        self.save_message()
        msg = ChatMessage.objects.using("default").get()
        conv = msg.conversation

        tracked = TrackedMeal.objects.create(
            owner_id=self.owner_id,
            conversation_id=str(conv.id),
            source_message_id=str(msg.id),
            meal_title="Lentil soup",
        )

        result = delete_conversation(self.owner_id, str(conv.id))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(ChatConversation.objects.filter(id=conv.id).count(), 0)
        self.assertEqual(TrackedMeal.objects.filter(id=tracked.id).count(), 0)


class ModelAudioTranscriptionTests(TestCase):
    def test_uses_the_configured_model_and_returns_its_transcript(self):
        client = object.__new__(LlamaCppClient)
        client.backend = "gemini"
        client.model_name = "test-audio-model"
        client.client = MagicMock()
        client.client.chat.completions.create.return_value.choices[0].message.content = (
            "I had rice and lentils."
        )

        transcript = client.transcribe_audio("encoded-audio", "wav")

        self.assertEqual(transcript, "I had rice and lentils.")
        request = client.client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "test-audio-model")
        self.assertEqual(
            request["messages"][1]["content"][0]["input_audio"]["data"],
            "encoded-audio",
        )

    def test_rejects_an_empty_model_transcript(self):
        client = object.__new__(LlamaCppClient)
        client.backend = "gemini"
        client.model_name = "test-audio-model"
        client.client = MagicMock()
        client.client.chat.completions.create.return_value.choices[0].message.content = " "

        with self.assertRaisesRegex(ValueError, "empty audio transcription"):
            client.transcribe_audio("encoded-audio", "wav")


class MealPlanTests(TestCase):
    databases = {"default", "nutrition"}

    def setUp(self):
        self.owner_id = str(uuid.uuid4())

    def test_save_and_list_meal_plans(self):
        saved = save_meal_plan(
            owner_id=self.owner_id,
            preferences=["High-protein", "Plant-forward"],
            custom_request="Vegetarian meals",
            plan={"summary": "Sample plan", "breakfast": {"options": []}},
        )
        self.assertEqual(saved["preferences"], ["High-protein", "Plant-forward"])
        self.assertEqual(saved["custom_request"], "Vegetarian meals")

        plans = list_meal_plans(self.owner_id)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["id"], saved["id"])
        self.assertEqual(plans[0]["title"], "High-protein, Plant-forward")

    @patch("nutrition.api.run_meal_plan_workflow")
    def test_meal_plan_generate_api_endpoint(self, mock_workflow):
        mock_workflow.return_value = {
            "summary": "Tailored meal plan",
            "breakfast": {
                "options": [
                    {
                        "name": "Tofu Scramble",
                        "details": "200g firm tofu with spinach",
                        "why_it_fits": "High in plant protein",
                    }
                ]
            },
            "lunch": {
                "options": [
                    {
                        "name": "Lentil Bowl",
                        "details": "1 cup lentils with quinoa",
                        "why_it_fits": "Rich in protein and fiber",
                    }
                ]
            },
            "snacks": {
                "options": [
                    {
                        "name": "Edamame",
                        "details": "1 cup steamed edamame",
                        "why_it_fits": "Quick protein boost",
                    }
                ]
            },
            "dinner": {
                "options": [
                    {
                        "name": "Chickpea Curry",
                        "details": "Chickpeas with tomatoes and brown rice",
                        "why_it_fits": "Complete vegetarian protein",
                    }
                ]
            },
        }

        response = self.client.post(
            "/api/nutrition/meal-plans/generate",
            data={
                "preferences": ["High Protein"],
                "custom_request": "vegetarian",
                "owner_id": self.owner_id,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["preferences"], ["High-protein"])
        self.assertEqual(data["plan"]["summary"], "Tailored meal plan")
        self.assertEqual(len(data["plan"]["breakfast"]["options"]), 1)

        persisted = list_meal_plans(self.owner_id)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["id"], data["id"])


class ChatHistoryAdminTests(TestCase):
    databases = {"default", "nutrition"}

    def test_chat_models_are_visible_read_only_and_use_core_app_database(self):
        from chat_history.admin import ChatConversationAdmin, ChatMessageAdmin

        request = RequestFactory().get("/admin/")
        request.user = MagicMock(is_staff=True)

        for model, model_admin_type in (
            (ChatConversation, ChatConversationAdmin),
            (ChatMessage, ChatMessageAdmin),
        ):
            self.assertIn(model, admin.site._registry)
            model_admin = model_admin_type(model, admin.site)
            self.assertTrue(model_admin.has_module_permission(request))
            self.assertTrue(model_admin.has_view_permission(request))
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
            self.assertEqual(model_admin.get_queryset(request).db, "default")

    def test_staff_user_can_view_saved_conversations_in_admin(self):
        owner_id = str(uuid.uuid4())
        conversation = ChatConversation.objects.using("default").create(
            owner_id=owner_id,
            title="Admin-visible chat",
        )
        user = get_user_model().objects.create_superuser(
            username="chat-admin-test",
            email="chat-admin-test@example.com",
            password="test-password",
        )
        self.client.force_login(user)

        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chat conversations")
        self.assertContains(response, "Chat messages")

        changelist = self.client.get("/admin/chat_history/chatconversation/")
        self.assertEqual(changelist.status_code, 200)
        self.assertContains(changelist, conversation.title)


class UserCustomRecipeTests(TestCase):
    databases = {"default", "nutrition"}

    @classmethod
    def setUpTestData(cls):
        from nutrition.models import Food, FoodGroup, ProximateNutrient
        from backend.food_database.services import clear_food_lookup_cache

        clear_food_lookup_cache()
        grp_a, _ = FoodGroup.objects.get_or_create(code="A", defaults={"name": "Cereals and Millets"})
        grp_t, _ = FoodGroup.objects.get_or_create(code="T", defaults={"name": "Edible Oils and Fats"})
        grp_h, _ = FoodGroup.objects.get_or_create(code="H", defaults={"name": "Nuts and Oilseeds"})

        f_poha, _ = Food.objects.get_or_create(food_code="A011", defaults={"group": grp_a, "name": "Rice flakes"})
        ProximateNutrient.objects.get_or_create(
            food=f_poha, defaults={"energy_kcal": 346.0, "protein_g": 6.6, "carbohydrates_g": 77.3, "total_fat_g": 1.2, "total_fiber_g": 2.8}
        )

        f_coconut_oil, _ = Food.objects.get_or_create(food_code="T001", defaults={"group": grp_t, "name": "Coconut oil"})
        ProximateNutrient.objects.get_or_create(
            food=f_coconut_oil, defaults={"energy_kcal": 900.0, "protein_g": 0.0, "carbohydrates_g": 0.0, "total_fat_g": 100.0, "total_fiber_g": 0.0}
        )

        f_peanuts, _ = Food.objects.get_or_create(food_code="H012", defaults={"group": grp_h, "name": "Ground nut"})
        ProximateNutrient.objects.get_or_create(
            food=f_peanuts, defaults={"energy_kcal": 567.0, "protein_g": 25.8, "carbohydrates_g": 16.1, "total_fat_g": 49.2, "total_fiber_g": 8.5}
        )

        f_ghee, _ = Food.objects.get_or_create(food_code="T013", defaults={"group": grp_t, "name": "Ghee"})
        ProximateNutrient.objects.get_or_create(
            food=f_ghee, defaults={"energy_kcal": 900.0, "protein_g": 0.0, "carbohydrates_g": 0.0, "total_fat_g": 100.0, "total_fiber_g": 0.0}
        )

        f_rava, _ = Food.objects.get_or_create(food_code="A022", defaults={"group": grp_a, "name": "Semolina"})
        ProximateNutrient.objects.get_or_create(
            food=f_rava, defaults={"energy_kcal": 360.0, "protein_g": 12.0, "carbohydrates_g": 72.8, "total_fat_g": 1.0, "total_fiber_g": 3.9}
        )

    def setUp(self):
        from backend.food_database.services import clear_food_lookup_cache
        clear_food_lookup_cache()
        self.owner_id = str(uuid.uuid4())
        self.conversation_id = str(uuid.uuid4())

    def _create_message(self, dish_name="Avalakki", logged_to_tracker=False):
        return save_chat_message(
            owner_id=self.owner_id,
            conversation_id=self.conversation_id,
            user_query=f"I had {dish_name} for breakfast",
            transcription="",
            modalities=["text"],
            ai_response={
                "dish_name": dish_name,
                "recognized_input_summary": f"A bowl of {dish_name}",
                "ingredients": [
                    {
                        "ingredient_name": "Rice flakes",
                        "serving_size_description": "1 bowl",
                        "estimated_weight_grams": 100,
                        "confidence": 0.95,
                    },
                    {
                        "ingredient_name": "Mustard oil",
                        "serving_size_description": "1 tsp",
                        "estimated_weight_grams": 5,
                        "confidence": 0.95,
                    },
                ],
                "dietary_tags": ["Vegetarian"],
                "health_insights": ["Classic breakfast dish."],
            },
            logged_to_tracker=logged_to_tracker,
        )

    def test_customize_dish_recipe_creates_db_record_and_recalculates(self):
        msg = self._create_message("Avalakki")
        msg_id = str(msg.id)

        # Household uses Coconut oil (15g) instead of mustard oil, and added Peanuts (20g)
        custom_ingredients = [
            {"food_name": "Rice flakes", "estimated_weight_grams": 120, "serving_size_description": "1.2 cups"},
            {"food_name": "Coconut oil", "estimated_weight_grams": 15, "serving_size_description": "1 tbsp"},
            {"food_name": "Peanuts", "estimated_weight_grams": 20, "serving_size_description": "2 tbsp"},
        ]

        result = customize_dish_recipe(
            owner_id=self.owner_id,
            conversation_id=self.conversation_id,
            message_id=msg_id,
            customized_ingredients=custom_ingredients,
            dish_name="Mom's Special Avalakki",
            description="Traditional coastal Avalakki with roasted peanuts and coconut oil",
            notes="South Indian household recipe using coconut oil",
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["is_customized"])
        self.assertEqual(result["dish_name"], "Mom's Special Avalakki")
        self.assertEqual(result["description"], "Traditional coastal Avalakki with roasted peanuts and coconut oil")
        self.assertEqual(result["ai_dish_name"], "Avalakki")
        analysis = result["analysis"]
        self.assertIn("total_macronutrients", analysis)
        self.assertGreater(analysis["total_macronutrients"]["calories_kcal"], 0)

        # Verify UserCustomRecipe was persisted in the new database table
        saved_recipe = UserCustomRecipe.objects.using("default").filter(
            owner_id=self.owner_id, message_id=msg_id
        ).first()
        self.assertIsNotNone(saved_recipe)
        self.assertEqual(saved_recipe.dish_name, "Mom's Special Avalakki")
        self.assertEqual(saved_recipe.description, "Traditional coastal Avalakki with roasted peanuts and coconut oil")
        self.assertEqual(saved_recipe.ai_dish_name, "Avalakki")
        self.assertEqual(len(saved_recipe.customized_ingredients), 3)
        self.assertIn("coconut oil", saved_recipe.notes.lower())
        self.assertGreater(saved_recipe.total_macronutrients.get("calories_kcal", 0), 0)

        # Verify ChatMessage ai_response is updated
        msg.refresh_from_db()
        self.assertTrue(msg.ai_response.get("is_customized"))
        self.assertEqual(msg.ai_response.get("dish_name"), "Mom's Special Avalakki")
        self.assertEqual(msg.ai_response.get("recognized_input_summary"), "Traditional coastal Avalakki with roasted peanuts and coconut oil")
        self.assertEqual(len(msg.ai_response.get("ingredients", [])), 3)

    def test_customize_dish_recipe_cascades_to_tracked_meal(self):
        msg = self._create_message("Poha", logged_to_tracker=True)
        msg_id = str(msg.id)

        # Create a linked TrackedMeal
        tracked_meal = TrackedMeal.objects.using("default").create(
            owner_id=self.owner_id,
            conversation_id=self.conversation_id,
            source_message_id=msg_id,
            meal_title="Poha",
            macronutrients={"calories_kcal": 200, "protein_g": 5},
            items=[],
        )

        # User swaps cooking oil to Ghee (20g)
        custom_ingredients = [
            {"food_name": "Rice flakes", "estimated_weight_grams": 100, "serving_size_description": "1 cup"},
            {"food_name": "Ghee", "estimated_weight_grams": 20, "serving_size_description": "1.5 tbsp"},
        ]

        result = customize_dish_recipe(
            owner_id=self.owner_id,
            conversation_id=self.conversation_id,
            message_id=msg_id,
            customized_ingredients=custom_ingredients,
            dish_name="Poha",
            notes="Made with pure desi ghee",
        )

        self.assertTrue(result["is_customized"])
        tracked_meal.refresh_from_db()
        self.assertGreater(tracked_meal.macronutrients["calories_kcal"], 200)
        self.assertEqual(len(tracked_meal.items), 2)

    def test_reset_dish_recipe_reverts_to_baseline(self):
        msg = self._create_message("Avalakki")
        msg_id = str(msg.id)

        # Customize first
        customize_dish_recipe(
            owner_id=self.owner_id,
            conversation_id=self.conversation_id,
            message_id=msg_id,
            customized_ingredients=[{"food_name": "Ghee", "estimated_weight_grams": 30}],
            dish_name="Custom Avalakki",
            description="Customized avalakki recipe",
        )

        msg.refresh_from_db()
        self.assertTrue(msg.ai_response.get("is_customized"))
        self.assertEqual(msg.ai_response.get("dish_name"), "Custom Avalakki")

        # Revert back
        reset_res = reset_dish_recipe(
            owner_id=self.owner_id,
            conversation_id=self.conversation_id,
            message_id=msg_id,
        )
        self.assertFalse(reset_res["is_customized"])
        self.assertEqual(reset_res["dish_name"], "Avalakki")

        msg.refresh_from_db()
        self.assertFalse(msg.ai_response.get("is_customized"))
        self.assertEqual(msg.ai_response.get("dish_name"), "Avalakki")
        self.assertEqual(len(msg.ai_response.get("ingredients", [])), 2)

    def test_customize_recipe_api_endpoint(self):
        msg = self._create_message("Upma")
        msg_id = str(msg.id)

        response = self.client.post(
            f"/api/chat-history/conversations/{self.conversation_id}/messages/{msg_id}/customize-recipe",
            data={
                "owner_id": self.owner_id,
                "dish_name": "Upma",
                "notes": "Customized upma",
                "ingredients": [
                    {
                        "food_name": "Semolina",
                        "estimated_weight_grams": 80,
                        "serving_size_description": "1 cup",
                    },
                    {
                        "food_name": "Ghee",
                        "estimated_weight_grams": 15,
                        "serving_size_description": "1 tbsp",
                    },
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_customized"])
        self.assertEqual(data["dish_name"], "Upma")
        self.assertIn("analysis", data)
        self.assertGreater(data["analysis"]["total_macronutrients"]["calories_kcal"], 0)

    def test_customize_recipe_direct_endpoint(self):
        msg = self._create_message("Poha")
        msg_id = str(msg.id)

        response = self.client.post(
            f"/api/chat-history/messages/{msg_id}/customize-recipe",
            data={
                "owner_id": self.owner_id,
                "dish_name": "Poha Customized",
                "notes": "Added peanuts and curry leaves",
                "ingredients": [
                    {
                        "food_name": "Rice flakes",
                        "estimated_weight_grams": 70,
                        "serving_size_description": "1 cup",
                    },
                    {
                        "food_name": "Peanuts",
                        "estimated_weight_grams": 20,
                        "serving_size_description": "2 tbsp",
                    },
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_customized"])
        self.assertEqual(data["dish_name"], "Poha Customized")

        # Test reset recipe endpoint
        reset_resp = self.client.post(
            f"/api/chat-history/messages/{msg_id}/reset-recipe?owner_id={self.owner_id}",
        )
        self.assertEqual(reset_resp.status_code, 200)
        reset_data = reset_resp.json()
        self.assertFalse(reset_data["is_customized"])

    def test_get_conversation_includes_message_id_in_result(self):
        msg = self._create_message("Dosa")
        from backend.assistant.services import get_conversation
        conv_data = get_conversation(self.owner_id, self.conversation_id)
        self.assertTrue(len(conv_data["messages"]) > 0)
        first_msg = conv_data["messages"][0]
        self.assertEqual(first_msg["result"].get("message_id"), first_msg["id"])

    def test_frontend_server_recipe_route_parsing(self):
        from unittest.mock import patch, MagicMock
        from web_frontend.server import FrontendHandler
        import io

        body = b'{"conversation_id": "conv-123", "message_id": "msg-456", "ingredients": []}'
        handler = object.__new__(FrontendHandler)
        handler.headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.client_address = ("127.0.0.1", 12345)
        handler._get_effective_owner_id = MagicMock(return_value="owner-1")
        handler._get_auth_token = MagicMock(return_value=None)
        handler._auth_headers = MagicMock(return_value={})
        handler._send_json = MagicMock()
        handler.path = "/chats/customize-recipe"

        # Mock httpx client post to verify URL called
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "ok", "is_customized": True}
            mock_client.post.return_value = mock_resp

            handler.do_POST()

            self.assertTrue(mock_client.post.called)
            called_url = mock_client.post.call_args[0][0]
            # Must NOT contain duplicate customize-recipe as msg_id!
            self.assertIn("/conversations/conv-123/messages/msg-456/customize-recipe", called_url)
            self.assertNotIn("customize-recipe/customize-recipe", called_url)

    def test_frontend_server_recipe_post_browser_redirect(self):
        from unittest.mock import patch, MagicMock
        from web_frontend.server import FrontendHandler
        import io

        body = b'{"conversation_id": "conv-123", "message_id": "msg-456", "ingredients": []}'
        handler = object.__new__(FrontendHandler)
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Accept": "text/html,application/xhtml+xml",
        }
        handler.rfile = io.BytesIO(body)
        handler.client_address = ("127.0.0.1", 12345)
        handler._get_effective_owner_id = MagicMock(return_value="owner-1")
        handler._get_auth_token = MagicMock(return_value=None)
        handler._auth_headers = MagicMock(return_value={})
        handler._send_redirect = MagicMock()
        handler.path = "/chats/customize-recipe"

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "ok", "is_customized": True}
            mock_client.post.return_value = mock_resp

            handler.do_POST()

            handler._send_redirect.assert_called_once_with("/chats/conv-123", status=303)

    def test_frontend_server_recipe_get_redirects_to_root(self):
        from unittest.mock import MagicMock
        from web_frontend.server import FrontendHandler

        handler = object.__new__(FrontendHandler)
        handler.headers = {"Accept": "text/html"}
        handler.client_address = ("127.0.0.1", 12345)
        handler._send_redirect = MagicMock()
        handler.path = "/chats/customize-recipe"

        handler.do_GET()

        handler._send_redirect.assert_called_once_with("/", status=303)

    def test_frontend_server_tracker_log_browser_redirect(self):
        from unittest.mock import patch, MagicMock
        from web_frontend.server import FrontendHandler
        import io

        body = b'{"conversation_id": "conv-789", "message_id": "msg-999", "meal_title": "Rice"}'
        handler = object.__new__(FrontendHandler)
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Accept": "text/html,application/xhtml+xml",
        }
        handler.rfile = io.BytesIO(body)
        handler.client_address = ("127.0.0.1", 12345)
        handler._get_effective_owner_id = MagicMock(return_value="owner-1")
        handler._get_auth_token = MagicMock(return_value=None)
        handler._auth_headers = MagicMock(return_value={})
        handler._send_redirect = MagicMock()
        handler.path = "/tracker/log"

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.is_success = True
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "ok", "meal": {"id": "log-1"}}
            mock_client.post.return_value = mock_resp

            handler.do_POST()

            handler._send_redirect.assert_called_once_with("/chats/conv-789", status=303)

    def test_frontend_server_tracker_log_get_redirects_to_tracker(self):
        from unittest.mock import MagicMock
        from web_frontend.server import FrontendHandler

        handler = object.__new__(FrontendHandler)
        handler.headers = {"Accept": "text/html"}
        handler.client_address = ("127.0.0.1", 12345)
        handler._send_redirect = MagicMock()
        handler.path = "/tracker/log"

        handler.do_GET()

        handler._send_redirect.assert_called_once_with("/tracker", status=303)

    def test_user_custom_recipe_admin_registration(self):
        from chat_history.admin import UserCustomRecipeAdmin
        self.assertIn(UserCustomRecipe, admin.site._registry)
        request = RequestFactory().get("/admin/")
        request.user = MagicMock(is_staff=True)
        model_admin = UserCustomRecipeAdmin(UserCustomRecipe, admin.site)
        self.assertTrue(model_admin.has_module_permission(request))

