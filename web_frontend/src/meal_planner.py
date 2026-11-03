"""
AI Meal Planner for NutriGuide PyScript Frontend.
Generates personalized meal plans, manages voice notes/images, and archives history.
Zero JavaScript. Pure Python.
"""

from datetime import datetime
import json
from pyscript import window
from pyscript.ffi import to_js  # dicts -> plain JS objects (not Map)

from ui import (
    DIET_LABELS,
    DURATION_LABELS,
    MEAL_SECTION_META,
    encode_audio_buffer_to_wav,
    error_detail,
    read_json,
    show_feedback,
)


meal_plan_history = []
mp_recording = {
    "stream": None,
    "recorder": None,
    "chunks": [],
    "image_url": None,
}


def set_meal_plan_error(message: str) -> None:
    """Toggle visibility and message content of the meal planner error container."""
    err = window.document.getElementById("meal-plan-error")
    if not err:
        return
    err.textContent = message or ""
    if message:
        err.classList.remove("hidden")
    else:
        err.classList.add("hidden")


def sync_meal_plan_mode_ui(is_generating: bool = False) -> None:
    """Synchronize the header mode badge with current form radio choices and update active selection classes."""
    mp_form = window.document.getElementById("meal-plan-form")
    if not mp_form:
        return
    dur_checked = mp_form.querySelector('input[name="duration"]:checked')
    diet_checked = mp_form.querySelector('input[name="diet_type"]:checked')

    duration = dur_checked.value if dur_checked else "daily"
    diet_type = diet_checked.value if diet_checked else "veg"

    dur_label = DURATION_LABELS.get(duration, f"{duration.capitalize()} Plan")
    diet_label = DIET_LABELS.get(diet_type, diet_type.capitalize())

    # Update is-selected class on duration tabs
    dur_tabs = mp_form.querySelectorAll("[data-duration-tab]")
    for i in range(dur_tabs.length):
        tab = dur_tabs.item(i)
        radio = tab.querySelector('input[name="duration"]')
        if radio and radio.checked:
            tab.classList.add("is-selected")
        else:
            tab.classList.remove("is-selected")

    # Update is-selected class on diet cards
    diet_tabs = mp_form.querySelectorAll("[data-diet-tab]")
    for i in range(diet_tabs.length):
        card = diet_tabs.item(i)
        radio = card.querySelector('input[name="diet_type"]')
        if radio and radio.checked:
            card.classList.add("is-selected")
        else:
            card.classList.remove("is-selected")

    active_badge = window.document.getElementById("meal-plan-active-mode-badge")
    if active_badge:
        active_badge.textContent = (
            f"Generating {dur_label} · {diet_label}…"
            if is_generating
            else f"{dur_label} · {diet_label}"
        )

    submit_btn = window.document.getElementById("generate-meal-plan")
    if submit_btn and not submit_btn.disabled and not is_generating:
        label_el = window.document.getElementById("generate-meal-plan-label")
        if label_el:
            label_el.textContent = f"Create {duration} meal plan"


def toggle_meal_plan_preference(btn) -> None:
    """Toggle selected state of a health focus pill."""
    if not btn:
        return
    is_pressed = btn.getAttribute("aria-pressed") == "true"
    new_state = not is_pressed
    btn.setAttribute("aria-pressed", "true" if new_state else "false")
    if new_state:
        btn.classList.add("is-selected")
    else:
        btn.classList.remove("is-selected")

    hidden_input = window.document.getElementById("meal-plan-preferences-input")
    if hidden_input:
        prefs = get_selected_meal_plan_preferences()
        hidden_input.value = json.dumps(prefs)


def get_selected_meal_plan_preferences() -> list[str]:
    """Return the list of currently active health focus preferences."""
    btns = window.document.querySelectorAll(
        '.meal-preference[aria-pressed="true"], .meal-preference.is-selected'
    )
    prefs = []
    for i in range(btns.length):
        b = btns.item(i)
        p = b.dataset.preference or b.textContent.strip()
        if p and p not in prefs:
            prefs.append(p)
    return prefs


def trigger_meal_plan_image_picker() -> None:
    """Open system file picker for meal plan food/ingredient photo."""
    inp = window.document.getElementById("meal-plan-image")
    if inp:
        inp.click()


def trigger_meal_plan_audio_upload() -> None:
    """Open system file picker for audio file (WAV/MP3)."""
    inp = window.document.getElementById("meal-plan-voice")
    if inp:
        inp.click()


def update_meal_plan_attachment_chips() -> None:
    """Render removable preview chips for attached food photos and voice notes with Tailwind classes."""
    container = window.document.getElementById("meal-plan-attachment-chips")
    if not container:
        return
    container.replaceChildren()

    img_input = window.document.getElementById("meal-plan-image")
    voice_input = window.document.getElementById("meal-plan-voice")

    if img_input and img_input.files and img_input.files.length:
        file = img_input.files.item(0)
        if mp_recording.get("image_url"):
            try:
                window.URL.revokeObjectURL(mp_recording["image_url"])
            except Exception:
                pass
        mp_recording["image_url"] = window.URL.createObjectURL(file)

        chip = window.document.createElement("span")
        chip.className = "inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-emerald-200 bg-emerald-50/90 text-xs font-semibold text-emerald-900 shadow-sm"
        thumb = window.document.createElement("img")
        thumb.src = mp_recording["image_url"]
        thumb.alt = file.name
        thumb.className = "w-5 h-5 rounded-md object-cover border border-emerald-300"

        label = window.document.createElement("span")
        label.className = "truncate max-w-[150px]"
        label.textContent = file.name

        remove_btn = window.document.createElement("button")
        remove_btn.type = "button"
        remove_btn.className = "ml-1 h-4 w-4 rounded-full flex items-center justify-center text-stone-400 hover:text-red-600 hover:bg-red-100 transition text-sm cursor-pointer"
        remove_btn.textContent = "×"
        remove_btn.title = "Remove photo"
        remove_btn.dataset.removeAttachment = "image"

        chip.append(thumb, label, remove_btn)
        container.append(chip)

    if voice_input and voice_input.files and voice_input.files.length:
        file = voice_input.files.item(0)
        chip = window.document.createElement("span")
        chip.className = "inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-sky-200 bg-sky-50/90 text-xs font-semibold text-sky-900 shadow-sm"

        icon = window.document.createElement("span")
        icon.className = "font-bold text-sky-700"
        icon.textContent = "♪"

        label = window.document.createElement("span")
        label.className = "truncate max-w-[150px]"
        label.textContent = file.name or "Voice note.wav"

        remove_btn = window.document.createElement("button")
        remove_btn.type = "button"
        remove_btn.className = "ml-1 h-4 w-4 rounded-full flex items-center justify-center text-stone-400 hover:text-red-600 hover:bg-red-100 transition text-sm cursor-pointer"
        remove_btn.textContent = "×"
        remove_btn.title = "Remove voice note"
        remove_btn.dataset.removeAttachment = "voice"

        chip.append(icon, label, remove_btn)
        container.append(chip)


def remove_attachment(kind: str) -> None:
    """Clear an attached photo or recorded voice note."""
    if kind == "image":
        img_input = window.document.getElementById("meal-plan-image")
        if img_input:
            img_input.value = ""
        if mp_recording.get("image_url"):
            try:
                window.URL.revokeObjectURL(mp_recording["image_url"])
            except Exception:
                pass
            mp_recording["image_url"] = None
    elif kind == "voice":
        voice_input = window.document.getElementById("meal-plan-voice")
        if voice_input:
            voice_input.value = ""
    update_meal_plan_attachment_chips()


async def toggle_meal_plan_voice_recording() -> None:
    """Start or stop recording a voice note for meal planning via MediaRecorder."""
    mic_btn = window.document.getElementById("meal-plan-mic-btn") or window.document.getElementById("meal-plan-record-btn")
    mic_label = window.document.getElementById("meal-plan-mic-label")
    status_el = window.document.getElementById("meal-plan-recording-status") or window.document.getElementById("meal-plan-record-status")

    if mp_recording.get("recorder") and mp_recording["recorder"].state == "recording":
        # Stop recording
        try:
            mp_recording["recorder"].stop()
        except Exception:
            pass
        if mic_btn:
            mic_btn.classList.remove("is-recording", "bg-red-50", "border-red-300", "text-red-600")
        if mic_label:
            mic_label.textContent = "Voice Note"
        if status_el:
            status_el.classList.add("hidden")
            status_el.style.display = "none"
        return

    # Start recording
    try:
        stream = await window.navigator.mediaDevices.getUserMedia(to_js({"audio": True}))
        mp_recording["stream"] = stream
        mp_recording["chunks"] = []

        recorder = window.MediaRecorder.new(stream)
        mp_recording["recorder"] = recorder

        def on_data_available(event):
            if event.data and event.data.size > 0:
                mp_recording["chunks"].append(event.data)

        async def on_stop(event):
            try:
                # Stop audio tracks safely without calling .item()
                if mp_recording.get("stream"):
                    for track in mp_recording["stream"].getTracks():
                        try:
                            track.stop()
                        except Exception:
                            pass
                    mp_recording["stream"] = None

                chunks = mp_recording.get("chunks") or []
                if not chunks:
                    return

                mime_type = getattr(recorder, "mimeType", "") or "audio/webm"
                raw_blob = window.Blob.new(to_js(chunks), to_js({"type": mime_type}))

                audio_ctx_cls = window.AudioContext or getattr(window, "webkitAudioContext", None)
                wav_blob = None
                if audio_ctx_cls:
                    try:
                        audio_ctx = audio_ctx_cls.new()
                        array_buffer = await raw_blob.arrayBuffer()
                        decoded_buffer = await audio_ctx.decodeAudioData(array_buffer)
                        wav_blob = encode_audio_buffer_to_wav(decoded_buffer)
                        await audio_ctx.close()
                    except Exception:
                        wav_blob = None

                final_blob = wav_blob if wav_blob else raw_blob
                file_name = "meal_plan_voice.wav" if wav_blob else "meal_plan_voice.webm"
                out_mime = "audio/wav" if wav_blob else mime_type

                wav_file = window.File.new(
                    to_js([final_blob]),
                    file_name,
                    to_js({"type": out_mime}),
                )

                dt = window.DataTransfer.new()
                dt.items.add(wav_file)
                voice_input = window.document.getElementById("meal-plan-voice")
                if voice_input:
                    voice_input.files = dt.files

                update_meal_plan_attachment_chips()
            except Exception as e:
                set_meal_plan_error(f"Could not encode voice recording: {e}")
            finally:
                if status_el:
                    status_el.classList.add("hidden")
                    status_el.style.display = "none"
                if mic_btn:
                    mic_btn.classList.remove("is-recording", "bg-red-50", "border-red-300", "text-red-600")
                if mic_label:
                    mic_label.textContent = "Voice Note"

        recorder.ondataavailable = to_js(on_data_available)
        recorder.onstop = to_js(on_stop)
        recorder.start()

        if mic_btn:
            mic_btn.classList.add("is-recording", "bg-red-50", "border-red-300", "text-red-600")
        if mic_label:
            mic_label.textContent = "Stop Recording"
        if status_el:
            status_el.classList.remove("hidden")
            status_el.style.display = "inline-flex"
    except Exception as exc:
        set_meal_plan_error(f"Microphone access denied: {exc}")
        if status_el:
            status_el.classList.add("hidden")
            status_el.style.display = "none"
        if mic_btn:
            mic_btn.classList.remove("is-recording", "bg-red-50", "border-red-300", "text-red-600")
        if mic_label:
            mic_label.textContent = "Voice Note"


def render_meal_plan(record: dict) -> None:
    """Render the generated structured meal plan with breakfast, lunch, snacks, and dinner cards."""
    result = window.document.getElementById("meal-plan-result")
    if not result or not record or not record.get("plan"):
        return

    plan = record.get("plan") or {}
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except Exception:
            plan = {}

    summary_el = window.document.getElementById("meal-plan-summary")
    if summary_el:
        summary_el.textContent = plan.get("summary") or ""

    meta_badges = window.document.getElementById("meal-plan-meta-badges")
    if meta_badges:
        meta_badges.replaceChildren()
        dur = record.get("duration") or plan.get("duration") or "daily"
        diet = record.get("diet_type") or plan.get("diet_type") or ""

        b1 = window.document.createElement("span")
        b1.className = "inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-200"
        b1.textContent = DURATION_LABELS.get(dur, dur.upper())
        meta_badges.append(b1)

        if diet:
            b2 = window.document.createElement("span")
            b2.className = (
                "inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-200" if diet == "non-veg"
                else ("inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-200" if diet == "egg"
                      else "inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200")
            )
            b2.textContent = DIET_LABELS.get(diet, diet.capitalize())
            meta_badges.append(b2)

    transcript_el = window.document.getElementById("meal-plan-transcription")
    transcript_text = record.get("transcription") or plan.get("transcription") or ""
    if transcript_el:
        if transcript_text:
            transcript_el.textContent = f'Voice note transcribed: "{transcript_text}"'
            transcript_el.classList.remove("hidden")
        else:
            transcript_el.classList.add("hidden")

    sections = window.document.getElementById("meal-plan-sections")
    if sections:
        sections.replaceChildren()
        for key in ["breakfast", "lunch", "snacks", "dinner"]:
            meta = MEAL_SECTION_META.get(key, {})
            options = (plan.get(key) or {}).get("options") or []

            section = window.document.createElement("section")
            section.className = "bg-white rounded-2xl border border-stone-200/90 p-5 sm:p-6 shadow-sm mb-6 transition-all hover:shadow-md"

            header = window.document.createElement("div")
            header.className = "flex items-center justify-between border-b border-stone-100 pb-4 mb-4 gap-3"

            title_group = window.document.createElement("div")
            title_group.className = "flex items-center gap-3"

            icon_box = window.document.createElement("span")
            icon_box.className = "w-10 h-10 rounded-xl bg-emerald-50 text-emerald-800 flex items-center justify-center border border-emerald-100/80 shadow-xs flex-none"
            icon_box.innerHTML = meta.get("svg", "")

            text_wrap = window.document.createElement("div")
            heading = window.document.createElement("h2")
            heading.className = "font-serif text-xl sm:text-2xl font-bold text-[#173c2c] m-0"
            heading.textContent = meta.get("label", key.capitalize())
            sub = window.document.createElement("span")
            sub.className = "block text-xs text-stone-500 mt-0.5"
            sub.textContent = meta.get("subtitle", "")
            text_wrap.append(heading, sub)

            title_group.append(icon_box, text_wrap)

            count_badge = window.document.createElement("span")
            count_badge.className = "inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-800 border border-emerald-200"
            count_badge.textContent = f"{len(options)} {'option' if len(options) == 1 else 'options'}"

            header.append(title_group, count_badge)
            section.append(header)

            for idx, opt in enumerate(options):
                article = window.document.createElement("article")
                article.className = "bg-stone-50/70 rounded-xl border border-stone-200/80 p-4 mb-3 transition hover:bg-white hover:border-emerald-300 hover:shadow-sm"

                opt_badge = window.document.createElement("span")
                opt_badge.className = "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-800 mb-1.5"
                opt_badge.textContent = f"Option {idx + 1}"

                t_el = window.document.createElement("h3")
                t_el.className = "text-base font-bold text-[#173c2c] m-0 mb-1"
                t_el.textContent = opt.get("name") or "Meal idea"

                d_el = window.document.createElement("p")
                d_el.className = "text-xs text-stone-600 leading-relaxed m-0 mb-2.5"
                d_el.textContent = opt.get("details") or ""

                r_el = window.document.createElement("p")
                r_el.className = "flex items-start gap-1.5 text-xs text-emerald-900 bg-emerald-50/80 p-2.5 rounded-lg border border-emerald-200/60 m-0"
                r_el.innerHTML = (
                    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="flex-none mt-0.5 text-emerald-700" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'
                )
                r_span = window.document.createElement("span")
                r_span.textContent = opt.get("why_it_fits") or ""
                r_el.append(r_span)

                article.append(opt_badge, t_el, d_el, r_el)
                section.append(article)

            sections.append(section)

    result.classList.remove("hidden")
    result.scrollIntoView(to_js({"behavior": "smooth", "block": "start"}))


def render_meal_plan_history() -> None:
    """Render saved previous meal plans in the sidebar history list with Tailwind classes."""
    container = window.document.getElementById("meal-plan-history-list")
    if not container:
        return
    container.replaceChildren()

    count = window.document.getElementById("meal-plan-history-count")
    if count:
        count.textContent = str(len(meal_plan_history))

    status = window.document.getElementById("meal-plan-history-status")
    if status:
        status.textContent = "" if meal_plan_history else "Your meal plans will appear here after you create one."

    for record in meal_plan_history:
        rec_id = str(record.get("id"))
        row = window.document.createElement("div")
        row.className = "flex items-center justify-between gap-1 p-1 rounded-xl mb-1.5 group hover:bg-stone-50 border border-transparent hover:border-stone-200 transition"
        row.dataset.mealPlanRowId = rec_id

        btn = window.document.createElement("button")
        btn.type = "button"
        btn.className = "flex-1 min-w-0 text-left p-2 rounded-lg transition cursor-pointer"
        btn.dataset.mealPlanId = rec_id
        btn.setAttribute("aria-current", "false")

        title = window.document.createElement("span")
        title.className = "block truncate text-xs font-bold text-[#173c2c]"
        title.textContent = record.get("title") or "Meal Plan"

        meta_line = window.document.createElement("span")
        meta_line.className = "mt-0.5 flex items-center gap-1.5 text-[10px] text-stone-500"
        plan_data = record.get("plan") or {}
        if isinstance(plan_data, str):
            try:
                plan_data = json.loads(plan_data)
            except Exception:
                plan_data = {}
        dur = (plan_data.get("duration") or "DAILY").upper()
        diet = f" · {plan_data['diet_type'].upper()}" if plan_data.get("diet_type") else ""
        meta_line.textContent = f"{dur}{diet}"

        btn.append(title, meta_line)

        del_btn = window.document.createElement("button")
        del_btn.type = "button"
        del_btn.className = "h-7 w-7 rounded-lg flex items-center justify-center text-stone-400 hover:text-red-600 hover:bg-red-50 transition ml-1 flex-none cursor-pointer"
        del_btn.dataset.deleteMealPlanId = rec_id
        del_btn.title = "Delete this meal plan"
        del_btn.setAttribute("aria-label", f"Delete meal plan {record.get('title')}")
        del_btn.innerHTML = (
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>'
        )

        row.append(btn, del_btn)
        container.append(row)


async def load_meal_plan_history() -> None:
    """Fetch archived meal plans for the current owner/user."""
    global meal_plan_history
    if not window.document.querySelector('[data-page="meal-plan"]'):
        return

    status = window.document.getElementById("meal-plan-history-status")
    try:
        resp = await window.fetch("/meal-plans/history", to_js({"headers": {"Accept": "application/json"}}))
        data = await read_json(resp)
        if not resp.ok:
            detail = error_detail(data, "Could not load meal plan history.")
            if status:
                status.textContent = str(detail)
            return
        meal_plan_history = data if isinstance(data, list) else []
        render_meal_plan_history()
    except Exception as exc:
        if status:
            status.textContent = f"Could not load previous meal plans: {exc}"


def show_historical_meal_plan(plan_id: str) -> None:
    """Display a previously saved meal plan selected from the history sidebar."""
    for record in meal_plan_history:
        if str(record.get("id")) == str(plan_id):
            render_meal_plan(record)
            # Highlight active button
            items = window.document.querySelectorAll("[data-meal-plan-id]")
            for i in range(items.length):
                it = items.item(i)
                it.setAttribute("aria-current", "true" if it.dataset.mealPlanId == str(plan_id) else "false")
            break


async def delete_meal_plan(plan_id: str) -> None:
    """Delete a saved meal plan from database and sidebar list."""
    if not plan_id:
        return

    row = window.document.querySelector(f'[data-meal-plan-row-id="{plan_id}"]')
    if row:
        row.style.opacity = "0.3"
        row.style.pointerEvents = "none"

    try:
        resp = await window.fetch(
            f"/meal-plans/{plan_id}/delete",
            to_js({
                "method": "POST",
                "headers": {"Accept": "application/json"},
            }),
        )
        data = await read_json(resp)
        if not resp.ok:
            detail = error_detail(data, "Could not delete meal plan.")
            set_meal_plan_error(str(detail))
            if row:
                row.style.opacity = "1"
                row.style.pointerEvents = "auto"
            return

        if row:
            row.remove()
        await load_meal_plan_history()
    except Exception as exc:
        set_meal_plan_error(f"Error deleting meal plan: {exc}")
        if row:
            row.style.opacity = "1"
            row.style.pointerEvents = "auto"


async def handle_meal_plan_submit(form) -> None:
    """Submit the meal plan generation request with preferences, photo, and voice note."""
    set_meal_plan_error("")
    submit_btn = window.document.getElementById("generate-meal-plan")
    submit_label = window.document.getElementById("generate-meal-plan-label")
    spinner = window.document.getElementById("meal-plan-spinner")

    if submit_btn:
        submit_btn.disabled = True
    if submit_label:
        submit_label.textContent = "Creating personalized plan…"
    if spinner:
        spinner.classList.remove("hidden")

    sync_meal_plan_mode_ui(is_generating=True)

    try:
        form_data = window.FormData.new(form)
        prefs = get_selected_meal_plan_preferences()
        if prefs:
            form_data.set("preferences", json.dumps(prefs))

        resp = await window.fetch(
            "/meal-plans/generate",
            to_js({
                "method": "POST",
                "body": form_data,
            }),
        )
        data = await read_json(resp)
        if not resp.ok:
            detail = error_detail(data, "Could not generate meal plan. Please check inputs.")
            set_meal_plan_error(str(detail))
            return

        render_meal_plan(data)
        await load_meal_plan_history()
    except Exception as exc:
        set_meal_plan_error(f"Network error generating meal plan: {exc}")
    finally:
        if submit_btn:
            submit_btn.disabled = False
        if spinner:
            spinner.classList.add("hidden")
        sync_meal_plan_mode_ui(is_generating=False)
