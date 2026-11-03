"""
Dedicated Nutrition Tracker for NutriGuide PyScript Frontend.
Aggregates personal nutrition across Daily, Weekly, and Monthly periods.
STRICT TODAY DATE LOGIC: Automatically fetches today's local date and strictly
filters daily meals so yesterday's logs are never shown as today's logs.
"""

from datetime import date, datetime
import json
from pyscript import window
from pyscript.ffi import to_js  # dicts -> plain JS objects (not Map)

from ui import close_modal, open_modal, show_feedback


active_tracker_period = "daily"
tracker_cache = None
active_chat_log_button = None
active_chat_dish_analysis = None


def get_today_iso() -> str:
    """Return today's date in ISO YYYY-MM-DD format based on browser local time."""
    return date.today().isoformat()


def init_tracker_from_dom() -> None:
    """Load pre-rendered tracker JSON embedded in the HTML on first load."""
    global tracker_cache
    script_el = window.document.getElementById("initial-tracker-data")
    if script_el and script_el.textContent.strip():
        try:
            tracker_cache = json.loads(script_el.textContent)
        except Exception:
            tracker_cache = None


def render_tracker_period(period_key: str = None) -> None:
    """
    Render tracker stats, macros, vitamins, minerals, and meal logs.
    Enforces strict today filtering when viewing the Daily period.
    """
    global active_tracker_period, tracker_cache
    if period_key:
        active_tracker_period = period_key

    # Update tab buttons
    tabs = window.document.querySelectorAll("[data-tracker-tab]")
    for i in range(tabs.length):
        btn = tabs.item(i)
        is_sel = (btn.dataset.trackerTab == active_tracker_period)
        if is_sel:
            btn.classList.add("is-active")
            btn.setAttribute("aria-selected", "true")
        else:
            btn.classList.remove("is-active")
            btn.setAttribute("aria-selected", "false")

    if not tracker_cache or not isinstance(tracker_cache, dict):
        return

    periods = tracker_cache.get("periods") or {}
    period_data = periods.get(active_tracker_period)
    if not period_data:
        return

    today_str = get_today_iso()
    all_meals = period_data.get("meals") or []

    # STRICT TODAY DATE FILTER: When viewing the daily tracker, strictly exclude past days
    if active_tracker_period == "daily":
        meals = []
        for m in all_meals:
            c_date = m.get("consumed_date") or ""
            is_today = bool(m.get("is_today", False))
            # Include meal ONLY if consumed_date matches today's date or is_today is True
            if c_date == today_str or (not c_date and is_today):
                meals.append(m)
    else:
        meals = all_meals

    macros = period_data.get("macronutrients") or {}
    micros = period_data.get("micronutrients") or {"vitamins": [], "minerals": []}

    # Header badges
    period_badge = window.document.getElementById("tracker-period-badge")
    if period_badge:
        lbl = period_data.get("label") or active_tracker_period.upper()
        if active_tracker_period == "daily":
            lbl = f"Daily Tracker (Today - {datetime.now().strftime('%b %d, %Y')})"
        period_badge.textContent = lbl

    count_badge = window.document.getElementById("tracker-meals-count-badge")
    if count_badge:
        m_count = len(meals)
        count_badge.textContent = f"{m_count} {'meal' if m_count == 1 else 'meals'} logged"

    avg_badge = window.document.getElementById("tracker-daily-avg-badge")
    if avg_badge:
        avg_cals = round(period_data.get("daily_average_calories_kcal") or 0.0)
        avg_badge.innerHTML = f'Avg: <strong class="text-[#173c2c]">{avg_cals} kcal / day</strong>'

    # Hero Cards
    hero_cals = window.document.getElementById("tracker-hero-calories")
    if hero_cals:
        cals_val = round(macros.get("calories_kcal") or 0.0)
        hero_cals.innerHTML = f"{cals_val} <small>kcal</small>"

    hero_cals_sub = window.document.getElementById("tracker-hero-calories-sub")
    if hero_cals_sub:
        hero_cals_sub.textContent = f"Across {len(meals)} logged meals"

    hero_prot = window.document.getElementById("tracker-hero-protein")
    if hero_prot:
        prot_val = round(macros.get("protein_g") or 0.0, 1)
        hero_prot.innerHTML = f"{prot_val} <small>g</small>"

    hero_carbs = window.document.getElementById("tracker-hero-carbs")
    if hero_carbs:
        carb_val = round(macros.get("carbohydrates_g") or 0.0, 1)
        hero_carbs.innerHTML = f"{carb_val} <small>g</small>"

    hero_carbs_sub = window.document.getElementById("tracker-hero-carbs-sub")
    if hero_carbs_sub:
        sugar_val = round(macros.get("total_sugars_g") or 0.0, 1)
        hero_carbs_sub.textContent = f"Sugars: {sugar_val}g"

    hero_fat = window.document.getElementById("tracker-hero-fat")
    if hero_fat:
        fat_val = round(macros.get("total_fat_g") or 0.0, 1)
        hero_fat.innerHTML = f"{fat_val} <small>g</small>"

    hero_sat_chol = window.document.getElementById("tracker-hero-sat-chol")
    if hero_sat_chol:
        sat_val = round(macros.get("saturated_fat_g") or 0.0, 1)
        trans_val = round(macros.get("trans_fat_g") or 0.0, 1)
        hero_sat_chol.textContent = f"Sat: {sat_val}g · Trans: {trans_val}g"

    hero_fiber = window.document.getElementById("tracker-hero-fiber")
    if hero_fiber:
        fiber_val = round(macros.get("dietary_fiber_g") or 0.0, 1)
        hero_fiber.innerHTML = f"{fiber_val} <small>g</small>"

    # 13 Macronutrients list
    macro_items = window.document.querySelectorAll("#tracker-macros-list [data-macro-key]")
    for i in range(macro_items.length):
        dd = macro_items.item(i)
        key = dd.dataset.macroKey
        unit = dd.dataset.macroUnit or "g"
        val = float(macros.get(key) or 0.0)
        formatted = f"{val:.1f}" if unit in ("kcal", "mg") else f"{val:.2f}"
        dd.textContent = f"{formatted} {unit}"

    # Vitamins list
    vit_count = window.document.getElementById("tracker-vitamins-count")
    vit_list = window.document.getElementById("tracker-vitamins-list")
    vitamins = micros.get("vitamins") or []
    if vit_count:
        vit_count.textContent = f"{len(vitamins)} tracked"
    if vit_list:
        vit_list.replaceChildren()
        if not vitamins:
            vit_list.innerHTML = (
                '<p class="m-0 rounded-xl border border-dashed border-[#d5ded4] p-5 text-center text-xs text-[#748078]">'
                'No vitamin data recorded for this period yet. Log an analyzed dish from Chat using '
                '<strong>“Log to Tracker”</strong> to populate full USDA vitamin profiles.</p>'
            )
        else:
            for v in vitamins:
                row = window.document.createElement("div")
                row.className = "flex items-center justify-between py-2.5"
                amt = float(v.get("amount") or 0.0)
                unit = v.get("unit") or ""
                name = v.get("name") or "Vitamin"
                row.innerHTML = f'<span class="font-medium text-[#53645a]">{name}</span><strong class="text-[#173c2c]">{amt:.2f} {unit}</strong>'
                vit_list.append(row)

    # Minerals list
    min_count = window.document.getElementById("tracker-minerals-count")
    min_list = window.document.getElementById("tracker-minerals-list")
    minerals = micros.get("minerals") or []
    if min_count:
        min_count.textContent = f"{len(minerals)} tracked"
    if min_list:
        min_list.replaceChildren()
        if not minerals:
            min_list.innerHTML = (
                '<p class="m-0 rounded-xl border border-dashed border-[#d5ded4] p-5 text-center text-xs text-[#748078]">'
                'No mineral data recorded for this period yet. Log an analyzed dish from Chat using '
                '<strong>“Log to Tracker”</strong> to populate full mineral &amp; electrolyte data.</p>'
            )
        else:
            for m in minerals:
                row = window.document.createElement("div")
                row.className = "flex items-center justify-between py-2.5"
                amt = float(m.get("amount") or 0.0)
                unit = m.get("unit") or ""
                name = m.get("name") or "Mineral"
                row.innerHTML = f'<span class="font-medium text-[#53645a]">{name}</span><strong class="text-[#173c2c]">{amt:.2f} {unit}</strong>'
                min_list.append(row)

    # Meals list
    meals_badge = window.document.getElementById("tracker-meals-section-badge")
    if meals_badge:
        m_len = len(meals)
        meals_badge.textContent = f"{m_len} {'entry' if m_len == 1 else 'entries'}"

    meals_container = window.document.getElementById("tracker-meals-list")
    if meals_container:
        meals_container.replaceChildren()
        if not meals:
            meals_container.innerHTML = (
                '<div class="rounded-xl border border-dashed border-[#d5ded4] p-8 text-center">'
                '<p class="serif m-0 text-xl text-[#173c2c]">No meals logged in this period yet</p>'
                '<p class="mx-auto mt-1.5 max-w-[520px] text-xs leading-relaxed text-[#6d7871]">'
                'General questions in chat are never automatically added to your tracker. To log a meal, either say '
                '<em>“Log this meal to my tracker”</em> in chat/voice, click the <strong>“Log to Tracker”</strong> button next to any analyzed dish, '
                'or click <strong>“+ Log Custom Meal”</strong> above.</p></div>'
            )
        else:
            for item in meals:
                m_macs = item.get("macronutrients") or {}
                logged_via = item.get("logged_via") or "manual"
                if logged_via in ("explicit_chat", "text_intent", "voice_intent"):
                    via_label = "Logged via Chat/Voice Intent"
                elif logged_via in ("chat_button", "button"):
                    via_label = "Logged via Chat Button"
                else:
                    via_label = "Manual Entry"

                conv_id = item.get("conversation_id") or ""
                msg_id = item.get("source_message_id") or ""
                chat_turn_url = f"/chats/{conv_id}#turn-{msg_id}" if (conv_id and msg_id) else (f"/chats/{conv_id}" if conv_id else "")

                meal_title = item.get("meal_title") or "Meal"
                if chat_turn_url:
                    title_markup = (
                        f'<a href="{chat_turn_url}" hx-get="/chats/{conv_id}" hx-select="main[data-conversation-id]" '
                        f'hx-target="#chat-view" hx-swap="innerHTML" hx-push-url="{chat_turn_url}" hx-indicator="#chat-loading" '
                        f'class="group/title inline-flex items-center gap-1.5 text-sm font-bold text-[#173c2c] hover:text-[#2d6f51] hover:underline transition" title="Go to this meal in Chat">'
                        f'<span>{meal_title}</span>'
                        f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="opacity-60 group-hover/title:opacity-100 transition" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>'
                    )
                    chat_btn_markup = (
                        f'<a href="{chat_turn_url}" hx-get="/chats/{conv_id}" hx-select="main[data-conversation-id]" '
                        f'hx-target="#chat-view" hx-swap="innerHTML" hx-push-url="{chat_turn_url}" hx-indicator="#chat-loading" '
                        f'class="tracker-chat-link h-8 px-2.5 rounded-lg inline-flex items-center gap-1.5 text-xs font-semibold text-stone-600 hover:text-stone-900 bg-stone-100 hover:bg-stone-200 border border-stone-200 transition cursor-pointer" title="Jump to the original chat turn where this dish was analyzed">'
                        f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
                        f'<span>View in Chat</span></a>'
                    )
                else:
                    title_markup = f'<strong class="text-sm font-bold text-[#173c2c]">{meal_title}</strong>'
                    chat_btn_markup = ""

                article = window.document.createElement("article")
                article.className = "tracker-meal-card flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-2xl border border-stone-200 bg-white shadow-2xs hover:border-[#245c43]/40 transition"
                article.dataset.trackedMealRow = str(item.get("id"))

                c_cal = round(m_macs.get("calories_kcal") or 0.0)
                c_prot = round(m_macs.get("protein_g") or 0.0, 1)
                c_carb = round(m_macs.get("carbohydrates_g") or 0.0, 1)
                c_fat = round(m_macs.get("total_fat_g") or 0.0, 1)
                c_fiber = round(m_macs.get("dietary_fiber_g") or 0.0, 1)
                c_time = item.get("consumed_display") or item.get("consumed_time") or "Recorded"
                m_type = item.get("meal_type") or "Meal"
                log_id = str(item.get("id"))

                article.innerHTML = f"""
                  <div class="min-w-0 flex-1">
                    <div class="flex flex-wrap items-center gap-2">
                      {title_markup}
                      <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800">{m_type}</span>
                      <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-900 border border-amber-200" title="Consumption time">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                        <span>{c_time}</span>
                      </span>
                      <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-100 text-blue-800">{via_label}</span>
                    </div>
                    <p class="m-0 mt-2 text-xs text-stone-600">
                      <strong class="text-stone-900">{c_cal} kcal</strong> ·
                      Protein: <strong class="text-stone-800">{c_prot}g</strong> ·
                      Carbs: <strong class="text-stone-800">{c_carb}g</strong> ·
                      Fat: <strong class="text-stone-800">{c_fat}g</strong> ·
                      Fiber: <strong class="text-stone-800">{c_fiber}g</strong>
                    </p>
                  </div>
                  <div class="flex items-center gap-2">
                    {chat_btn_markup}
                    <button
                      type="button"
                      data-delete-tracked-meal-id="{log_id}"
                      class="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-xs font-semibold text-stone-500 hover:text-red-700 hover:bg-red-50 border border-stone-200 hover:border-red-200 transition cursor-pointer"
                      title="Remove this meal from your tracker"
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                      <span>Delete</span>
                    </button>
                  </div>
                """
                meals_container.append(article)
                if window.htmx:
                    window.htmx.process(article)


async def load_tracker_data(period: str = None) -> None:
    """
    Fetch updated tracker data for the active period from the backend.
    Sends today's date parameter so the backend strictly segments daily logs.
    """
    global active_tracker_period, tracker_cache
    if period:
        active_tracker_period = period

    tracker_page = window.document.querySelector('[data-page="tracker"]')
    if not tracker_page:
        return

    today_str = get_today_iso()
    url = f"/tracker/data?period={active_tracker_period}&date={today_str}"
    try:
        resp = await window.fetch(url, to_js({"headers": {"Accept": "application/json"}}))
        payload = await resp.json()
        if not resp.ok:
            detail = getattr(payload, "detail", "Could not load tracker data.")
            show_feedback("tracker-feedback", str(detail), True)
            return
        tracker_cache = payload
        render_tracker_period(active_tracker_period)
    except Exception as exc:
        show_feedback("tracker-feedback", f"Could not refresh tracker: {exc}", True)


async def handle_delete_tracked_meal(log_id: str) -> None:
    """Delete a tracked meal entry from the personal nutrition diary."""
    if not log_id:
        return

    # Instant UI removal for responsive feedback
    row = window.document.querySelector(f'[data-tracked-meal-row="{log_id}"]')
    if row:
        row.style.opacity = "0.3"
        row.style.pointerEvents = "none"

    try:
        resp = await window.fetch(
            f"/tracker/meals/{log_id}/delete",
            to_js({
                "method": "POST",
                "headers": {"Accept": "application/json"},
            }),
        )
        if not resp.ok:
            data = await resp.json()
            detail = getattr(data, "detail", "Could not delete tracked meal.")
            show_feedback("tracker-feedback", str(detail), True)
            if row:
                row.style.opacity = "1"
                row.style.pointerEvents = "auto"
            return

        if row:
            row.remove()
        show_feedback("tracker-feedback", "Meal entry deleted from tracker. ✓", False)
        # Reload latest tracker totals
        await load_tracker_data(active_tracker_period)
    except Exception as exc:
        show_feedback("tracker-feedback", f"Error deleting meal: {exc}", True)
        if row:
            row.style.opacity = "1"
            row.style.pointerEvents = "auto"


def open_chat_log_modal(button_el) -> None:
    """Populate and open the log-to-tracker modal when clicked from a chat dish card."""
    global active_chat_log_button, active_chat_dish_analysis
    active_chat_log_button = button_el

    dish_title = button_el.dataset.mealTitle or button_el.dataset.dishTitle or "Analyzed Dish"
    cals = button_el.dataset.calories or button_el.dataset.cals or "0"
    protein = button_el.dataset.protein or "0"
    carbs = button_el.dataset.carbs or "0"
    fat = button_el.dataset.fat or "0"
    fiber = button_el.dataset.fiber or "0"

    title_input = window.document.getElementById("log-modal-meal-title")
    if title_input:
        title_input.value = dish_title

    conv_input = window.document.getElementById("log-modal-conversation-id")
    if conv_input:
        conv_input.value = button_el.dataset.conversationId or ""

    msg_input = window.document.getElementById("log-modal-message-id")
    if msg_input:
        msg_input.value = button_el.dataset.messageId or ""

    # Populate preview chips
    chips_container = window.document.getElementById("log-modal-macros-preview")
    if chips_container:
        chips_container.innerHTML = f"""
          <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-800 border border-emerald-200">{cals} kcal</span>
          <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-800 border border-blue-200">Protein: {protein}g</span>
          <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-800 border border-amber-200">Carbs: {carbs}g</span>
          <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-rose-50 text-rose-800 border border-rose-200">Fat: {fat}g</span>
          <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200">Fiber: {fiber}g</span>
        """

    # Reset time option to 'now'
    now_radio = window.document.getElementById("log-modal-time-now")
    if now_radio:
        now_radio.checked = True
    custom_container = window.document.getElementById("log-modal-custom-time-container")
    if custom_container:
        custom_container.classList.add("hidden")

    # Auto-infer meal category by current hour
    current_hour = datetime.now().hour
    if 5 <= current_hour < 11:
        cat = "breakfast"
    elif 11 <= current_hour < 16:
        cat = "lunch"
    elif 16 <= current_hour < 19:
        cat = "snacks"
    else:
        cat = "dinner"

    cat_radio = window.document.getElementById(f"log-modal-cat-{cat}")
    if cat_radio:
        cat_radio.checked = True

    feedback = window.document.getElementById("log-modal-feedback")
    if feedback:
        feedback.classList.add("hidden")

    open_modal("log-to-tracker-modal")


async def handle_submit_chat_log(form) -> None:
    """Confirm and post chat-analyzed dish to user's personal tracker."""
    global active_chat_log_button
    title_inp = window.document.getElementById("log-modal-meal-title")
    meal_title = (title_inp.value if title_inp else "").strip() or "Logged Meal"
    cat_checked = form.querySelector('input[name="log_modal_category"]:checked')
    meal_type = (cat_checked.value if cat_checked else "Meal").capitalize()

    time_checked = form.querySelector('input[name="log_modal_time_option"]:checked')
    time_option = time_checked.value if time_checked else "now"

    consumed_at = None
    if time_option == "custom":
        dt_input = window.document.getElementById("log-modal-custom-datetime")
        consumed_at = dt_input.value if dt_input else None

    c_el = window.document.getElementById("log-modal-conversation-id")
    m_el = window.document.getElementById("log-modal-message-id")
    conv_id = (c_el.value if c_el else "") or (active_chat_log_button.dataset.conversationId if active_chat_log_button else "")
    msg_id = (m_el.value if m_el else "") or (active_chat_log_button.dataset.messageId if active_chat_log_button else "")

    submit_btn = window.document.getElementById("log-modal-submit-btn")
    if submit_btn:
        submit_btn.disabled = True

    show_feedback("log-modal-feedback", "Logging meal to tracker...", False)

    try:
        payload = {
            "conversation_id": conv_id,
            "message_id": msg_id,
            "meal_title": meal_title,
            "meal_type": meal_type,
            "time_option": time_option,
            "consumed_at": consumed_at,
            "logged_via": "chat_button",
        }
        resp = await window.fetch(
            "/tracker/log",
            to_js({
                "method": "POST",
                "headers": {"Content-Type": "application/json", "Accept": "application/json"},
                "body": json.dumps(payload),
            }),
        )
        data = await resp.json()
        if not resp.ok:
            detail = getattr(data, "detail", "Could not log meal.")
            show_feedback("log-modal-feedback", str(detail), True)
            if submit_btn:
                submit_btn.disabled = False
            return

        # Success: update chat turn button to logged state
        if active_chat_log_button:
            active_chat_log_button.disabled = True
            active_chat_log_button.className = "turn-action-btn turn-action-logged inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-50 text-emerald-800 border border-emerald-300 opacity-90 cursor-default"
            active_chat_log_button.innerHTML = (
                '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>'
                '<span>Logged to Tracker ✓</span>'
            )

        close_modal("log-to-tracker-modal")
        if submit_btn:
            submit_btn.disabled = False

        # Refresh tracker view if active
        await load_tracker_data(active_tracker_period)
    except Exception as exc:
        show_feedback("log-modal-feedback", f"Network error: {exc}", True)
        if submit_btn:
            submit_btn.disabled = False


async def handle_submit_manual_tracker_log(form) -> None:
    """Submit a custom manual meal entry to the tracker."""
    title_input = form.querySelector('input[name="meal_title"]')
    type_checked = form.querySelector('input[name="meal_type"]:checked')
    cal_input = form.querySelector('input[name="calories_kcal"]')
    prot_input = form.querySelector('input[name="protein_g"]')
    carb_input = form.querySelector('input[name="carbohydrates_g"]')
    fat_input = form.querySelector('input[name="total_fat_g"]')
    fiber_input = form.querySelector('input[name="dietary_fiber_g"]')
    time_checked = form.querySelector('input[name="time_option"]:checked')
    custom_dt = form.querySelector('input[name="consumed_at"]')

    meal_title = (title_input.value if title_input else "").strip() or "Custom Meal"
    meal_type = (type_checked.value if type_checked else "Meal").capitalize()
    time_option = time_checked.value if time_checked else "now"
    consumed_at = custom_dt.value if (time_option == "custom" and custom_dt) else None

    def parse_float(inp):
        try:
            return float(inp.value) if (inp and inp.value) else 0.0
        except ValueError:
            return 0.0

    payload = {
        "meal_title": meal_title,
        "meal_type": meal_type,
        "calories_kcal": parse_float(cal_input),
        "protein_g": parse_float(prot_input),
        "carbohydrates_g": parse_float(carb_input),
        "total_fat_g": parse_float(fat_input),
        "dietary_fiber_g": parse_float(fiber_input),
        "time_option": time_option,
        "consumed_at": consumed_at,
        "logged_via": "manual",
    }

    show_feedback("manual-tracker-feedback", "Logging meal...", False)
    submit_btn = form.querySelector('button[type="submit"]')
    if submit_btn:
        submit_btn.disabled = True

    try:
        resp = await window.fetch(
            "/tracker/log",
            to_js({
                "method": "POST",
                "headers": {"Content-Type": "application/json", "Accept": "application/json"},
                "body": json.dumps(payload),
            }),
        )
        data = await resp.json()
        if not resp.ok:
            detail = getattr(data, "detail", "Could not log custom meal.")
            show_feedback("manual-tracker-feedback", str(detail), True)
            if submit_btn:
                submit_btn.disabled = False
            return

        close_modal("manual-tracker-modal")
        if submit_btn:
            submit_btn.disabled = False
        show_feedback("tracker-feedback", f"Added '{meal_title}' to your tracker! ✓", False)
        await load_tracker_data(active_tracker_period)
    except Exception as exc:
        show_feedback("manual-tracker-feedback", f"Error: {exc}", True)
        if submit_btn:
            submit_btn.disabled = False
