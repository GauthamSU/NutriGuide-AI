"""
Backward-compatibility model registry for Django 'nutrition' app.
All models are modularly defined and documented in backend/food_database/models.py:
- Food, FoodGroup, FoodVernacularName
- ProximateNutrient, VitaminNutrient, MineralNutrient, etc.
"""

from backend.food_database.models import (
    AminoAcidNutrient,
    BioactiveNutrient,
    CarotenoidNutrient,
    FattyAcidNutrient,
    Food,
    FoodGroup,
    FoodVernacularName,
    MineralNutrient,
    OrganicAcidNutrient,
    PolyphenolNutrient,
    ProximateNutrient,
    SugarNutrient,
    VitaminNutrient,
)

__all__ = [
    "FoodGroup",
    "Food",
    "FoodVernacularName",
    "ProximateNutrient",
    "VitaminNutrient",
    "MineralNutrient",
    "FattyAcidNutrient",
    "AminoAcidNutrient",
    "CarotenoidNutrient",
    "PolyphenolNutrient",
    "OrganicAcidNutrient",
    "BioactiveNutrient",
    "SugarNutrient",
]
