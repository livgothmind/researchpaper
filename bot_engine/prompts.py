POSTER_PROMPT = ""

WHY_USEFUL_PROMPT = ""

DESCRIPTION_FROM_PDF_PROMPT = ""
DESCRIPTION_FROM_SCRAPE_PROMPT = ""


def build_tag_match_prompt(user_tags: str, all_valid_slugs: list[str]) -> str:
    return (
        f"User tags: {user_tags}\n"
        f"Valid slugs (already-existing ones excluded): {', '.join(all_valid_slugs)}\n\n"
        "Return ONLY the NEW slugs (from the list above) that best match the user tags. "
        "Do NOT repeat any already-existing slug. "
        "Return a comma-separated list of slugs (empty string if none match), no explanation."
    )
