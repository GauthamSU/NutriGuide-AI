"""
User Profile & Biometrics Management for NutriGuide PyScript Frontend.
Handles profile updates, multipart avatar uploads with instant preview, and allergen tagging.
"""

from pyscript import window
from pyscript.ffi import to_js  # dicts -> plain JS objects (not Map)

from ui import show_feedback


preview_avatar_url = None


def handle_avatar_file_change(input_el) -> None:
    """Instantly render an uploaded photo preview in the profile card before submission."""
    global preview_avatar_url
    if not input_el or not input_el.files or not input_el.files.length:
        return

    file = input_el.files.item(0)
    if preview_avatar_url:
        window.URL.revokeObjectURL(preview_avatar_url)
    preview_avatar_url = window.URL.createObjectURL(file)

    preview_img = window.document.getElementById("profile-avatar-preview")
    if preview_img:
        preview_img.src = preview_avatar_url
        preview_img.classList.remove("hidden")

    preview_placeholder = window.document.getElementById("profile-avatar-placeholder")
    if preview_placeholder:
        preview_placeholder.classList.add("hidden")

    remove_flag = window.document.getElementById("remove-profile-picture-flag")
    if remove_flag:
        remove_flag.value = "0"


def handle_remove_avatar() -> None:
    """Reset user profile photo to the default initials/icon placeholder."""
    global preview_avatar_url
    if preview_avatar_url:
        window.URL.revokeObjectURL(preview_avatar_url)
        preview_avatar_url = None

    file_input = window.document.getElementById("profile-avatar-file") or window.document.getElementById("profile-picture-file")
    if file_input:
        file_input.value = ""

    preview_img = window.document.getElementById("profile-avatar-preview")
    if preview_img:
        preview_img.src = ""
        preview_img.classList.add("hidden")

    preview_placeholder = window.document.getElementById("profile-avatar-placeholder")
    if preview_placeholder:
        preview_placeholder.classList.remove("hidden")

    remove_flag = window.document.getElementById("remove-profile-picture-flag")
    if remove_flag:
        remove_flag.value = "1"


def handle_add_allergen_chip(chip_el) -> None:
    """Append a clicked allergen tag to the comma-separated allergies input."""
    allergen = (chip_el.dataset.addAllergen or chip_el.textContent or "").strip()
    if not allergen:
        return

    input_el = window.document.getElementById("profile-allergies")
    if not input_el:
        return

    current = [x.strip() for x in (input_el.value or "").split(",") if x.strip()]
    if allergen.lower() not in [x.lower() for x in current]:
        current.append(allergen)
        input_el.value = ", ".join(current)


async def handle_profile_submit(form) -> None:
    """Submit the user profile form with multipart avatar file upload support."""
    show_feedback("profile-feedback", "Saving profile changes...", False)
    submit_btn = form.querySelector('button[type="submit"]')
    if submit_btn:
        submit_btn.disabled = True

    try:
        form_data = window.FormData.new(form)
        resp = await window.fetch(
            "/profile",
            to_js({
                "method": "POST",
                "body": form_data,
            }),
        )
        data = await resp.json()
        if not resp.ok:
            detail = getattr(data, "detail", "Failed to update profile.")
            show_feedback("profile-feedback", str(detail), True)
            if submit_btn:
                submit_btn.disabled = False
            return

        show_feedback("profile-feedback", "Profile updated successfully! ✓", False)
        if submit_btn:
            submit_btn.disabled = False

        # Refresh header user avatar/display name if available
        header_name = window.document.getElementById("header-user-name")
        if header_name and getattr(data, "full_name", None):
            header_name.textContent = str(data.full_name)
    except Exception as exc:
        show_feedback("profile-feedback", f"Network error saving profile: {exc}", True)
        if submit_btn:
            submit_btn.disabled = False
