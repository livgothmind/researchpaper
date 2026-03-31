
# ---------------------------------------------------------------------------
# Poster image analysis prompt (GPT-4o Vision)
# ---------------------------------------------------------------------------
POSTER_PROMPT = """
Analyze this image. Determine if it contains any scientific or academic content
with readable text. This includes: research posters, paper screenshots, article
pages, conference slides, or any image showing a paper title and text.
Return ONLY valid JSON (no markdown) with these fields:
{
    "is_research_poster": true or false,
    "title": "Complete paper title",
    "authors": "All authors in 'First Last' format, separated by comma and space (e.g. 'Lorenzo Baraldi, Rita Cucchiara')",
    "subfields": ["slug1", "slug2"],
    "conference": "Conference/venue if visible",
    "year": "Publication year if visible",
    "institution": "University/institution if visible",
    "search_query": "Search query to find paper online (title + first author)",
    "github_query": "Short project name or method acronym for GitHub search"
}

For "subfields", choose ONE to FOUR slugs from this list that best describe the
paper's topic. Pick only the most relevant ones:
  artificial_intelligence, machine_learning, deep_learning,
  reinforcement_learning, nlp, expert_systems, knowledge_representation,
  generative_model, continual_learning, foundation_model, model_merging, mil,
  computer_vision, medical_imaging, image_processing, computer_graphics,
  augmented_reality, virtual_reality, segmentation, classification,
  vision_text, mri, cbct, pet, xray, wsi, ct, us,
  distributed_systems, embedded_systems, computer_architecture,
  operating_systems, parallel_computing, hpc, dependable_systems,
  cybersecurity, cryptography, blockchain, network_security, iot, edge_computing,
  data_mining, big_data, dbms, information_retrieval,
  multimodal, missing_modalities, report, challenge,
  software_engineering, algorithm_design, computational_complexity,
  formal_methods, software_testing, cloud_computing, quantum_computing,
  neuromorphic_computing, mobile_computing, wearable_computing,
  pervasive_computing, robotics, autonomous_systems, bioinformatics,
  computational_biology, hci, speech_recognition, signal_processing,
  smart_grids, cyber_physical_systems, brain, abdomen, maxillofacial

Set is_research_poster to true if you can extract a paper title and any
scientific content, even from a screenshot or photo of a screen.
Set is_research_poster to false ONLY if the image has no scientific text at all
(e.g. selfie, meme, landscape, random photo with no readable academic content).
If a field is not visible, use empty string "" (or empty list [] for subfields).
"""

# ---------------------------------------------------------------------------
# Why-useful one-liner generation
# ---------------------------------------------------------------------------
WHY_USEFUL_PROMPT = """
You are an academic research assistant.
Given a paper abstract and optional user notes/tags, write ONE sentence (max 25 words)
that captures the paper's core contribution and practical value to a researcher.
Return ONLY the plain-text sentence, no labels, no bullet points.
"""

# ---------------------------------------------------------------------------
# Summary generation from PDF text
# ---------------------------------------------------------------------------
DESCRIPTION_FROM_PDF_PROMPT = """
You are a research paper summariser.
Below is the extracted text from a scientific PDF.

Write a concise description of the paper (max 80 words).
Cover: what problem is addressed, the proposed method/approach, and the main
results or contributions.
Write in third person, in a neutral academic tone.
Return ONLY the plain-text description, nothing else.
"""

# ---------------------------------------------------------------------------
# Summary generation from scraped web-page abstract
# ---------------------------------------------------------------------------
DESCRIPTION_FROM_SCRAPE_PROMPT = """
You are a research paper summariser.
Below is the abstract or description scraped from the paper's web page.

Rewrite it as a concise summary of 80 to 120 words.
Cover: what problem is addressed, the proposed method, and the main contributions.
Write in third person, in a neutral academic tone.
Remove any artefacts like "Abstract:" prefixes, HTML leftovers, or broken sentences.
Return ONLY the plain-text summary, nothing else.
"""

DESCRIPTION_FROM_POSTER_PROMPT = """
You are a research paper summariser.
Analyze this poster/paper image and write a concise summary of 80 to 120 words.
Cover: what problem is addressed, the proposed method/approach, and the main
results or contributions.
Write in third person, in a neutral academic tone.
Return ONLY the plain-text summary, nothing else.
"""


# ---------------------------------------------------------------------------
# User-tag → subfield-slug matching
# ---------------------------------------------------------------------------
def build_tag_match_prompt(user_tags: str, all_valid_slugs: list[str]) -> str:
    """
    Build the prompt that asks GPT to map free-text user tags to subfield slugs.

    Parameters
    ----------
    user_tags : str
        Comma-separated string of user-typed tags.
    all_valid_slugs : list[str]
        Slugs that are valid AND not already present in the poster's subfields
        (so GPT only returns genuinely new ones).

    Returns
    -------
    str
        Prompt string ready to be sent to GPT.
    """
    return (
        f"User tags: {user_tags}\n"
        f"Valid slugs (already-existing ones excluded): {', '.join(all_valid_slugs)}\n\n"
        "Return ONLY the NEW slugs (from the list above) that best match the user tags. "
        "Do NOT repeat any already-existing slug. "
        "Return a comma-separated list of slugs (empty string if none match), no explanation."
    )