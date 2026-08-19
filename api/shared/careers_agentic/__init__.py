# Existing imports made optional to avoid breaking the Career Connect flow
# These rely on a 'core' module that may not be available in all deployments
try:
    from .jd_enhancer import enhance_jd_markdown
    from .jd_enhancer import enhance_jd_with_existing_llm
    from .resume_analyzer import analyze_application
except ImportError:
    enhance_jd_markdown = None
    enhance_jd_with_existing_llm = None
    analyze_application = None

__all__ = [
    "enhance_jd_markdown",
    "enhance_jd_with_existing_llm",
    "analyze_application",
]