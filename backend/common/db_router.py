class CoreAppDatabaseRouter:
    """
    Database router that routes nutrition reference models (app_label == 'nutrition')
    to the read-only 'nutrition' database (db.sqlite3), and all application tables
    (auth, sessions, contenttypes, admin, chat_history, user profiles, groups, tracker,
    meal plans, and any future apps) to the primary 'default' database (core_app.sqlite3).
    """

    nutrition_alias = "nutrition"
    nutrition_app = "nutrition"
    core_app_alias = "default"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.nutrition_app:
            return self.nutrition_alias
        return self.core_app_alias

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.nutrition_app:
            return self.nutrition_alias
        return self.core_app_alias

    def allow_relation(self, obj1, obj2, **hints):
        is_obj1_nutrition = obj1._meta.app_label == self.nutrition_app
        is_obj2_nutrition = obj2._meta.app_label == self.nutrition_app
        return is_obj1_nutrition == is_obj2_nutrition

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.nutrition_app:
            return db == self.nutrition_alias
        return db == self.core_app_alias


# Alias for backward compatibility
ChatHistoryRouter = CoreAppDatabaseRouter
