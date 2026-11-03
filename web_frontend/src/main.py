"""
NutriGuide Application Coordinator (PyScript Entrypoint).
Zero JavaScript. Pure Python client-side event delegation, state coordination, and HTMX lifecycle hooks.
"""

import asyncio
import sys
from pyscript import when, window
from pyscript.ffi import to_js  # dicts -> plain JS objects (not Map)

for p in [".", "/home/pyodide", "/", "./src", "/src"]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import ui
except ModuleNotFoundError:
    try:
        from pyodide.http import open_url
        for mod_name in ["ui", "auth", "profile", "tracker", "meal_planner", "groups", "chat"]:
            try:
                code_text = open_url(f"/src/{mod_name}.py").read()
                with open(f"{mod_name}.py", "w", encoding="utf-8") as f:
                    f.write(code_text)
            except Exception:
                pass
    except Exception:
        pass

from ui import (
    close_delete_confirmation,
    close_modal,
    execute_confirmed_delete,
    open_modal,
    request_delete_confirmation,
    set_page_loading,
    show_feedback,
    toggle_sidebar,
)
from auth import (
    generate_strong_password,
    handle_login,
    handle_logout,
    handle_signup,
    switch_auth_tab,
    toggle_password_visibility,
    update_password_strength_ui,
)
from profile import (
    handle_add_allergen_chip,
    handle_avatar_file_change,
    handle_profile_submit,
    handle_remove_avatar,
)
from tracker import (
    active_tracker_period,
    handle_delete_tracked_meal,
    handle_submit_chat_log,
    handle_submit_manual_tracker_log,
    init_tracker_from_dom,
    load_tracker_data,
    open_chat_log_modal,
    render_tracker_period,
)
from meal_planner import (
    delete_meal_plan,
    get_selected_meal_plan_preferences,
    handle_meal_plan_submit,
    load_meal_plan_history,
    remove_attachment,
    show_historical_meal_plan,
    sync_meal_plan_mode_ui,
    toggle_meal_plan_preference,
    toggle_meal_plan_voice_recording,
    trigger_meal_plan_audio_upload,
    trigger_meal_plan_image_picker,
    update_meal_plan_attachment_chips,
)
from groups import (
    focus_public_search,
    handle_create_group,
    handle_group_meal_image_change,
    handle_group_meal_voice_change,
    handle_group_page_invite_member,
    handle_group_page_log_meal,
    handle_join_group,
    handle_respond_group_request,
    load_groups_data,
    navigate_to_group,
    open_create_group_modal,
    refresh_group_notifications,
    refresh_sidebar_groups,
    remove_group_meal_image,
    remove_group_meal_voice,
    switch_groups_tab,
    sync_sidebar_active_group,
    sync_visibility_cards,
    toggle_group_meal_voice_recording,
    trigger_group_meal_audio_upload,
    trigger_group_meal_image_picker,
)
from chat import (
    handle_delete_chat_message,
    handle_delete_conversation,
)


# ─── Global Click Delegation ───────────────────────────────────────────────────


@when("click", "body")
async def handle_global_clicks(event):
    target = getattr(event, "target", None)
    if not target or not hasattr(target, "closest"):
        return

    # 1. Sidebar Toggle
    sidebar_btn = target.closest("#sidebar-toggle")
    if sidebar_btn:
        toggle_sidebar()
        return

    # 1b. Sidebar Groups Collapse Toggle
    groups_toggle_btn = target.closest("#sidebar-groups-toggle")
    if groups_toggle_btn:
        wrapper = window.document.getElementById("sidebar-groups-wrapper")
        if wrapper:
            is_open = wrapper.classList.toggle("is-open")
            groups_toggle_btn.setAttribute("aria-expanded", "true" if is_open else "false")
        return

    # 1c. Jump to Group Meal Composer
    jump_post_btn = target.closest(".jump-to-post-meal-btn")
    if jump_post_btn:
        composer = window.document.getElementById("group-meal-composer")
        if composer:
            composer.scrollIntoView(to_js({"behavior": "smooth", "block": "center"}))
            m_input = window.document.getElementById("group-meal-title")
            if m_input:
                m_input.focus()
        return

    # 2. Modal Close button or backdrop
    close_btn = target.closest("[data-close-modal]")
    if close_btn:
        modal_id = close_btn.dataset.closeModal
        close_modal(modal_id)
        return

    if getattr(target, "classList", None) and (
        target.classList.contains("modal-backdrop") or target.classList.contains("app-modal-backdrop")
    ):
        target.classList.add("hidden")
        return

    # 3. Open Create Group Modal
    create_grp_trigger = (
        target.closest("[data-open-create-group-modal]")
        or target.closest("#open-create-group-modal-btn")
        or target.closest(".open-create-group-trigger")
    )
    if create_grp_trigger:
        if hasattr(create_grp_trigger, "hasAttribute") and create_grp_trigger.hasAttribute("disabled"):
            return
        if getattr(create_grp_trigger, "disabled", False) is True:
            return
        open_create_group_modal()
        return

    # 4. Open Manual Tracker Modal
    manual_tracker_trigger = target.closest(".open-manual-tracker-trigger")
    if manual_tracker_trigger:
        open_modal("manual-tracker-modal")
        return

    # 5. Focus Public Search
    search_trigger = target.closest("#focus-public-search-btn") or target.closest(".focus-public-search-trigger")
    if search_trigger:
        focus_public_search()
        return

    # 5b. Public Groups Search Button
    search_btn = target.closest("#public-groups-search-btn")
    if search_btn:
        s_input = window.document.getElementById("public-groups-search")
        await load_groups_data((s_input.value if s_input else "").strip(), public_only=True)
        return

    # 6. Tracker Period Tab Switch
    tracker_tab = target.closest("[data-tracker-tab]")
    if tracker_tab:
        period = tracker_tab.dataset.trackerTab
        render_tracker_period(period)
        await load_tracker_data(period)
        return

    # 2b. Universal Delete Confirmation Modal Actions
    if target.closest("#confirm-delete-proceed-btn"):
        await execute_confirmed_delete()
        return

    if target.closest("#confirm-delete-cancel-btn") or target.closest('[data-close-modal="confirm-delete-modal"]'):
        close_delete_confirmation()
        return

    # 7. Delete Tracked Meal (With Confirmation Popup)
    del_meal_btn = target.closest("[data-delete-tracked-meal-id]")
    if del_meal_btn:
        log_id = del_meal_btn.dataset.deleteTrackedMealId
        if log_id:
            request_delete_confirmation(
                "Delete Tracked Meal",
                "Are you sure you want to remove this meal from your nutrition diary? Your daily totals will update.",
                lambda: handle_delete_tracked_meal(log_id),
            )
        return

    # 8. Chat Turn: Pop-up "Log to Tracker" Modal
    log_tracker_btn = target.closest("[data-log-to-tracker-btn], .log-tracker-btn, .turn-action-log")
    if log_tracker_btn:
        if (
            log_tracker_btn.hasAttribute("disabled")
            or log_tracker_btn.classList.contains("is-logged")
            or log_tracker_btn.classList.contains("turn-action-logged")
        ):
            return
        open_chat_log_modal(log_tracker_btn)
        return

    # 9. Delete Individual Chat Message (With Confirmation Popup)
    del_msg_btn = target.closest("[data-delete-message-btn], [data-delete-message-id]")
    if del_msg_btn:
        msg_id = del_msg_btn.dataset.messageId or del_msg_btn.dataset.deleteMessageId
        conv_id = del_msg_btn.dataset.conversationId or ""
        if msg_id:
            request_delete_confirmation(
                "Delete Chat Message",
                "Are you sure you want to delete this meal analysis turn? This action cannot be undone.",
                lambda: handle_delete_chat_message(msg_id, conv_id),
            )
        return

    # 10. Delete Entire Conversation (With Confirmation Popup)
    del_conv_btn = target.closest("[data-delete-chat-id], [data-delete-conversation-id]")
    if del_conv_btn:
        conv_id = del_conv_btn.dataset.deleteChatId or del_conv_btn.dataset.deleteConversationId
        if conv_id:
            c_label = del_conv_btn.getAttribute("aria-label") or "this chat"
            request_delete_confirmation(
                "Delete Chat Conversation",
                f"Are you sure you want to delete {c_label}? All messages in this chat will be permanently deleted.",
                lambda: handle_delete_conversation(conv_id),
            )
        return

    # 11. Delete Saved Meal Plan (With Confirmation Popup)
    del_plan_btn = target.closest("[data-delete-meal-plan-id]")
    if del_plan_btn:
        plan_id = del_plan_btn.dataset.deleteMealPlanId
        if plan_id:
            p_label = del_plan_btn.getAttribute("aria-label") or "this meal plan"
            request_delete_confirmation(
                "Delete Saved Meal Plan",
                f"Are you sure you want to delete {p_label} from your library? This action cannot be undone.",
                lambda: delete_meal_plan(plan_id),
            )
        return

    # 12. View Saved Meal Plan from History
    plan_item_btn = target.closest("[data-meal-plan-id]")
    if plan_item_btn:
        plan_id = plan_item_btn.dataset.mealPlanId
        show_historical_meal_plan(plan_id)
        return

    # 13. Meal Plan Duration Radio Tab Click
    dur_tab = target.closest("[data-duration-tab]")
    if dur_tab:
        radio = dur_tab.querySelector('input[name="duration"]')
        if radio and not radio.checked:
            radio.checked = True
        sync_meal_plan_mode_ui()
        return

    # 14. Meal Plan Dietary Preference Radio Card Click
    diet_tab = target.closest("[data-diet-tab]")
    if diet_tab:
        radio = diet_tab.querySelector('input[name="diet_type"]')
        if radio and not radio.checked:
            radio.checked = True
        sync_meal_plan_mode_ui()
        return

    # 15. Meal Plan Health Focus Pill Click
    pref_btn = target.closest(".meal-preference, [data-preference]")
    if pref_btn:
        toggle_meal_plan_preference(pref_btn)
        return

    # 16. Meal Plan Attach Photo Click
    mp_attach_btn = target.closest("#meal-plan-attach-btn")
    if mp_attach_btn:
        trigger_meal_plan_image_picker()
        return

    # 17. Meal Plan Audio Upload Click
    mp_audio_upload_btn = target.closest("#meal-plan-audio-upload-btn")
    if mp_audio_upload_btn:
        trigger_meal_plan_audio_upload()
        return

    # 18. Meal Plan Voice Note Recording Click
    mp_rec_btn = target.closest("#meal-plan-mic-btn, #meal-plan-record-btn")
    if mp_rec_btn:
        await toggle_meal_plan_voice_recording()
        return

    # 19. Meal Plan Remove Attachment
    rem_att_btn = target.closest("[data-remove-attachment]")
    if rem_att_btn:
        kind = rem_att_btn.dataset.removeAttachment
        remove_attachment(kind)
        return

    # 15. Generate Strong Password
    gen_pw_btn = target.closest("[data-generate-pw]")
    if gen_pw_btn:
        generate_strong_password()
        return

    # 16. Toggle Password Visibility
    toggle_pw_btn = target.closest("[data-toggle-pw]")
    if toggle_pw_btn:
        toggle_password_visibility(toggle_pw_btn)
        return

    # 17. Switch Auth Mode Tabs
    auth_tab_btn = target.closest("[data-auth-tab]")
    if auth_tab_btn:
        mode = auth_tab_btn.dataset.authTab
        switch_auth_tab(mode)
        return

    # 18. Logout
    logout_btn = target.closest("#logout-button") or target.closest("[data-logout-button]")
    if logout_btn:
        await handle_logout()
        return

    # 19. Profile Remove Picture
    rem_pic_btn = target.closest("#remove-profile-picture-btn")
    if rem_pic_btn:
        handle_remove_avatar()
        return

    # 20. Profile Add Allergen Tag
    allergen_chip = target.closest("[data-add-allergen]")
    if allergen_chip:
        handle_add_allergen_chip(allergen_chip)
        return

    # 21. Groups Directory Tab Switch
    groups_tab_btn = target.closest("[data-groups-tab]")
    if groups_tab_btn:
        tab_name = groups_tab_btn.dataset.groupsTab
        switch_groups_tab(tab_name)
        return

    # 22. Open Group Page
    open_grp_btn = target.closest("[data-open-group-id]")
    if open_grp_btn:
        grp_id = open_grp_btn.dataset.openGroupId
        await navigate_to_group(grp_id)
        return

    # 23. Join Public Group
    join_grp_btn = target.closest("[data-join-group-id]")
    if join_grp_btn:
        grp_id = join_grp_btn.dataset.joinGroupId
        await handle_join_group(grp_id)
        return

    # 24. Respond to Group Request (Accept / Reject / Cancel)
    req_action_btn = target.closest("[data-request-action]")
    if req_action_btn:
        req_id = req_action_btn.dataset.requestId
        action = req_action_btn.dataset.requestAction
        await handle_respond_group_request(req_id, action)
        return

    # 25. Modal Category Card Selection
    cat_card = target.closest(".modal-cat-card")
    if cat_card:
        radio = cat_card.querySelector('input[type="radio"]')
        if radio:
            radio.checked = True
        return

    # 26. Modal Time Option Card Selection
    time_card = target.closest(".modal-time-card")
    if time_card:
        radio = time_card.querySelector('input[type="radio"]')
        if radio:
            radio.checked = True
            is_custom = (radio.value == "custom")
            custom_box = window.document.getElementById("log-modal-custom-time-container")
            if custom_box:
                custom_box.classList.toggle("hidden", not is_custom)
            m_custom_box = window.document.getElementById("manual-custom-time-container")
            if m_custom_box:
                m_custom_box.classList.toggle("hidden", not is_custom)
        return

    # 27. Visibility Card Selection in Create Group Modal
    vis_card = target.closest("[data-visibility-card]")
    if vis_card:
        radio = vis_card.querySelector('input[type="radio"]')
        if radio:
            radio.checked = True
            sync_visibility_cards()
        return

    # 28. Group Meal Attach Photo Button
    grp_attach_btn = target.closest("#group-meal-attach-btn")
    if grp_attach_btn:
        trigger_group_meal_image_picker()
        return

    # 29. Group Meal Voice Recording Button
    grp_mic_btn = target.closest("#group-meal-mic-btn")
    if grp_mic_btn:
        asyncio.create_task(toggle_group_meal_voice_recording())
        return

    # 30. Group Meal Audio Upload Button
    grp_audio_btn = target.closest("#group-meal-audio-upload-btn")
    if grp_audio_btn:
        trigger_group_meal_audio_upload()
        return

    # 31. Remove Group Meal Image Attachment
    if target.closest("[data-remove-group-meal-image]"):
        remove_group_meal_image()
        return

    # 32. Remove Group Meal Voice Attachment
    if target.closest("[data-remove-group-meal-voice]"):
        remove_group_meal_voice()
        return


# ─── Global Input Delegation ───────────────────────────────────────────────────


@when("input", "body")
def handle_global_inputs(event):
    target = getattr(event, "target", None)
    if not target:
        return

    # 1. Password Complexity Evaluation
    if getattr(target, "id", "") == "signup-password":
        update_password_strength_ui(target.value)

    # 2. Live Public Groups Search
    elif getattr(target, "id", "") in ("public-groups-search", "groups-search-input"):
        asyncio.create_task(load_groups_data(target.value.strip(), public_only=True))


# ─── Global Change Delegation ──────────────────────────────────────────────────


@when("change", "body")
def handle_global_changes(event):
    target = getattr(event, "target", None)
    if not target:
        return

    # 1. Profile Picture Avatar Upload
    if getattr(target, "id", "") == "profile-picture-file":
        handle_avatar_file_change(target)

    # 2. Meal Plan Image Attachment
    elif getattr(target, "id", "") == "meal-plan-image":
        update_meal_plan_attachment_chips()

    # 3. Meal Plan Voice Attachment
    elif getattr(target, "id", "") == "meal-plan-voice":
        update_meal_plan_attachment_chips()

    # 4. Meal Plan Form Duration / Diet Radio Changes
    elif getattr(target, "name", "") in ("duration", "diet_type"):
        sync_meal_plan_mode_ui()

    # 4b. Create Group Public / Private Visibility Cards
    elif getattr(target, "name", "") == "visibility":
        sync_visibility_cards()

    # 4c. Group Meal Photo Selected
    elif getattr(target, "id", "") == "group-meal-image":
        handle_group_meal_image_change(event)

    # 4d. Group Meal Audio Selected
    elif getattr(target, "id", "") == "group-meal-voice":
        handle_group_meal_voice_change(event)

    # 5. Modal Time Option Radios
    elif getattr(target, "name", "") in ("log_modal_time_option", "time_option"):
        is_custom = (target.value == "custom")
        c_box = window.document.getElementById("log-modal-custom-time-container")
        if c_box:
            c_box.classList.toggle("hidden", not is_custom)
        m_box = window.document.getElementById("manual-custom-time-container")
        if m_box:
            m_box.classList.toggle("hidden", not is_custom)


# ─── Global Form Submit Delegation ─────────────────────────────────────────────


@when("submit", "body")
async def handle_global_submits(event):
    form = getattr(event, "target", None)
    if not form or getattr(form, "tagName", "").upper() != "FORM":
        return

    form_id = getattr(form, "id", "")

    # 1. Login Form
    if form_id == "login-form":
        event.preventDefault()
        await handle_login(form)

    # 2. Signup Form
    elif form_id == "signup-form":
        event.preventDefault()
        await handle_signup(form)

    # 3. User Profile Form
    elif form_id == "profile-form":
        event.preventDefault()
        await handle_profile_submit(form)

    # 4. Create Group Form
    elif form_id == "create-group-form":
        event.preventDefault()
        await handle_create_group(form)

    # 5. Meal Plan Generator Form
    elif form_id == "meal-plan-form":
        event.preventDefault()
        await handle_meal_plan_submit(form)

    # 6. Manual Tracker Log Form
    elif form_id == "manual-tracker-form":
        event.preventDefault()
        await handle_submit_manual_tracker_log(form)

    # 7. Chat Dish "Log to Tracker" Confirmation Form
    elif form_id == "log-to-tracker-form":
        event.preventDefault()
        await handle_submit_chat_log(form)

    # 8. Group Detail Page Log Meal
    elif form_id == "group-page-log-meal-form":
        event.preventDefault()
        await handle_group_page_log_meal(form)

    # 9. Group Detail Page Add/Invite Member
    elif form_id == "group-page-add-member-form":
        event.preventDefault()
        await handle_group_page_invite_member(form)


# ─── HTMX Lifecycle Coordination & Page Anchors ────────────────────────────────


def highlight_hash_anchor() -> None:
    """Jump to and highlight target message if a #turn-{id} anchor is in the URL."""
    hash_str = window.location.hash
    if hash_str and hash_str.startswith("#turn-"):
        turn_el = window.document.querySelector(hash_str)
        if turn_el:
            turn_el.scrollIntoView(to_js({"behavior": "smooth", "block": "center"}))
            turn_el.classList.add("ring-2", "ring-[#245c43]", "ring-offset-2")


@when("htmx:afterSwap", "body")
def on_htmx_after_swap(event):
    """Re-initialize view-specific listeners and components after HTMX swap."""
    init_tracker_from_dom()
    render_tracker_period()
    asyncio.create_task(load_meal_plan_history())
    asyncio.create_task(load_groups_data())
    asyncio.create_task(refresh_group_notifications())
    highlight_hash_anchor()


# ─── Initial Page Startup ──────────────────────────────────────────────────────


init_tracker_from_dom()
render_tracker_period()
sync_meal_plan_mode_ui()
asyncio.create_task(load_meal_plan_history())
asyncio.create_task(refresh_sidebar_groups())
asyncio.create_task(refresh_group_notifications())
sync_sidebar_active_group()
highlight_hash_anchor()
