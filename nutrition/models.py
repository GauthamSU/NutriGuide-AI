from django.db import models


class FoodGroup(models.Model):
    """
    Food groups categorized according to the Indian Food Composition Tables (IFCT 2017).
    Codes A through T (19 food groups + Group T: Edible Oils and Fats).
    """
    code = models.CharField(max_length=5, primary_key=True, help_text="Group letter code, e.g., 'A', 'B', 'T'")
    name = models.CharField(max_length=150, help_text="Full group name, e.g., 'Cereals and Millets'")
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["code"]
        verbose_name = "Food Group"
        verbose_name_plural = "Food Groups"

    def __str__(self):
        return f"{self.code} - {self.name}"


class Food(models.Model):
    """
    Individual key food item from IFCT 2017 (528 foods + 14 edible oils).
    """
    food_code = models.CharField(max_length=10, primary_key=True, help_text="IFCT Food code, e.g., 'A001'")
    group = models.ForeignKey(FoodGroup, on_delete=models.CASCADE, related_name="foods")
    name = models.CharField(max_length=255, db_index=True, help_text="Common food name")
    scientific_name = models.CharField(max_length=255, blank=True, null=True, db_index=True, help_text="Botanical/taxonomic name")
    no_of_regions = models.PositiveSmallIntegerField(default=1, help_text="Number of sampling regions across India")
    vernacular_names = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dictionary of regional language names: {'Hindi': 'Bajra', 'Tamil': 'Kambu', ...}",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["food_code"]
        verbose_name = "Food"
        verbose_name_plural = "Foods"

    def __str__(self):
        return f"{self.food_code}: {self.name}"


class FoodVernacularName(models.Model):
    """
    Relational mapping of food items to Indian regional language names.
    Enables indexed, high-speed multi-lingual queries (Hindi, Tamil, Telugu, Kannada, Bengali, etc.).
    """
    food = models.ForeignKey(Food, on_delete=models.CASCADE, related_name="vernacular_records")
    language = models.CharField(max_length=50, db_index=True, help_text="Language name, e.g., 'Hindi', 'Tamil'")
    name = models.CharField(max_length=255, db_index=True, help_text="Regional food name")

    class Meta:
        ordering = ["language", "name"]
        verbose_name = "Food Vernacular Name"
        verbose_name_plural = "Food Vernacular Names"
        unique_together = [("food", "language", "name")]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["language", "name"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.language}) -> {self.food_id}"


class ProximateNutrient(models.Model):
    """
    Table 1: Proximate Principles and Dietary Fibre (expressed per 100g edible portion).
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="proximates")
    moisture_g = models.FloatField(null=True, blank=True, help_text="Moisture in grams (WATER)")
    protein_g = models.FloatField(null=True, blank=True, help_text="Protein in grams (PROTCNT)")
    ash_g = models.FloatField(null=True, blank=True, help_text="Ash in grams (ASH)")
    total_fat_g = models.FloatField(null=True, blank=True, help_text="Total Fat in grams (FATCE)")
    total_fiber_g = models.FloatField(null=True, blank=True, help_text="Total Dietary Fibre in grams (FIBTG)")
    insoluble_fiber_g = models.FloatField(null=True, blank=True, help_text="Insoluble Dietary Fibre in grams (FIBINS)")
    soluble_fiber_g = models.FloatField(null=True, blank=True, help_text="Soluble Dietary Fibre in grams (FIBSOL)")
    carbohydrates_g = models.FloatField(null=True, blank=True, help_text="Available Carbohydrate in grams (CHOAVLDF)")
    energy_kj = models.FloatField(null=True, blank=True, help_text="Energy in kilojoules (ENERC)")
    energy_kcal = models.FloatField(null=True, blank=True, help_text="Energy in kilocalories (ENERC / 4.184)")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values: {'protein_g': 0.34, ...}")

    def __str__(self):
        return f"Proximates for {self.food_id}"


class VitaminNutrient(models.Model):
    """
    Tables 2 & 3: Water Soluble & Fat Soluble Vitamins (per 100g edible portion).
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="vitamins")
    # Water Soluble Vitamins (Table 2)
    thiamine_b1_mg = models.FloatField(null=True, blank=True, help_text="Thiamine B1 in mg (THIA)")
    riboflavin_b2_mg = models.FloatField(null=True, blank=True, help_text="Riboflavin B2 in mg (RIBF)")
    niacin_b3_mg = models.FloatField(null=True, blank=True, help_text="Niacin B3 in mg (NIA)")
    pantothenic_acid_b5_mg = models.FloatField(null=True, blank=True, help_text="Pantothenic Acid B5 in mg (PANTAC)")
    vitamin_b6_mg = models.FloatField(null=True, blank=True, help_text="Total B6 in mg (VITB6A)")
    biotin_b7_mcg = models.FloatField(null=True, blank=True, help_text="Biotin B7 in mcg (BIOT)")
    folates_b9_mcg = models.FloatField(null=True, blank=True, help_text="Total Folates B9 in mcg (FOLSUM)")
    vitamin_c_mg = models.FloatField(null=True, blank=True, help_text="Total Ascorbic Acid C in mg (VITC)")

    # Fat Soluble Vitamins (Table 3)
    ergocalciferol_d2_mcg = models.FloatField(null=True, blank=True, help_text="Vitamin D2 Ergocalciferol in mcg (ERGCAL)")
    alpha_tocopherol_mcg = models.FloatField(null=True, blank=True, help_text="Alpha-tocopherol in mcg")
    beta_tocopherol_mcg = models.FloatField(null=True, blank=True, help_text="Beta-tocopherol in mcg")
    gamma_tocopherol_mcg = models.FloatField(null=True, blank=True, help_text="Gamma-tocopherol in mcg")
    delta_tocopherol_mcg = models.FloatField(null=True, blank=True, help_text="Delta-tocopherol in mcg")
    alpha_tocotrienol_mcg = models.FloatField(null=True, blank=True, help_text="Alpha-tocotrienol in mcg")
    beta_tocotrienol_mcg = models.FloatField(null=True, blank=True, help_text="Beta-tocotrienol in mcg")
    gamma_tocotrienol_mcg = models.FloatField(null=True, blank=True, help_text="Gamma-tocotrienol in mcg")
    delta_tocotrienol_mcg = models.FloatField(null=True, blank=True, help_text="Delta-tocotrienol in mcg")
    vitamin_e_mg = models.FloatField(null=True, blank=True, help_text="Vitamin E (alpha-tocopherol equivalent) in mg (VITE)")
    vitamin_k1_mcg = models.FloatField(null=True, blank=True, help_text="Vitamin K1 Phylloquinones in mcg (VITK1)")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values")

    def __str__(self):
        return f"Vitamins for {self.food_id}"


class CarotenoidNutrient(models.Model):
    """
    Table 4: Carotenoids (expressed in mcg per 100g edible portion).
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="carotenoids")
    lutein_mcg = models.FloatField(null=True, blank=True, help_text="Lutein in mcg (LUTN)")
    zeaxanthin_mcg = models.FloatField(null=True, blank=True, help_text="Zeaxanthin in mcg (ZEA)")
    lycopene_mcg = models.FloatField(null=True, blank=True, help_text="Lycopene in mcg (LYCPN)")
    beta_cryptoxanthin_mcg = models.FloatField(null=True, blank=True, help_text="Beta-Cryptoxanthin in mcg (CRYPXB)")
    gamma_carotene_mcg = models.FloatField(null=True, blank=True, help_text="Gamma-Carotene in mcg (CARTG)")
    alpha_carotene_mcg = models.FloatField(null=True, blank=True, help_text="Alpha-Carotene in mcg (CARTA)")
    beta_carotene_mcg = models.FloatField(null=True, blank=True, help_text="Beta-Carotene in mcg (CARTB)")
    total_carotenoids_mcg = models.FloatField(null=True, blank=True, help_text="Total Carotenoids in mcg (CARTOT)")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values")

    def __str__(self):
        return f"Carotenoids for {self.food_id}"


class MineralNutrient(models.Model):
    """
    Table 5: Minerals & Trace Elements (per 100g edible portion).
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="minerals")
    # Macrominerals
    calcium_mg = models.FloatField(null=True, blank=True, help_text="Calcium in mg (CA)")
    phosphorus_mg = models.FloatField(null=True, blank=True, help_text="Phosphorus in mg (P)")
    magnesium_mg = models.FloatField(null=True, blank=True, help_text="Magnesium in mg (MG)")
    sodium_mg = models.FloatField(null=True, blank=True, help_text="Sodium in mg (NA)")
    potassium_mg = models.FloatField(null=True, blank=True, help_text="Potassium in mg (K)")

    # Microminerals / Trace elements
    iron_mg = models.FloatField(null=True, blank=True, help_text="Iron in mg (FE)")
    zinc_mg = models.FloatField(null=True, blank=True, help_text="Zinc in mg (ZN)")
    copper_mg = models.FloatField(null=True, blank=True, help_text="Copper in mg (CU)")
    manganese_mg = models.FloatField(null=True, blank=True, help_text="Manganese in mg (MN)")
    selenium_mcg = models.FloatField(null=True, blank=True, help_text="Selenium in mcg (SE)")
    chromium_mg = models.FloatField(null=True, blank=True, help_text="Chromium in mg (CR)")
    cobalt_mg = models.FloatField(null=True, blank=True, help_text="Cobalt in mg (CO)")
    nickel_mg = models.FloatField(null=True, blank=True, help_text="Nickel in mg (NI)")
    molybdenum_mg = models.FloatField(null=True, blank=True, help_text="Molybdenum in mg (MO)")
    aluminium_mg = models.FloatField(null=True, blank=True, help_text="Aluminium in mg (AL)")
    arsenic_mcg = models.FloatField(null=True, blank=True, help_text="Arsenic in mcg (AS)")
    cadmium_mg = models.FloatField(null=True, blank=True, help_text="Cadmium in mg (CD)")
    lead_mg = models.FloatField(null=True, blank=True, help_text="Lead in mg (PB)")
    lithium_mg = models.FloatField(null=True, blank=True, help_text="Lithium in mg (LI)")
    mercury_mcg = models.FloatField(null=True, blank=True, help_text="Mercury in mcg (HG)")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values")

    def __str__(self):
        return f"Minerals for {self.food_id}"


class SugarNutrient(models.Model):
    """
    Table 6: Starch and Individual Sugars (expressed in grams per 100g edible portion).
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="sugars")
    total_starch_g = models.FloatField(null=True, blank=True, help_text="Total Available Starch in grams (STARCH)")
    fructose_g = models.FloatField(null=True, blank=True, help_text="Fructose in grams (FRUS)")
    glucose_g = models.FloatField(null=True, blank=True, help_text="Glucose in grams (GLUS)")
    sucrose_g = models.FloatField(null=True, blank=True, help_text="Sucrose in grams (SUCS)")
    maltose_g = models.FloatField(null=True, blank=True, help_text="Maltose in grams (MALS)")
    total_free_sugars_g = models.FloatField(null=True, blank=True, help_text="Total Free Sugars in grams (SUGARS)")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values")

    def __str__(self):
        return f"Sugars for {self.food_id}"


class FattyAcidNutrient(models.Model):
    """
    Table 7 & Table 12: Fatty Acid Profile.
    For standard foods (Table 7), expressed in mg per 100g edible portion.
    For edible cooking oils (Table 12), expressed as % of total fatty acids.
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="fatty_acids")
    is_cooking_oil_percent = models.BooleanField(
        default=False,
        help_text="True if values represent % of total fatty acids (Table 12), False for mg/100g (Table 7)",
    )

    # Saturated Fatty Acids (SFA)
    butyric_c4_0_mg = models.FloatField(null=True, blank=True, help_text="Butyric C4:0")
    caproic_c6_0_mg = models.FloatField(null=True, blank=True, help_text="Caproic C6:0")
    caprylic_c8_0_mg = models.FloatField(null=True, blank=True, help_text="Caprylic C8:0")
    capric_c10_0_mg = models.FloatField(null=True, blank=True, help_text="Capric C10:0")
    lauric_c12_0_mg = models.FloatField(null=True, blank=True, help_text="Lauric C12:0")
    myristic_c14_0_mg = models.FloatField(null=True, blank=True, help_text="Myristic C14:0")
    palmitic_c16_0_mg = models.FloatField(null=True, blank=True, help_text="Palmitic C16:0")
    stearic_c18_0_mg = models.FloatField(null=True, blank=True, help_text="Stearic C18:0")
    arachidic_c20_0_mg = models.FloatField(null=True, blank=True, help_text="Arachidic C20:0")
    behenic_c22_0_mg = models.FloatField(null=True, blank=True, help_text="Behenic C22:0")
    lignoceric_c24_0_mg = models.FloatField(null=True, blank=True, help_text="Lignoceric C24:0")
    total_sfa_mg = models.FloatField(null=True, blank=True, help_text="Total Saturated Fatty Acids (TSFA)")

    # Monounsaturated Fatty Acids (MUFA)
    myristoleic_c14_1_mg = models.FloatField(null=True, blank=True, help_text="Myristoleic C14:1")
    palmitoleic_c16_1_mg = models.FloatField(null=True, blank=True, help_text="Palmitoleic C16:1")
    elaidic_c18_1n9t_mg = models.FloatField(null=True, blank=True, help_text="Elaidic C18:1n9t trans")
    oleic_c18_1n9_mg = models.FloatField(null=True, blank=True, help_text="Oleic C18:1n9")
    eicosenoic_c20_1n9_mg = models.FloatField(null=True, blank=True, help_text="Eicosenoic C20:1n9")
    erucic_c22_1n9_mg = models.FloatField(null=True, blank=True, help_text="Erucic C22:1n9")
    nervonic_c24_1n9_mg = models.FloatField(null=True, blank=True, help_text="Nervonic C24:1n9")
    total_mufa_mg = models.FloatField(null=True, blank=True, help_text="Total Monounsaturated Fatty Acids (TMUFA)")

    # Polyunsaturated Fatty Acids (PUFA)
    linoleic_c18_2n6_mg = models.FloatField(null=True, blank=True, help_text="Linoleic C18:2n6 (LA)")
    eicosadienoic_c20_2_mg = models.FloatField(null=True, blank=True, help_text="Eicosadienoic C20:2")
    alpha_linolenic_c18_3n3_mg = models.FloatField(null=True, blank=True, help_text="Alpha-Linolenic C18:3n3 (ALA)")
    eicosatrienoic_c20_3n6_mg = models.FloatField(null=True, blank=True, help_text="Eicosatrienoic C20:3n6")
    arachidonic_c20_4n6_mg = models.FloatField(null=True, blank=True, help_text="Arachidonic C20:4n6 (AA)")
    epa_c20_5n3_mg = models.FloatField(null=True, blank=True, help_text="Eicosapentaenoic C20:5n3 (EPA)")
    dha_c22_6n3_mg = models.FloatField(null=True, blank=True, help_text="Docosahexaenoic C22:6n3 (DHA)")
    total_pufa_mg = models.FloatField(null=True, blank=True, help_text="Total Polyunsaturated Fatty Acids (TPUFA)")

    # Sterol
    cholesterol_mg = models.FloatField(null=True, blank=True, help_text="Cholesterol in mg per 100g (CHOLC)")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values")

    def __str__(self):
        return f"Fatty Acids for {self.food_id}"


class AminoAcidNutrient(models.Model):
    """
    Table 8: Amino Acid Profile (expressed in grams per 100g protein).
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="amino_acids")

    # Essential Amino Acids
    histidine_g = models.FloatField(null=True, blank=True, help_text="Histidine (HIS) g/100g protein")
    isoleucine_g = models.FloatField(null=True, blank=True, help_text="Isoleucine (ILE) g/100g protein")
    leucine_g = models.FloatField(null=True, blank=True, help_text="Leucine (LEU) g/100g protein")
    lysine_g = models.FloatField(null=True, blank=True, help_text="Lysine (LYS) g/100g protein")
    methionine_g = models.FloatField(null=True, blank=True, help_text="Methionine (MET) g/100g protein")
    cystine_g = models.FloatField(null=True, blank=True, help_text="Cystine (CYS) g/100g protein")
    phenylalanine_g = models.FloatField(null=True, blank=True, help_text="Phenylalanine (PHE) g/100g protein")
    threonine_g = models.FloatField(null=True, blank=True, help_text="Threonine (THR) g/100g protein")
    tryptophan_g = models.FloatField(null=True, blank=True, help_text="Tryptophan (TRP) g/100g protein")
    valine_g = models.FloatField(null=True, blank=True, help_text="Valine (VAL) g/100g protein")

    # Non-Essential Amino Acids
    alanine_g = models.FloatField(null=True, blank=True, help_text="Alanine (ALA) g/100g protein")
    arginine_g = models.FloatField(null=True, blank=True, help_text="Arginine (ARG) g/100g protein")
    aspartic_acid_g = models.FloatField(null=True, blank=True, help_text="Aspartic acid (ASP) g/100g protein")
    glutamic_acid_g = models.FloatField(null=True, blank=True, help_text="Glutamic acid (GLU) g/100g protein")
    glycine_g = models.FloatField(null=True, blank=True, help_text="Glycine (GLY) g/100g protein")
    proline_g = models.FloatField(null=True, blank=True, help_text="Proline (PRO) g/100g protein")
    serine_g = models.FloatField(null=True, blank=True, help_text="Serine (SER) g/100g protein")
    tyrosine_g = models.FloatField(null=True, blank=True, help_text="Tyrosine (TYR) g/100g protein")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values")

    def __str__(self):
        return f"Amino Acids for {self.food_id}"


class OrganicAcidNutrient(models.Model):
    """
    Table 9: Organic Acids (expressed in mg per 100g edible portion).
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="organic_acids")
    oxalate_total_mg = models.FloatField(null=True, blank=True, help_text="Total Oxalate in mg")
    oxalate_soluble_mg = models.FloatField(null=True, blank=True, help_text="Soluble Oxalate in mg")
    oxalate_insoluble_mg = models.FloatField(null=True, blank=True, help_text="Insoluble Oxalate in mg")
    cis_aconitic_acid_mg = models.FloatField(null=True, blank=True, help_text="Cis-Aconitic Acid in mg")
    citric_acid_mg = models.FloatField(null=True, blank=True, help_text="Citric Acid in mg (CITAC)")
    fumaric_acid_mg = models.FloatField(null=True, blank=True, help_text="Fumaric Acid in mg (FUMAC)")
    malic_acid_mg = models.FloatField(null=True, blank=True, help_text="Malic Acid in mg (MALAC)")
    quinic_acid_mg = models.FloatField(null=True, blank=True, help_text="Quinic Acid in mg")
    succinic_acid_mg = models.FloatField(null=True, blank=True, help_text="Succinic Acid in mg (SUCAC)")
    tartaric_acid_mg = models.FloatField(null=True, blank=True, help_text="Tartaric Acid in mg (TARAC)")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values")

    def __str__(self):
        return f"Organic Acids for {self.food_id}"


class PolyphenolNutrient(models.Model):
    """
    Table 10: Polyphenols and Flavonoids (expressed in mg per 100g edible portion).
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="polyphenols")

    # Phenolic Acids
    dihydroxy_benzoic_3_4_mg = models.FloatField(null=True, blank=True, help_text="3,4-Dihydroxybenzoic acid in mg")
    hydroxy_benzaldehyde_3_mg = models.FloatField(null=True, blank=True, help_text="3-Hydroxybenzaldehyde in mg")
    protocatechuic_acid_mg = models.FloatField(null=True, blank=True, help_text="Protocatechuic acid in mg")
    vanillic_acid_mg = models.FloatField(null=True, blank=True, help_text="Vanillic acid in mg")
    gallic_acid_mg = models.FloatField(null=True, blank=True, help_text="Gallic acid in mg (GALLAC)")
    cinnamic_acid_mg = models.FloatField(null=True, blank=True, help_text="Cinnamic acid in mg")
    o_coumaric_acid_mg = models.FloatField(null=True, blank=True, help_text="o-Coumaric acid in mg")
    p_coumaric_acid_mg = models.FloatField(null=True, blank=True, help_text="p-Coumaric acid in mg")
    caffeic_acid_mg = models.FloatField(null=True, blank=True, help_text="Caffeic acid in mg")
    chlorogenic_acid_mg = models.FloatField(null=True, blank=True, help_text="Chlorogenic acid in mg (CHLRAC)")
    ferulic_acid_mg = models.FloatField(null=True, blank=True, help_text="Ferulic acid in mg (FERAC)")
    syringic_acid_mg = models.FloatField(null=True, blank=True, help_text="Syringic acid in mg")
    sinapinic_acid_mg = models.FloatField(null=True, blank=True, help_text="Sinapinic acid in mg")
    ellagic_acid_mg = models.FloatField(null=True, blank=True, help_text="Ellagic acid in mg")

    # Flavonoids & Isoflavonoids
    apigenin_mg = models.FloatField(null=True, blank=True, help_text="Apigenin in mg (APIGEN)")
    apigenin_6_c_glucoside_mg = models.FloatField(null=True, blank=True, help_text="Apigenin-6-C-glucoside in mg")
    apigenin_7_o_neohesperidoside_mg = models.FloatField(null=True, blank=True, help_text="Apigenin-7-O-neohesperidoside in mg")
    luteolin_mg = models.FloatField(null=True, blank=True, help_text="Luteolin in mg (LUTEOL)")
    kaempferol_mg = models.FloatField(null=True, blank=True, help_text="Kaempferol in mg (KAEMF)")
    quercetin_mg = models.FloatField(null=True, blank=True, help_text="Quercetin in mg (QUERCE)")
    quercetin_3_beta_d_glucoside_mg = models.FloatField(null=True, blank=True, help_text="Quercetin-3-beta-D-glucoside in mg")
    quercetin_3_o_rutinoside_mg = models.FloatField(null=True, blank=True, help_text="Quercetin-3-O-rutinoside in mg")
    quercetin_3_galactoside_mg = models.FloatField(null=True, blank=True, help_text="Quercetin-3-galactoside in mg")
    isorhamnetin_mg = models.FloatField(null=True, blank=True, help_text="Isorhamnetin in mg")
    myricetin_mg = models.FloatField(null=True, blank=True, help_text="Myricetin in mg")
    resveratrol_mg = models.FloatField(null=True, blank=True, help_text="Resveratrol in mg")
    hesperetin_mg = models.FloatField(null=True, blank=True, help_text="Hesperetin in mg (HESPT)")
    naringenin_mg = models.FloatField(null=True, blank=True, help_text="Naringenin in mg")
    hesperidin_mg = models.FloatField(null=True, blank=True, help_text="Hesperidin in mg (HESPD)")
    daidzein_mg = models.FloatField(null=True, blank=True, help_text="Daidzein in mg (DAIDZN)")
    genistein_mg = models.FloatField(null=True, blank=True, help_text="Genistein in mg (GNSTEIN)")

    # Flavan-3-ols / Catechins
    epicatechin_mg = models.FloatField(null=True, blank=True, help_text="(-)-Epicatechin in mg (EPICATEC)")
    epigallocatechin_mg = models.FloatField(null=True, blank=True, help_text="(-)-Epigallocatechin in mg")
    epigallocatechin_3_gallate_mg = models.FloatField(null=True, blank=True, help_text="(-)-Epigallocatechin-3-gallate (EGCG) in mg")
    catechin_mg = models.FloatField(null=True, blank=True, help_text="(+)-Catechin in mg")
    gallocatechin_mg = models.FloatField(null=True, blank=True, help_text="Gallocatechin in mg")
    epicatechin_gallate_mg = models.FloatField(null=True, blank=True, help_text="(-)-Epicatechin gallate in mg")

    # Total Polyphenols
    total_polyphenols_mg = models.FloatField(null=True, blank=True, help_text="Total Polyphenols in mg (POLYT)")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values")

    def __str__(self):
        return f"Polyphenols for {self.food_id}"


class BioactiveNutrient(models.Model):
    """
    Table 11: Oligosaccharides, Phytosterols, Phytates and Saponins (per 100g edible portion).
    """
    food = models.OneToOneField(Food, on_delete=models.CASCADE, related_name="bioactives")

    # Oligosaccharides (g/100g)
    raffinose_g = models.FloatField(null=True, blank=True, help_text="Raffinose in grams (RAFS)")
    stachyose_g = models.FloatField(null=True, blank=True, help_text="Stachyose in grams (STAS)")
    verbascose_g = models.FloatField(null=True, blank=True, help_text="Verbascose in grams (VERS)")
    ajugose_g = models.FloatField(null=True, blank=True, help_text="Ajugose in grams")

    # Phytosterols (mg/100g)
    campesterol_mg = models.FloatField(null=True, blank=True, help_text="Campesterol in mg (CAMT)")
    stigmasterol_mg = models.FloatField(null=True, blank=True, help_text="Stigmasterol in mg (STGSTR)")
    beta_sitosterol_mg = models.FloatField(null=True, blank=True, help_text="Beta-Sitosterol in mg (SITSTR)")

    # Phytate & Saponin (mg/100g)
    phytate_mg = models.FloatField(null=True, blank=True, help_text="Total Phytate in mg (PHYTC)")
    total_saponin_mg = models.FloatField(null=True, blank=True, help_text="Total Saponin in mg")
    sd_values = models.JSONField(default=dict, blank=True, help_text="Standard deviation values")

    def __str__(self):
        return f"Bioactives for {self.food_id}"


def __getattr__(name: str):
    """
    Re-export core application models from chat_history.models for backward compatibility
    while keeping the nutrition app strictly limited to read-only IFCT 2017 reference tables.
    """
    if name in {
        "UserProfile",
        "NutritionGroup",
        "GroupMembership",
        "GroupMealLog",
        "TrackedMeal",
    }:
        from chat_history import models as core_models

        return getattr(core_models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


