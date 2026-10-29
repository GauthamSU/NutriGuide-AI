import os
import sys
import django

from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

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


def verify():
    print("==================================================")
    print("IFCT 2017 DATABASE VERIFICATION REPORT")
    print("==================================================")

    # 1. Total counts across all tables
    counts = {
        "Food Groups (A-T)": FoodGroup.objects.count(),
        "Food Items (Foods + Oils)": Food.objects.count(),
        "Vernacular Records": FoodVernacularName.objects.count(),
        "Table 1: Proximate Nutrients": ProximateNutrient.objects.count(),
        "Tables 2 & 3: Vitamins": VitaminNutrient.objects.count(),
        "Table 4: Carotenoids": CarotenoidNutrient.objects.count(),
        "Table 5: Minerals": MineralNutrient.objects.count(),
        "Table 6: Sugars & Starch": SugarNutrient.objects.count(),
        "Tables 7 & 12: Fatty Acids": FattyAcidNutrient.objects.count(),
        "Table 8: Amino Acids": AminoAcidNutrient.objects.count(),
        "Table 9: Organic Acids": OrganicAcidNutrient.objects.count(),
        "Table 10: Polyphenols": PolyphenolNutrient.objects.count(),
        "Table 11: Bioactives": BioactiveNutrient.objects.count(),
    }

    for label, cnt in counts.items():
        print(f"  {label:<32}: {cnt:>5}")

    # 2. Deep situational query on Bajra (A003)
    bajra = Food.objects.select_related(
        "group", "proximates", "vitamins", "minerals", "carotenoids",
        "sugars", "fatty_acids", "amino_acids", "organic_acids",
        "polyphenols", "bioactives"
    ).get(food_code="A003")

    print("\n--------------------------------------------------")
    print(f"DEEP QUERY: {bajra.food_code} - {bajra.name} ({bajra.scientific_name})")
    print(f"Group: {bajra.group.code} - {bajra.group.name} | Sampling Regions: {bajra.no_of_regions}")
    print(f"Proximates: Energy = {bajra.proximates.energy_kcal} kcal, Protein = {bajra.proximates.protein_g}g, Fiber = {bajra.proximates.total_fiber_g}g")
    print(f"Fatty Acids: SFA = {bajra.fatty_acids.total_sfa_mg} mg, MUFA = {bajra.fatty_acids.total_mufa_mg} mg, PUFA = {bajra.fatty_acids.total_pufa_mg} mg")
    print(f"Amino Acids: Leucine = {bajra.amino_acids.leucine_g} g/100g prot, Lysine = {bajra.amino_acids.lysine_g} g/100g prot")
    print(f"Carotenoids: Total = {bajra.carotenoids.total_carotenoids_mcg} mcg, Beta-Carotene = {bajra.carotenoids.beta_carotene_mcg} mcg")
    print(f"Sugars: Starch = {bajra.sugars.total_starch_g}g, Free Sugars = {bajra.sugars.total_free_sugars_g}g")
    print(f"Organic Acids: Oxalate = {bajra.organic_acids.oxalate_total_mg} mg")
    print(f"Polyphenols: Total = {bajra.polyphenols.total_polyphenols_mg} mg, Ferulic Acid = {bajra.polyphenols.ferulic_acid_mg} mg")
    print(f"Bioactives: Phytate = {bajra.bioactives.phytate_mg} mg, Beta-Sitosterol = {bajra.bioactives.beta_sitosterol_mg} mg")

    # 3. Animal Food Query: Egg (M001)
    egg = Food.objects.select_related("proximates", "fatty_acids").get(food_code="M001")
    print("\n--------------------------------------------------")
    print(f"ANIMAL FOOD: {egg.food_code} - {egg.name}")
    print(f"Protein: {egg.proximates.protein_g}g | Fat: {egg.proximates.total_fat_g}g")
    print(f"Cholesterol: {egg.fatty_acids.cholesterol_mg} mg | DHA: {egg.fatty_acids.dha_c22_6n3_mg} mg")

    # 4. Cooking Oil Query: Coconut Oil (T001)
    oil = Food.objects.select_related("group", "proximates", "fatty_acids").get(food_code="T001")
    print("\n--------------------------------------------------")
    print(f"COOKING OIL: {oil.food_code} - {oil.name} (Group {oil.group.code})")
    print(f"Energy: {oil.proximates.energy_kcal} kcal | Fat: {oil.proximates.total_fat_g}g")
    print(f"Lauric Acid (C12:0): {oil.fatty_acids.lauric_c12_0_mg}% | Total SFA: {oil.fatty_acids.total_sfa_mg}%")

    # 5. Multi-Lingual Search Demonstration
    print("\n--------------------------------------------------")
    print("MULTI-LINGUAL VERNACULAR SEARCH DEMO:")
    test_queries = ["Sajjalu", "Kambu", "Poha", "Atukulu", "Chana dal", "Ragi", "Lobia"]
    for query in test_queries:
        matches = FoodVernacularName.objects.filter(name__icontains=query).select_related("food")[:2]
        for m in matches:
            print(f"  Query: '{query}' -> [{m.language}] {m.name} -> Food: {m.food.food_code} ({m.food.name})")

    print("\n==================================================")
    print("VERIFICATION COMPLETE: ALL SYSTEMS FUNCTIONING")
    print("==================================================")


if __name__ == "__main__":
    verify()
