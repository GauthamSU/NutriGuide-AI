import tempfile
import uuid
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from chat_history.models import ChatConversation, ChatMessage, MealPlanHistory
from chat_history.services import get_conversation, list_conversations, save_chat_message, save_meal_plan, list_meal_plans
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
