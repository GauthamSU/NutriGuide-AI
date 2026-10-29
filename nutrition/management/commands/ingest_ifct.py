from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from nutrition.ingestion.pipeline import run_ifct_ingestion


class Command(BaseCommand):
    help = "Ingest Indian Food Composition Tables (IFCT 2017) PDF into the SQL database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--pdf-path",
            type=str,
            default="raw_data/IFCT2017_16122024.pdf",
            help="Relative or absolute path to IFCT2017 PDF file",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse PDF without writing changes to the database",
        )

    def handle(self, *args, **options):
        pdf_path = options["pdf_path"]
        dry_run = options["dry_run"]

        if not Path(pdf_path).exists():
            raise CommandError(f"PDF file does not exist at: {pdf_path}")

        self.stdout.write(self.style.NOTICE(f"Starting IFCT ingestion from: {pdf_path} (dry_run={dry_run})"))
        try:
            summary = run_ifct_ingestion(pdf_path=pdf_path, dry_run=dry_run)
            self.stdout.write(self.style.SUCCESS("=== Ingestion Finished Successfully ==="))
            self.stdout.write(f"  Food Groups:         {summary['groups_count']}")
            self.stdout.write(f"  Food Items:          {summary['foods_count']}")
            self.stdout.write(f"  Vernacular Records:  {summary['vernacular_names_count']}")
            self.stdout.write(f"  Proximates (T1):     {summary['proximates_count']}")
            self.stdout.write(f"  Vitamins (T2, T3):   {summary['vitamins_count']}")
            self.stdout.write(f"  Carotenoids (T4):    {summary['carotenoids_count']}")
            self.stdout.write(f"  Minerals (T5):       {summary['minerals_count']}")
            self.stdout.write(f"  Sugars & Starch (T6):{summary['sugars_count']}")
            self.stdout.write(f"  Fatty Acids (T7,T12):{summary['fatty_acids_count']}")
            self.stdout.write(f"  Amino Acids (T8):    {summary['amino_acids_count']}")
            self.stdout.write(f"  Organic Acids (T9):  {summary['organic_acids_count']}")
            self.stdout.write(f"  Polyphenols (T10):   {summary['polyphenols_count']}")
            self.stdout.write(f"  Bioactives (T11):    {summary['bioactives_count']}")
            self.stdout.write(f"  Total Time:          {summary['elapsed_seconds']}s")
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Ingestion failed: {exc}"))
            raise CommandError(exc) from exc
