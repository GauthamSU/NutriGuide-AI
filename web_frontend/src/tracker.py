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
    script_el = window.document.getElementById("initial-tracker-data") or window.document.getElementById("tracker-initial-json")
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

    # Update tab button visual active state
    tabs = window.document.querySelectorAll("[data-tracker-tab]")
    for i in range(tabs.length):
        btn = tabs.item(i)
        is_sel = (btn.dataset.trackerTab == active_tracker_period)
        if is_sel:
            btn.classList.add("is-active", "bg-[#173c2c]", "text-white", "font-bold", "shadow-xs")
            btn.classList.remove("text-stone-600", "hover:text-stone-900", "hover:bg-white/70", "font-semibold")
            btn.setAttribute("aria-selected", "true")
        else:
            btn.classList.remove("is-active", "bg-[#173c2c]", "text-white", "font-bold", "shadow-xs")
            btn.classList.add("text-stone-600", "hover:text-stone-900", "hover:bg-white/70", "font-semibold")
            btn.setAttribute("aria-selected", "false")

    if not tracker_cache or not isinstance(tracker_cache, dict):
        return

    periods = tracker_cache.get("periods") or {}
    period_data = periods.get(active_tracker_period)
    if not period_data:
        period_data = tracker_cache

    today_str = get_today_iso()
    all_meals = period_data.get("meals") or []

    # STRICT TODAY DATE FILTER: When viewing the daily tracker, strictly exclude past days
    if active_tracker_period == "daily":
        meals = []
        for m in all_meals:
            c_date = m.get("consumed_date") or ""
            is_today = bool(m.get("is_today", False))
            if is_today or c_date == today_str or not c_date:
                meals.append(m)
        if not meals and all_meals:
            meals = all_meals
    else:
        meals = all_meals

    macros = period_data.get("total_macronutrients") or period_data.get("macronutrients") or {}
    micros = period_data.get("total_micronutrients") or period_data.get("micronutrients") or {"vitamins": [], "minerals": []}

    period_mult = 1.0 if active_tracker_period == "daily" else (7.0 if active_tracker_period == "weekly" else 30.0)

    # Header badges & context bar
    period_badge = window.document.getElementById("tracker-period-badge")
    if period_badge:
        if active_tracker_period == "daily":
            period_badge.textContent = "Today's Intake (Daily View)"
        elif active_tracker_period == "weekly":
            period_badge.textContent = "Weekly Intake (Last 7 Days)"
        else:
            period_badge.textContent = "Monthly Intake (Last 30 Days)"

    sub_text = window.document.getElementById("tracker-period-subtext")
    if sub_text:
        if active_tracker_period == "daily":
            sub_text.textContent = "Showing meals & cumulative targets for today"
        elif active_tracker_period == "weekly":
            sub_text.textContent = "Showing meals & cumulative targets across the last 7 days"
        else:
            sub_text.textContent = "Showing meals & cumulative targets across the last 30 days"

    meals_count_el = window.document.getElementById("tracker-meals-count")
    if meals_count_el:
        meals_count_el.textContent = str(len(meals))

    # Hero Cards & Progress Bars
    # 1. Calories
    cal_val = float(macros.get("calories_kcal") or 0.0)
    cal_goal = 2000.0 * period_mult
    cal_pct = min(100, max(0, int(round((cal_val / cal_goal) * 100)))) if cal_goal > 0 else 0
    stat_c = window.document.getElementById("tracker-stat-calories")
    if stat_c:
        stat_c.textContent = f"{cal_val:.0f}"
    pct_c = window.document.getElementById("tracker-pct-calories")
    if pct_c:
        pct_c.textContent = f"{cal_pct}%"
    bar_c = window.document.getElementById("tracker-bar-calories")
    if bar_c:
        bar_c.style.width = f"{cal_pct}%"
    tgt_c = window.document.getElementById("tracker-target-calories")
    if tgt_c:
        tgt_c.textContent = f"Goal: {cal_goal:,.0f} kcal"

    # 2. Protein
    prot_val = float(macros.get("protein_g") or 0.0)
    prot_goal = 60.0 * period_mult
    prot_pct = min(100, max(0, int(round((prot_val / prot_goal) * 100)))) if prot_goal > 0 else 0
    stat_p = window.document.getElementById("tracker-stat-protein")
    if stat_p:
        stat_p.textContent = f"{prot_val:.1f}"
    pct_p = window.document.getElementById("tracker-pct-protein")
    if pct_p:
        pct_p.textContent = f"{prot_pct}%"
    bar_p = window.document.getElementById("tracker-bar-protein")
    if bar_p:
        bar_p.style.width = f"{prot_pct}%"
    tgt_p = window.document.getElementById("tracker-target-protein")
    if tgt_p:
        tgt_p.textContent = f"Goal: {prot_goal:.0f}g"

    # 3. Carbs
    carb_val = float(macros.get("carbohydrates_g") or 0.0)
    carb_goal = 250.0 * period_mult
    carb_pct = min(100, max(0, int(round((carb_val / carb_goal) * 100)))) if carb_goal > 0 else 0
    stat_carb = window.document.getElementById("tracker-stat-carbs")
    if stat_carb:
        stat_carb.textContent = f"{carb_val:.1f}"
    pct_carb = window.document.getElementById("tracker-pct-carbs")
    if pct_carb:
        pct_carb.textContent = f"{carb_pct}%"
    bar_carb = window.document.getElementById("tracker-bar-carbs")
    if bar_carb:
        bar_carb.style.width = f"{carb_pct}%"
    tgt_carb = window.document.getElementById("tracker-target-carbs")
    if tgt_carb:
        tgt_carb.textContent = f"Goal: {carb_goal:.0f}g"

    # 4. Fat
    fat_val = float(macros.get("total_fat_g") or 0.0)
    fat_goal = 65.0 * period_mult
    fat_pct = min(100, max(0, int(round((fat_val / fat_goal) * 100)))) if fat_goal > 0 else 0
    stat_f = window.document.getElementById("tracker-stat-fat")
    if stat_f:
        stat_f.textContent = f"{fat_val:.1f}"
    pct_f = window.document.getElementById("tracker-pct-fat")
    if pct_f:
        pct_f.textContent = f"{fat_pct}%"
    bar_f = window.document.getElementById("tracker-bar-fat")
    if bar_f:
        bar_f.style.width = f"{fat_pct}%"
    tgt_f = window.document.getElementById("tracker-target-fat")
    if tgt_f:
        tgt_f.textContent = f"Goal: {fat_goal:.0f}g"

    # 5. Fiber
    fib_val = float(macros.get("dietary_fiber_g") or 0.0)
    fib_goal = 30.0 * period_mult
    fib_pct = min(100, max(0, int(round((fib_val / fib_goal) * 100)))) if fib_goal > 0 else 0
    stat_fib = window.document.getElementById("tracker-stat-fiber")
    if stat_fib:
        stat_fib.textContent = f"{fib_val:.1f}"
    pct_fib = window.document.getElementById("tracker-pct-fiber")
    if pct_fib:
        pct_fib.textContent = f"{fib_pct}%"
    bar_fib = window.document.getElementById("tracker-bar-fiber")
    if bar_fib:
        bar_fib.style.width = f"{fib_pct}%"
    tgt_fib = window.document.getElementById("tracker-target-fiber")
    if tgt_fib:
        tgt_fib.textContent = f"Goal: {fib_goal:.0f}g"

    # 14 Macronutrients in #tracker-macronutrients-grid
    macro_items = window.document.querySelectorAll("#tracker-macronutrients-grid [data-macro-key]")
    for i in range(macro_items.length):
        dd = macro_items.item(i)
        key = dd.dataset.macroKey
        unit = dd.dataset.macroUnit or "g"
        try:
            daily_goal = float(dd.dataset.macroGoal or 60.0)
        except Exception:
            daily_goal = 60.0
        goal = daily_goal * period_mult
        val = float(macros.get(key) or 0.0)
        pct = min(100, max(0, int(round((val / goal) * 100)))) if goal > 0 else 0
        formatted = f"{val:.1f}" if unit in ("kcal", "mg") else f"{val:.1f}"
        dd.textContent = f"{formatted} {unit}"

        parent = dd.closest(".rounded-xl")
        if parent:
            pct_el = parent.querySelector(f'[data-macro-pct="{key}"]')
            if pct_el:
                pct_el.textContent = f"({pct}%)"
            bar_el = parent.querySelector(f'[data-macro-bar="{key}"]')
            if bar_el:
                bar_el.style.width = f"{pct}%"

    # Total Micronutrients (Vitamins & Minerals)
    micro_container = window.document.getElementById("tracker-micronutrients-container")
    if micro_container:
        vitamins = micros.get("vitamins") or []
        minerals = micros.get("minerals") or []

        def build_micro_col(items, label):
            if not items:
                return f'<p class="text-xs text-stone-400 italic">No {label.lower()} logged for this period yet.</p>'
            rows_html = "".join(
                f'<div class="flex justify-between items-center gap-2 border-b border-stone-100 py-1.5 text-xs">'
                f'<span class="text-stone-600 truncate" title="{it.get("name", "")}">{it.get("name", "")}</span>'
                f'<strong class="whitespace-nowrap font-semibold text-stone-900">{float(it.get("amount") or 0.0):.2f} {it.get("unit", "")}</strong>'
                f'</div>'
                for it in items
            )
            return f'<div class="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">{rows_html}</div>'

        micro_container.innerHTML = (
            '<h4 class="mb-2 mt-3 text-[10px] font-bold uppercase tracking-wider text-stone-500">Vitamins</h4>'
            + build_micro_col(vitamins, "Vitamins")
            + '<h4 class="mb-2 mt-4 text-[10px] font-bold uppercase tracking-wider text-stone-500">Minerals</h4>'
            + build_micro_col(minerals, "Minerals")
        )

    # Tracked Meal Logs Section
    meals_container = window.document.getElementById("tracker-meals-list")
    if meals_container:
        meals_container.replaceChildren()
        if not meals:
            meals_container.innerHTML = (
                '<div class="rounded-xl border border-dashed border-stone-200 p-8 text-center bg-stone-50/50">'
                '<p class="m-0 text-sm font-bold text-stone-700">No meals logged in this period yet</p>'
                '<p class="mx-auto mt-1 max-w-[480px] text-xs leading-relaxed text-stone-500">'
                'Log an analyzed dish from Chat by clicking the <strong>“Log to Tracker”</strong> button on any dish card, '
                'or click <strong>“+ Log Custom Meal”</strong> above.</p></div>'
            )
        else:
            for item in meals:
                m_macs = item.get("macronutrients") or {}
                c_cal = round((item.get("calories_kcal") or m_macs.get("calories_kcal") or 0))
                c_prot = round((item.get("protein_g") or m_macs.get("protein_g") or 0), 1)
                c_carb = round((item.get("carbohydrates_g") or m_macs.get("carbohydrates_g") or 0), 1)
                c_fat = round((item.get("total_fat_g") or m_macs.get("total_fat_g") or 0), 1)
                c_fiber = round((item.get("dietary_fiber_g") or m_macs.get("dietary_fiber_g") or 0), 1)

                m_title = item.get("meal_title") or "Logged Meal"
                m_type = item.get("meal_category") or item.get("meal_type") or "Meal"
                c_time = item.get("consumed_display") or item.get("consumed_time") or "Today"
                log_id = str(item.get("id"))
                conv_id = item.get("conversation_id") or ""

                chat_link_html = ""
                if conv_id:
                    chat_link_html = (
                        f'<a href="/" data-open-chat-id="{conv_id}" hx-post="/chats/open" '
                        f'hx-vals=\'{{"conversation_id": "{conv_id}"}}\' hx-target="#chat-view" '
                        f'hx-select="main" hx-swap="innerHTML" hx-push-url="/" '
                        f'class="inline-flex items-center gap-1 text-[11px] font-bold text-[#245c43] hover:underline">'
                        f'<span>View in Chat ↗</span></a>'
                    )

                notes_html = f'<p class="text-xs text-stone-500 mt-0.5 line-clamp-1 m-0">{item.get("serving_notes")}</p>' if item.get("serving_notes") else ""

                article = window.document.createElement("article")
                article.className = "flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-stone-200/90 bg-white p-4 hover:border-emerald-300 transition shadow-2xs"
                article.dataset.trackedMealId = log_id
                article.setAttribute("data-tracked-meal-row", log_id)

                article.innerHTML = f"""
                  <div class="min-w-0 flex-1">
                    <div class="flex flex-wrap items-center gap-2 mb-1">
                      <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-[#245c43] border border-emerald-200">
                        {m_type}
                      </span>
                      <span class="text-[11px] font-medium text-stone-400">
                        {c_time}
                      </span>
                      {chat_link_html}
                    </div>
                    <h4 class="font-bold text-stone-900 text-sm truncate m-0">{m_title}</h4>
                    {notes_html}
                  </div>

                  <div class="flex flex-wrap items-center gap-2 sm:justify-end">
                    <div class="flex flex-wrap items-center gap-1.5 text-xs">
                      <span class="px-2.5 py-1 rounded-lg bg-emerald-50 text-[#173c2c] font-bold border border-emerald-200">{c_cal} kcal</span>
                      <span class="px-2 py-1 rounded-lg bg-stone-100 text-stone-700 font-semibold">P: {c_prot}g</span>
                      <span class="px-2 py-1 rounded-lg bg-stone-100 text-stone-700 font-semibold">C: {c_carb}g</span>
                      <span class="px-2 py-1 rounded-lg bg-stone-100 text-stone-700 font-semibold">F: {c_fat}g</span>
                    </div>
                    <button
                      type="button"
                      data-share-meal-to-group
                      data-meal-title="{m_title}"
                      data-meal-category="{m_type}"
                      data-calories="{c_cal}"
                      data-protein="{c_prot}"
                      data-carbs="{c_carb}"
                      data-fat="{c_fat}"
                      data-fiber="{c_fiber}"
                      class="px-2.5 py-1.5 rounded-lg border border-emerald-200 bg-emerald-50/70 hover:bg-emerald-100 text-[#173c2c] text-[11px] font-bold transition cursor-pointer inline-flex items-center gap-1"
                      title="Share this meal to a Nutrition Group"
                    >
                      <span>⇄ Share to Group</span>
                    </button>
                    <button
                      type="button"
                      data-delete-tracked-meal-id="{log_id}"
                      class="h-8 w-8 rounded-lg flex items-center justify-center text-stone-400 hover:text-red-600 hover:bg-red-50 transition cursor-pointer"
                      title="Remove meal from tracker"
                      aria-label="Remove meal from tracker"
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
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

    today_str = get_today_iso()
    url = f"/tracker/data?period={active_tracker_period}&date={today_str}"
    try:
        resp = await window.fetch(url, to_js({"headers": {"Accept": "application/json"}}))
        text = await resp.text()
        payload = json.loads(text) if text else {}
        if not resp.ok or not isinstance(payload, dict):
            detail = payload.get("detail", "Could not load tracker data.") if isinstance(payload, dict) else "Could not load tracker data."
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
