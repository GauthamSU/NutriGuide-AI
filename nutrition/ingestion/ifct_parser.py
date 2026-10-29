import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pymupdf

logger = logging.getLogger(__name__)

IFCT_FOOD_GROUPS: Dict[str, str] = {
    "A": "Cereals and Millets",
    "B": "Grain Legumes",
    "C": "Green Leafy Vegetables",
    "D": "Other Vegetables",
    "E": "Fruits",
    "F": "Roots and Tubers",
    "G": "Condiments and Spices",
    "H": "Nuts and Oil Seeds",
    "I": "Sugars",
    "J": "Mushrooms",
    "K": "Miscellaneous Foods",
    "L": "Milk and Milk Products",
    "M": "Egg and Egg Products",
    "N": "Poultry",
    "O": "Animal Meat",
    "P": "Marine Fish",
    "Q": "Marine Shellfish",
    "R": "Marine Mollusks",
    "S": "Freshwater Fish and Shellfish",
    "T": "Edible Oils and Fats",
}

LANG_MAP: Dict[str, str] = {
    "A": "Assamese",
    "B": "Bengali",
    "G": "Gujarati",
    "H": "Hindi",
    "Kan": "Kannada",
    "Kash": "Kashmiri",
    "Kh": "Khasi",
    "Mal": "Malayalam",
    "M": "Manipuri",
    "Mar": "Marathi",
    "N": "Nepali",
    "O": "Oriya",
    "P": "Punjabi",
    "S": "Sanskrit",
    "Tam": "Tamil",
    "Tel": "Telugu",
    "U": "Urdu",
}


def parse_numeric_token(token: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Parses numeric text into (mean, sd). Handles 'mean ± sd', 'mean', or returns (None, None).
    """
    if not token or token in ("-", "ND", "BDL"):
        return None, None

    cleaned = token.replace(chr(177), "±").replace("\ufffd", "±").replace(" ", "")
    cleaned = re.sub(r"(\d+)\.\s+(\d+)", r"\1.\2", cleaned)

    if "±" in cleaned:
        parts = cleaned.split("±")
        try:
            mean = float(parts[0])
            sd = float(parts[1]) if len(parts) > 1 and parts[1] else None
            return mean, sd
        except ValueError:
            pass

    try:
        return float(cleaned), None
    except ValueError:
        return None, None


def split_common_and_scientific_name(full_name: str) -> Tuple[str, Optional[str]]:
    """
    Separates common name and botanical/scientific name from:
    'Amaranth seed, black (Amaranthus cruentus)' -> ('Amaranth seed, black', 'Amaranthus cruentus')
    """
    m = re.search(r"^(.*?)\s*\((.*?)\)\s*$", full_name.strip())
    if m:
        common = m.group(1).strip()
        scientific = m.group(2).strip()
        return common or full_name.strip(), scientific or None
    return full_name.strip(), None


class IFCTParser:
    """
    Robust Coordinate-Aware Parser for Indian Food Composition Tables (IFCT 2017).
    Extracts Food Groups, Food metadata, and all Chapter 6 Tables (1 through 12)
    plus Chapter 7 Vernacular names and description metadata.
    """

    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"IFCT PDF not found at: {self.pdf_path}")
        self.doc = pymupdf.open(str(self.pdf_path))

    def _parse_page_rows_with_bins(
        self,
        page_idx: int,
        col_bins: List[Tuple[str, float, float]],
        y_min: float = 105.0,
        y_max: float = 780.0,
        code_prefix_pattern: str = r"^[A-T]\d{3}$",
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extracts table cells using horizontal coordinate intervals (x_min to x_max).
        Words are grouped vertically into table rows using y-clustering.
        Guarantees blank/ND cells are preserved without column drift.
        """
        page = self.doc[page_idx]
        words = [w for w in page.get_text("words") if y_min <= w[1] <= y_max]
        if not words:
            return {}

        words.sort(key=lambda w: w[1])
        lines: List[List[Any]] = []
        current_line: List[Any] = []
        current_y: Optional[float] = None

        for w in words:
            if current_y is None or abs(w[1] - current_y) <= 5.5:
                current_line.append(w)
                current_y = w[1] if current_y is None else (current_y + w[1]) / 2.0
            else:
                lines.append(current_line)
                current_line = [w]
                current_y = w[1]
        if current_line:
            lines.append(current_line)

        page_data: Dict[str, Dict[str, Any]] = {}
        first_col_x = col_bins[0][1]

        for line_words in lines:
            line_words.sort(key=lambda w: w[0])
            code_w = [w for w in line_words if w[0] < 115 and re.match(code_prefix_pattern, w[4])]
            if not code_w:
                continue
            code = code_w[0][4]
            code_x_end = code_w[0][2]

            name_words = [w[4] for w in line_words if code_x_end <= w[0] < first_col_x]
            row_data: Dict[str, Any] = {"raw_name": " ".join(name_words).strip()}

            for col_name, x_start, x_end in col_bins:
                cell_words = [w[4] for w in line_words if x_start <= w[0] < x_end]
                if cell_words:
                    token = "".join(cell_words)
                    row_data[col_name] = parse_numeric_token(token)
                else:
                    row_data[col_name] = (None, None)

            page_data[code] = row_data

        return page_data

    def parse_table1_proximates(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 1: Proximate Principles and Dietary Fibre (Pages 41–68, 0-indexed 40–67).
        """
        plant_bins = [
            ("regions", 260.0, 305.0),
            ("moisture_g", 305.0, 365.0),
            ("protein_g", 365.0, 425.0),
            ("ash_g", 425.0, 475.0),
            ("total_fat_g", 475.0, 530.0),
            ("total_fiber_g", 530.0, 585.0),
            ("insoluble_fiber_g", 585.0, 640.0),
            ("soluble_fiber_g", 640.0, 695.0),
            ("carbohydrates_g", 695.0, 755.0),
            ("energy_kj", 755.0, 820.0),
        ]

        animal_bins = [
            ("regions", 280.0, 325.0),
            ("moisture_g", 325.0, 400.0),
            ("protein_g", 400.0, 490.0),
            ("ash_g", 490.0, 570.0),
            ("total_fat_g", 570.0, 660.0),
            ("energy_kj", 660.0, 760.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}
        for pno in range(40, 68):
            is_animal = (pno >= 57)
            col_bins = animal_bins if is_animal else plant_bins

            page_data = self._parse_page_rows_with_bins(pno, col_bins)
            for code, data in page_data.items():
                common_name, sci_name = split_common_and_scientific_name(data["raw_name"])
                reg_mean = data.get("regions", (1, None))[0]
                no_of_regions = int(reg_mean) if reg_mean else 1

                prox: Dict[str, Any] = {
                    "name": common_name,
                    "scientific_name": sci_name,
                    "no_of_regions": no_of_regions,
                    "total_fiber_g": 0.0 if is_animal else None,
                    "insoluble_fiber_g": 0.0 if is_animal else None,
                    "soluble_fiber_g": 0.0 if is_animal else None,
                    "carbohydrates_g": 0.0 if is_animal else None,
                    "sd_values": {},
                }

                for col_name, _, _ in col_bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    prox[col_name] = mean
                    if sd is not None:
                        prox["sd_values"][col_name] = sd

                if prox.get("energy_kj") is not None:
                    prox["energy_kcal"] = round(prox["energy_kj"] / 4.184, 1)
                else:
                    p = prox.get("protein_g") or 0.0
                    c = prox.get("carbohydrates_g") or 0.0
                    f = prox.get("total_fat_g") or 0.0
                    if p or c or f:
                        prox["energy_kcal"] = round((p * 4.0) + (c * 4.0) + (f * 9.0), 1)

                results[code] = prox

        return results

    def parse_table2_water_vitamins(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 2: Water-Soluble Vitamins (Pages 71–98, 0-indexed 70–97).
        """
        col_bins = [
            ("regions", 260.0, 305.0),
            ("thiamine_b1_mg", 305.0, 360.0),
            ("riboflavin_b2_mg", 360.0, 425.0),
            ("niacin_b3_mg", 425.0, 485.0),
            ("pantothenic_acid_b5_mg", 485.0, 545.0),
            ("vitamin_b6_mg", 545.0, 610.0),
            ("biotin_b7_mcg", 610.0, 670.0),
            ("folates_b9_mcg", 670.0, 745.0),
            ("vitamin_c_mg", 745.0, 810.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}
        for pno in range(70, 98):
            page_data = self._parse_page_rows_with_bins(pno, col_bins)
            for code, data in page_data.items():
                vit: Dict[str, Any] = {"sd_values": {}}
                for col_name, _, _ in col_bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    vit[col_name] = mean
                    if sd is not None:
                        vit["sd_values"][col_name] = sd
                results[code] = vit

        return results

    def parse_table3_fat_vitamins(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 3: Fat-Soluble Vitamins (Pages 101–128, 0-indexed 100–127).
        Extracts D2, individual Tocopherols (alpha, beta, gamma, delta),
        Tocotrienols (alpha, beta, gamma, delta), Vitamin E (eq), and Vitamin K1.
        """
        col_bins = [
            ("regions", 235.0, 275.0),
            ("ergocalciferol_d2_mcg", 275.0, 325.0),
            ("alpha_tocopherol_mcg", 325.0, 375.0),
            ("beta_tocopherol_mcg", 375.0, 420.0),
            ("gamma_tocopherol_mcg", 420.0, 470.0),
            ("delta_tocopherol_mcg", 470.0, 520.0),
            ("alpha_tocotrienol_mcg", 520.0, 565.0),
            ("beta_tocotrienol_mcg", 565.0, 610.0),
            ("gamma_tocotrienol_mcg", 610.0, 655.0),
            ("delta_tocotrienol_mcg", 655.0, 700.0),
            ("vitamin_e_mg", 700.0, 755.0),
            ("vitamin_k1_mcg", 755.0, 815.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}
        for pno in range(100, 128):
            page_data = self._parse_page_rows_with_bins(pno, col_bins)
            for code, data in page_data.items():
                vit: Dict[str, Any] = {"sd_values": {}}
                for col_name, _, _ in col_bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    vit[col_name] = mean
                    if sd is not None:
                        vit["sd_values"][col_name] = sd
                results[code] = vit

        return results

    def parse_table4_carotenoids(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 4: Carotenoids (Pages 131–148, 0-indexed 130–147).
        """
        col_bins = [
            ("regions", 235.0, 280.0),
            ("lutein_mcg", 280.0, 340.0),
            ("zeaxanthin_mcg", 340.0, 400.0),
            ("lycopene_mcg", 400.0, 465.0),
            ("beta_cryptoxanthin_mcg", 465.0, 530.0),
            ("gamma_carotene_mcg", 530.0, 590.0),
            ("alpha_carotene_mcg", 590.0, 650.0),
            ("beta_carotene_mcg", 650.0, 720.0),
            ("total_carotenoids_mcg", 720.0, 810.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}
        for pno in range(130, 148):
            page_data = self._parse_page_rows_with_bins(pno, col_bins)
            for code, data in page_data.items():
                res: Dict[str, Any] = {"sd_values": {}}
                for col_name, _, _ in col_bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    res[col_name] = mean
                    if sd is not None:
                        res["sd_values"][col_name] = sd
                results[code] = res

        return results

    def parse_table5_minerals(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 5: Minerals & Trace Elements (Pages 151–206, 0-indexed 150–205).
        Alternating pages: Part 1 (Heavy/trace & Ca), Part 2 (Macrominerals & Zn).
        """
        part1_bins = [
            ("regions", 225.0, 260.0),
            ("aluminium_mg", 260.0, 310.0),
            ("arsenic_mcg", 310.0, 360.0),
            ("cadmium_mg", 360.0, 410.0),
            ("calcium_mg", 410.0, 465.0),
            ("chromium_mg", 465.0, 520.0),
            ("cobalt_mg", 520.0, 575.0),
            ("copper_mg", 575.0, 630.0),
            ("iron_mg", 630.0, 685.0),
            ("lead_mg", 685.0, 745.0),
            ("lithium_mg", 745.0, 810.0),
        ]

        part2_bins = [
            ("regions", 225.0, 260.0),
            ("magnesium_mg", 260.0, 310.0),
            ("manganese_mg", 310.0, 365.0),
            ("mercury_mcg", 365.0, 415.0),
            ("molybdenum_mg", 415.0, 465.0),
            ("nickel_mg", 465.0, 530.0),
            ("phosphorus_mg", 530.0, 585.0),
            ("potassium_mg", 585.0, 640.0),
            ("selenium_mcg", 640.0, 695.0),
            ("sodium_mg", 695.0, 750.0),
            ("zinc_mg", 750.0, 810.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}

        for pno in range(150, 206):
            page_text = self.doc[pno].get_text()
            is_part_1 = any(k in page_text for k in ["Aluminium", "Arsenic", "Cadmium", "AL", "AS", "CD"])
            bins = part1_bins if is_part_1 else part2_bins
            page_data = self._parse_page_rows_with_bins(pno, bins)

            for code, data in page_data.items():
                if code not in results:
                    results[code] = {"sd_values": {}}
                for col_name, _, _ in bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    results[code][col_name] = mean
                    if sd is not None:
                        results[code]["sd_values"][col_name] = sd

        return results

    def parse_table6_sugars(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 6: Starch and Individual Sugars (Pages 209–224, 0-indexed 208–223).
        """
        col_bins = [
            ("regions", 280.0, 335.0),
            ("total_starch_g", 415.0, 485.0),
            ("fructose_g", 485.0, 550.0),
            ("glucose_g", 550.0, 615.0),
            ("sucrose_g", 615.0, 680.0),
            ("maltose_g", 680.0, 745.0),
            ("total_free_sugars_g", 745.0, 815.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}
        for pno in range(208, 224):
            page_data = self._parse_page_rows_with_bins(pno, col_bins)
            for code, data in page_data.items():
                res: Dict[str, Any] = {"sd_values": {}}
                for col_name, _, _ in col_bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    res[col_name] = mean
                    if sd is not None:
                        res["sd_values"][col_name] = sd
                results[code] = res

        return results

    def parse_table7_fatty_acids(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 7: Fatty Acid Profile (Pages 227–294, 0-indexed 226–293).
        Dynamic detection of Part 1 (SFA & C14:1, C16:1, C18:1n9)
        vs Part 2 (PUFA, Totals, and Animal EPA, DHA, Cholesterol).
        """
        p1_bins = [
            ("regions", 215.0, 255.0),
            ("capric_c10_0_mg", 255.0, 300.0),
            ("lauric_c12_0_mg", 300.0, 345.0),
            ("myristic_c14_0_mg", 345.0, 395.0),
            ("palmitic_c16_0_mg", 395.0, 445.0),
            ("stearic_c18_0_mg", 445.0, 500.0),
            ("arachidic_c20_0_mg", 500.0, 550.0),
            ("behenic_c22_0_mg", 550.0, 600.0),
            ("lignoceric_c24_0_mg", 600.0, 650.0),
            ("myristoleic_c14_1_mg", 650.0, 700.0),
            ("palmitoleic_c16_1_mg", 700.0, 750.0),
            ("oleic_c18_1n9_mg", 750.0, 810.0),
        ]

        p2_plant_bins = [
            ("regions", 215.0, 255.0),
            ("eicosenoic_c20_1n9_mg", 255.0, 305.0),
            ("erucic_c22_1n9_mg", 305.0, 355.0),
            ("nervonic_c24_1n9_mg", 355.0, 405.0),
            ("linoleic_c18_2n6_mg", 405.0, 460.0),
            ("eicosadienoic_c20_2_mg", 460.0, 515.0),
            ("alpha_linolenic_c18_3n3_mg", 515.0, 575.0),
            ("arachidonic_c20_4n6_mg", 575.0, 635.0),
            ("total_sfa_mg", 635.0, 690.0),
            ("total_mufa_mg", 690.0, 750.0),
            ("total_pufa_mg", 750.0, 810.0),
        ]

        p2_animal_bins = [
            ("regions", 235.0, 275.0),
            ("eicosatrienoic_c20_3n6_mg", 275.0, 340.0),
            ("arachidonic_c20_4n6_mg", 340.0, 400.0),
            ("epa_c20_5n3_mg", 400.0, 470.0),
            ("dha_c22_6n3_mg", 470.0, 535.0),
            ("total_sfa_mg", 535.0, 600.0),
            ("total_mufa_mg", 600.0, 670.0),
            ("total_pufa_mg", 670.0, 740.0),
            ("cholesterol_mg", 740.0, 810.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}

        for pno in range(226, 294):
            header_words = [w[4] for w in self.doc[pno].get_text("words") if w[1] < 140]
            if any(k in header_words for k in ["Capric", "Lauric", "Palmitic", "Stearic", "(C10:0)", "(C12:0)", "(C14:0)", "(C16:0)", "(C18:0)"]):
                bins = p1_bins
            elif any(k in header_words for k in ["Cholesterol", "CHOLC", "(C20:5n3)", "(C22:6n3)", "F20D5N3"]):
                bins = p2_animal_bins
            elif any(k in header_words for k in ["Linoleic", "(C18:2n6)", "(TSFA)", "(TMUFA)", "(TPUFA)", "Eicosenoic"]):
                bins = p2_plant_bins
            else:
                continue

            page_data = self._parse_page_rows_with_bins(pno, bins)
            for code, data in page_data.items():
                if code not in results:
                    results[code] = {"is_cooking_oil_percent": False, "sd_values": {}}
                for col_name, _, _ in bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    results[code][col_name] = mean
                    if sd is not None:
                        results[code]["sd_values"][col_name] = sd

        return results

    def parse_table8_amino_acids(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 8: Amino Acid Profile (Pages 297–361, 0-indexed 296–360).
        Dynamic detection of Part 1 (Essential amino acids) vs Part 2 (Non-essential amino acids).
        """
        p1_bins = [
            ("regions", 215.0, 255.0),
            ("histidine_g", 255.0, 305.0),
            ("isoleucine_g", 305.0, 360.0),
            ("leucine_g", 360.0, 415.0),
            ("lysine_g", 415.0, 465.0),
            ("methionine_g", 465.0, 530.0),
            ("cystine_g", 530.0, 580.0),
            ("phenylalanine_g", 580.0, 645.0),
            ("threonine_g", 645.0, 700.0),
            ("tryptophan_g", 700.0, 760.0),
            ("valine_g", 760.0, 815.0),
        ]

        p2_bins = [
            ("regions", 215.0, 255.0),
            ("alanine_g", 255.0, 320.0),
            ("arginine_g", 320.0, 380.0),
            ("aspartic_acid_g", 380.0, 450.0),
            ("glutamic_acid_g", 450.0, 535.0),
            ("glycine_g", 535.0, 605.0),
            ("proline_g", 605.0, 675.0),
            ("serine_g", 675.0, 745.0),
            ("tyrosine_g", 745.0, 815.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}

        for pno in range(296, 361):
            header_words = [w[4] for w in self.doc[pno].get_text("words") if w[1] < 135]
            if any(k in header_words for k in ["Histidine", "HIS", "Threonine", "Valine", "Luecine"]):
                bins = p1_bins
            elif any(k in header_words for k in ["Alanine", "ALA", "Arginine", "Glutamic", "Glycine", "Tyrosine"]):
                bins = p2_bins
            else:
                continue

            page_data = self._parse_page_rows_with_bins(pno, bins)
            for code, data in page_data.items():
                if code not in results:
                    results[code] = {"sd_values": {}}
                for col_name, _, _ in bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    results[code][col_name] = mean
                    if sd is not None:
                        results[code]["sd_values"][col_name] = sd

        return results

    def parse_table9_organic_acids(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 9: Organic Acids (Pages 364–381, 0-indexed 363–380).
        """
        col_bins = [
            ("regions", 215.0, 255.0),
            ("oxalate_total_mg", 255.0, 310.0),
            ("oxalate_soluble_mg", 310.0, 365.0),
            ("oxalate_insoluble_mg", 365.0, 420.0),
            ("cis_aconitic_acid_mg", 420.0, 475.0),
            ("citric_acid_mg", 475.0, 525.0),
            ("fumaric_acid_mg", 525.0, 580.0),
            ("malic_acid_mg", 580.0, 635.0),
            ("quinic_acid_mg", 635.0, 690.0),
            ("succinic_acid_mg", 690.0, 750.0),
            ("tartaric_acid_mg", 750.0, 810.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}
        for pno in range(363, 381):
            page_data = self._parse_page_rows_with_bins(pno, col_bins)
            for code, data in page_data.items():
                res: Dict[str, Any] = {"sd_values": {}}
                for col_name, _, _ in col_bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    res[col_name] = mean
                    if sd is not None:
                        res["sd_values"][col_name] = sd
                results[code] = res

        return results

    def parse_table10_polyphenols(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 10: Polyphenols and Flavonoids (Pages 384–451, 0-indexed 383–450).
        4-page spread dynamic classification:
        - Part 1: Phenolic acids (3,4-Dihydroxybenzoic to Caffeic)
        - Part 2: Chlorogenic to Quercetin-3-O-rutinoside
        - Part 3: Quercetin-3-galactoside to Epicatechin
        - Part 4: Catechins, Syringic, Sinapinic, Ellagic, Total polyphenols
        """
        p1_bins = [
            ("regions", 235.0, 275.0),
            ("dihydroxy_benzoic_3_4_mg", 275.0, 335.0),
            ("hydroxy_benzaldehyde_3_mg", 335.0, 395.0),
            ("protocatechuic_acid_mg", 395.0, 465.0),
            ("vanillic_acid_mg", 465.0, 520.0),
            ("gallic_acid_mg", 520.0, 575.0),
            ("cinnamic_acid_mg", 575.0, 630.0),
            ("o_coumaric_acid_mg", 630.0, 685.0),
            ("p_coumaric_acid_mg", 685.0, 745.0),
            ("caffeic_acid_mg", 745.0, 810.0),
        ]

        p2_bins = [
            ("regions", 235.0, 275.0),
            ("chlorogenic_acid_mg", 275.0, 330.0),
            ("ferulic_acid_mg", 330.0, 385.0),
            ("apigenin_mg", 385.0, 435.0),
            ("apigenin_6_c_glucoside_mg", 435.0, 495.0),
            ("apigenin_7_o_neohesperidoside_mg", 495.0, 550.0),
            ("luteolin_mg", 550.0, 600.0),
            ("kaempferol_mg", 600.0, 650.0),
            ("quercetin_mg", 650.0, 705.0),
            ("quercetin_3_beta_d_glucoside_mg", 705.0, 760.0),
            ("quercetin_3_o_rutinoside_mg", 760.0, 810.0),
        ]

        p3_bins = [
            ("regions", 235.0, 275.0),
            ("quercetin_3_galactoside_mg", 275.0, 330.0),
            ("isorhamnetin_mg", 330.0, 385.0),
            ("myricetin_mg", 385.0, 440.0),
            ("resveratrol_mg", 440.0, 490.0),
            ("hesperetin_mg", 490.0, 545.0),
            ("naringenin_mg", 545.0, 600.0),
            ("hesperidin_mg", 600.0, 655.0),
            ("daidzein_mg", 655.0, 705.0),
            ("genistein_mg", 705.0, 755.0),
            ("epicatechin_mg", 755.0, 810.0),
        ]

        p4_bins = [
            ("regions", 235.0, 270.0),
            ("epigallocatechin_mg", 270.0, 330.0),
            ("epigallocatechin_3_gallate_mg", 330.0, 395.0),
            ("catechin_mg", 395.0, 450.0),
            ("gallocatechin_mg", 450.0, 505.0),
            ("epicatechin_gallate_mg", 505.0, 565.0),
            ("syringic_acid_mg", 565.0, 625.0),
            ("sinapinic_acid_mg", 625.0, 685.0),
            ("ellagic_acid_mg", 685.0, 745.0),
            ("total_polyphenols_mg", 745.0, 815.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}

        for pno in range(383, 451):
            header_words = [w[4] for w in self.doc[pno].get_text("words") if w[1] < 140]
            if any(k in header_words for k in ["3,4-Dihydroxy", "Protocatechuic", "Vanillic", "Cinnamic", "GALLAC"]):
                bins = p1_bins
            elif any(k in header_words for k in ["Chlorogenic", "Ferulic", "Apigenin", "Luteolin", "Kaempferol", "CHLRAC"]):
                bins = p2_bins
            elif any(k in header_words for k in ["Isorhamnetin", "Myricetin", "Resveratrol", "Hesperetin", "Daidzein", "HESPT"]):
                bins = p3_bins
            elif any(k in header_words for k in ["Epigallocatechin", "Catechin", "Syringic", "polyphenols", "POLYT", "Sinapinic"]):
                bins = p4_bins
            else:
                continue

            page_data = self._parse_page_rows_with_bins(pno, bins)
            for code, data in page_data.items():
                if code not in results:
                    results[code] = {"sd_values": {}}
                for col_name, _, _ in bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    results[code][col_name] = mean
                    if sd is not None:
                        results[code]["sd_values"][col_name] = sd

        return results

    def parse_table11_bioactives(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 11: Oligosaccharides, Phytosterols, Phytates and Saponins (Pages 454–471, 0-indexed 453–470).
        """
        col_bins = [
            ("regions", 210.0, 245.0),
            ("raffinose_g", 245.0, 305.0),
            ("stachyose_g", 305.0, 365.0),
            ("verbascose_g", 365.0, 430.0),
            ("ajugose_g", 430.0, 490.0),
            ("campesterol_mg", 490.0, 550.0),
            ("stigmasterol_mg", 550.0, 615.0),
            ("beta_sitosterol_mg", 615.0, 680.0),
            ("phytate_mg", 680.0, 740.0),
            ("total_saponin_mg", 740.0, 810.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}
        for pno in range(453, 471):
            page_data = self._parse_page_rows_with_bins(pno, col_bins)
            for code, data in page_data.items():
                res: Dict[str, Any] = {"sd_values": {}}
                for col_name, _, _ in col_bins:
                    if col_name == "regions":
                        continue
                    mean, sd = data.get(col_name, (None, None))
                    res[col_name] = mean
                    if sd is not None:
                        res["sd_values"][col_name] = sd
                results[code] = res

        return results

    def parse_table12_cooking_oils(self) -> Dict[str, Dict[str, Any]]:
        """
        Table 12: Fatty Acid Profile of Edible Cooking Oils and Fats (Pages 474–475, 0-indexed 473–474).
        Creates foods T001 to T014 with fatty acid percentage profile.
        """
        p1_bins = [
            ("regions", 180.0, 215.0),
            ("butyric_c4_0_mg", 215.0, 260.0),
            ("caproic_c6_0_mg", 260.0, 310.0),
            ("caprylic_c8_0_mg", 310.0, 360.0),
            ("capric_c10_0_mg", 360.0, 410.0),
            ("lauric_c12_0_mg", 410.0, 465.0),
            ("myristic_c14_0_mg", 465.0, 520.0),
            ("palmitic_c16_0_mg", 520.0, 575.0),
            ("stearic_c18_0_mg", 575.0, 630.0),
            ("arachidic_c20_0_mg", 630.0, 690.0),
            ("behenic_c22_0_mg", 690.0, 745.0),
            ("lignoceric_c24_0_mg", 745.0, 805.0),
        ]

        p2_bins = [
            ("regions", 180.0, 210.0),
            ("myristoleic_c14_1_mg", 210.0, 255.0),
            ("palmitoleic_c16_1_mg", 255.0, 300.0),
            ("elaidic_c18_1n9t_mg", 300.0, 350.0),
            ("oleic_c18_1n9_mg", 350.0, 405.0),
            ("eicosenoic_c20_1n9_mg", 405.0, 455.0),
            ("erucic_c22_1n9_mg", 455.0, 505.0),
            ("linoleic_c18_2n6_mg", 505.0, 560.0),
            ("alpha_linolenic_c18_3n3_mg", 560.0, 620.0),
            ("total_sfa_mg", 620.0, 680.0),
            ("total_mufa_mg", 680.0, 740.0),
            ("total_pufa_mg", 740.0, 805.0),
        ]

        results: Dict[str, Dict[str, Any]] = {}

        p1_data = self._parse_page_rows_with_bins(473, p1_bins, code_prefix_pattern=r"^T\d{3}$")
        p2_data = self._parse_page_rows_with_bins(474, p2_bins, code_prefix_pattern=r"^T\d{3}$")

        all_codes = sorted(set(list(p1_data.keys()) + list(p2_data.keys())))

        for code in all_codes:
            d1 = p1_data.get(code, {})
            d2 = p2_data.get(code, {})
            name = d1.get("raw_name") or d2.get("raw_name") or f"Edible Oil {code}"
            reg_mean = d1.get("regions", (1, None))[0] or d2.get("regions", (1, None))[0] or 1

            oil_record: Dict[str, Any] = {
                "name": name,
                "scientific_name": None,
                "no_of_regions": int(reg_mean),
                "is_cooking_oil_percent": True,
                "sd_values": {},
            }

            for col_name, _, _ in p1_bins:
                if col_name == "regions":
                    continue
                mean, sd = d1.get(col_name, (None, None))
                oil_record[col_name] = mean
                if sd is not None:
                    oil_record["sd_values"][col_name] = sd

            for col_name, _, _ in p2_bins:
                if col_name == "regions":
                    continue
                mean, sd = d2.get(col_name, (None, None))
                oil_record[col_name] = mean
                if sd is not None:
                    oil_record["sd_values"][col_name] = sd

            results[code] = oil_record

        return results

    def parse_chapter7_vernacular_names(self) -> Dict[str, Dict[str, str]]:
        """
        Parses Chapter 7 (Food Pictures and Description, Pages 478–549) and
        the Index (Pages 552–585) to build a complete vernacular name mapping.
        """
        vernacular_by_food: Dict[str, Dict[str, str]] = {}

        # 1. Parse Chapter 7 descriptions
        for pno in range(477, 549):
            text = self.doc[pno].get_text()
            text = re.sub(r"Food Picture and Description\s*\d*", "", text)
            entries = re.split(r"(?=\b[A-S]\d{3}\.)", text)
            for entry in entries:
                m = re.match(r"^([A-S]\d{3})\.\s*([^;\n]+(?:\([^\)]+\))?)\s*;?(.*)$", entry.strip(), re.DOTALL)
                if not m:
                    continue
                code = m.group(1)
                rest = m.group(3).strip()
                names = vernacular_by_food.setdefault(code, {})

                lang_parts = re.split(r";\s*", rest)
                for part in lang_parts:
                    part = part.strip()
                    if not part:
                        continue
                    lm = re.match(r"^([A-Za-z\s,\.]+?)\.\s*(.+)$", part)
                    if lm:
                        langs_raw = lm.group(1)
                        val = re.sub(r"\s+", " ", lm.group(2).strip()).rstrip(". ")
                        found_langs = re.findall(r"[A-Za-z]+", langs_raw)
                        for lk in found_langs:
                            if lk in LANG_MAP:
                                names[LANG_MAP[lk]] = val

        # 2. Complement with Index (Pages 552 to 585)
        for pno in range(551, 585):
            lines = [l.strip() for l in self.doc[pno].get_text().split("\n") if l.strip()]
            i = 0
            while i < len(lines):
                line = lines[i]
                m = re.match(r"^(.*?)\s*\(([A-Za-z\s,\.]+)\)$", line)
                if m and i + 1 < len(lines):
                    raw_name = m.group(1).strip()
                    raw_langs = m.group(2).strip()
                    codes_line = lines[i + 1]
                    found_codes = re.findall(r"[A-S]\d{3}", codes_line)
                    if found_codes:
                        i += 1
                        for c in found_codes:
                            names = vernacular_by_food.setdefault(c, {})
                            found_langs = re.findall(r"[A-Za-z]+", raw_langs)
                            for lk in found_langs:
                                if lk in LANG_MAP:
                                    lang_full = LANG_MAP[lk]
                                    if lang_full not in names:
                                        names[lang_full] = raw_name
                i += 1

        return vernacular_by_food

    def parse_all(self) -> Dict[str, Any]:
        """
        Coordinates full parsing of IFCT 2017:
        Food groups, foods, and all 12 nutrient tables + vernacular names.
        """
        logger.info("Parsing Table 1: Proximate Principles...")
        proximates = self.parse_table1_proximates()

        logger.info("Parsing Table 2: Water Soluble Vitamins...")
        water_vits = self.parse_table2_water_vitamins()

        logger.info("Parsing Table 3: Fat Soluble Vitamins...")
        fat_vits = self.parse_table3_fat_vitamins()

        logger.info("Parsing Table 4: Carotenoids...")
        carotenoids = self.parse_table4_carotenoids()

        logger.info("Parsing Table 5: Minerals and Trace Elements...")
        minerals = self.parse_table5_minerals()

        logger.info("Parsing Table 6: Starch and Individual Sugars...")
        sugars = self.parse_table6_sugars()

        logger.info("Parsing Table 7: Fatty Acid Profile...")
        fatty_acids = self.parse_table7_fatty_acids()

        logger.info("Parsing Table 8: Amino Acid Profile...")
        amino_acids = self.parse_table8_amino_acids()

        logger.info("Parsing Table 9: Organic Acids...")
        organic_acids = self.parse_table9_organic_acids()

        logger.info("Parsing Table 10: Polyphenols and Flavonoids...")
        polyphenols = self.parse_table10_polyphenols()

        logger.info("Parsing Table 11: Bioactives (Oligosaccharides, Phytosterols, Phytates, Saponins)...")
        bioactives = self.parse_table11_bioactives()

        logger.info("Parsing Table 12: Cooking Oils and Fats...")
        cooking_oils = self.parse_table12_cooking_oils()

        logger.info("Parsing Chapter 7 & Index: Vernacular Names...")
        vernacular_names = self.parse_chapter7_vernacular_names()

        foods_data: Dict[str, Dict[str, Any]] = {}

        # Aggregate standard foods (Codes A to S)
        for code, prox in proximates.items():
            grp_code = code[0]

            # Merge water and fat soluble vitamins
            vit_data = water_vits.get(code, {})
            fat_data = fat_vits.get(code, {})
            combined_vits = {**vit_data}
            for k, v in fat_data.items():
                if k == "sd_values":
                    combined_vits.setdefault("sd_values", {}).update(v)
                else:
                    combined_vits[k] = v

            foods_data[code] = {
                "food_code": code,
                "group_code": grp_code,
                "group_name": IFCT_FOOD_GROUPS.get(grp_code, f"Group {grp_code}"),
                "name": prox["name"],
                "scientific_name": prox["scientific_name"],
                "no_of_regions": prox["no_of_regions"],
                "vernacular_names": vernacular_names.get(code, {}),
                "proximates": prox,
                "vitamins": combined_vits,
                "carotenoids": carotenoids.get(code, {}),
                "minerals": minerals.get(code, {}),
                "sugars": sugars.get(code, {}),
                "fatty_acids": fatty_acids.get(code, {}),
                "amino_acids": amino_acids.get(code, {}),
                "organic_acids": organic_acids.get(code, {}),
                "polyphenols": polyphenols.get(code, {}),
                "bioactives": bioactives.get(code, {}),
            }

        # Aggregate cooking oils (Group T: T001 to T014)
        for code, oil_data in cooking_oils.items():
            foods_data[code] = {
                "food_code": code,
                "group_code": "T",
                "group_name": IFCT_FOOD_GROUPS["T"],
                "name": oil_data["name"],
                "scientific_name": None,
                "no_of_regions": oil_data["no_of_regions"],
                "vernacular_names": {},
                "proximates": {
                    "total_fat_g": 100.0,
                    "protein_g": 0.0,
                    "carbohydrates_g": 0.0,
                    "total_fiber_g": 0.0,
                    "moisture_g": 0.0,
                    "ash_g": 0.0,
                    "energy_kcal": 900.0,
                    "energy_kj": 3766.0,
                    "sd_values": {},
                },
                "vitamins": {},
                "carotenoids": {},
                "minerals": {},
                "sugars": {},
                "fatty_acids": oil_data,
                "amino_acids": {},
                "organic_acids": {},
                "polyphenols": {},
                "bioactives": {},
            }

        return {
            "groups": IFCT_FOOD_GROUPS,
            "foods": foods_data,
        }
