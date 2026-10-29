import logging
import time
from typing import Any, Dict
from django.db import transaction

from nutrition.ingestion.ifct_parser import IFCTParser
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

logger = logging.getLogger(__name__)


def run_ifct_ingestion(
    pdf_path: str = "raw_data/IFCT2017_16122024.pdf",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Executes the comprehensive IFCT ingestion pipeline:
    1. Parses IFCT 2017 PDF into structured dictionaries across all 12 tables + Chapter 7.
    2. Inserts/updates FoodGroup models (Groups A through T).
    3. Inserts/updates Food models (528 key foods + 14 cooking oils = 542 foods).
    4. Inserts/updates FoodVernacularName multi-lingual records.
    5. Inserts/updates all satellite nutrient models:
       - ProximateNutrient (Table 1)
       - VitaminNutrient (Tables 2 & 3)
       - CarotenoidNutrient (Table 4)
       - MineralNutrient (Table 5)
       - SugarNutrient (Table 6)
       - FattyAcidNutrient (Tables 7 & 12)
       - AminoAcidNutrient (Table 8)
       - OrganicAcidNutrient (Table 9)
       - PolyphenolNutrient (Table 10)
       - BioactiveNutrient (Table 11)
    """
    start_time = time.time()
    logger.info(f"Starting IFCT full ingestion from: {pdf_path}")

    parser = IFCTParser(pdf_path)
    parsed_data = parser.parse_all()

    groups_data = parsed_data["groups"]
    foods_data = parsed_data["foods"]

    summary = {
        "groups_count": len(groups_data),
        "foods_count": len(foods_data),
        "vernacular_names_count": 0,
        "proximates_count": 0,
        "vitamins_count": 0,
        "carotenoids_count": 0,
        "minerals_count": 0,
        "sugars_count": 0,
        "fatty_acids_count": 0,
        "amino_acids_count": 0,
        "organic_acids_count": 0,
        "polyphenols_count": 0,
        "bioactives_count": 0,
        "dry_run": dry_run,
        "elapsed_seconds": 0.0,
    }

    if dry_run:
        summary["elapsed_seconds"] = round(time.time() - start_time, 2)
        return summary

    with transaction.atomic():
        # 1. Ingest Food Groups (Groups A through T)
        group_objects = {}
        for code, name in groups_data.items():
            grp, _ = FoodGroup.objects.update_or_create(
                code=code,
                defaults={"name": name},
            )
            group_objects[code] = grp

        # 2. Ingest Foods and relational nutrient tables
        for code, f_info in foods_data.items():
            grp_code = f_info["group_code"]
            grp = group_objects.get(grp_code)

            food, _ = Food.objects.update_or_create(
                food_code=code,
                defaults={
                    "group": grp,
                    "name": f_info["name"],
                    "scientific_name": f_info["scientific_name"],
                    "no_of_regions": f_info["no_of_regions"],
                    "vernacular_names": f_info.get("vernacular_names", {}),
                },
            )

            # Ingest relational vernacular names
            vnames = f_info.get("vernacular_names", {})
            for lang, vname in vnames.items():
                if vname:
                    FoodVernacularName.objects.update_or_create(
                        food=food,
                        language=lang,
                        name=vname,
                    )
                    summary["vernacular_names_count"] += 1

            # 3. Proximate nutrients (Table 1)
            prox_info = f_info.get("proximates")
            if prox_info and any(v is not None for k, v in prox_info.items() if k not in ("name", "scientific_name", "no_of_regions", "sd_values")):
                ProximateNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "moisture_g": prox_info.get("moisture_g"),
                        "protein_g": prox_info.get("protein_g"),
                        "ash_g": prox_info.get("ash_g"),
                        "total_fat_g": prox_info.get("total_fat_g"),
                        "total_fiber_g": prox_info.get("total_fiber_g"),
                        "insoluble_fiber_g": prox_info.get("insoluble_fiber_g"),
                        "soluble_fiber_g": prox_info.get("soluble_fiber_g"),
                        "carbohydrates_g": prox_info.get("carbohydrates_g"),
                        "energy_kj": prox_info.get("energy_kj"),
                        "energy_kcal": prox_info.get("energy_kcal"),
                        "sd_values": prox_info.get("sd_values", {}),
                    },
                )
                summary["proximates_count"] += 1

            # 4. Vitamins (Tables 2 & 3)
            vit_info = f_info.get("vitamins")
            if vit_info and any(v is not None for k, v in vit_info.items() if k != "sd_values"):
                VitaminNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "thiamine_b1_mg": vit_info.get("thiamine_b1_mg"),
                        "riboflavin_b2_mg": vit_info.get("riboflavin_b2_mg"),
                        "niacin_b3_mg": vit_info.get("niacin_b3_mg"),
                        "pantothenic_acid_b5_mg": vit_info.get("pantothenic_acid_b5_mg"),
                        "vitamin_b6_mg": vit_info.get("vitamin_b6_mg"),
                        "biotin_b7_mcg": vit_info.get("biotin_b7_mcg"),
                        "folates_b9_mcg": vit_info.get("folates_b9_mcg"),
                        "vitamin_c_mg": vit_info.get("vitamin_c_mg"),
                        "ergocalciferol_d2_mcg": vit_info.get("ergocalciferol_d2_mcg"),
                        "alpha_tocopherol_mcg": vit_info.get("alpha_tocopherol_mcg"),
                        "beta_tocopherol_mcg": vit_info.get("beta_tocopherol_mcg"),
                        "gamma_tocopherol_mcg": vit_info.get("gamma_tocopherol_mcg"),
                        "delta_tocopherol_mcg": vit_info.get("delta_tocopherol_mcg"),
                        "alpha_tocotrienol_mcg": vit_info.get("alpha_tocotrienol_mcg"),
                        "beta_tocotrienol_mcg": vit_info.get("beta_tocotrienol_mcg"),
                        "gamma_tocotrienol_mcg": vit_info.get("gamma_tocotrienol_mcg"),
                        "delta_tocotrienol_mcg": vit_info.get("delta_tocotrienol_mcg"),
                        "vitamin_e_mg": vit_info.get("vitamin_e_mg"),
                        "vitamin_k1_mcg": vit_info.get("vitamin_k1_mcg"),
                        "sd_values": vit_info.get("sd_values", {}),
                    },
                )
                summary["vitamins_count"] += 1

            # 5. Carotenoids (Table 4)
            carot_info = f_info.get("carotenoids")
            if carot_info and any(v is not None for k, v in carot_info.items() if k != "sd_values"):
                CarotenoidNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "lutein_mcg": carot_info.get("lutein_mcg"),
                        "zeaxanthin_mcg": carot_info.get("zeaxanthin_mcg"),
                        "lycopene_mcg": carot_info.get("lycopene_mcg"),
                        "beta_cryptoxanthin_mcg": carot_info.get("beta_cryptoxanthin_mcg"),
                        "gamma_carotene_mcg": carot_info.get("gamma_carotene_mcg"),
                        "alpha_carotene_mcg": carot_info.get("alpha_carotene_mcg"),
                        "beta_carotene_mcg": carot_info.get("beta_carotene_mcg"),
                        "total_carotenoids_mcg": carot_info.get("total_carotenoids_mcg"),
                        "sd_values": carot_info.get("sd_values", {}),
                    },
                )
                summary["carotenoids_count"] += 1

            # 6. Minerals (Table 5)
            min_info = f_info.get("minerals")
            if min_info and any(v is not None for k, v in min_info.items() if k != "sd_values"):
                MineralNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "calcium_mg": min_info.get("calcium_mg"),
                        "phosphorus_mg": min_info.get("phosphorus_mg"),
                        "magnesium_mg": min_info.get("magnesium_mg"),
                        "sodium_mg": min_info.get("sodium_mg"),
                        "potassium_mg": min_info.get("potassium_mg"),
                        "iron_mg": min_info.get("iron_mg"),
                        "zinc_mg": min_info.get("zinc_mg"),
                        "copper_mg": min_info.get("copper_mg"),
                        "manganese_mg": min_info.get("manganese_mg"),
                        "selenium_mcg": min_info.get("selenium_mcg"),
                        "chromium_mg": min_info.get("chromium_mg"),
                        "cobalt_mg": min_info.get("cobalt_mg"),
                        "nickel_mg": min_info.get("nickel_mg"),
                        "molybdenum_mg": min_info.get("molybdenum_mg"),
                        "aluminium_mg": min_info.get("aluminium_mg"),
                        "arsenic_mcg": min_info.get("arsenic_mcg"),
                        "cadmium_mg": min_info.get("cadmium_mg"),
                        "lead_mg": min_info.get("lead_mg"),
                        "lithium_mg": min_info.get("lithium_mg"),
                        "mercury_mcg": min_info.get("mercury_mcg"),
                        "sd_values": min_info.get("sd_values", {}),
                    },
                )
                summary["minerals_count"] += 1

            # 7. Sugars & Starch (Table 6)
            sug_info = f_info.get("sugars")
            if sug_info and any(v is not None for k, v in sug_info.items() if k != "sd_values"):
                SugarNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "total_starch_g": sug_info.get("total_starch_g"),
                        "fructose_g": sug_info.get("fructose_g"),
                        "glucose_g": sug_info.get("glucose_g"),
                        "sucrose_g": sug_info.get("sucrose_g"),
                        "maltose_g": sug_info.get("maltose_g"),
                        "total_free_sugars_g": sug_info.get("total_free_sugars_g"),
                        "sd_values": sug_info.get("sd_values", {}),
                    },
                )
                summary["sugars_count"] += 1

            # 8. Fatty Acids (Tables 7 & 12)
            fa_info = f_info.get("fatty_acids")
            if fa_info and any(v is not None for k, v in fa_info.items() if k not in ("is_cooking_oil_percent", "name", "scientific_name", "no_of_regions", "sd_values")):
                FattyAcidNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "is_cooking_oil_percent": fa_info.get("is_cooking_oil_percent", False),
                        "butyric_c4_0_mg": fa_info.get("butyric_c4_0_mg"),
                        "caproic_c6_0_mg": fa_info.get("caproic_c6_0_mg"),
                        "caprylic_c8_0_mg": fa_info.get("caprylic_c8_0_mg"),
                        "capric_c10_0_mg": fa_info.get("capric_c10_0_mg"),
                        "lauric_c12_0_mg": fa_info.get("lauric_c12_0_mg"),
                        "myristic_c14_0_mg": fa_info.get("myristic_c14_0_mg"),
                        "palmitic_c16_0_mg": fa_info.get("palmitic_c16_0_mg"),
                        "stearic_c18_0_mg": fa_info.get("stearic_c18_0_mg"),
                        "arachidic_c20_0_mg": fa_info.get("arachidic_c20_0_mg"),
                        "behenic_c22_0_mg": fa_info.get("behenic_c22_0_mg"),
                        "lignoceric_c24_0_mg": fa_info.get("lignoceric_c24_0_mg"),
                        "total_sfa_mg": fa_info.get("total_sfa_mg"),
                        "myristoleic_c14_1_mg": fa_info.get("myristoleic_c14_1_mg"),
                        "palmitoleic_c16_1_mg": fa_info.get("palmitoleic_c16_1_mg"),
                        "elaidic_c18_1n9t_mg": fa_info.get("elaidic_c18_1n9t_mg"),
                        "oleic_c18_1n9_mg": fa_info.get("oleic_c18_1n9_mg"),
                        "eicosenoic_c20_1n9_mg": fa_info.get("eicosenoic_c20_1n9_mg"),
                        "erucic_c22_1n9_mg": fa_info.get("erucic_c22_1n9_mg"),
                        "nervonic_c24_1n9_mg": fa_info.get("nervonic_c24_1n9_mg"),
                        "total_mufa_mg": fa_info.get("total_mufa_mg"),
                        "linoleic_c18_2n6_mg": fa_info.get("linoleic_c18_2n6_mg"),
                        "eicosadienoic_c20_2_mg": fa_info.get("eicosadienoic_c20_2_mg"),
                        "alpha_linolenic_c18_3n3_mg": fa_info.get("alpha_linolenic_c18_3n3_mg"),
                        "eicosatrienoic_c20_3n6_mg": fa_info.get("eicosatrienoic_c20_3n6_mg"),
                        "arachidonic_c20_4n6_mg": fa_info.get("arachidonic_c20_4n6_mg"),
                        "epa_c20_5n3_mg": fa_info.get("epa_c20_5n3_mg"),
                        "dha_c22_6n3_mg": fa_info.get("dha_c22_6n3_mg"),
                        "total_pufa_mg": fa_info.get("total_pufa_mg"),
                        "cholesterol_mg": fa_info.get("cholesterol_mg"),
                        "sd_values": fa_info.get("sd_values", {}),
                    },
                )
                summary["fatty_acids_count"] += 1

            # 9. Amino Acids (Table 8)
            aa_info = f_info.get("amino_acids")
            if aa_info and any(v is not None for k, v in aa_info.items() if k != "sd_values"):
                AminoAcidNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "histidine_g": aa_info.get("histidine_g"),
                        "isoleucine_g": aa_info.get("isoleucine_g"),
                        "leucine_g": aa_info.get("leucine_g"),
                        "lysine_g": aa_info.get("lysine_g"),
                        "methionine_g": aa_info.get("methionine_g"),
                        "cystine_g": aa_info.get("cystine_g"),
                        "phenylalanine_g": aa_info.get("phenylalanine_g"),
                        "threonine_g": aa_info.get("threonine_g"),
                        "tryptophan_g": aa_info.get("tryptophan_g"),
                        "valine_g": aa_info.get("valine_g"),
                        "alanine_g": aa_info.get("alanine_g"),
                        "arginine_g": aa_info.get("arginine_g"),
                        "aspartic_acid_g": aa_info.get("aspartic_acid_g"),
                        "glutamic_acid_g": aa_info.get("glutamic_acid_g"),
                        "glycine_g": aa_info.get("glycine_g"),
                        "proline_g": aa_info.get("proline_g"),
                        "serine_g": aa_info.get("serine_g"),
                        "tyrosine_g": aa_info.get("tyrosine_g"),
                        "sd_values": aa_info.get("sd_values", {}),
                    },
                )
                summary["amino_acids_count"] += 1

            # 10. Organic Acids (Table 9)
            org_info = f_info.get("organic_acids")
            if org_info and any(v is not None for k, v in org_info.items() if k != "sd_values"):
                OrganicAcidNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "oxalate_total_mg": org_info.get("oxalate_total_mg"),
                        "oxalate_soluble_mg": org_info.get("oxalate_soluble_mg"),
                        "oxalate_insoluble_mg": org_info.get("oxalate_insoluble_mg"),
                        "cis_aconitic_acid_mg": org_info.get("cis_aconitic_acid_mg"),
                        "citric_acid_mg": org_info.get("citric_acid_mg"),
                        "fumaric_acid_mg": org_info.get("fumaric_acid_mg"),
                        "malic_acid_mg": org_info.get("malic_acid_mg"),
                        "quinic_acid_mg": org_info.get("quinic_acid_mg"),
                        "succinic_acid_mg": org_info.get("succinic_acid_mg"),
                        "tartaric_acid_mg": org_info.get("tartaric_acid_mg"),
                        "sd_values": org_info.get("sd_values", {}),
                    },
                )
                summary["organic_acids_count"] += 1

            # 11. Polyphenols (Table 10)
            poly_info = f_info.get("polyphenols")
            if poly_info and any(v is not None for k, v in poly_info.items() if k != "sd_values"):
                PolyphenolNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "dihydroxy_benzoic_3_4_mg": poly_info.get("dihydroxy_benzoic_3_4_mg"),
                        "hydroxy_benzaldehyde_3_mg": poly_info.get("hydroxy_benzaldehyde_3_mg"),
                        "protocatechuic_acid_mg": poly_info.get("protocatechuic_acid_mg"),
                        "vanillic_acid_mg": poly_info.get("vanillic_acid_mg"),
                        "gallic_acid_mg": poly_info.get("gallic_acid_mg"),
                        "cinnamic_acid_mg": poly_info.get("cinnamic_acid_mg"),
                        "o_coumaric_acid_mg": poly_info.get("o_coumaric_acid_mg"),
                        "p_coumaric_acid_mg": poly_info.get("p_coumaric_acid_mg"),
                        "caffeic_acid_mg": poly_info.get("caffeic_acid_mg"),
                        "chlorogenic_acid_mg": poly_info.get("chlorogenic_acid_mg"),
                        "ferulic_acid_mg": poly_info.get("ferulic_acid_mg"),
                        "syringic_acid_mg": poly_info.get("syringic_acid_mg"),
                        "sinapinic_acid_mg": poly_info.get("sinapinic_acid_mg"),
                        "ellagic_acid_mg": poly_info.get("ellagic_acid_mg"),
                        "apigenin_mg": poly_info.get("apigenin_mg"),
                        "apigenin_6_c_glucoside_mg": poly_info.get("apigenin_6_c_glucoside_mg"),
                        "apigenin_7_o_neohesperidoside_mg": poly_info.get("apigenin_7_o_neohesperidoside_mg"),
                        "luteolin_mg": poly_info.get("luteolin_mg"),
                        "kaempferol_mg": poly_info.get("kaempferol_mg"),
                        "quercetin_mg": poly_info.get("quercetin_mg"),
                        "quercetin_3_beta_d_glucoside_mg": poly_info.get("quercetin_3_beta_d_glucoside_mg"),
                        "quercetin_3_o_rutinoside_mg": poly_info.get("quercetin_3_o_rutinoside_mg"),
                        "quercetin_3_galactoside_mg": poly_info.get("quercetin_3_galactoside_mg"),
                        "isorhamnetin_mg": poly_info.get("isorhamnetin_mg"),
                        "myricetin_mg": poly_info.get("myricetin_mg"),
                        "resveratrol_mg": poly_info.get("resveratrol_mg"),
                        "hesperetin_mg": poly_info.get("hesperetin_mg"),
                        "naringenin_mg": poly_info.get("naringenin_mg"),
                        "hesperidin_mg": poly_info.get("hesperidin_mg"),
                        "daidzein_mg": poly_info.get("daidzein_mg"),
                        "genistein_mg": poly_info.get("genistein_mg"),
                        "epicatechin_mg": poly_info.get("epicatechin_mg"),
                        "epigallocatechin_mg": poly_info.get("epigallocatechin_mg"),
                        "epigallocatechin_3_gallate_mg": poly_info.get("epigallocatechin_3_gallate_mg"),
                        "catechin_mg": poly_info.get("catechin_mg"),
                        "gallocatechin_mg": poly_info.get("gallocatechin_mg"),
                        "epicatechin_gallate_mg": poly_info.get("epicatechin_gallate_mg"),
                        "total_polyphenols_mg": poly_info.get("total_polyphenols_mg"),
                        "sd_values": poly_info.get("sd_values", {}),
                    },
                )
                summary["polyphenols_count"] += 1

            # 12. Bioactives (Table 11)
            bio_info = f_info.get("bioactives")
            if bio_info and any(v is not None for k, v in bio_info.items() if k != "sd_values"):
                BioactiveNutrient.objects.update_or_create(
                    food=food,
                    defaults={
                        "raffinose_g": bio_info.get("raffinose_g"),
                        "stachyose_g": bio_info.get("stachyose_g"),
                        "verbascose_g": bio_info.get("verbascose_g"),
                        "ajugose_g": bio_info.get("ajugose_g"),
                        "campesterol_mg": bio_info.get("campesterol_mg"),
                        "stigmasterol_mg": bio_info.get("stigmasterol_mg"),
                        "beta_sitosterol_mg": bio_info.get("beta_sitosterol_mg"),
                        "phytate_mg": bio_info.get("phytate_mg"),
                        "total_saponin_mg": bio_info.get("total_saponin_mg"),
                        "sd_values": bio_info.get("sd_values", {}),
                    },
                )
                summary["bioactives_count"] += 1

    summary["elapsed_seconds"] = round(time.time() - start_time, 2)
    logger.info(f"Ingestion completed in {summary['elapsed_seconds']}s: {summary}")
    return summary
