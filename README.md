# NutriGuide-AI Backend API

Multimodal (Text, Image, Voice) Food Nutrient Analysis API built with **Django Ninja** and **LangGraph**, powered by a comprehensive relational reference database parsed from the **Indian Food Composition Tables (IFCT 2017)** (ICMR - National Institute of Nutrition). Inference can use either local Gemma 4 through **llama.cpp** or Google **Gemini** through its OpenAI-compatible API.

- 📊 **Architecture & Flowchart**: See [flowchart.md](file:///d:/Agentic_AI/NutriGuide-AI/flowchart.md) for the end-to-end processing and ingestion flows.
- 🗄️ **Database Schema & ER Diagrams**: See [er_diagrams.md](file:///d:/Agentic_AI/NutriGuide-AI/er_diagrams.md) for the complete relational satellite schema.

---

## Quick Start

### 1. Configure the environment
Create a local `.env` from the tracked example:

```powershell
Copy-Item .env.example .env
```

Choose the inference backend in `.env` with `INFERENCE_BACKEND`:

- `local` uses the local llama.cpp server and the configured Gemma model files.
- `gemini` uses the Gemini API. Set `GEMINI_API_KEY` to your own API key and, optionally, change `GEMINI_MODEL_NAME`.

Do not commit `.env`; it contains local configuration and may contain secrets. The `.env.example` file is safe to commit and should contain placeholders only.

### 2. Start the selected inference backend

For `INFERENCE_BACKEND=local`, start the local Gemma 4 multimodal server (`llama-server.exe`). Run the helper script in a terminal to start it on `http://127.0.0.1:8080`:

```powershell
.\scripts\start_llama_server.ps1
```

For `INFERENCE_BACKEND=gemini`, no local inference server is needed; make sure the API key is set in `.env`.

### 3. Start the Django Ninja API server
Run the Django server using the project's `venv`:

```powershell
.\venv\Scripts\python.exe manage.py runserver 8000
```

Open the interactive Swagger UI at:
- **`http://127.0.0.1:8000/api/docs`**

The health endpoint (`/api/nutrition/health`) reports the active inference backend and its connectivity status.

### 4. Start the standalone web frontend
In another terminal, run its independent static server:

```powershell
.\venv\Scripts\python.exe web_frontend\server.py
```

The frontend is served at **`http://127.0.0.1:5500/`**; the API and Swagger UI remain on port `8000`. Frontend page routes are defined separately in `web_frontend/urls.py`, and Django's URL configuration contains only API/admin routes.

The frontend reads its API origin from `web_frontend/config.json` (or `API_BASE_URL` in the frontend server environment). The browser submits to the frontend server, which forwards the request to the API and renders the response using Jinja templates. This server-side proxy means the browser does not need direct cross-origin API access.

The UI uses Jinja templates in `web_frontend/templates`, split into page templates and reusable components. The frontend server logs browser requests, forwarded API request details, API response status/body excerpts, and request timing to its terminal. Tailwind is compiled to static CSS with:

```powershell
cd web_frontend
npm install
npm run build:css
```

Node/npm is only required to build the CSS; the deployed frontend is Jinja-rendered HTML and static CSS, served independently from Django.

### 5. Frontend Architecture: Pure Python with PyScript (Strict Zero-JavaScript Policy)

> [!IMPORTANT]
> **Strict Policy for Developers and AI Coding Agents**:
> NutriGuide-AI is intentionally engineered as a **100% pure Python web application**.
> - **NO JavaScript files (`.js`)** are permitted in the client-side codebase.
> - **NO `<script>` application blocks or inline JS attributes** (`onclick="..."`, `onsubmit="..."`, `onchange="..."`) are permitted in HTML templates.
> - All client-side reactivity, event delegation, DOM manipulation, modals, and asynchronous state handling **MUST be written exclusively in Python using PyScript / Pyodide** under `web_frontend/src/` (`main.py`, `chat.py`, `tracker.py`, `groups.py`, `meal_planner.py`, `profile.py`, `auth.py`, `ui.py`).
> - Future coding tasks and AI agent calls must preserve this pure-Python constraint.

All browser-side interactivity uses:
1. **PyScript / Pyodide (Python 3.14 WebAssembly)**: Executes Python modules directly in the browser. Global event handlers use `@when("click", "body")`, `@when("submit", "body")`, and `@when("change", "body")` in `web_frontend/src/main.py` to route events to domain modules.
2. **HTMX**: Declarative server-side swaps (`hx-post`, `hx-target`, `hx-swap="outerHTML"`) to fetch server-rendered Jinja fragments without client JavaScript.

---

## Indian Household Recipe Customization & Personalization Engine

Every Indian household cooks differently. The same dish (e.g. *Avalakki*, *Poha*, *Khichdi*, *Sambar*) uses distinct staple fats and ingredients across regions:
- **Cooking Oils & Fats**: Coconut oil in Kerala/Coastal Karnataka, Mustard oil in Bengal/Bihar/UP, Gingelly/Sesame oil in Tamil Nadu, and Desi Ghee in North/Western India.
- **Custom Additions / Ratios**: Peanuts, curry leaves, cashews, vegetables, or custom gram portions.

### Features
1. **In-Place Transformation & Editable Title/Description**: Clicking **"Customize Recipe"** or the **"Edit"** button next to the dish title converts the static view into an interactive editable form directly in the card. Users can personalize the **Dish Title**, **Dish Description / Notes**, and constituent ingredients.
2. **Single-Line Composition**: Ingredient Name, Portion Description, Weight (grams), and Delete action display neatly on a single horizontal row across all viewports.
3. **Delete Confirmation Popup**: Deleting an ingredient row triggers a universal modal (`#confirm-delete-modal`) confirming the specific ingredient deletion before modifying the recipe.
4. **Quick-Add Staples**: Shortcut chips (`+ Ghee (15g)`, `+ Coconut oil (15g)`, `+ Mustard oil (15g)`, `+ Peanuts (20g)`, `+ Curry leaves (5g)`) allow adding common staples in one click.
5. **Verified IFCT 2017 Recalculation**: Submitting recalculates both macronutrients and micronutrients against the Indian Food Composition Tables (IFCT 2017) reference database.
6. **Live Tracker Sync**: If the meal was previously logged to the nutrition diary, saving the customized recipe automatically synchronizes the linked [`TrackedMeal`](file:///d:/Agentic_AI/NutriGuide-AI/backend/assistant/models.py) record with the new title and calculated nutrients.
7. **`UserCustomRecipe` Database Table**: Stores both baseline AI suggested values (`ai_dish_name`, `ai_description`, `original_ingredients`) and user-customized values (`dish_name`, `description`, `customized_ingredients`) to power future recommendation engines and fine-tune localized LLM models.
8. **Household Memory**: LangGraph's `identify_dish_node` queries `UserCustomRecipe` to automatically pre-populate known household dish names, descriptions, and ingredient preferences when analyzing future meals.

---

Chat conversations are stored in a separate `chat_history.sqlite3` database, not the nutrient database. Apply its schema separately:

```powershell
.\venv\Scripts\python.exe manage.py migrate --database=chat_history
```

The chat-history database stores submitted text, modality metadata, model-generated transcription and meal-identification output, plus uploaded image/audio files under `media/chat_history/`. Nutrient values are not persisted; opening a prior chat resolves its saved model-generated ingredient estimates against the current nutrient reference database. The browser receives a random owner cookie; this is a local history partition, not account authentication.

Chat rows are also available as read-only **Chat history → Chat conversations / Chat messages** sections in Django Admin (`/admin/`). Sign in with a staff account; these admin views read from the separate chat-history database.

---

## Production Database Ingestion (One-Off Step)

Follow these exact steps when initializing or deploying NutriGuide-AI to a staging or production environment.

### Step 1: Install Dependencies
Ensure all parsing and cryptographic dependencies are installed:

```bash
pip install -r requirements.txt
```
*(Crucial packages include `pymupdf`, `cryptography`, `pdfplumber`, `django`, and `django-ninja`.)*

### Step 2: Configure Database & Run Migrations
Configure your database settings in `.env` (SQLite for local dev or PostgreSQL for production). Then apply all schema migrations:

```bash
python manage.py makemigrations nutrition
python manage.py migrate
```

### Step 3: Verify Reference PDF Location
Verify that the reference PDF `IFCT2017_16122024.pdf` is present at:
```
raw_data/IFCT2017_16122024.pdf
```
*(If stored in another directory or mounted volume in production, pass `--pdf-path /path/to/IFCT2017_16122024.pdf`.)*

### Step 4: Execute the Ingestion Command
You can test the parser without writing to the database by using `--dry-run`:

```bash
# Preview parsing without DB writes
python manage.py ingest_ifct --dry-run
```

Execute the full transactional database ingestion:

```bash
# Full ingestion (writes all 20 groups, 542 foods, 4386 vernacular names, and 10 satellite tables)
python manage.py ingest_ifct --pdf-path raw_data/IFCT2017_16122024.pdf
```

*Alternative (standalone runner script)*:
```bash
python scripts/run_ifct_ingestion.py
```

### Step 5: Verify Ingestion Data Integrity
Run the built-in verification script to assert that all tables and multi-lingual records have been populated:

```bash
python scripts/verify_ingestion.py
```

Expected Output:
```text
==================================================
IFCT 2017 DATABASE VERIFICATION REPORT
==================================================
  Food Groups (A-T)               :    20
  Food Items (Foods + Oils)       :   542
  Vernacular Records              :  4386
  Table 1: Proximate Nutrients    :   542
  Tables 2 & 3: Vitamins          :   528
  Table 4: Carotenoids            :   323
  Table 5: Minerals               :   528
  Table 6: Sugars & Starch        :   314
  Tables 7 & 12: Fatty Acids      :   542
  Table 8: Amino Acids            :   527
  Table 9: Organic Acids          :   312
  Table 10: Polyphenols           :   303
  Table 11: Bioactives            :   305
==================================================
VERIFICATION COMPLETE: ALL SYSTEMS FUNCTIONING
==================================================
```

### Step 6: Run Automated Tests
Execute the unit test suite to confirm model relations, schema serialization, and API endpoints:

```bash
python manage.py test
```

---

## Production Deployment Checklist & Best Practices

1. **Database Engine**:
   - Use **PostgreSQL 14+** in production instead of SQLite.
   - Configure `CHAT_HISTORY_DB_ENGINE` and `CHAT_HISTORY_DB_*` independently from the nutrient database. Apply `python manage.py migrate --database=chat_history`.
   - Use a Django storage backend backed by object storage for chat uploads in production; the default local storage is for development only.
   - Configure connection pooling (e.g., via `django-db-geventpool`, `pgbouncer`, or Gunicorn worker threads).
   - Because the IFCT dataset is static ground-truth reference data (~542 food entities), enable in-memory caching (Redis / Memcached) for frequent food lookups.
2. **Environment Variables (`.env`)**:
   - `DEBUG=False`
   - `SECRET_KEY=<strong-unique-secret-key>`
   - `ALLOWED_HOSTS=api.yourdomain.com,127.0.0.1`
   - Set `INFERENCE_BACKEND=local` and configure `LLAMA_SERVER_BASE_URL` / `LLAMA_TIMEOUT_SECONDS` for a local inference server, or set `INFERENCE_BACKEND=gemini` and provide `GEMINI_API_KEY` / `GEMINI_MODEL_NAME`.
   - The supported environment variables and development defaults are listed in `.env.example`.
3. **Static Files & Admin**:
   - Collect static assets for the Django Admin interface:
     ```bash
     python manage.py collectstatic --noinput
     ```
   - Create the administrative superuser:
     ```bash
     python manage.py createsuperuser
     ```
4. **Inference Server Hardware Acceleration**:
   - For local inference, run `llama-server` on a GPU-enabled host (NVIDIA CUDA or Vulkan build).
   - Ensure `gemma-4-E2B-it-Q4_K_M.gguf` and `mmproj-F16.gguf` are accessible on fast NVMe storage.
   - For Gemini inference, secure and rotate the API key using your deployment's secret manager.

---

## AI Dish & Ingredient Identification + Ground-Truth Database Nutrition

NutriGuide-AI enforces a strict separation between **AI culinary perception** and **scientific nutrient calculation**:

1. **AI Perception Role**:
   - The multimodal LLM (Gemma 4 via `llama-server.exe`) is prompted **only** to identify the dish and its constituent ingredients with estimated edible weights (in grams) and culinary portions.
   - **Zero AI Hallucination**: The system prompt strictly prohibits the AI from guessing or estimating calories, macronutrients, or micronutrients.
2. **Database-Driven Nutrient Calculation**:
   - All identified ingredients are resolved against the **IFCT 2017 reference database** (`Food`, `FoodVernacularName`, and satellite tables).
   - Macronutrients and micronutrients are deterministically calculated by scaling the ground-truth per-100g database values to the ingredient's estimated portion.
3. **Missing Ingredient Flagging**:
   - Any ingredient not currently found in the database is flagged with `found_in_database: false` and explicitly added to `missing_ingredients`.
   - The API response notifies users/administrators so the unmapped ingredient can be reviewed and manually loaded into the database.

---

## API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/nutrition/health` | Verifies API status and the active inference backend's connectivity. |
| `POST` | `/api/nutrition/analyze/text` | Accepts JSON `{"text": "...", "user_id": "..."}`, identifies dish/ingredients via AI, and calculates database nutrients. |
| `POST` | `/api/nutrition/analyze` | Accepts `multipart/form-data` with `text`, `image` (JPEG/PNG/WebP), and/or `voice` (WAV/MP3). |
| `POST` | `/api/chat-history/conversations/{conv_id}/messages/{msg_id}/customize-recipe` | Customizes recipe ingredients/weights, recalculates IFCT nutrition, stores `UserCustomRecipe`, and updates `TrackedMeal`. |
| `POST` | `/api/chat-history/conversations/{conv_id}/messages/{msg_id}/reset-recipe` | Reverts customized recipe back to baseline AI ingredients. |

---

## Example Requests

### 1. Text-only Analysis (`POST /api/nutrition/analyze/text`)
```bash
curl -X POST "http://127.0.0.1:8000/api/nutrition/analyze/text" \
  -H "Content-Type: application/json" \
  -d '{"text": "2 boiled eggs, 1 slice whole wheat toast, and half an avocado"}'
```

### 2. Multimodal Analysis (`POST /api/nutrition/analyze`)
```bash
curl -X POST "http://127.0.0.1:8000/api/nutrition/analyze" \
  -F "text=What are the nutrients in my lunch?" \
  -F "image=@meal.jpg" \
  -F "voice=@voice_note.wav"
```

---

## Multi-Lingual & Situational Queries (Python / Django ORM)

### Multi-Lingual Food Search:
```python
from nutrition.models import FoodVernacularName

# Instant lookup in regional languages (Telugu, Tamil, Hindi, etc.)
matches = FoodVernacularName.objects.filter(name__icontains="Sajjalu").select_related("food")
for m in matches:
    print(f"[{m.language}] {m.name} -> {m.food.name} ({m.food.food_code})")
```

### Situational Nutrient Join:
```python
from nutrition.models import Food

# Querying only cardiovascular fatty acids and cholesterol
food = Food.objects.select_related("proximates", "fatty_acids").get(food_code="M001")
print(f"Cholesterol: {food.fatty_acids.cholesterol_mg} mg | DHA: {food.fatty_acids.dha_c22_6n3_mg} mg")
```
