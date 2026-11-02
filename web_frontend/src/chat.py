import asyncio

from pyscript import when, web, window
from pyodide.ffi import to_js


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
    return web.page[element_id]


def set_composer_error(message):
    error = element("composer-error")
    if not error:
        return
    error.textContent = message
    if message:
        error.classes.discard("hidden")
    else:
        error.classes.add("hidden")


def revoke_selected_image():
    if recording["image_url"]:
        window.URL.revokeObjectURL(recording["image_url"])
        recording["image_url"] = None


def update_attachment_chips():
    container = element("attachment-label")
    image_input = element("meal-image")
    voice_input = element("voice-upload")
    if not container or not image_input or not voice_input:
        return
    container.innerHTML = ""

    if image_input.files.length:
        if not recording["image_url"]:
            recording["image_url"] = window.URL.createObjectURL(image_input.files.item(0))
        append_image_chip(container, image_input.files.item(0).name, recording["image_url"])

    if voice_input.files.length:
        append_voice_chip(container)


def append_image_chip(container, filename, image_url):
    chip = web.span(classes=["attachment-chip", "image-attachment-chip"])
    thumbnail = web.img(
        src=image_url,
        alt=f"Preview of {filename}",
        classes=["attachment-thumbnail"],
    )
    chip.append(thumbnail)
    chip.append(web.span(filename, classes=["attachment-chip-label"]))
    remove_button = web.button(
        "x",
        type="button",
        title="Remove image",
        classes=["attachment-remove"],
    )
    remove_button._dom_element.setAttribute("aria-label", "Remove image")
    chip.append(remove_button)
    container.append(chip)

    @when("click", remove_button)
    def remove_image(event):
        event.preventDefault()
        img_el = element("meal-image")
        if img_el:
            img_el.value = ""
        revoke_selected_image()
        update_attachment_chips()


def append_voice_chip(container):
    chip = web.span(classes=["attachment-chip", "voice-chip"])
    chip.append(web.span("♫", classes=["attachment-chip-symbol"]))
    chip.append(web.span("Voice note", classes=["attachment-chip-label"]))
    remove_button = web.button(
        "x",
        type="button",
        title="Remove voice note",
        classes=["attachment-remove"],
    )
    remove_button._dom_element.setAttribute("aria-label", "Remove voice note")
    chip.append(remove_button)
    container.append(chip)

    @when("click", remove_button)
    def remove_voice(event):
        event.preventDefault()
        v_el = element("voice-upload")
        if v_el:
            v_el.value = ""
        update_attachment_chips()


def clear_selected_attachments_after_submit():
    if recording["image_url"]:
        recording["submitted_image_urls"].append(recording["image_url"])
        recording["image_url"] = None
    meal_img = element("meal-image")
    voice_up = element("voice-upload")
    if meal_img:
        meal_img.value = ""
    if voice_up:
        voice_up.value = ""
    update_attachment_chips()


def append_pending_turn(description):
    conversation_content = element("conversation-content")
    if not conversation_content:
        return
    user_turn = web.div(classes=["user-turn", "mb-5", "text-sm", "leading-relaxed"])
    if description:
        user_turn.append(web.p(description, classes=["m-0", "break-words"]))

    image_input = element("meal-image")
    voice_input = element("voice-upload")
    if image_input and image_input.files.length and recording["image_url"]:
        preview = web.img(
            src=recording["image_url"],
            alt="Attached meal photo",
            classes=["submitted-image-preview"],
        )
        user_turn.append(preview)
    if voice_input and voice_input.files.length:
        user_turn.append(web.span("Voice note attached", classes=["submitted-voice-label"]))
    conversation_content.append(user_turn)

    pending_turn = web.article(
        id="active-pending-turn",
        classes=["assistant-turn", "mx-auto", "mb-8", "w-full", "min-w-0", "max-w-[760px]"],
    )
    pending_turn.innerHTML = (
        '<div class="mb-3 flex items-center gap-2 text-[11px] font-semibold text-[#53645a]">'
        '<span class="brand-mark !h-7 !w-7 !rounded-[8px_8px_8px_2px] !text-sm">N</span>NutriGuide</div>'
        '<div class="flex items-center gap-3 py-4 text-sm text-[#6d7871]">'
        '<span class="pending-dots inline-flex gap-1"><i class="h-1.5 w-1.5 rounded-full bg-[#245c43]"></i>'
        '<i class="h-1.5 w-1.5 rounded-full bg-[#245c43]"></i><i class="h-1.5 w-1.5 rounded-full bg-[#245c43]"></i></span>'
        'Working on your meal</div>'
    )
    conversation_content.append(pending_turn)
    pending_turn.show_me()


def clear_composer():
    desc = element("meal-description")
    if desc:
        desc.value = ""
    clear_selected_attachments_after_submit()
    set_composer_error("")
    resize_textarea()


def resize_textarea(event=None):
    textarea = element("meal-description")
    if not textarea:
        return
    textarea.style["height"] = "auto"
    textarea.style["height"] = f"{min(textarea._dom_element.scrollHeight, 144)}px"


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

        mic_button = element("mic-button")
        if mic_button:
            mic_button.classes.add("recording")
            mic_button.title = "Stop recording"
            mic_button.setAttribute("aria-label", "Stop recording")
            mic_button.innerHTML = '<svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>'
        status = element("recording-status")
        if status:
            status.classes.discard("hidden")
            status.classes.add("inline-flex")
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

    mic_button = element("mic-button")
    if mic_button:
        mic_button.classes.discard("recording")
        mic_button.title = "Record a voice note"
        mic_button.setAttribute("aria-label", "Record a voice note")
        mic_button.innerHTML = '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></svg>'
    status = element("recording-status")
    if status:
        status.classes.add("hidden")
        status.classes.discard("inline-flex")

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
        voice_up = element("voice-upload")
        if voice_up:
            voice_up.files = transfer.files

        update_attachment_chips()
    except Exception as exc:
        voice_up = element("voice-upload")
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
    desc_el = element("meal-description")
    img_el = element("meal-image")
    voice_el = element("voice-upload")
    if not desc_el or not img_el or not voice_el:
        return
    description = desc_el.value.strip()
    has_image = img_el.files.length > 0
    has_voice = voice_el.files.length > 0
    if not description and not has_image and not has_voice:
        event.preventDefault()
        set_composer_error("Add a meal description, photo, or voice note to continue.")
        desc_el.focus()
    elif recording["recorder"]:
        event.preventDefault()
        set_composer_error("Stop the recording to attach it, then press send.")
    else:
        welcome_message = element("welcome-message")
        if welcome_message:
            welcome_message.classes.add("hidden")
        append_pending_turn(description)
        clear_composer()
        send_button = element("send-button")
        if send_button:
            send_button.disabled = True
            send_button.classes.add("sending")


def after_request(event):
    elt = getattr(getattr(event, "detail", None), "elt", None)
    if not elt or getattr(elt, "id", "") != "chat-form":
        return
    pending_turn = element("active-pending-turn")
    if pending_turn:
        pending_turn.remove()
    send_button = element("send-button")
    if send_button:
        send_button.disabled = False
        send_button.classes.discard("sending")
    if event.detail.successful:
        conv = element("conversation")
        desc = element("meal-description")
        if conv:
            conv.scrollTop = conv.scrollHeight
        if desc:
            desc.focus()


def handle_image_change(event):
    set_composer_error("")
    revoke_selected_image()
    update_attachment_chips()


def handle_enter(event):
    if event.key == "Enter" and not event.shiftKey:
        event.preventDefault()
        send_btn = element("send-button")
        if send_btn:
            send_btn.click()


@when("click", "body")
async def handle_body_click(event):
    target = getattr(event, "target", None)
    if not target or not hasattr(target, "closest"):
        return
    mic_el = target.closest("#mic-button")
    if mic_el and getattr(mic_el, "id", None) == "mic-button":
        if recording["recorder"]:
            await stop_recording()
        else:
            await start_recording()
        return
    attach_el = target.closest("#attach-button")
    if attach_el and getattr(attach_el, "id", None) == "attach-button":
        meal_img = window.document.getElementById("meal-image")
        if meal_img:
            meal_img.click()
        return
    nav_el = target.closest("[data-sidebar-link]") or target.closest(".chat-history-link")
    if nav_el and getattr(nav_el, "href", None):
        if recording["stream"]:
            stop_microphone_tracks()


@when("change", "body")
def handle_image_change_event(event):
    target = getattr(event, "target", None)
    if target and getattr(target, "id", "") == "meal-image":
        handle_image_change(event)


@when("input", "body")
def handle_description_input(event):
    target = getattr(event, "target", None)
    if target and getattr(target, "id", "") == "meal-description":
        resize_textarea(event)


@when("keydown", "body")
def handle_description_keydown(event):
    target = getattr(event, "target", None)
    if target and getattr(target, "id", "") == "meal-description":
        handle_enter(event)


@when("htmx:beforeRequest", "body")
def handle_before_request(event):
    before_request(event)


@when("htmx:afterRequest", "body")
def handle_after_request(event):
    after_request(event)


@when("beforeunload", window)
def cleanup_image_urls(event):
    for image_url in recording["submitted_image_urls"]:
        window.URL.revokeObjectURL(image_url)
