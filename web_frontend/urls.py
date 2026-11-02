"""Page routes for the standalone static frontend server."""

PAGE_ROUTES = {
    "/": "pages/analyze.html",
    "/analyze": "pages/analyze.html",
    "/meal-plan": "pages/meal_plan.html",
    "/tracker": "pages/tracker.html",
    "/login": "pages/auth.html",
    "/signup": "pages/auth.html",
    "/auth": "pages/auth.html",
    "/profile": "pages/profile.html",
    "/groups": "pages/groups.html",
}

FRAGMENT_ROUTES = {
    "/": "components/chat_view.html",
    "/analyze": "components/chat_view.html",
    "/meal-plan": "components/meal_plan_view.html",
    "/tracker": "components/tracker_view.html",
    "/login": "components/auth_view.html",
    "/signup": "components/auth_view.html",
    "/auth": "components/auth_view.html",
    "/profile": "components/profile_view.html",
    "/groups": "components/groups_view.html",
}
