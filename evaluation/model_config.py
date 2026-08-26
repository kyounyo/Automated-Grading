# Central place to map friendly role names -> OpenRouter model IDs, and
# per-model token pricing used for cost estimation in the evaluation reports.
#
# Pricing is USD per 1,000,000 tokens, taken from the project's own
# benchmarking table (Proposal Report, Table 5.3.1).

MODELS = {
    "gemini": "google/gemini-3.1-flash-lite",
    "claude": "anthropic/claude-sonnet-4.6",
    "nemotron": "nvidia/nemotron-3-super-120b-a12b",
    # Free model used to test the low-stakes Retriever/Parser role.
    # Swap this if the slug becomes unavailable on OpenRouter.
    "free": "meta-llama/llama-3.3-70b-instruct:free",
}

# input_per_m / output_per_m in USD per 1,000,000 tokens
PRICING = {
    "google/gemini-3.1-flash-lite": {"input_per_m": 0.25, "output_per_m": 1.50},
    "anthropic/claude-sonnet-4.6": {"input_per_m": 3.00, "output_per_m": 15.00},
    "nvidia/nemotron-3-super-120b-a12b": {"input_per_m": 0.085, "output_per_m": 0.40},
    "meta-llama/llama-3.3-70b-instruct:free": {"input_per_m": 0.0, "output_per_m": 0.0},
}


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a single API call given token usage."""
    price = PRICING.get(model_id, {"input_per_m": 0.0, "output_per_m": 0.0})
    return (input_tokens / 1_000_000.0) * price["input_per_m"] + (
        output_tokens / 1_000_000.0
    ) * price["output_per_m"]


def model_label(model_id: str) -> str:
    """Human-friendly label for a model id, for reports/sheet names."""
    for name, mid in MODELS.items():
        if mid == model_id:
            return name
    return model_id
