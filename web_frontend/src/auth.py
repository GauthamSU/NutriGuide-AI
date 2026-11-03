"""
Authentication & Password Intelligence for NutriGuide PyScript Frontend.
Evaluates password strength, generates secure credentials, and manages auth flows.
"""

import json
import random
import re
import secrets
from pyscript import window
from pyscript.ffi import to_js  # dicts -> plain JS objects (not Map)

from ui import show_feedback


def evaluate_password_strength(password: str) -> dict:
    """Evaluate password complexity across length, case, digits, and special characters."""
    pw = str(password or "")
    rules = {
        "length": len(pw) >= 8,
        "upper": bool(re.search(r"[A-Z]", pw)),
        "lower": bool(re.search(r"[a-z]", pw)),
        "digit": bool(re.search(r"[0-9]", pw)),
        "special": bool(re.search(r"[^A-Za-z0-9\s]", pw)),
    }
    score = sum(1 for v in rules.values() if v)
    return {
        "rules": rules,
        "score": score,
        "is_strong": score == 5,
    }


def update_password_strength_ui(password: str) -> None:
    """Update progress bars, badge, and requirement checklist in the DOM."""
    analysis = evaluate_password_strength(password)
    rules = analysis["rules"]
    score = analysis["score"]

    color_map = {
        0: "#dfe6dc",
        1: "#c65a42",
        2: "#d97706",
        3: "#d97706",
        4: "#3b82f6",
        5: "#1f7a44",
    }
    label_map = {
        0: {"text": "Enter password", "cls": "badge-pill badge-amber !py-0.5 !px-2.5 !text-[10.5px]"},
        1: {"text": "Very Weak (1/5)", "cls": "badge-pill badge-coral !py-0.5 !px-2.5 !text-[10.5px]"},
        2: {"text": "Weak (2/5)", "cls": "badge-pill badge-coral !py-0.5 !px-2.5 !text-[10.5px]"},
        3: {"text": "Fair (3/5)", "cls": "badge-pill badge-amber !py-0.5 !px-2.5 !text-[10.5px]"},
        4: {"text": "Almost Strong (4/5)", "cls": "badge-pill badge-blue !py-0.5 !px-2.5 !text-[10.5px]"},
        5: {"text": "Strong Password ✓", "cls": "badge-pill badge-green !py-0.5 !px-2.5 !text-[10.5px]"},
    }

    bars_container = window.document.getElementById("password-strength-bars")
    if bars_container:
        bars_container.setAttribute("aria-valuenow", str(score))

    bars = window.document.querySelectorAll(
        "#password-strength-bars .pw-strength-seg, #password-strength-bars [data-pw-bar]"
    )
    for i in range(bars.length):
        bar = bars.item(i)
        bar_idx = int(bar.dataset.pwBar) if bar.dataset.pwBar else (i + 1)
        bar.style.backgroundColor = color_map.get(score, "#dfe6dc") if bar_idx <= score else "#dfe6dc"

    badge = window.document.getElementById("password-strength-badge")
    if badge:
        meta = label_map.get(score, label_map[0])
        badge.textContent = meta["text"]
        badge.className = meta["cls"]

    checks = window.document.querySelectorAll("[data-pw-check], [data-pw-rule]")
    for i in range(checks.length):
        li = checks.item(i)
        key = li.dataset.pwCheck or li.dataset.pwRule
        met = bool(rules.get(key, False))
        icon = li.querySelector(".pw-check-icon, [data-pw-icon]")
        if met:
            li.className = "pw-check-item flex items-center gap-2 font-semibold text-[#1f7a44]"
            if icon:
                icon.textContent = "✓"
                icon.className = "pw-check-icon inline-grid h-4 w-4 place-items-center rounded-full bg-[#1f7a44] text-[10px] font-bold text-white"
        else:
            li.className = "pw-check-item flex items-center gap-2 text-[#6d7871]"
            if icon:
                icon.textContent = "○"
                icon.className = "pw-check-icon inline-grid h-4 w-4 place-items-center rounded-full border border-[#c5d1c6] bg-white text-[10px] font-bold"


def generate_strong_password() -> str:
    """Generate a cryptographically random, high-entropy 16-character password."""
    upper = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    lower = "abcdefghijkmnopqrstuvwxyz"
    digits = "23456789"
    specials = "!@#$%^&*_-+="
    all_chars = upper + lower + digits + specials

    chars = [
        secrets.choice(upper),
        secrets.choice(upper),
        secrets.choice(lower),
        secrets.choice(lower),
        secrets.choice(digits),
        secrets.choice(digits),
        secrets.choice(specials),
        secrets.choice(specials),
    ]
    for _ in range(8):
        chars.append(secrets.choice(all_chars))

    random.shuffle(chars)
    password = "".join(chars)

    pw_input = window.document.getElementById("signup-password")
    if pw_input:
        pw_input.value = password
        pw_input.setAttribute("type", "text")
        update_password_strength_ui(password)

    toggle_btn = window.document.querySelector('[data-toggle-pw="signup-password"]')
    if toggle_btn:
        toggle_btn.textContent = "Hide"

    return password


def toggle_password_visibility(btn) -> None:
    """Toggle password text input visibility between obscured and readable."""
    target_id = btn.dataset.togglePw if hasattr(btn, "dataset") and btn.dataset.togglePw else None
    if not target_id:
        return
    pw_input = window.document.getElementById(target_id)
    if not pw_input:
        return
    current_type = pw_input.getAttribute("type")
    if current_type == "password":
        pw_input.setAttribute("type", "text")
        btn.textContent = "Hide"
    else:
        pw_input.setAttribute("type", "password")
        btn.textContent = "Show"


def switch_auth_tab(mode: str) -> None:
    """Toggle between Login and Signup panels and update tabs."""
    login_panel = window.document.getElementById("login-form") or window.document.getElementById("auth-panel-login")
    signup_panel = window.document.getElementById("signup-form") or window.document.getElementById("auth-panel-signup")
    login_tab = window.document.getElementById("auth-tab-login")
    signup_tab = window.document.getElementById("auth-tab-signup")

    is_signup = (mode == "signup")
    if login_panel:
        login_panel.classList.toggle("hidden", is_signup)
    if signup_panel:
        signup_panel.classList.toggle("hidden", not is_signup)

    if login_tab:
        login_tab.classList.toggle("is-active", not is_signup)
        login_tab.setAttribute("aria-selected", "false" if is_signup else "true")
    if signup_tab:
        signup_tab.classList.toggle("is-active", is_signup)
        signup_tab.setAttribute("aria-selected", "true" if is_signup else "false")


async def handle_login(form) -> None:
    """Process login form submission asynchronously via window.fetch."""
    ident_input = form.querySelector('input[name="identifier"]')
    pw_input = form.querySelector('input[name="password"]')
    ident = (ident_input.value if ident_input else "").strip()
    pw = pw_input.value if pw_input else ""

    if not ident or not pw:
        show_feedback("login-feedback", "Please enter both username/email and password.", True)
        return

    show_feedback("login-feedback", "Signing in...", False)
    submit_btn = form.querySelector('button[type="submit"]')
    if submit_btn:
        submit_btn.disabled = True

    try:
        payload = json.dumps({"identifier": ident, "password": pw})
        resp = await window.fetch(
            "/auth/login",
            to_js({
                "method": "POST",
                "headers": {"Content-Type": "application/json", "Accept": "application/json"},
                "body": payload,
            }),
        )
        data = await resp.json()
        if not resp.ok:
            detail = getattr(data, "detail", "Invalid username or password.")
            show_feedback("login-feedback", str(detail), True)
            if submit_btn:
                submit_btn.disabled = False
            return

        show_feedback("login-feedback", "Signed in successfully! Redirecting...", False)
        window.location.href = "/"
    except Exception as exc:
        show_feedback("login-feedback", f"Network error during sign in: {exc}", True)
        if submit_btn:
            submit_btn.disabled = False


async def handle_signup(form) -> None:
    """Process user registration with strict password strength validation."""
    username_input = form.querySelector('input[name="username"]')
    email_input = form.querySelector('input[name="email"]')
    name_input = form.querySelector('input[name="full_name"]')
    pw_input = form.querySelector('input[name="password"]')

    username = (username_input.value if username_input else "").strip()
    email = (email_input.value if email_input else "").strip()
    full_name = (name_input.value if name_input else "").strip()
    password = pw_input.value if pw_input else ""

    if not username or not email or not password:
        show_feedback("signup-feedback", "Username, email, and password are required.", True)
        return

    strength = evaluate_password_strength(password)
    if strength["score"] < 4:
        show_feedback(
            "signup-feedback",
            "Please choose a stronger password (must meet at least 4 of the 5 security requirements).",
            True,
        )
        return

    show_feedback("signup-feedback", "Creating your account...", False)
    submit_btn = form.querySelector('button[type="submit"]')
    if submit_btn:
        submit_btn.disabled = True

    try:
        payload = json.dumps({
            "username": username,
            "email": email,
            "full_name": full_name,
            "password": password,
        })
        resp = await window.fetch(
            "/auth/signup",
            to_js({
                "method": "POST",
                "headers": {"Content-Type": "application/json", "Accept": "application/json"},
                "body": payload,
            }),
        )
        data = await resp.json()
        if not resp.ok:
            detail = getattr(data, "detail", "Registration could not be completed.")
            show_feedback("signup-feedback", str(detail), True)
            if submit_btn:
                submit_btn.disabled = False
            return

        show_feedback("signup-feedback", "Account created successfully! Redirecting...", False)
        window.location.href = "/"
    except Exception as exc:
        show_feedback("signup-feedback", f"Registration error: {exc}", True)
        if submit_btn:
            submit_btn.disabled = False


async def handle_logout() -> None:
    """End the current session and reload the application."""
    try:
        await window.fetch(
            "/auth/logout",
            to_js({
                "method": "POST",
                "headers": {"Accept": "application/json"},
            }),
        )
    finally:
        window.location.href = "/"
