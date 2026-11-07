"""
Community Nutrition Groups for NutriGuide PyScript Frontend.

Responsibilities:
  * Groups directory (joined groups + public search) on the /groups page
  * Collapsible sidebar list of the user's groups (Discord / WhatsApp style)
  * Full-page group view at /groups/{id}: meal posts and admin invites
  * Create / join group and membership request responses

Zero JavaScript. Pure Python.
"""

import json
from pyscript import window
from pyscript.ffi import to_js  # dicts -> plain JS objects (not Map)

from ui import close_modal, encode_audio_buffer_to_wav, error_detail, open_modal, read_json, set_page_loading, show_feedback


groups_cache = {"my_groups": [], "public_groups": []}
active_group_tab = "my-groups"

JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


# ─── Small helpers ────────────────────────────────────────────────────────────


def _htmx_attrs(el, url: str) -> None:
    """Attach HTMX navigation attributes so a link swaps into #chat-view."""
    el.setAttribute("hx-get", url)
    el.setAttribute("hx-select", "main")
    el.setAttribute("hx-target", "#chat-view")
    el.setAttribute("hx-swap", "innerHTML")
    el.setAttribute("hx-push-url", url)
    el.setAttribute("hx-indicator", "#chat-loading")


def _htmx_process(el) -> None:
    """Ask HTMX to wire up hx-* attributes on dynamically created elements."""
    try:
        if el and getattr(window, "htmx", None):
            window.htmx.process(el)
    except Exception:
        pass


async def _post_json(url: str, body: dict | None = None):
    """POST JSON to the frontend proxy and return (ok, python_dict)."""
    options = {"method": "POST", "headers": JSON_HEADERS}
    if body is not None:
        options["body"] = json.dumps(body)
    resp = await window.fetch(url, to_js(options))
    data = await read_json(resp)
    return bool(resp.ok), data


async def _get_json(url: str):
    """GET JSON from the frontend proxy and return (ok, python_dict)."""
    resp = await window.fetch(
        url, to_js({"headers": {"Accept": "application/json"}})
    )
    data = await read_json(resp)
    return bool(resp.ok), data


def current_group_page_id() -> str:
    """Return the group id if the user is currently viewing a group page."""
    main_page = window.document.querySelector('main[data-page="group-detail"]')
    if main_page and main_page.dataset.groupId:
        return str(main_page.dataset.groupId)
    return ""


# ─── Navigation ───────────────────────────────────────────────────────────────


async def navigate_to(url: str) -> None:
    """Swap a page into #chat-view via HTMX (falls back to a full page load)."""
    htmx = getattr(window, "htmx", None)
    if not htmx:
        window.location.href = url
        return
    set_page_loading(True)
    try:
        await htmx.ajax(
            "GET",
            url,
            to_js(
                {"target": "#chat-view", "select": "main", "swap": "innerHTML"},
            ),
        )
        if window.location.pathname != url:
            window.history.pushState(None, "", url)
    except Exception:
        window.location.href = url
    finally:
        set_page_loading(False)
    sync_sidebar_active_group()


async def navigate_to_group(group_id: str) -> None:
    """Open the dedicated full-page view for a group."""
    await navigate_to(f"/groups/{group_id}")


# ─── Sidebar (collapsible list of joined groups) ─────────────────────────────


def sync_sidebar_active_group() -> None:
    """Highlight the sidebar group that matches the current URL."""
    path = str(window.location.pathname or "")
    active_id = path.removeprefix("/groups/").strip("/") if path.startswith("/groups/") else ""
    for item in window.document.querySelectorAll("[data-sidebar-group-id]"):
        item.classList.toggle("is-active", bool(active_id) and item.dataset.sidebarGroupId == active_id)


def render_sidebar_groups(groups: list) -> None:
    """Rebuild the sidebar list of groups the user is a member / admin of."""
    container = window.document.getElementById("sidebar-my-groups-list")
    if not container:
        return
    container.replaceChildren()
    doc = window.document

    # Update badge with count of joined groups
    badge = window.document.getElementById("groups-nav-badge")
    if badge:
        count = len(groups) if groups else 0
        if count > 0:
            badge.textContent = str(count)
            badge.className = "ml-auto inline-flex items-center justify-center rounded-full bg-[#245c43] px-2 py-0.5 text-[10px] font-bold text-white shadow-2xs"
        else:
            badge.className = "ml-auto hidden items-center justify-center rounded-full bg-[#245c43] px-2 py-0.5 text-[10px] font-bold text-white"

    if not groups:
        empty = doc.createElement("div")
        empty.className = "px-2 py-1 text-[11px] text-stone-500 italic"
        empty.textContent = "No joined groups yet"
        container.append(empty)
    else:
        for grp in groups:
            grp_id = str(grp.get("id"))
            name = grp.get("name") or "Nutrition Group"

            link = doc.createElement("a")
            link.href = f"/groups/{grp_id}"
            link.className = "sidebar-group-item flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-stone-600 hover:text-stone-900 hover:bg-white transition-colors"
            link.dataset.sidebarGroupId = grp_id
            link.title = name
            _htmx_attrs(link, f"/groups/{grp_id}")

            avatar = doc.createElement("span")
            avatar.className = "sidebar-group-avatar grid h-5 w-5 place-items-center rounded-md bg-stone-200 text-[10px] font-bold text-stone-700 flex-none"
            avatar.textContent = name[:2].upper()

            label = doc.createElement("span")
            label.className = "sidebar-group-name truncate flex-1 font-medium text-xs text-stone-800"
            label.textContent = name

            link.append(avatar, label)
            if grp.get("is_admin"):
                admin_badge = doc.createElement("span")
                admin_badge.className = "badge-pill rounded-full bg-emerald-100 text-emerald-800 px-1.5 py-0.2 text-[9px] font-bold"
                admin_badge.textContent = "Admin"
                link.append(admin_badge)
            container.append(link)

    explore = doc.createElement("a")
    explore.href = "/groups"
    explore.className = "sidebar-group-explore flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-semibold text-[#245c43] hover:underline"
    _htmx_attrs(explore, "/groups")
    explore_label = doc.createElement("span")
    explore_label.textContent = "+ Explore Directory"
    explore.append(explore_label)
    container.append(explore)

    _htmx_process(container)
    sync_sidebar_active_group()


async def refresh_sidebar_groups() -> None:
    """Fetch the user's groups and refresh the sidebar list."""
    if not window.document.getElementById("sidebar-my-groups-list"):
        return
    try:
        ok, payload = await _get_json("/groups/data")
        if ok and isinstance(payload, dict):
            render_sidebar_groups(payload.get("my_groups") or [])
    except Exception:
        pass


# ─── Groups directory page (/groups) ─────────────────────────────────────────


def render_group_directory_list(container_id: str, groups: list, is_public_tab: bool = False) -> None:
    """Render list cards for the public directory or the user's joined groups."""
    container = window.document.getElementById(container_id)
    if not container:
        return
    container.replaceChildren()
    doc = window.document

    if not groups:
        empty = doc.createElement("div")
        empty.className = "rounded-xl border border-dashed border-[#c8d8ca] bg-[#f8fbf7] p-5 text-center"
        if is_public_tab:
            empty.innerHTML = '<p class="m-0 text-xs text-[#6d7871]">No matching public groups found.</p>'
        else:
            empty.innerHTML = """
              <p class="serif m-0 text-lg text-[#173c2c]">You haven't joined any groups yet</p>
              <p class="m-0 mt-1 text-xs leading-relaxed text-[#53645a]">
                Create your own private or public group, or search the public directory to join an existing community.
              </p>
              <div class="group-empty-state-actions">
                <button type="button" class="btn-primary !py-2 !px-3.5 !text-xs" data-open-create-group-modal>+ Create a Group</button>
                <button type="button" class="btn-secondary !py-2 !px-3.5 !text-xs" id="focus-public-search-btn">Search Public Groups</button>
              </div>
            """
        container.append(empty)
        return

    for grp in groups:
        grp_id = str(grp.get("id"))
        is_member = bool(grp.get("is_member"))
        is_public = bool(grp.get("is_public"))
        can_open = is_member or is_public

        card = doc.createElement("div")
        card.className = "group-list-card"
        card.dataset.groupCardId = grp_id

        left = doc.createElement("div")
        left.className = "min-w-0 flex-1"

        top_row = doc.createElement("div")
        top_row.className = "mb-1 flex flex-wrap items-center gap-1.5"

        name_el = doc.createElement("strong")
        name_el.className = "truncate text-sm font-bold text-[#173c2c]"
        name_el.textContent = grp.get("name") or "Nutrition Group"

        badge = doc.createElement("span")
        badge.className = (
            "badge-pill badge-green !py-0.5 !px-2 !text-[10px]"
            if is_public
            else "badge-pill badge-amber !py-0.5 !px-2 !text-[10px]"
        )
        badge.textContent = "Public" if is_public else "Private"
        top_row.append(name_el, badge)

        if grp.get("is_admin"):
            a_badge = doc.createElement("span")
            a_badge.className = "badge-pill badge-blue !py-0.5 !px-2 !text-[10px]"
            a_badge.textContent = "Admin"
            top_row.append(a_badge)
        elif is_member and is_public_tab:
            m_badge = doc.createElement("span")
            m_badge.className = "badge-pill badge-blue !py-0.5 !px-2 !text-[10px]"
            m_badge.textContent = "Joined"
            top_row.append(m_badge)

        desc = doc.createElement("p")
        desc.className = "m-0 truncate text-xs text-[#6d7871]"
        desc.textContent = grp.get("description") or "Shared collective nutrition group"

        m_count = grp.get("member_count") or 1
        cals = round(grp.get("total_calories_kcal") or 0.0)
        prot = round(grp.get("total_protein_g") or 0.0, 1)
        stats = doc.createElement("p")
        stats.className = "m-0 mt-1 text-[11px] font-semibold text-[#245c43]"
        stats.textContent = f"{m_count} {'member' if m_count == 1 else 'members'} · {cals} kcal · {prot}g protein"

        left.append(top_row, desc, stats)

        actions = doc.createElement("div")
        actions.className = "flex items-center gap-2"

        if is_public_tab and not is_member:
            if grp.get("has_pending_join_request"):
                pending = doc.createElement("span")
                pending.className = "badge-pill badge-amber !py-1 !px-2.5 !text-[11px] font-semibold"
                pending.textContent = "Request Pending"
                actions.append(pending)
                if grp.get("pending_request_id"):
                    cancel_btn = doc.createElement("button")
                    cancel_btn.type = "button"
                    cancel_btn.className = "btn-secondary !py-1 !px-2.5 !text-[11px] text-[#9d4534]"
                    cancel_btn.dataset.requestAction = "cancel"
                    cancel_btn.dataset.requestId = str(grp["pending_request_id"])
                    cancel_btn.textContent = "Cancel"
                    actions.append(cancel_btn)
            elif grp.get("has_pending_invitation"):
                acc_btn = doc.createElement("button")
                acc_btn.type = "button"
                acc_btn.className = "btn-primary !py-1.5 !px-3 !text-xs"
                acc_btn.dataset.requestAction = "accept"
                acc_btn.dataset.requestId = str(grp.get("pending_request_id"))
                acc_btn.textContent = "Accept Invite"
                actions.append(acc_btn)
            else:
                join_btn = doc.createElement("button")
                join_btn.type = "button"
                join_btn.className = "btn-secondary !py-1.5 !px-3 !text-xs"
                join_btn.dataset.joinGroupId = grp_id
                join_btn.textContent = "Request to Join"
                actions.append(join_btn)

        if can_open:
            view_link = doc.createElement("a")
            view_link.href = f"/groups/{grp_id}"
            view_link.className = "btn-primary !py-1.5 !px-3 !text-xs inline-flex items-center gap-1"
            _htmx_attrs(view_link, f"/groups/{grp_id}")
            view_link.textContent = "View Group →" if is_member else "Open →"
            actions.append(view_link)

        card.append(left, actions)
        container.append(card)

    _htmx_process(container)


def _set_count(element_id: str, value: int) -> None:
    el = window.document.getElementById(element_id)
    if el:
        el.textContent = str(value)


async def load_groups_data(query: str = "", public_only: bool = False) -> None:
    """Fetch groups from the backend and re-render the directory lists."""
    global groups_cache
    if not window.document.querySelector('[data-page="groups"]'):
        return

    url = f"/groups/data?q={window.encodeURIComponent(query)}" if query else "/groups/data"
    try:
        ok, payload = await _get_json(url)
        if not ok or not isinstance(payload, dict):
            return
        groups_cache["public_groups"] = payload.get("public_groups") or []
        render_group_directory_list("public-groups-list", groups_cache["public_groups"], True)
        _set_count("public-groups-count", len(groups_cache["public_groups"]))

        if not public_only:
            groups_cache["my_groups"] = payload.get("my_groups") or []
            render_group_directory_list("my-groups-list", groups_cache["my_groups"], False)
            _set_count("my-groups-count", len(groups_cache["my_groups"]))
            render_sidebar_groups(groups_cache["my_groups"])
    except Exception:
        pass


def focus_public_search() -> None:
    """Scroll to and focus the public groups search box."""
    s_input = window.document.getElementById("public-groups-search")
    if s_input:
        s_input.scrollIntoView(to_js({"behavior": "smooth", "block": "center"}))
        s_input.focus()


def switch_groups_tab(tab_name: str) -> None:
    """Toggle between My Groups and Public Groups directory tabs (if present)."""
    global active_group_tab
    active_group_tab = tab_name
    my_panel = window.document.getElementById("groups-tab-panel-my")
    pub_panel = window.document.getElementById("groups-tab-panel-public")
    my_tab = window.document.getElementById("groups-tab-my")
    pub_tab = window.document.getElementById("groups-tab-public")

    is_pub = tab_name == "public-groups"
    if my_panel:
        my_panel.classList.toggle("hidden", is_pub)
    if pub_panel:
        pub_panel.classList.toggle("hidden", not is_pub)
    if my_tab:
        my_tab.classList.toggle("is-active", not is_pub)
        my_tab.setAttribute("aria-selected", "false" if is_pub else "true")
    if pub_tab:
        pub_tab.classList.toggle("is-active", is_pub)
        pub_tab.setAttribute("aria-selected", "true" if is_pub else "false")


# ─── Create group modal ──────────────────────────────────────────────────────


def open_create_group_modal() -> None:
    """Open the Create Group modal with a clean form."""
    show_feedback("create-group-feedback", "")
    open_modal("create-group-modal")
    name_input = window.document.getElementById("group-name-input")
    if name_input:
        name_input.focus()


def sync_visibility_cards() -> None:
    """Highlight the selected Public / Private card and update the name hint."""
    form = window.document.getElementById("create-group-form")
    if not form:
        return
    selected = "public"
    for card in form.querySelectorAll("[data-visibility-card]"):
        radio = card.querySelector('input[type="radio"]')
        is_checked = bool(radio and radio.checked)
        card.classList.toggle("is-selected", is_checked)
        if is_checked:
            selected = radio.value
    hint = window.document.getElementById("group-name-hint")
    if hint:
        hint.textContent = (
            "Public group names must be unique across NutriGuide."
            if selected == "public"
            else "Private groups are invite-only and visible only to members."
        )


async def handle_create_group(form) -> None:
    """Create a new nutrition group, then open its group page."""
    name_input = form.querySelector('input[name="name"]')
    desc_input = form.querySelector('textarea[name="description"]')
    vis_checked = form.querySelector('input[name="visibility"]:checked')
    members_input = form.querySelector('input[name="member_identifiers"]')

    name = (name_input.value if name_input else "").strip()
    desc = (desc_input.value if desc_input else "").strip()
    visibility = vis_checked.value if vis_checked else "public"
    members_raw = (members_input.value if members_input else "").strip()
    members = [m.strip() for m in members_raw.replace(";", ",").split(",") if m.strip()]

    if not name:
        show_feedback("create-group-feedback", "Group name is required.", True)
        if name_input:
            name_input.focus()
        return

    show_feedback("create-group-feedback", "Creating group...", False)
    submit_btn = form.querySelector('button[type="submit"]')
    if submit_btn:
        submit_btn.disabled = True

    try:
        ok, data = await _post_json(
            "/groups/create",
            {
                "name": name,
                "description": desc,
                "visibility": visibility,
                "is_public": visibility == "public",
                "member_identifiers": members,
            },
        )
        if not ok:
            show_feedback("create-group-feedback", error_detail(data, "Could not create group."), True)
            return

        form.reset()
        sync_visibility_cards()
        show_feedback("create-group-feedback", "")
        close_modal("create-group-modal")
        await refresh_sidebar_groups()

        new_grp_id = data.get("id") if isinstance(data, dict) else None
        if new_grp_id:
            await navigate_to_group(str(new_grp_id))
        else:
            await load_groups_data()
    except Exception as exc:
        show_feedback("create-group-feedback", f"Network error: {exc}", True)
    finally:
        if submit_btn:
            submit_btn.disabled = False


# ─── Membership actions ──────────────────────────────────────────────────────


async def _reload_current_groups_view() -> None:
    """Refresh whichever groups view is on screen plus the sidebar."""
    group_id = current_group_page_id()
    if group_id:
        await navigate_to_group(group_id)
    elif window.document.querySelector('[data-page="groups"]'):
        await navigate_to("/groups")
    await refresh_sidebar_groups()
    await refresh_group_notifications()


async def handle_join_group(group_id: str) -> None:
    """Send a join request for a public group."""
    try:
        ok, data = await _post_json(f"/groups/{group_id}/join")
        if not ok:
            show_feedback("group-create-feedback", error_detail(data, "Could not join this group."), True)
            return
        await _reload_current_groups_view()
    except Exception:
        pass


async def handle_respond_group_request(request_id: str, action: str) -> None:
    """Accept, reject, or cancel a group membership request or invitation."""
    try:
        ok, data = await _post_json(f"/groups/requests/{request_id}/respond", {"action": action})
        if not ok:
            show_feedback("group-create-feedback", error_detail(data, "Could not update this request."), True)
            return
        await _reload_current_groups_view()
    except Exception:
        pass


# ─── Group page (/groups/{id}) forms ─────────────────────────────────────────


group_meal_media = {
    "image_url": None,
    "stream": None,
    "recorder": None,
    "chunks": [],
    "recorder_callback": None,
    "recorder_stop_callback": None,
}


def trigger_group_meal_image_picker() -> None:
    """Admin/Member: Open image file picker dialog."""
    img_el = window.document.getElementById("group-meal-image")
    if img_el:
        img_el.click()


def trigger_group_meal_audio_upload() -> None:
    """Open audio file picker dialog."""
    voice_el = window.document.getElementById("group-meal-voice")
    if voice_el:
        voice_el.click()


def handle_group_meal_image_change(event=None) -> None:
    """Handle selected image file and display preview chip."""
    img_input = window.document.getElementById("group-meal-image")
    if not img_input or not img_input.files or not img_input.files.length:
        return
    if group_meal_media["image_url"]:
        try:
            window.URL.revokeObjectURL(group_meal_media["image_url"])
        except Exception:
            pass
    file = img_input.files.item(0)
    group_meal_media["image_url"] = window.URL.createObjectURL(file)
    render_group_meal_attachment_chips()


def remove_group_meal_image() -> None:
    """Clear the selected group meal image file."""
    if group_meal_media["image_url"]:
        try:
            window.URL.revokeObjectURL(group_meal_media["image_url"])
        except Exception:
            pass
        group_meal_media["image_url"] = None
    img_input = window.document.getElementById("group-meal-image")
    if img_input:
        img_input.value = ""
    render_group_meal_attachment_chips()


def handle_group_meal_voice_change(event=None) -> None:
    """Handle manually uploaded audio file."""
    render_group_meal_attachment_chips()


def remove_group_meal_voice() -> None:
    """Clear the attached voice recording or uploaded audio."""
    voice_input = window.document.getElementById("group-meal-voice")
    if voice_input:
        voice_input.value = ""
    status_el = window.document.getElementById("group-meal-recording-status")
    if status_el:
        status_el.classList.remove("inline-flex")
        status_el.classList.add("hidden")
        status_el.style.display = "none"
    mic_btn = window.document.getElementById("group-meal-mic-btn")
    if mic_btn:
        mic_btn.classList.remove("recording")
    mic_label = window.document.getElementById("group-meal-mic-label")
    if mic_label:
        mic_label.textContent = "Record Voice"
    render_group_meal_attachment_chips()


async def toggle_group_meal_voice_recording() -> None:
    """Toggle live microphone recording for group meal notes with instant UI response."""
    mic_btn = window.document.getElementById("group-meal-mic-btn")
    mic_label = window.document.getElementById("group-meal-mic-label")
    status_el = window.document.getElementById("group-meal-recording-status")

    if group_meal_media["recorder"]:
        # 1. User clicked STOP -> IMMEDIATELY hide recording status banner and reset button
        if mic_btn:
            mic_btn.classList.remove("recording")
        if mic_label:
            mic_label.textContent = "Record Voice"
        if status_el:
            status_el.classList.remove("inline-flex")
            status_el.classList.add("hidden")
            status_el.style.display = "none"

        recorder = group_meal_media["recorder"]
        group_meal_media["recorder"] = None

        try:
            if recorder and getattr(recorder, "state", "") != "inactive":
                import asyncio
                loop = asyncio.get_running_loop()
                stopped_future = loop.create_future()

                def on_stop(event=None):
                    if not stopped_future.done():
                        stopped_future.set_result(True)

                recorder.onstop = on_stop
                group_meal_media["recorder_stop_callback"] = on_stop
                try:
                    recorder.stop()
                    await asyncio.wait_for(stopped_future, timeout=2.5)
                except Exception:
                    pass

            # Stop microphone tracks safely
            if group_meal_media["stream"]:
                for track in group_meal_media["stream"].getTracks():
                    try:
                        track.stop()
                    except Exception:
                        pass
                group_meal_media["stream"] = None

            # Process collected audio chunks into voice attachment
            chunks = group_meal_media["chunks"]
            if chunks:
                audio_blob = window.Blob.new(to_js(chunks), to_js({"type": getattr(recorder, "mimeType", "") or "audio/webm"}))
                audio_context_cls = window.AudioContext or getattr(window, "webkitAudioContext", None)
                if audio_context_cls:
                    try:
                        audio_ctx = audio_context_cls.new()
                        arr_buffer = await audio_blob.arrayBuffer()
                        audio_buffer = await audio_ctx.decodeAudioData(arr_buffer)
                        wav_blob = encode_audio_buffer_to_wav(audio_buffer)
                    except Exception:
                        wav_blob = audio_blob
                else:
                    wav_blob = audio_blob
                audio_file = window.File.new(to_js([wav_blob]), "group-voice-note.wav", to_js({"type": "audio/wav"}))
                data_transfer = window.DataTransfer.new()
                data_transfer.items.add(audio_file)
                voice_el = window.document.getElementById("group-meal-voice")
                if voice_el:
                    voice_el.files = data_transfer.files
                render_group_meal_attachment_chips()
        except Exception as exc:
            show_feedback("group-meal-feedback", f"Voice recording error: {exc}", True)
        finally:
            if group_meal_media["stream"]:
                for track in group_meal_media["stream"].getTracks():
                    try:
                        track.stop()
                    except Exception:
                        pass
                group_meal_media["stream"] = None
            group_meal_media["recorder"] = None
            group_meal_media["recorder_callback"] = None
            group_meal_media["recorder_stop_callback"] = None
            if mic_btn:
                mic_btn.classList.remove("recording")
            if mic_label:
                mic_label.textContent = "Record Voice"
            if status_el:
                status_el.classList.remove("inline-flex")
                status_el.classList.add("hidden")
                status_el.style.display = "none"

    else:
        # Not recording -> START
        try:
            stream = await window.navigator.mediaDevices.getUserMedia(to_js({"audio": True}))
            group_meal_media["stream"] = stream
            recorder = window.MediaRecorder.new(stream)
            group_meal_media["recorder"] = recorder
            group_meal_media["chunks"] = []

            def on_data(event):
                if getattr(event, "data", None) and event.data.size:
                    group_meal_media["chunks"].append(event.data)

            recorder.ondataavailable = on_data
            group_meal_media["recorder_callback"] = on_data
            recorder.start()

            if mic_btn:
                mic_btn.classList.add("recording")
            if mic_label:
                mic_label.textContent = "Stop Recording"
            if status_el:
                status_el.classList.remove("hidden")
                status_el.classList.add("inline-flex")
                status_el.style.display = "inline-flex"
        except Exception as exc:
            show_feedback("group-meal-feedback", f"Microphone access error: {exc}", True)


def render_group_meal_attachment_chips() -> None:
    """Render chip badges with remove buttons for attached meal photos or voice notes."""
    container = window.document.getElementById("group-meal-attachment-chips")
    if not container:
        return
    container.replaceChildren()
    doc = window.document

    img_input = doc.getElementById("group-meal-image")
    voice_input = doc.getElementById("group-meal-voice")

    has_chips = False
    if img_input and img_input.files and img_input.files.length:
        has_chips = True
        chip = doc.createElement("div")
        chip.className = "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#eaf4ec] border border-[#cbe3cf] text-xs font-semibold text-[#1a5336]"
        if group_meal_media["image_url"]:
            thumb = doc.createElement("img")
            thumb.src = group_meal_media["image_url"]
            thumb.className = "w-4 h-4 rounded object-cover flex-none"
            chip.append(thumb)
        file_name = img_input.files.item(0).name
        label = doc.createElement("span")
        label.textContent = file_name
        label.className = "truncate max-w-[160px]"
        chip.append(label)

        rm_btn = doc.createElement("button")
        rm_btn.type = "button"
        rm_btn.textContent = "✕"
        rm_btn.className = "ml-1 text-[#9d4534] hover:text-[#c65a42] font-bold cursor-pointer"
        rm_btn.setAttribute("data-remove-group-meal-image", "true")
        chip.append(rm_btn)
        container.append(chip)

    if voice_input and voice_input.files and voice_input.files.length:
        has_chips = True
        chip = doc.createElement("div")
        chip.className = "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#edf4fc] border border-[#c3daf5] text-xs font-semibold text-[#15467c]"
        chip.innerHTML = "<span>🎙️</span><span>Voice note attached</span>"

        rm_btn = doc.createElement("button")
        rm_btn.type = "button"
        rm_btn.textContent = "✕"
        rm_btn.className = "ml-1 text-[#9d4534] hover:text-[#c65a42] font-bold cursor-pointer"
        rm_btn.setAttribute("data-remove-group-meal-voice", "true")
        chip.append(rm_btn)
        container.append(chip)

    if has_chips:
        container.classList.remove("hidden")
    else:
        container.classList.add("hidden")


async def handle_group_page_log_meal(form) -> None:
    """Post a meal to the current group's feed and collective totals using AI database resolution."""
    gid_input = form.querySelector('input[name="group_id"]')
    title_input = form.querySelector('textarea[name="meal_title"]') or form.querySelector('input[name="meal_title"]')
    type_select = form.querySelector('select[name="meal_type"]')
    img_input = form.querySelector('input[name="image"]')
    voice_input = form.querySelector('input[name="voice"]')

    group_id = gid_input.value if gid_input else current_group_page_id()
    meal_title = (title_input.value if title_input else "").strip()
    meal_type = type_select.value if type_select else "Lunch"

    has_img = bool(img_input and img_input.files and img_input.files.length)
    has_voice = bool(voice_input and voice_input.files and voice_input.files.length)

    if not meal_title and not has_img and not has_voice:
        show_feedback("group-meal-feedback", "Please enter what you ate or attach a photo / voice note.", True)
        return

    show_feedback("group-meal-feedback", "Analyzing meal with AI & calculating database nutrition...", False)
    submit_btn = form.querySelector('button[type="submit"]')
    if submit_btn:
        submit_btn.disabled = True

    try:
        form_data = window.FormData.new()
        form_data.append("group_id", group_id)
        form_data.append("meal_title", meal_title or "Shared Meal")
        form_data.append("meal_type", meal_type)

        if has_img:
            form_data.append("image", img_input.files.item(0))
        if has_voice:
            form_data.append("voice", voice_input.files.item(0))

        resp = await window.fetch(f"/groups/{group_id}/meals", to_js({
            "method": "POST",
            "body": form_data,
        }))
        data = await read_json(resp)
        if not resp.ok:
            show_feedback("group-meal-feedback", error_detail(data, "Failed to post meal."), True)
            return

        form.reset()
        remove_group_meal_image()
        remove_group_meal_voice()
        show_feedback("group-meal-feedback", "")
        await navigate_to_group(group_id)
    except Exception as exc:
        show_feedback("group-meal-feedback", f"Network error: {exc}", True)
    finally:
        if submit_btn:
            submit_btn.disabled = False


async def handle_group_page_invite_member(form) -> None:
    """Admin: invite a user to the group by username or email."""
    gid_input = form.querySelector('input[name="group_id"]')
    id_input = form.querySelector('input[name="identifier"]')

    group_id = gid_input.value if gid_input else current_group_page_id()
    identifier = (id_input.value if id_input else "").strip()

    if not identifier:
        show_feedback("group-invite-feedback", "Please enter a username or email.", True)
        return

    show_feedback("group-invite-feedback", "Sending invitation...", False)
    submit_btn = form.querySelector('button[type="submit"]')
    if submit_btn:
        submit_btn.disabled = True

    try:
        ok, data = await _post_json(f"/groups/{group_id}/members", {"identifier": identifier})
        if not ok:
            show_feedback("group-invite-feedback", error_detail(data, "Could not send invitation."), True)
            return
        await navigate_to_group(group_id)
    except Exception as exc:
        show_feedback("group-invite-feedback", f"Network error: {exc}", True)
    finally:
        if submit_btn:
            submit_btn.disabled = False


# ─── Notifications badge ─────────────────────────────────────────────────────


async def refresh_group_notifications() -> None:
    """Update the sidebar badge with pending invitations / join requests or joined group count."""
    badge = window.document.getElementById("groups-nav-badge")
    if not badge:
        return
    try:
        ok, payload = await _get_json("/groups/notifications")
        if not ok or not isinstance(payload, dict):
            return
        total_count = int(payload.get("notifications_count") or payload.get("total_count") or 0)
        if total_count > 0:
            badge.textContent = str(total_count)
            badge.className = "ml-auto inline-flex items-center justify-center rounded-full bg-[#c65a42] px-1.5 py-0.5 text-[10px] font-bold text-white shadow-2xs"
        else:
            sidebar_links = window.document.querySelectorAll("#sidebar-my-groups-list [data-sidebar-group-id]")
            grp_count = sidebar_links.length if sidebar_links else 0
            if grp_count > 0:
                badge.textContent = str(grp_count)
                badge.className = "ml-auto inline-flex items-center justify-center rounded-full bg-[#245c43] px-2 py-0.5 text-[10px] font-bold text-white shadow-2xs"
            else:
                badge.className = "ml-auto hidden items-center justify-center rounded-full bg-[#245c43] px-2 py-0.5 text-[10px] font-bold text-white"
    except Exception:
        pass


async def handle_delete_group_meal(group_id: str, meal_id: str) -> None:
    """Delete a meal from a group feed and refresh the view."""
    if not group_id or not meal_id:
        return
    try:
        ok, data = await _post_json(f"/groups/{group_id}/meals/{meal_id}/delete")
        if not ok:
            window.alert(error_detail(data, "Could not delete this meal from the group."))
            return
        await _reload_current_groups_view()
    except Exception as exc:
        window.alert(f"An error occurred: {exc}")

