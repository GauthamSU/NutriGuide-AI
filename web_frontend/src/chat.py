import asyncio
import json

from pyscript import when, web, window
from pyscript.ffi import to_js  # dicts -> plain JS objects (not Map)


recording = {
    "stream": None,
    "recorder": None,
    "chunks": [],
    "image_url": None,
    "submitted_image_urls": [],
}


def element(element_id):
    raw_el = window.document.getElementById(element_id)
    if not raw_el:
        return None
    try:
        return web.page[element_id]
    except Exception:
        return raw_el


def set_composer_error(message):
    error = window.document.getElementById("composer-error")
    if not error:
        return
    error.textContent = message
    if message:
        error.classList.remove("hidden")
    else:
        error.classList.add("hidden")


def revoke_selected_image():
    if recording["image_url"]:
        window.URL.revokeObjectURL(recording["image_url"])
        recording["image_url"] = None


def update_attachment_chips():
    container = window.document.getElementById("attachment-label")
    image_input = window.document.getElementById("meal-image")
    voice_input = window.document.getElementById("voice-upload")
    if not container or not image_input or not voice_input:
        return
    container.innerHTML = ""

    if image_input.files and image_input.files.length:
        if not recording["image_url"]:
            recording["image_url"] = window.URL.createObjectURL(image_input.files.item(0))
        append_image_chip(container, image_input.files.item(0).name, recording["image_url"])

    if voice_input.files and voice_input.files.length:
        append_voice_chip(container)


def append_image_chip(container, filename, image_url):
    chip = window.document.createElement("span")
    chip.className = "inline-flex items-center gap-2 rounded-full bg-stone-100 border border-stone-300 pl-1.5 pr-2.5 py-1 text-xs font-semibold text-stone-800 shadow-2xs"

    thumb = window.document.createElement("img")
    thumb.src = image_url
    thumb.alt = f"Preview of {filename}"
    thumb.className = "h-5 w-5 rounded-full object-cover"
    chip.appendChild(thumb)

    label = window.document.createElement("span")
    label.className = "max-w-[130px] truncate"
    label.textContent = filename
    chip.appendChild(label)

    remove_btn = window.document.createElement("button")
    remove_btn.type = "button"
    remove_btn.title = "Remove image"
    remove_btn.setAttribute("aria-label", "Remove image")
    remove_btn.className = "ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full text-stone-500 hover:bg-stone-200 hover:text-stone-800 cursor-pointer text-xs font-bold leading-none"
    remove_btn.textContent = "×"
    chip.appendChild(remove_btn)

    def on_remove(event):
        event.preventDefault()
        img_el = window.document.getElementById("meal-image")
        if img_el:
            img_el.value = ""
        revoke_selected_image()
        update_attachment_chips()

    remove_btn.onclick = on_remove
    container.appendChild(chip)


def append_voice_chip(container):
    chip = window.document.createElement("span")
    chip.className = "inline-flex items-center gap-2 rounded-full bg-emerald-50 border border-emerald-300 px-3 py-1 text-xs font-semibold text-emerald-900 shadow-2xs"

    icon = window.document.createElement("span")
    icon.className = "text-sm"
    icon.textContent = "🎙️"
    chip.appendChild(icon)

    label = window.document.createElement("span")
    label.textContent = "Voice note"
    chip.appendChild(label)

    remove_btn = window.document.createElement("button")
    remove_btn.type = "button"
    remove_btn.title = "Remove voice note"
    remove_btn.setAttribute("aria-label", "Remove voice note")
    remove_btn.className = "ml-1.5 inline-flex h-4 w-4 items-center justify-center rounded-full text-emerald-700 hover:bg-emerald-200 hover:text-emerald-950 cursor-pointer text-xs font-bold leading-none"
    remove_btn.textContent = "×"
    chip.appendChild(remove_btn)

    def on_remove(event):
        event.preventDefault()
        v_el = window.document.getElementById("voice-upload")
        if v_el:
            v_el.value = ""
        update_attachment_chips()

    remove_btn.onclick = on_remove
    container.appendChild(chip)


def clear_selected_attachments_after_submit():
    if recording["image_url"]:
        recording["submitted_image_urls"].append(recording["image_url"])
        recording["image_url"] = None
    meal_img = window.document.getElementById("meal-image")
    voice_up = window.document.getElementById("voice-upload")
    if meal_img:
        meal_img.value = ""
    if voice_up:
        voice_up.value = ""
    update_attachment_chips()


def append_pending_turn(description):
    """
    Append user's query turn and active loading indicator into chat stream.
    Displays user message on right with distinct styling and miniaturized preview.
    """
    conversation_content = window.document.getElementById("conversation-content")
    if not conversation_content:
        return

    pending_container = window.document.createElement("div")
    pending_container.id = "active-pending-turn"
    pending_container.className = "w-full max-w-[760px] mx-auto mb-8 transition-all"

    # User query bubble (right-aligned, distinct green theme, miniaturized image)
    user_bubble = window.document.createElement("div")
    user_bubble.className = "user-turn ml-auto mb-4 max-w-[88%] sm:max-w-[80%] rounded-2xl rounded-tr-xs bg-[#eaf4ec] border border-[#cce5d2] p-4 text-sm leading-relaxed text-stone-900 shadow-2xs"

    if description:
        desc_p = window.document.createElement("p")
        desc_p.className = "m-0 break-words font-medium"
        desc_p.textContent = description
        user_bubble.appendChild(desc_p)

    img_input = window.document.getElementById("meal-image")
    voice_input = window.document.getElementById("voice-upload")

    if voice_input and getattr(voice_input, "files", None) and voice_input.files.length:
        voice_badge = window.document.createElement("div")
        voice_badge.className = "mt-2 flex gap-1.5"
        voice_badge.innerHTML = '<span class="inline-flex items-center gap-1 rounded-full bg-white/80 border border-emerald-200 px-2.5 py-1 text-[11px] font-medium text-emerald-900">🎙️ Voice note</span>'
        user_bubble.appendChild(voice_badge)

    if img_input and getattr(img_input, "files", None) and img_input.files.length and recording["image_url"]:
        preview = window.document.createElement("img")
        preview.src = recording["image_url"]
        preview.alt = "Attached meal photo"
        preview.className = "submitted-image-preview mt-2.5 max-h-56 max-w-xs rounded-xl border border-emerald-200 object-cover shadow-xs"
        user_bubble.appendChild(preview)

    pending_container.appendChild(user_bubble)

    # Pulsing Assistant Loading Card
    loader_card = window.document.createElement("article")
    loader_card.className = "assistant-turn bg-white rounded-2xl border border-stone-200/90 p-5 sm:p-6 shadow-sm"
    loader_card.innerHTML = (
        '<div class="mb-3 flex items-center gap-2 text-xs font-semibold text-stone-600">'
        '<span class="flex h-7 w-7 items-center justify-center rounded-[8px_8px_8px_2px] bg-[#245c43] text-sm font-bold text-[#d7ed9f]">N</span>'
        '<span class="text-stone-800 font-bold">NutriGuide</span>'
        '</div>'
        '<div class="flex items-center gap-3 py-4 text-sm text-[#53645a]">'
        '<span class="pending-dots inline-flex gap-1.5">'
        '<i class="h-2 w-2 rounded-full bg-[#245c43] animate-bounce"></i>'
        '<i class="h-2 w-2 rounded-full bg-[#245c43] animate-bounce [animation-delay:0.2s]"></i>'
        '<i class="h-2 w-2 rounded-full bg-[#245c43] animate-bounce [animation-delay:0.4s]"></i>'
        '</span>'
        '<span class="font-medium">Analyzing your meal nutrition with verified IFCT data...</span>'
        '</div>'
    )
    pending_container.appendChild(loader_card)

    conversation_content.appendChild(pending_container)
    pending_container.scrollIntoView(to_js({"behavior": "smooth", "block": "end"}))


def clear_composer():
    desc = window.document.getElementById("meal-description")
    if desc:
        desc.value = ""
    clear_selected_attachments_after_submit()
    set_composer_error("")
    resize_textarea()


def resize_textarea(event=None):
    textarea = window.document.getElementById("meal-description")
    if not textarea:
        return
    textarea.style.height = "auto"
    textarea.style.height = f"{min(textarea.scrollHeight, 144)}px"


async def start_recording():
    if not window.document.getElementById("mic-button"):
        return
    set_composer_error("")
    try:
        recording["stream"] = await window.navigator.mediaDevices.getUserMedia({"audio": True})
        recording["recorder"] = window.MediaRecorder.new(recording["stream"])
        recording["chunks"] = []

        def capture_chunk(media_event):
            if media_event.data.size:
                recording["chunks"].append(media_event.data)

        recording["recorder"].ondataavailable = capture_chunk
        recording["recorder_callback"] = capture_chunk
        recording["recorder"].start()

        mic_button = window.document.getElementById("mic-button")
        if mic_button:
            mic_button.classList.add("recording")
            mic_button.title = "Stop recording"
            mic_button.setAttribute("aria-label", "Stop recording")
            mic_button.innerHTML = '<svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>'
        status = window.document.getElementById("recording-status")
        if status:
            status.classList.remove("hidden")
            status.classList.add("inline-flex")
    except Exception as exc:
        set_composer_error(f"Microphone access failed: {exc}")
        stop_microphone_tracks()


def stop_microphone_tracks():
    if recording["stream"]:
        for track in recording["stream"].getTracks():
            track.stop()
    recording["stream"] = None
    recording["recorder"] = None


async def stop_recording():
    recorder = recording["recorder"]
    if not recorder:
        return

    recorder_stopped = asyncio.get_running_loop().create_future()

    def on_recorder_stopped(event):
        if not recorder_stopped.done():
            recorder_stopped.set_result(True)

    recorder.onstop = on_recorder_stopped
    recording["recorder_stop_callback"] = on_recorder_stopped
    recorder.stop()

    await recorder_stopped

    stream = recording["stream"]
    if stream:
        for track in stream.getTracks():
            track.stop()
    recording["stream"] = None
    recording["recorder"] = None
    recording["recorder_callback"] = None
    recording["recorder_stop_callback"] = None

    mic_button = window.document.getElementById("mic-button")
    if mic_button:
        mic_button.classList.remove("recording")
        mic_button.title = "Record a voice note"
        mic_button.setAttribute("aria-label", "Record a voice note")
        mic_button.innerHTML = '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></svg>'
    status = window.document.getElementById("recording-status")
    if status:
        status.classList.add("hidden")
        status.classList.remove("inline-flex")

    await save_recording(recorder)


async def save_recording(recorder):
    audio_context_type = window.AudioContext or window.webkitAudioContext
    audio_context = audio_context_type.new()
    try:
        chunks = recording["chunks"]
        audio_blob = window.Blob.new(to_js(chunks), {"type": recorder.mimeType or "audio/webm"})
        audio_buffer = await audio_context.decodeAudioData(await audio_blob.arrayBuffer())
        wav_blob = encode_wav(audio_buffer)
        voice_file = window.File.new([wav_blob], "voice-note.wav", {"type": "audio/wav"})
        transfer = window.DataTransfer.new()
        transfer.items.add(voice_file)
        voice_up = window.document.getElementById("voice-upload")
        if voice_up:
            voice_up.files = transfer.files

        update_attachment_chips()
    except Exception as exc:
        voice_up = window.document.getElementById("voice-upload")
        if voice_up:
            voice_up.value = ""
        update_attachment_chips()
        set_composer_error(f"Could not prepare the voice recording. Try a shorter note. ({exc})")
    finally:
        recording["chunks"] = []
        await audio_context.close()


def encode_wav(audio_buffer):
    channel_count = int(audio_buffer.numberOfChannels)
    sample_rate = int(audio_buffer.sampleRate)
    channels = [audio_buffer.getChannelData(index).to_py() for index in range(channel_count)]
    frame_count = len(channels[0])
    samples = bytearray()
    for frame_index in range(frame_count):
        for channel_index in range(channel_count):
            sample = max(-1.0, min(1.0, float(channels[channel_index][frame_index])))
            pcm_sample = int(sample * (32768 if sample < 0 else 32767))
            samples.extend(pcm_sample.to_bytes(2, "little", signed=True))

    data_size = len(samples)
    header = bytearray(b"RIFF")
    header.extend((36 + data_size).to_bytes(4, "little"))
    header.extend(b"WAVEfmt ")
    header.extend((16).to_bytes(4, "little"))
    header.extend((1).to_bytes(2, "little"))
    header.extend(channel_count.to_bytes(2, "little"))
    header.extend(sample_rate.to_bytes(4, "little"))
    header.extend((sample_rate * channel_count * 2).to_bytes(4, "little"))
    header.extend((channel_count * 2).to_bytes(2, "little"))
    header.extend((16).to_bytes(2, "little"))
    header.extend(b"data")
    header.extend(data_size.to_bytes(4, "little"))
    return window.Blob.new(to_js([bytes(header) + bytes(samples)]), {"type": "audio/wav"})


def before_request(event):
    elt = getattr(getattr(event, "detail", None), "elt", None)
    if not elt or getattr(elt, "id", "") != "chat-form":
        return
    desc_el = window.document.getElementById("meal-description")
    img_el = window.document.getElementById("meal-image")
    voice_el = window.document.getElementById("voice-upload")
    if not desc_el or not img_el or not voice_el:
        return
    description = (desc_el.value or "").strip()
    has_image = bool(img_el.files and img_el.files.length > 0)
    has_voice = bool(voice_el.files and voice_el.files.length > 0)
    if not description and not has_image and not has_voice:
        event.preventDefault()
        set_composer_error("Add a meal description, photo, or voice note to continue.")
        desc_el.focus()
    elif recording["recorder"]:
        event.preventDefault()
        set_composer_error("Stop the recording to attach it, then press send.")
    else:
        set_composer_error("")
        welcome_message = window.document.getElementById("welcome-message")
        if welcome_message:
            welcome_message.classList.add("hidden")
        append_pending_turn(description)
        send_button = window.document.getElementById("send-button")
        if send_button:
            send_button.disabled = True
            send_button.classList.add("opacity-50", "cursor-wait")


def after_request(event):
    elt = getattr(getattr(event, "detail", None), "elt", None)
    if not elt or getattr(elt, "id", "") != "chat-form":
        return
    pending_turn = window.document.getElementById("active-pending-turn")
    if pending_turn:
        pending_turn.remove()
    send_button = window.document.getElementById("send-button")
    if send_button:
        send_button.disabled = False
        send_button.classList.remove("opacity-50", "cursor-wait")
    if getattr(getattr(event, "detail", None), "successful", False):
        clear_composer()
        conv = window.document.getElementById("conversation")
        desc = window.document.getElementById("meal-description")
        if conv:
            conv.scrollTop = conv.scrollHeight
        if desc:
            desc.focus()
    else:
        xhr = getattr(getattr(event, "detail", None), "xhr", None)
        status_num = getattr(xhr, "status", None)
        status_str = f" (Status {status_num})" if status_num else ""
        set_composer_error(f"Analysis request could not be completed{status_str}. Please try again.")


def handle_image_change(event):
    set_composer_error("")
    revoke_selected_image()
    update_attachment_chips()


def handle_enter(event):
    """Handle Enter key in meal description textarea to submit without Shift."""
    if event.key == "Enter" and not event.shiftKey:
        event.preventDefault()
        send_btn = window.document.getElementById("send-button")
        if send_btn and not getattr(send_btn, "disabled", False):
            send_btn.click()
        else:
            chat_form = window.document.getElementById("chat-form")
            if chat_form:
                chat_form.requestSubmit()


async def handle_delete_chat_message(msg_id: str, conv_id: str = "") -> None:
    """Delete a single chat message turn from conversation history via secure POST body."""
    if not msg_id:
        return
    turn = window.document.getElementById(f"turn-{msg_id}")
    if turn:
        turn.style.opacity = "0.3"
        turn.style.pointerEvents = "none"
    try:
        if not conv_id:
            active_chat = window.document.querySelector("main[data-conversation-id]")
            if active_chat:
                conv_id = getattr(active_chat.dataset, "conversationId", "") or ""

        resp = await window.fetch(
            "/chats/messages/delete",
            to_js({
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                "body": json.dumps({
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                }),
            }),
        )
        if resp.ok and turn:
            turn.remove()
        elif turn:
            turn.style.opacity = "1"
            turn.style.pointerEvents = "auto"
    except Exception:
        if turn:
            turn.style.opacity = "1"
            turn.style.pointerEvents = "auto"


async def handle_delete_conversation(conv_id: str) -> None:
    """Delete an entire chat conversation from database and sidebar via secure POST body."""
    if not conv_id:
        return
    item = (
        window.document.querySelector(f'[data-chat-history-row="{conv_id}"]')
        or window.document.querySelector(f'[data-conversation-item-id="{conv_id}"]')
    )
    if item:
        item.style.opacity = "0.3"
        item.style.pointerEvents = "none"
    try:
        resp = await window.fetch(
            "/chats/delete",
            to_js({
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                "body": json.dumps({
                    "conversation_id": conv_id,
                }),
            }),
        )
        if resp.ok:
            if item:
                item.remove()
            active_chat = window.document.querySelector("main[data-conversation-id]")
            if active_chat and getattr(active_chat.dataset, "conversationId", "") == conv_id:
                window.location.href = "/"
        elif item:
            item.style.opacity = "1"
            item.style.pointerEvents = "auto"
    except Exception:
        if item:
            item.style.opacity = "1"
            item.style.pointerEvents = "auto"


# ─── Household Recipe Customization & Real-Time Macro Recalculation ────────────

CLIENT_INGREDIENT_STATES = {}

ALL_MACRO_KEYS = [
    "calories_kcal",
    "protein_g",
    "carbohydrates_g",
    "dietary_fiber_g",
    "total_sugars_g",
    "added_sugars_g",
    "total_fat_g",
    "saturated_fat_g",
    "monounsaturated_fat_g",
    "polyunsaturated_fat_g",
    "unsaturated_fat_g",
    "trans_fat_g",
    "cholesterol_mg",
    "sodium_mg",
    "water_g",
]

COMMON_INDIAN_FOOD_DENSITIES_PER_100G = {
    "ghee": {"calories_kcal": 900.0, "protein_g": 0.0, "carbohydrates_g": 0.0, "dietary_fiber_g": 0.0, "total_fat_g": 100.0, "saturated_fat_g": 62.0, "monounsaturated_fat_g": 29.0, "polyunsaturated_fat_g": 4.0, "unsaturated_fat_g": 33.0, "cholesterol_mg": 250.0},
    "coconut oil": {"calories_kcal": 892.0, "protein_g": 0.0, "carbohydrates_g": 0.0, "dietary_fiber_g": 0.0, "total_fat_g": 99.1, "saturated_fat_g": 82.5, "monounsaturated_fat_g": 6.3, "polyunsaturated_fat_g": 1.7, "unsaturated_fat_g": 8.0},
    "mustard oil": {"calories_kcal": 884.0, "protein_g": 0.0, "carbohydrates_g": 0.0, "dietary_fiber_g": 0.0, "total_fat_g": 100.0, "saturated_fat_g": 11.6, "monounsaturated_fat_g": 59.2, "polyunsaturated_fat_g": 21.2, "unsaturated_fat_g": 80.4},
    "oil": {"calories_kcal": 884.0, "protein_g": 0.0, "carbohydrates_g": 0.0, "dietary_fiber_g": 0.0, "total_fat_g": 100.0, "saturated_fat_g": 14.0, "monounsaturated_fat_g": 45.0, "polyunsaturated_fat_g": 36.0, "unsaturated_fat_g": 81.0},
    "butter": {"calories_kcal": 717.0, "protein_g": 0.9, "carbohydrates_g": 0.1, "dietary_fiber_g": 0.0, "total_fat_g": 81.1, "saturated_fat_g": 51.4, "monounsaturated_fat_g": 21.0, "polyunsaturated_fat_g": 3.0, "unsaturated_fat_g": 24.0, "cholesterol_mg": 215.0, "sodium_mg": 640.0, "water_g": 16.0},
    "peanut": {"calories_kcal": 567.0, "protein_g": 25.8, "carbohydrates_g": 16.1, "dietary_fiber_g": 8.5, "total_sugars_g": 4.7, "total_fat_g": 49.2, "saturated_fat_g": 6.3, "monounsaturated_fat_g": 24.4, "polyunsaturated_fat_g": 15.6, "unsaturated_fat_g": 40.0, "water_g": 6.5},
    "groundnut": {"calories_kcal": 567.0, "protein_g": 25.8, "carbohydrates_g": 16.1, "dietary_fiber_g": 8.5, "total_fat_g": 49.2, "saturated_fat_g": 6.3, "monounsaturated_fat_g": 24.4, "polyunsaturated_fat_g": 15.6, "unsaturated_fat_g": 40.0},
    "curry leaves": {"calories_kcal": 108.0, "protein_g": 6.1, "carbohydrates_g": 18.7, "dietary_fiber_g": 6.4, "total_fat_g": 1.0, "water_g": 63.8},
    "rice flakes": {"calories_kcal": 346.0, "protein_g": 6.6, "carbohydrates_g": 77.3, "dietary_fiber_g": 3.4, "total_fat_g": 1.2, "water_g": 12.2},
    "poha": {"calories_kcal": 346.0, "protein_g": 6.6, "carbohydrates_g": 77.3, "dietary_fiber_g": 3.4, "total_fat_g": 1.2, "water_g": 12.2},
    "avalakki": {"calories_kcal": 346.0, "protein_g": 6.6, "carbohydrates_g": 77.3, "dietary_fiber_g": 3.4, "total_fat_g": 1.2, "water_g": 12.2},
    "paneer": {"calories_kcal": 265.0, "protein_g": 18.3, "carbohydrates_g": 3.4, "dietary_fiber_g": 0.0, "total_fat_g": 20.8, "saturated_fat_g": 13.1, "monounsaturated_fat_g": 5.4, "unsaturated_fat_g": 6.2, "cholesterol_mg": 55.0, "water_g": 54.0},
    "roti": {"calories_kcal": 297.0, "protein_g": 9.8, "carbohydrates_g": 58.5, "dietary_fiber_g": 8.2, "total_fat_g": 3.4, "water_g": 26.0},
    "chapati": {"calories_kcal": 297.0, "protein_g": 9.8, "carbohydrates_g": 58.5, "dietary_fiber_g": 8.2, "total_fat_g": 3.4, "water_g": 26.0},
    "dal": {"calories_kcal": 116.0, "protein_g": 7.6, "carbohydrates_g": 18.5, "dietary_fiber_g": 4.2, "total_fat_g": 1.5, "water_g": 70.0},
    "rice": {"calories_kcal": 130.0, "protein_g": 2.7, "carbohydrates_g": 28.2, "dietary_fiber_g": 0.6, "total_fat_g": 0.3, "water_g": 68.4},
    "curd": {"calories_kcal": 61.0, "protein_g": 3.5, "carbohydrates_g": 4.7, "dietary_fiber_g": 0.0, "total_fat_g": 3.3, "saturated_fat_g": 2.1, "water_g": 87.9},
    "egg": {"calories_kcal": 143.0, "protein_g": 12.6, "carbohydrates_g": 0.7, "dietary_fiber_g": 0.0, "total_fat_g": 9.5, "saturated_fat_g": 3.1, "cholesterol_mg": 372.0, "water_g": 76.0},
    "chicken": {"calories_kcal": 165.0, "protein_g": 31.0, "carbohydrates_g": 0.0, "dietary_fiber_g": 0.0, "total_fat_g": 3.6, "saturated_fat_g": 1.0, "cholesterol_mg": 85.0, "water_g": 65.0},
    "potato": {"calories_kcal": 87.0, "protein_g": 1.9, "carbohydrates_g": 20.1, "dietary_fiber_g": 1.8, "total_fat_g": 0.1, "water_g": 77.0},
    "onion": {"calories_kcal": 40.0, "protein_g": 1.1, "carbohydrates_g": 9.3, "dietary_fiber_g": 1.7, "total_fat_g": 0.1, "water_g": 89.0},
    "tomato": {"calories_kcal": 18.0, "protein_g": 0.9, "carbohydrates_g": 3.9, "dietary_fiber_g": 1.2, "total_fat_g": 0.2, "water_g": 94.5},
}


def _estimate_row_macros(name_val: str, weight_val: float, orig_name: str, orig_weight: float, orig_macros_json: str) -> dict:
    """Compute macronutrients for an ingredient row based on original item data or reference density."""
    result = {k: 0.0 for k in ALL_MACRO_KEYS}
    if weight_val <= 0 or not name_val:
        return result

    name_clean = name_val.strip().lower()
    orig_clean = (orig_name or "").strip().lower()

    # If ingredient name was not changed and we have original server-calculated item macros, scale proportionally
    if name_clean == orig_clean and orig_weight > 0 and orig_macros_json:
        try:
            parsed = json.loads(orig_macros_json)
            if isinstance(parsed, dict) and parsed.get("calories_kcal") is not None:
                ratio = weight_val / orig_weight
                for k in ALL_MACRO_KEYS:
                    result[k] = round(float(parsed.get(k, 0.0) or 0.0) * ratio, 2)
                return result
        except Exception:
            pass

    # Match against client-side IFCT reference food densities (per 100g)
    matched_profile = None
    if name_clean in COMMON_INDIAN_FOOD_DENSITIES_PER_100G:
        matched_profile = COMMON_INDIAN_FOOD_DENSITIES_PER_100G[name_clean]
    else:
        for kw, prof in COMMON_INDIAN_FOOD_DENSITIES_PER_100G.items():
            if kw in name_clean or name_clean in kw:
                matched_profile = prof
                break

    if not matched_profile:
        matched_profile = {
            "calories_kcal": 140.0,
            "protein_g": 4.5,
            "carbohydrates_g": 22.0,
            "dietary_fiber_g": 2.5,
            "total_fat_g": 3.8,
            "saturated_fat_g": 0.9,
            "unsaturated_fat_g": 2.6,
            "water_g": 65.0,
        }

    scale = weight_val / 100.0
    for k in ALL_MACRO_KEYS:
        result[k] = round(float(matched_profile.get(k, 0.0) or 0.0) * scale, 2)
    return result


def recalculate_recipe_macros_realtime(msg_id: str) -> dict:
    """
    Maintain ingredient state in CLIENT_INGREDIENT_STATES[msg_id] and immediately
    recalculate and update all macro totals and progress bars locally on the client side.
    """
    if not msg_id:
        return {}

    doc = window.document
    rows = doc.querySelectorAll(f"#ingredient-rows-{msg_id} .ingredient-row, #ingredient-rows-{msg_id} [data-ingredient-row]")
    items_state = []
    totals = {k: 0.0 for k in ALL_MACRO_KEYS}

    if rows:
        for i in range(rows.length):
            r = rows.item(i)
            name_el = r.querySelector(".ing-name-input")
            desc_el = r.querySelector(".ing-desc-input")
            weight_el = r.querySelector(".ing-weight-input")

            name_val = (name_el.value if name_el else "").strip()
            desc_val = (desc_el.value if desc_el else "1 serving").strip() or "1 serving"
            try:
                weight_val = float(weight_el.value if weight_el else 0.0)
            except Exception:
                weight_val = 0.0

            orig_name = r.getAttribute("data-orig-name") or ""
            try:
                orig_weight = float(r.getAttribute("data-orig-weight") or 0.0)
            except Exception:
                orig_weight = 0.0
            orig_macros_json = r.getAttribute("data-item-macros") or ""

            row_macros = _estimate_row_macros(name_val, weight_val, orig_name, orig_weight, orig_macros_json)
            for k in ALL_MACRO_KEYS:
                totals[k] += row_macros[k]

            if name_val and weight_val > 0:
                items_state.append({
                    "food_name": name_val,
                    "serving_size_description": desc_val,
                    "estimated_weight_grams": weight_val,
                    "macronutrients": row_macros,
                })

    CLIENT_INGREDIENT_STATES[msg_id] = {
        "items": items_state,
        "totals": totals,
    }

    # Synchronize hidden JSON input
    json_input = doc.getElementById(f"ingredients-json-{msg_id}")
    if json_input:
        json_input.value = json.dumps([
            {
                "food_name": it["food_name"],
                "serving_size_description": it["serving_size_description"],
                "estimated_weight_grams": it["estimated_weight_grams"],
            }
            for it in items_state
        ])

    # 1. Update Live Preview Banner inside the customizer form
    preview_box = doc.getElementById(f"live-recipe-preview-{msg_id}")
    if preview_box:
        for sel, key, fmt in [
            ("[data-live-cal]", "calories_kcal", "{:.0f}"),
            ("[data-live-prot]", "protein_g", "{:.1f}"),
            ("[data-live-carb]", "carbohydrates_g", "{:.1f}"),
            ("[data-live-fat]", "total_fat_g", "{:.1f}"),
            ("[data-live-fib]", "dietary_fiber_g", "{:.1f}"),
        ]:
            el = preview_box.querySelector(sel)
            if el:
                el.textContent = fmt.format(totals[key])

    # 2. Update Turn Card Main Calories, 14 Macronutrients, and Hero Progress Bars in real time
    turn_root = doc.getElementById(f"results-{msg_id}")
    if turn_root:
        cal_el = doc.getElementById(f"turn-total-calories-{msg_id}")
        if cal_el:
            cal_el.textContent = f"{totals['calories_kcal']:.0f}"

        live_badge = doc.getElementById(f"turn-live-badge-{msg_id}")
        if live_badge:
            live_badge.classList.remove("hidden")
            live_badge.classList.add("inline-flex")

        macro_vals = turn_root.querySelectorAll("[data-turn-macro-val]")
        for i in range(macro_vals.length):
            m_el = macro_vals.item(i)
            m_key = m_el.dataset.turnMacroVal
            m_unit = m_el.dataset.turnMacroUnit or "g"
            if m_key in totals:
                m_el.textContent = f"{totals[m_key]:.1f} {m_unit}"

        hero_vals = turn_root.querySelectorAll("[data-turn-hero-macro]")
        for i in range(hero_vals.length):
            h_el = hero_vals.item(i)
            h_key = h_el.dataset.turnHeroMacro
            if h_key in totals:
                h_el.textContent = f"{totals[h_key]:.1f}g"

        bars = turn_root.querySelectorAll("[data-turn-macro-bar]")
        for i in range(bars.length):
            b_el = bars.item(i)
            b_key = b_el.dataset.turnMacroBar
            try:
                goal = float(b_el.dataset.macroGoal or 60.0)
            except Exception:
                goal = 60.0
            if b_key in totals and goal > 0:
                pct = min(100, max(0, int(round((totals[b_key] / goal) * 100.0))))
                b_el.style.width = f"{pct}%"

        # Live Dish Title & Description update
        form = doc.getElementById(f"recipe-form-{msg_id}")
        if form:
            d_name_inp = form.querySelector('input[name="dish_name"]')
            d_desc_inp = form.querySelector('textarea[name="dish_description"]')
            title_h2 = doc.getElementById(f"turn-dish-title-{msg_id}")
            desc_p = doc.getElementById(f"turn-dish-desc-{msg_id}")
            if d_name_inp and title_h2 and d_name_inp.value.strip():
                title_h2.textContent = d_name_inp.value.strip()
            if d_desc_inp and desc_p:
                val = d_desc_inp.value.strip()
                desc_p.textContent = val
                desc_p.classList.toggle("hidden", not bool(val))

        # Keep Log-to-Tracker button dataset in sync with live recalculated totals
        log_btn = doc.getElementById(f"turn-log-btn-{msg_id}")
        if log_btn:
            log_btn.dataset.calories = f"{totals['calories_kcal']:.0f}"
            log_btn.dataset.protein = f"{totals['protein_g']:.1f}"
            log_btn.dataset.carbs = f"{totals['carbohydrates_g']:.1f}"
            log_btn.dataset.fat = f"{totals['total_fat_g']:.1f}"
            log_btn.dataset.fiber = f"{totals['dietary_fiber_g']:.1f}"

    return totals


def serialize_recipe_ingredients(msg_id: str) -> bool:
    """Collect all ingredient input rows from DOM and serialize into hidden ingredients_json field."""
    if not msg_id:
        return False
    recalculate_recipe_macros_realtime(msg_id)
    state = CLIENT_INGREDIENT_STATES.get(msg_id) or {}
    return len(state.get("items") or []) > 0


def toggle_recipe_mode(msg_id: str, enable_edit: bool = True) -> None:
    """Toggle between read-only ingredients view and in-place editable recipe form."""
    if not msg_id:
        return
    static_view = window.document.getElementById(f"ingredients-static-{msg_id}")
    edit_form = window.document.getElementById(f"ingredients-form-{msg_id}")
    toggle_btn = window.document.getElementById(f"customize-recipe-btn-{msg_id}")
    details = window.document.getElementById(f"ingredients-details-{msg_id}")

    if details:
        details.open = True

    if enable_edit:
        if static_view:
            static_view.classList.add("hidden")
        if edit_form:
            edit_form.classList.remove("hidden")
        if toggle_btn:
            toggle_btn.classList.add("hidden")
        recalculate_recipe_macros_realtime(msg_id)
        if edit_form:
            edit_form.scrollIntoView(to_js({"behavior": "smooth", "block": "nearest"}))
            name_input = edit_form.querySelector('input[name="dish_name"]')
            if name_input:
                name_input.focus()
    else:
        if edit_form:
            edit_form.classList.add("hidden")
        if static_view:
            static_view.classList.remove("hidden")
        if toggle_btn:
            toggle_btn.classList.remove("hidden")


def add_ingredient_row_to_dom(msg_id: str, name: str = "", weight: float = 50.0, desc: str = "1 serving") -> None:
    """Add a new editable ingredient composition row with name, description, weight, and delete button."""
    if not msg_id:
        return
    container = window.document.getElementById(f"ingredient-rows-{msg_id}")
    if not container:
        return
    row = window.document.createElement("div")
    row.className = "ingredient-row flex flex-nowrap items-center gap-2 p-1.5 rounded-lg hover:bg-stone-50/80 transition"
    row.setAttribute("data-ingredient-row", "")
    row.setAttribute("data-orig-name", name)
    row.setAttribute("data-orig-weight", str(weight))
    weight_str = f"{weight:.0f}" if weight else "50"
    row.innerHTML = (
        '<div class="flex-1 min-w-[140px]">'
        f'<input type="text" class="ing-name-input form-input text-xs font-semibold text-stone-800 !py-1.5 !px-2.5 border-stone-200 rounded-lg w-full" placeholder="e.g. Rice flakes, Coconut oil, Ghee" value="{name}" required>'
        '</div>'
        '<div class="w-28 sm:w-36 flex-none">'
        f'<input type="text" class="ing-desc-input form-input text-xs text-stone-600 !py-1.5 !px-2 border-stone-200 rounded-lg w-full" placeholder="e.g. 1 tbsp, 1 cup" value="{desc}">'
        '</div>'
        '<div class="w-24 flex-none flex items-center justify-end gap-1">'
        f'<input type="number" step="1" min="1" max="5000" class="ing-weight-input form-input text-xs font-bold text-stone-900 !py-1.5 !px-2 w-16 text-right border-stone-200 rounded-lg" value="{weight_str}" required>'
        '<span class="text-[11px] font-medium text-stone-500">g</span>'
        '</div>'
        '<div class="w-8 flex-none flex justify-center">'
        f'<button type="button" class="delete-ingredient-row-btn h-8 w-8 rounded-lg flex items-center justify-center text-stone-400 hover:text-red-600 hover:bg-red-50 border border-transparent hover:border-red-200 transition cursor-pointer" data-ingredient-name="{name}" title="Remove ingredient" aria-label="Remove ingredient">'
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>'
        '</button>'
        '</div>'
    )
    container.appendChild(row)
    recalculate_recipe_macros_realtime(msg_id)
    inp = row.querySelector(".ing-name-input")
    if inp:
        inp.focus()


async def handle_recipe_customize_submit(form) -> None:
    """
    Pure PyScript handler for household recipe customization.
    Collects ingredients from the DOM, posts to backend, and updates DOM with recalculated nutrition.
    Zero JavaScript.
    """
    msg_id = getattr(form.dataset, "recipeFormMsg", "") or getattr(form, "id", "").replace("recipe-form-", "")
    if not msg_id:
        return

    conv_id = getattr(form.dataset, "conversationId", "")
    if not conv_id:
        c_input = form.querySelector('input[name="conversation_id"]')
        if c_input:
            conv_id = c_input.value or ""

    dish_name_input = form.querySelector('input[name="dish_name"]')
    dish_name = dish_name_input.value if dish_name_input else "Customized Meal"
    dish_desc_input = form.querySelector('textarea[name="dish_description"]')
    dish_desc = dish_desc_input.value if dish_desc_input else ""

    # Extract all ingredient rows directly from DOM
    rows = form.querySelectorAll(".ingredient-row, [data-ingredient-row]")
    ingredients = []
    if rows:
        for i in range(rows.length):
            r = rows.item(i)
            name_el = r.querySelector(".ing-name-input")
            desc_el = r.querySelector(".ing-desc-input")
            weight_el = r.querySelector(".ing-weight-input")
            name_val = (name_el.value if name_el else "").strip()
            desc_val = (desc_el.value if desc_el else "1 serving").strip() or "1 serving"
            try:
                weight_val = float(weight_el.value if weight_el else 0.0)
            except Exception:
                weight_val = 0.0
            if name_val and weight_val > 0:
                ingredients.append({
                    "food_name": name_val,
                    "serving_size_description": desc_val,
                    "estimated_weight_grams": weight_val,
                })

    if not ingredients:
        window.alert("Please provide at least one valid ingredient with weight greater than 0g.")
        return

    save_btn = form.querySelector(".save-recipe-btn, button[type='submit']")
    orig_html = save_btn.innerHTML if save_btn else ""
    if save_btn:
        save_btn.disabled = True
        save_btn.innerHTML = "<span>Recalculating...</span>"

    try:
        resp = await window.fetch(
            "/chats/customize-recipe",
            to_js({
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                    "HX-Request": "true",
                    "Accept": "text/html",
                },
                "body": json.dumps({
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "dish_name": dish_name,
                    "dish_description": dish_desc,
                    "ingredients": ingredients,
                }),
            }),
        )

        if resp.ok:
            html = await resp.text()
            target_section = window.document.getElementById(f"results-{msg_id}")
            if target_section:
                target_section.outerHTML = html
                # Re-run real-time recalculator to keep local state synced
                recalculate_recipe_macros_realtime(msg_id)
        else:
            err_data = await resp.text()
            window.alert(f"Failed to recalculate recipe: {err_data[:200]}")
    except Exception as exc:
        window.alert(f"An error occurred while saving the recipe: {exc}")
    finally:
        if save_btn:
            save_btn.disabled = False
            save_btn.innerHTML = orig_html


async def handle_reset_recipe(msg_id: str, conv_id: str = "") -> None:
    """Reset customized recipe back to original AI detected composition."""
    if not msg_id:
        return
    try:
        resp = await window.fetch(
            "/chats/reset-recipe",
            to_js({
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                    "HX-Request": "true",
                    "Accept": "text/html",
                },
                "body": json.dumps({
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                }),
            }),
        )
        if resp.ok:
            html = await resp.text()
            target_section = window.document.getElementById(f"results-{msg_id}")
            if target_section:
                target_section.outerHTML = html
                recalculate_recipe_macros_realtime(msg_id)
    except Exception as exc:
        window.alert(f"Could not reset recipe: {exc}")


@when("beforeunload", window)
def cleanup_image_urls(event):
    for image_url in recording["submitted_image_urls"]:
        window.URL.revokeObjectURL(image_url)
