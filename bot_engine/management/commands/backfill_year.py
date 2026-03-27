import re
from django.core.management.base import BaseCommand
from bot_engine.models import ResearchPoster


class Command(BaseCommand):
    help = "Backfill publication_year from notes field for existing posters"

    def handle(self, *args, **options):
        posters = ResearchPoster.objects.filter(
            publication_year__isnull=True,
        ).exclude(notes__isnull=True).exclude(notes="")

        updated = 0
        for p in posters:
            match = re.search(r'Year:\s*(\d{4})', p.notes)
            if match:
                p.publication_year = int(match.group(1))
                p.save(update_fields=["publication_year", "updated_at"])
                updated += 1
                self.stdout.write(f"  #{p.id} '{p.title[:50]}' -> {p.publication_year}")

        self.stdout.write(self.style.SUCCESS(f"Done. Updated {updated} posters."))
