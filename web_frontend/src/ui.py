"""
UI Utilities & Shared DOM Components for NutriGuide PyScript Frontend.
Zero JavaScript. Pure Python executing in-browser via PyScript.
"""

from pyscript import web, window
from pyscript.ffi import to_js  # dicts -> plain JS objects (not Map)
import json


MEAL_SECTION_META = {
    "breakfast": {
        "label": "Breakfast",
        "subtitle": "Morning nourishment & steady metabolic start",
        "iconClass": "meal-icon-breakfast",
        "svg": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 8h1a4 4 0 1 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4Z"/><line x1="6" y1="2" x2="6" y2="4"/><line x1="10" y1="2" x2="10" y2="4"/><line x1="14" y1="2" x2="14" y2="4"/></svg>',
    },
    "lunch": {
        "label": "Lunch",
        "subtitle": "Balanced midday fuel & sustained focus",
        "iconClass": "meal-icon-lunch",
        "svg": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>',
    },
    "snacks": {
        "label": "Snacks",
        "subtitle": "Smart afternoon bridge between meals",
        "iconClass": "meal-icon-snacks",
        "svg": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20.94c1.5 0 2.75 1.06 4 1.06 3 0 6-8 6-12.22A4.91 4.91 0 0 0 17 5c-2.22 0-4 1.44-5 2-1-.56-2.78-2-5-2a4.9 4.9 0 0 0-5 4.78C2 14 5 22 8 22c1.25 0 2.5-1.06 4-1.06Z"/><path d="M10 2c1 .5 2 2 2 5"/></svg>',
    },
    "dinner": {
        "label": "Dinner",
        "subtitle": "Light, restorative evening meal",
        "iconClass": "meal-icon-dinner",
        "svg": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/><path d="M19 3v4"/><path d="M21 5h-4"/></svg>',
    },
}

DIET_LABELS = {
    "veg": "Vegetarian (Veg)",
    "non-veg": "Non-Vegetarian",
    "vegan": "Vegan",
    "egg": "Eggetarian (Egg)",
}

DURATION_LABELS = {
    "daily": "Daily Plan",
    "weekly": "Weekly Plan (7 Days)",
    "monthly": "Monthly Plan (4 Weeks)",
}


def get_element(element_id: str):
    """Safely return a PyScript web element or raw DOM element."""
    raw = window.document.getElementById(element_id)
    if not raw:
        return None
    try:
        return web.page[element_id]
    except Exception:
        return raw


async def read_json(resp) -> dict:
    """
    Read a fetch Response body as native Python data (dict / list).

    `await resp.json()` returns a JsProxy, which does not support `.get()`.
    Decoding the text with Python's json module gives real dicts instead.
    """
    try:
        text = await resp.text()
        data = json.loads(text) if text else {}
    except Exception:
        return {}
    return data if isinstance(data, (dict, list)) else {}


def error_detail(data, default: str) -> str:
    """Extract a human readable error message from an API error payload."""
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("message") or data.get("error")
        if isinstance(detail, list):
            detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
        if detail:
            return str(detail)
    return default


def open_modal(modal_id: str) -> None:
    """Reveal a modal dialog by removing the 'hidden' CSS class."""
    modal = window.document.getElementById(modal_id)
    if modal:
        modal.classList.remove("hidden")


def close_modal(modal_id: str) -> None:
    """Hide a modal dialog by adding the 'hidden' CSS class."""
    modal = window.document.getElementById(modal_id)
    if modal:
        modal.classList.add("hidden")


# ─── Universal Delete Confirmation State & Helpers ─────────────────────────────

_pending_delete_action = None


def request_delete_confirmation(title: str, message: str, callback) -> None:
    """Open universal delete confirmation modal with custom title, message, and execution callback."""
    global _pending_delete_action
    _pending_delete_action = callback

    t_el = window.document.getElementById("confirm-delete-title")
    if t_el:
        t_el.textContent = title
    m_el = window.document.getElementById("confirm-delete-message")
    if m_el:
        m_el.textContent = message

    open_modal("confirm-delete-modal")


def close_delete_confirmation() -> None:
    """Dismiss the universal delete confirmation modal without performing action."""
    global _pending_delete_action
    _pending_delete_action = None
    close_modal("confirm-delete-modal")


async def execute_confirmed_delete() -> None:
    """Execute the pending confirmed deletion callback and close the modal."""
    global _pending_delete_action
    action = _pending_delete_action
    close_delete_confirmation()
    if action:
        try:
            import inspect
            if inspect.iscoroutinefunction(action):
                await action()
            else:
                res = action()
                import asyncio
                if asyncio.iscoroutine(res):
                    await res
        except Exception as exc:
            print("Error executing confirmed delete:", exc)


def show_feedback(element_id: str, message: str, is_error: bool = False) -> None:
    """Display an inline accessible toast / feedback message with Tailwind classes."""
    el = window.document.getElementById(element_id)
    if not el and element_id == "create-group-feedback":
        el = window.document.getElementById("group-create-feedback")
    if not el:
        return
    if not message:
        el.classList.add("hidden")
        return
    el.textContent = message
    if is_error:
        el.className = "mb-4 rounded-xl border border-red-200 bg-red-50/90 p-3.5 text-xs font-medium text-red-700 shadow-sm"
    else:
        el.className = "mb-4 rounded-xl border border-emerald-200 bg-emerald-50/90 p-3.5 text-xs font-medium text-emerald-800 shadow-sm"
    el.classList.remove("hidden")


def toggle_sidebar() -> None:
    """Toggle sidebar open/collapsed state across mobile and desktop breakpoints."""
    sidebar = window.document.getElementById("chat-sidebar")
    toggle = window.document.getElementById("sidebar-toggle")
    if not sidebar or not toggle:
        return

    is_mobile = bool(window.matchMedia("(max-width: 720px)").matches)
    if is_mobile:
        is_open = not sidebar.classList.contains("is-open")
        if is_open:
            sidebar.classList.add("is-open")
        else:
            sidebar.classList.remove("is-open")
        toggle.setAttribute("aria-expanded", "true" if is_open else "false")
    else:
        is_collapsed = sidebar.classList.contains("is-collapsed")
        if is_collapsed:
            sidebar.classList.remove("is-collapsed")
            toggle.setAttribute("aria-expanded", "true")
        else:
            sidebar.classList.add("is-collapsed")
            toggle.setAttribute("aria-expanded", "false")


def set_page_loading(show: bool, title: str = None, subtitle: str = None) -> None:
    """Control the centered mildly blurred loading overlay."""
    overlay = window.document.getElementById("chat-loading")
    if not overlay:
        return
    if title:
        t_el = window.document.getElementById("page-loading-title")
        if t_el:
            t_el.textContent = title
    if subtitle:
        s_el = window.document.getElementById("page-loading-sub")
        if s_el:
            s_el.textContent = subtitle
    if show:
        overlay.classList.add("is-active")
        overlay.style.display = "flex"
    else:
        overlay.classList.remove("is-active")
        overlay.style.display = "none"


def encode_audio_buffer_to_wav(audio_buffer):
    """
    Encode a Web Audio API AudioBuffer into a WAV PCM 16-bit Blob in browser memory.
    """
    num_channels = int(audio_buffer.numberOfChannels)
    sample_rate = int(audio_buffer.sampleRate)
    channels = [audio_buffer.getChannelData(i) for i in range(num_channels)]
    frame_count = int(channels[0].length)
    data_size = frame_count * num_channels * 2

    buffer = window.ArrayBuffer.new(44 + data_size)
    view = window.DataView.new(buffer)

    def write_string(offset: int, s: str):
        for i, ch in enumerate(s):
            view.setUint8(offset + i, ord(ch))

    write_string(0, "RIFF")
    view.setUint32(4, 36 + data_size, True)
    write_string(8, "WAVEfmt ")
    view.setUint32(16, 16, True)
    view.setUint16(20, 1, True)  # PCM
    view.setUint16(22, num_channels, True)
    view.setUint32(24, sample_rate, True)
    view.setUint32(28, sample_rate * num_channels * 2, True)
    view.setUint16(32, num_channels * 2, True)
    view.setUint16(34, 16, True)  # 16-bit
    write_string(36, "data")
    view.setUint32(40, data_size, True)

    offset = 44
    for f in range(frame_count):
        for ch in range(num_channels):
            sample = channels[ch][f]
            # Clamp sample to [-1.0, 1.0]
            if sample > 1.0:
                sample = 1.0
            elif sample < -1.0:
                sample = -1.0
            s_val = int(sample * 32767.0) if sample >= 0 else int(sample * 32768.0)
            view.setInt16(offset, s_val, True)
            offset += 2

    return window.Blob.new(to_js([buffer]), to_js({"type": "audio/wav"}))
