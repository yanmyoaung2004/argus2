DECOMPOSE_SYSTEM = (
    "You are a research planning assistant. Decompose a research query "
    "into a sequence of steps. Each step has a type "
    "(discover, extract, verify, synthesize), "
    "a goal, and dependencies. Return your answer as valid JSON."
)


def decompose_query(query: str) -> str:
    return f"Decompose this query into research steps:\n\n{query}"
