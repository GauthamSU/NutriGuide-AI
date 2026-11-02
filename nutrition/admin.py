from django.contrib import admin
from nutrition.models import (
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


class VernacularInline(admin.TabularInline):
    model = FoodVernacularName
    extra = 0


class ProximateInline(admin.StackedInline):
    model = ProximateNutrient
    can_delete = False
    extra = 0


class VitaminInline(admin.StackedInline):
    model = VitaminNutrient
    can_delete = False
    extra = 0


class CarotenoidInline(admin.StackedInline):
    model = CarotenoidNutrient
    can_delete = False
    extra = 0


class MineralInline(admin.StackedInline):
    model = MineralNutrient
    can_delete = False
    extra = 0


class SugarInline(admin.StackedInline):
    model = SugarNutrient
    can_delete = False
    extra = 0


class FattyAcidInline(admin.StackedInline):
    model = FattyAcidNutrient
    can_delete = False
    extra = 0


class AminoAcidInline(admin.StackedInline):
    model = AminoAcidNutrient
    can_delete = False
    extra = 0


class OrganicAcidInline(admin.StackedInline):
    model = OrganicAcidNutrient
    can_delete = False
    extra = 0


class PolyphenolInline(admin.StackedInline):
    model = PolyphenolNutrient
    can_delete = False
    extra = 0


class BioactiveInline(admin.StackedInline):
    model = BioactiveNutrient
    can_delete = False
    extra = 0


@admin.register(FoodGroup)
class FoodGroupAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    ordering = ("code",)


@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    list_display = ("food_code", "name", "group", "scientific_name", "no_of_regions")
    list_filter = ("group",)
    search_fields = ("food_code", "name", "scientific_name")
    ordering = ("food_code",)
    inlines = [
        VernacularInline,
        ProximateInline,
        VitaminInline,
        CarotenoidInline,
        MineralInline,
        SugarInline,
        FattyAcidInline,
        AminoAcidInline,
        OrganicAcidInline,
        PolyphenolInline,
        BioactiveInline,
    ]


@admin.register(FoodVernacularName)
class FoodVernacularNameAdmin(admin.ModelAdmin):
    list_display = ("food", "language", "name")
    list_filter = ("language",)
    search_fields = ("name", "food__name", "food__food_code")


@admin.register(ProximateNutrient)
class ProximateAdmin(admin.ModelAdmin):
    list_display = ("food", "energy_kcal", "protein_g", "carbohydrates_g", "total_fat_g", "total_fiber_g")
    search_fields = ("food__food_code", "food__name")


@admin.register(VitaminNutrient)
class VitaminAdmin(admin.ModelAdmin):
    list_display = ("food", "vitamin_c_mg", "thiamine_b1_mg", "folates_b9_mcg", "vitamin_e_mg")
    search_fields = ("food__food_code", "food__name")


@admin.register(CarotenoidNutrient)
class CarotenoidAdmin(admin.ModelAdmin):
    list_display = ("food", "total_carotenoids_mcg", "beta_carotene_mcg", "lutein_mcg", "lycopene_mcg")
    search_fields = ("food__food_code", "food__name")


@admin.register(MineralNutrient)
class MineralAdmin(admin.ModelAdmin):
    list_display = ("food", "calcium_mg", "iron_mg", "magnesium_mg", "potassium_mg", "sodium_mg", "zinc_mg")
    search_fields = ("food__food_code", "food__name")


@admin.register(SugarNutrient)
class SugarAdmin(admin.ModelAdmin):
    list_display = ("food", "total_starch_g", "total_free_sugars_g", "glucose_g", "fructose_g", "sucrose_g")
    search_fields = ("food__food_code", "food__name")


@admin.register(FattyAcidNutrient)
class FattyAcidAdmin(admin.ModelAdmin):
    list_display = ("food", "is_cooking_oil_percent", "total_sfa_mg", "total_mufa_mg", "total_pufa_mg", "cholesterol_mg")
    list_filter = ("is_cooking_oil_percent",)
    search_fields = ("food__food_code", "food__name")


@admin.register(AminoAcidNutrient)
class AminoAcidAdmin(admin.ModelAdmin):
    list_display = ("food", "leucine_g", "lysine_g", "methionine_g", "tryptophan_g", "valine_g")
    search_fields = ("food__food_code", "food__name")


@admin.register(OrganicAcidNutrient)
class OrganicAcidAdmin(admin.ModelAdmin):
    list_display = ("food", "oxalate_total_mg", "citric_acid_mg", "malic_acid_mg", "tartaric_acid_mg")
    search_fields = ("food__food_code", "food__name")


@admin.register(PolyphenolNutrient)
class PolyphenolAdmin(admin.ModelAdmin):
    list_display = ("food", "total_polyphenols_mg", "quercetin_mg", "ferulic_acid_mg", "chlorogenic_acid_mg")
    search_fields = ("food__food_code", "food__name")


@admin.register(BioactiveNutrient)
class BioactiveAdmin(admin.ModelAdmin):
    list_display = ("food", "beta_sitosterol_mg", "campesterol_mg", "phytate_mg", "total_saponin_mg")
    search_fields = ("food__food_code", "food__name")


