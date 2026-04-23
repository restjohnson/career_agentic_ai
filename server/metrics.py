"""
Metrics extraction from AgentState runs.

Collects critique scores, plan structure, iteration counts, and
action specificity (personalization) by parsing rationale fields
for mentions of skills/projects from the student's resume.
"""

import re
from typing import Dict, List, Tuple
from datetime import datetime

from app.state import AgentState


def extract_resume_terms(resume_text: str) -> List[str]:
    """
    Extract key skill/tech terms from resume text.
    Uses regex patterns for common technologies and capitalized phrases.

    Returns a deduplicated list of lowercase terms (length > 2).
    """
    terms = set()

    # Common technology/skill keywords
    tech_keywords = [
        'python', 'javascript', 'typescript', 'java', 'c++', 'c#', 'go', 'rust',
        'react', 'vue', 'angular', 'svelte', 'next.js', 'nuxt',
        'django', 'flask', 'fastapi', 'spring', 'express', 'node.js', 'nodejs',
        'docker', 'kubernetes', 'aws', 'gcp', 'azure', 'firebase',
        'postgresql', 'mysql', 'mongodb', 'redis', 'elasticsearch',
        'git', 'github', 'gitlab', 'sql', 'html', 'css', 'tailwind',
        'figma', 'tableau', 'pandas', 'numpy', 'tensorflow', 'pytorch',
        'scikit-learn', 'nltk', 'spacy', 'huggingface', 'openai', 'anthropic',
        'linux', 'bash', 'shell', 'graphql', 'rest', 'api', 'ci/cd', 'jenkins',
        'agile', 'scrum', 'machine learning', 'ml', 'nlp', 'computer vision',
        'data science', 'data engineering', 'full-stack', 'backend', 'frontend'
    ]

    # Extract matching keywords
    text_lower = resume_text.lower()
    for keyword in tech_keywords:
        if keyword in text_lower:
            terms.add(keyword)

    # Extract capitalized multi-word phrases (project names, companies)
    capitalized = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', resume_text)
    for phrase in capitalized:
        term = phrase.lower()
        if len(term) > 2:
            terms.add(term)

    # Extract single capitalized words (company names, tech)
    singles = re.findall(r'\b[A-Z]{2,}\b', resume_text)  # acronyms like "AWS", "ML"
    for s in singles:
        if len(s) > 1:
            terms.add(s.lower())

    return sorted(list(terms))


def simple_fuzzy_match(term: str, text: str) -> bool:
    """
    Check if a resume term appears in rationale text.
    Handles common variations (singular/plural, hyphenation).
    """
    text_lower = text.lower()
    term_lower = term.lower()

    # Exact substring match
    if term_lower in text_lower:
        return True

    # Handle singular/plural (e.g., "python" vs "pythons")
    if term_lower.endswith('s'):
        if term_lower[:-1] in text_lower:
            return True
    else:
        if term_lower + 's' in text_lower:
            return True

    # Handle hyphenation variations (e.g., "full-stack" vs "fullstack")
    if '-' in term_lower:
        variant = term_lower.replace('-', '')
        if variant in text_lower:
            return True

    return False


def calculate_action_specificity(
    resume_text: str,
    rationales: List[str]
) -> Tuple[float, int, int]:
    """
    Measure how personalized actions are to the student's background.

    Extracts resume terms and counts how many appear in the action rationales.

    Args:
        resume_text: Raw resume content
        rationales: List of learning_action.rationale strings

    Returns:
        (specificity_ratio [0-1], terms_mentioned, total_unique_terms)
        ratio = terms_mentioned / total_unique_terms
    """
    resume_terms = extract_resume_terms(resume_text)
    if not resume_terms:
        return 0.0, 0, 0

    # Check which resume terms appear in any rationale
    mentioned_terms = set()
    combined_rationale = ' '.join(rationales)

    for term in resume_terms:
        if simple_fuzzy_match(term, combined_rationale):
            mentioned_terms.add(term)

    ratio = len(mentioned_terms) / len(resume_terms) if resume_terms else 0.0
    return ratio, len(mentioned_terms), len(resume_terms)


def extract_metrics_from_state(
    state: AgentState,
    resume_text: str,
    condition: str = "full",
    scenario: str = "unknown",
    attempt: int = 1
) -> Dict:
    """
    Extract all metrics from AgentState after a run completes.

    Captures:
    - Critique rubric scores
    - Plan structure (phases, actions, resources)
    - Iteration count
    - Action specificity (personalization)

    Args:
        state: Final AgentState from the run
        resume_text: Student's raw resume text (for specificity parsing)
        condition: "full" or "ablation3" or other variant name
        scenario: Test scenario identifier (e.g., "ml_engineer_junior_cs")
        attempt: Run number (1, 2, 3, etc.)

    Returns:
        Dict with all metrics ready for CSV row
    """
    metrics = {}

    # Identifiers
    metrics['timestamp'] = datetime.now().isoformat()
    metrics['run_id'] = state.run_id or 'unknown'
    metrics['condition'] = condition
    metrics['scenario'] = scenario
    metrics['attempt'] = attempt

    # Critique metrics
    if state.critique and state.critique.rubric_scores:
        scores = state.critique.rubric_scores
        metrics['critique_satisfactory'] = state.critique.satisfactory
        metrics['rubric_feasibility'] = scores.get('feasibility')
        metrics['rubric_level_appropriateness'] = scores.get('level_appropriateness')
        metrics['rubric_gap_coverage'] = scores.get('gap_coverage')

        # Composite: mean of feasibility and level_appropriateness
        key_scores = [
            scores.get('feasibility'),
            scores.get('level_appropriateness'),
        ]
        valid = [s for s in key_scores if s is not None]
        metrics['rubric_composite'] = sum(valid) / len(valid) if valid else None
    else:
        metrics['critique_satisfactory'] = None
        metrics['rubric_feasibility'] = None
        metrics['rubric_level_appropriateness'] = None
        metrics['rubric_gap_coverage'] = None
        metrics['rubric_composite'] = None

    # Plan structure metrics
    if state.plan and state.plan.phases:
        metrics['plan_phases'] = len(state.plan.phases)

        total_actions = sum(len(p.learning_actions) for p in state.plan.phases)
        metrics['plan_actions_total'] = total_actions

        metrics['plan_timeline_weeks'] = state.plan.timeline_weeks

        # Action specificity: how many resume terms appear in rationales?
        rationales = [
            action.rationale
            for phase in state.plan.phases
            for action in phase.learning_actions
            if action.rationale
        ]

        specificity, terms_mentioned, terms_total = calculate_action_specificity(
            resume_text, rationales
        )
        metrics['action_specificity_ratio'] = specificity
        metrics['resume_terms_mentioned'] = terms_mentioned
        metrics['resume_terms_total'] = terms_total
    else:
        metrics['plan_phases'] = 0
        metrics['plan_actions_total'] = 0
        metrics['plan_timeline_weeks'] = 0
        metrics['action_specificity_ratio'] = 0.0
        metrics['resume_terms_mentioned'] = 0
        metrics['resume_terms_total'] = 0

    return metrics


def metrics_to_csv_row(metrics: Dict) -> List[str]:
    """Convert metrics dict to ordered CSV row (strings)."""
    keys = [
        'timestamp', 'run_id', 'condition', 'scenario', 'attempt',
        'critique_satisfactory', 'rubric_feasibility', 'rubric_level_appropriateness',
        'rubric_gap_coverage', 'rubric_composite', 'plan_phases', 'plan_actions_total',
        'plan_timeline_weeks', 'action_specificity_ratio', 'resume_terms_mentioned',
        'resume_terms_total',
    ]
    return [str(metrics.get(k, '')) for k in keys]


def get_csv_header() -> List[str]:
    """Get CSV header row."""
    return [
        'timestamp', 'run_id', 'condition', 'scenario', 'attempt',
        'critique_satisfactory', 'rubric_feasibility', 'rubric_level_appropriateness',
        'rubric_gap_coverage', 'rubric_composite', 'plan_phases', 'plan_actions_total',
        'plan_timeline_weeks', 'action_specificity_ratio', 'resume_terms_mentioned',
        'resume_terms_total',
    ]
