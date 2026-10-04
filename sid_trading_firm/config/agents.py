"""The agents SID Trading Firm knows about, by stable id.

Configuration maps each id to a model tier, so a typo in a config file is an
error rather than an agent silently running on the wrong model. Upstream
TradingAgents names its graph nodes differently; ``UPSTREAM_NODE_AGENTS``
translates them for cost attribution.
"""

from __future__ import annotations

# id -> display name
AGENTS: dict[str, str] = {
    # analysts
    "technical_analyst": "Technical Analyst",
    "fundamentals_analyst": "Fundamentals Analyst",
    "news_analyst": "News Analyst",
    "sentiment_analyst": "Sentiment Analyst",
    "macro_analyst": "Macro Analyst",
    "market_regime_analyst": "Market Regime Analyst",
    # research
    "bull_researcher": "Bull Researcher",
    "bear_researcher": "Bear Researcher",
    "research_manager": "Research Manager",
    "quant_validator": "Quant Validator",
    # decision layers
    "trader": "Trader",
    "aggressive_risk_analyst": "Aggressive Risk Analyst",
    "conservative_risk_analyst": "Conservative Risk Analyst",
    "neutral_risk_analyst": "Neutral Risk Analyst",
    "risk_manager": "Risk Manager",
    "portfolio_manager": "Portfolio Manager",
    "cio": "CIO",
    # support
    "reflector": "Reflector",
    "extractor": "Extractor",
}

# Upstream graph node name -> agent id. Upstream's "Market Analyst" is a
# single-ticker technical analyst, so it is attributed as one. Its "Memory Log"
# step settles past decisions and writes reflections.
UPSTREAM_NODE_AGENTS: dict[str, str] = {
    "Market Analyst": "technical_analyst",
    "Fundamentals Analyst": "fundamentals_analyst",
    "News Analyst": "news_analyst",
    "Sentiment Analyst": "sentiment_analyst",
    "Bull Researcher": "bull_researcher",
    "Bear Researcher": "bear_researcher",
    "Research Manager": "research_manager",
    "Trader": "trader",
    "Aggressive Analyst": "aggressive_risk_analyst",
    "Conservative Analyst": "conservative_risk_analyst",
    "Neutral Analyst": "neutral_risk_analyst",
    "Portfolio Manager": "portfolio_manager",
    "Memory Log": "reflector",
}


def display_name(agent: str) -> str:
    """The human name for an agent id; unknown ids are shown as given."""
    return AGENTS.get(agent, agent)
