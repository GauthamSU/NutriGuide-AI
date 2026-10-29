# NutriGuide-AI Backend API

Multimodal (Text, Image, Voice) Food Nutrient Analysis API built with **Django Ninja**, **LangGraph**, and local **Gemma 4 E2B** (`gemma-4-E2B-it-Q4_K_M.gguf` + `mmproj-F16.gguf`) via **llama.cpp**, powered by a comprehensive relational reference database parsed from the **Indian Food Composition Tables (IFCT 2017)** (ICMR - National Institute of Nutrition).

- 📊 **Architecture & Flowchart**: See [flowchart.md](file:///d:/Agentic_AI/NutriGuide-AI/flowchart.md) for the end-to-end processing and ingestion flows.
- 🗄️ **Database Schema & ER Diagrams**: See [er_diagrams.md](file:///d:/Agentic_AI/NutriGuide-AI/er_diagrams.md) for the complete relational satellite schema.

---

## Quick Start (Local Development)

### 1. Start Local Gemma 4 Multimodal Server (`llama-server.exe`)
Run the helper script in a terminal to start `D:\llama-cpp\llama-server.exe` on `http://127.0.0.1:8080`:

```powershell
.\scripts\start_llama_server.ps1
```

### 2. Start the Django Ninja API Server
In a second terminal, run the Django server using the project's `venv`:

```powershell
.\venv\Scripts\python.exe manage.py runserver 8000
```

Open the interactive Swagger UI at:
- **`http://127.0.0.1:8000/api/docs`**

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
   - Configure connection pooling (e.g., via `django-db-geventpool`, `pgbouncer`, or Gunicorn worker threads).
   - Because the IFCT dataset is static ground-truth reference data (~542 food entities), enable in-memory caching (Redis / Memcached) for frequent food lookups.
2. **Environment Variables (`.env`)**:
   - `DEBUG=False`
   - `SECRET_KEY=<strong-unique-secret-key>`
   - `ALLOWED_HOSTS=api.yourdomain.com,127.0.0.1`
   - `LLAMA_CPP_BASE_URL=http://<inference-host>:8080`
   - `LLAMA_CPP_TIMEOUT_SECONDS=45`
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
   - For lower inference latency, run `llama-server` on a GPU-enabled host (NVIDIA CUDA or Vulkan build).
   - Ensure `gemma-4-E2B-it-Q4_K_M.gguf` and `mmproj-F16.gguf` are accessible on fast NVMe storage.

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
| `GET` | `/api/nutrition/health` | Verifies API status, `llama-server` connectivity, and model file availability. |
| `POST` | `/api/nutrition/analyze/text` | Accepts JSON `{"text": "...", "user_id": "..."}`, identifies dish/ingredients via AI, and calculates database nutrients. |
| `POST` | `/api/nutrition/analyze` | Accepts `multipart/form-data` with `text`, `image` (JPEG/PNG/WebP), and/or `voice` (WAV/MP3). |

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
