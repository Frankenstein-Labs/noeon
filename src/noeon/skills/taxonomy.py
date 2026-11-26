from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORIES: dict[str, dict[str, int]] = {
    "software-engineering": {
        "refactor": 3, "architecture": 3, "design pattern": 2, "code review": 3,
        "debug": 3, "monorepo": 3, "api": 2, "typescript": 2, "python": 2,
        "javascript": 2, "rust": 2, "golang": 2, "go ": 1, "java": 2, "kotlin": 2,
        "swift": 2, "php": 2, "ruby": 2, "c++": 3, "system design": 3,
    },
    "frontend": {
        "react": 3, "next.js": 3, "nextjs": 3, "vue": 3, "nuxt": 3, "svelte": 3,
        "angular": 3, "tailwind": 3, "css": 2, "html": 2, "responsive": 2,
        "state management": 2, "component": 2, "accessibility": 3, "wcag": 3,
        "frontend performance": 3, "animation": 2, "motion": 2, "shadcn": 3,
        "radix": 2, "design system": 3,
    },
    "design": {
        "ui/ux": 4, "ux": 3, "figma": 4, "wireframe": 4, "prototype": 3,
        "typography": 3, "color palette": 3, "layout": 2, "visual design": 4,
        "design tokens": 3, "screenshot": 3, "brand": 2, "art direction": 3,
    },
    "backend": {
        "fastapi": 4, "django": 4, "flask": 3, "nestjs": 4, "express": 3,
        "node.js": 3, "postgres": 3, "postgresql": 3, "mysql": 3, "sqlite": 2,
        "redis": 3, "supabase": 4, "appwrite": 4, "authentication": 3,
        "authorization": 3, "rest api": 3, "graphql": 3, "queue": 2, "caching": 2,
        "distributed": 2, "microservice": 3, "orm": 3, "prisma": 3,
    },
    "devops": {
        "docker": 3, "kubernetes": 4, "k8s": 4, "terraform": 4, "ci/cd": 4,
        "github actions": 4, "linux": 2, "vercel": 3, "cloudflare": 3,
        "railway": 3, "infrastructure as code": 4, "monitoring": 3, "logging": 2,
        "deployment": 3, "observability": 3, "helm": 3, "ansible": 3,
    },
    "browser-automation": {
        "playwright": 4, "puppeteer": 4, "browser automation": 4, "browser use": 4,
        "stagehand": 4, "selenium": 4, "dom": 2, "accessibility tree": 4,
        "web scraping": 3, "form": 2, "screenshot": 2, "computer use": 4,
    },
    "research": {
        "research": 4, "deep research": 5, "web search": 3, "crawl": 3,
        "documentation research": 4, "repository exploration": 3, "citation": 3,
        "source verification": 4, "competitive analysis": 4, "synthesis": 2,
        "extract": 2, "investigation": 2,
    },
    "ai-ml": {
        "llm": 3, "rag": 4, "embedding": 3, "vector database": 4, "fine-tune": 4,
        "fine tuning": 4, "lora": 4, "qlora": 4, "transformer": 3, "inference": 3,
        "model evaluation": 3, "multimodal": 3, "computer vision": 3, "speech": 2,
        "agent architecture": 3, "prompt engineering": 3, "mcp": 2,
    },
    "security": {
        "security": 2, "threat model": 5, "vulnerability": 4, "cve": 4,
        "secret": 3, "credential": 3, "sandbox": 3, "supply chain": 4,
        "permission": 3, "audit": 2, "owasp": 4, "penetration": 4,
        "encryption": 3, "dependency audit": 4,
    },
    "qa": {
        "unit test": 4, "integration test": 4, "e2e": 4, "end-to-end": 4,
        "regression": 3, "load test": 4, "performance test": 3, "visual regression": 4,
        "lint": 2, "type check": 3, "test coverage": 3, "pytest": 3, "jest": 3,
        "vitest": 3, "playwright test": 3, "qa": 3,
    },
    "data": {
        "sql": 3, "etl": 4, "data pipeline": 4, "data validation": 4,
        "analytics": 3, "data visualization": 4, "data cleaning": 4,
        "migration": 3, "data modeling": 4, "warehouse": 3, "dbt": 4,
        "pandas": 3, "spark": 3,
    },
    "creative": {
        "image generation": 4, "image processing": 4, "video": 3, "audio": 3,
        "3d": 3, "svg": 3, "graphic design": 4, "presentation": 3,
        "document generation": 3, "multimedia": 3, "pdf": 2, "canvas": 2,
    },
    "documentation": {
        "documentation": 3, "readme": 4, "api documentation": 4,
        "architecture diagram": 4, "technical report": 4, "translation": 3,
        "specification": 3, "writing": 2, "diagram": 2, "changelog": 3,
    },
    "agent-management": {
        "sub-agent": 4, "subagent": 4, "delegation": 4, "orchestration": 4,
        "multi-agent": 5, "task decomposition": 4, "conflict resolution": 3,
        "shared memory": 4, "mission": 2, "agent coordination": 4,
        "parallel execution": 3, "handoff": 3,
    },
    "mobile": {
        "ios": 4, "android": 4, "react native": 4, "flutter": 4, "swiftui": 4,
        "jetpack compose": 4, "mobile app": 3, "expo": 3,
    },
}

CATEGORY_AGENTS: dict[str, tuple[str, ...]] = {
    "software-engineering": ("architect", "backend", "frontend", "debugger"),
    "frontend": ("frontend", "designer"),
    "design": ("designer", "frontend"),
    "backend": ("backend", "database", "architect"),
    "devops": ("devops", "security"),
    "browser-automation": ("research", "qa"),
    "research": ("research", "architect"),
    "ai-ml": ("ai-research", "backend"),
    "security": ("security", "devops"),
    "qa": ("qa", "debugger"),
    "data": ("database", "ai-research"),
    "creative": ("designer",),
    "documentation": ("research", "architect"),
    "agent-management": ("architect", "orchestrator"),
    "mobile": ("frontend",),
    "uncategorized": (),
}

WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#./_-]*")


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in keyword.strip().split()]
    body = r"\s+".join(parts)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


@dataclass(frozen=True)
class RoleProfile:
    name: str
    categories: tuple[str, ...]
    keywords: tuple[str, ...] = ()
    max_skills: int = 12
    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    denied_tools: frozenset[str] = field(default_factory=frozenset)


_ALL_CATEGORIES = tuple(CATEGORIES)

ROLE_PROFILES: dict[str, RoleProfile] = {
    "architect": RoleProfile(
        "architect",
        ("software-engineering", "agent-management", "documentation", "backend", "data"),
        ("architecture", "system design", "planning", "repository", "monorepo", "trade-off"),
        14,
        frozenset({"read", "execute"}),
    ),
    "backend": RoleProfile(
        "backend",
        ("backend", "software-engineering", "security", "data"),
        ("api", "database", "auth", "server", "queue", "cache"),
        14,
        frozenset({"read", "write", "execute"}),
    ),
    "frontend": RoleProfile(
        "frontend",
        ("frontend", "design", "software-engineering", "creative", "qa"),
        ("react", "next", "component", "css", "accessibility", "state"),
        14,
        frozenset({"read", "write", "execute"}),
    ),
    "designer": RoleProfile(
        "designer",
        ("design", "frontend", "creative", "documentation"),
        ("ui", "ux", "typography", "palette", "wireframe", "prototype", "screenshot"),
        14,
        frozenset({"read", "write"}),
    ),
    "devops": RoleProfile(
        "devops",
        ("devops", "security", "backend", "qa"),
        ("docker", "kubernetes", "deploy", "ci", "cloud", "infrastructure", "monitoring"),
        14,
        frozenset({"read", "write", "execute"}),
        frozenset({"secrets.write"}),
    ),
    "database": RoleProfile(
        "database",
        ("data", "backend", "qa"),
        ("sql", "postgres", "migration", "schema", "redis", "data modeling"),
        12,
        frozenset({"read", "execute"}),
    ),
    "security": RoleProfile(
        "security",
        ("security", "devops", "backend"),
        ("audit", "threat", "vulnerability", "secret", "sandbox", "permission"),
        16,
        frozenset({"read", "execute"}),
        frozenset({"secrets.read", "secrets.write"}),
    ),
    "qa": RoleProfile(
        "qa",
        ("qa", "browser-automation", "software-engineering"),
        ("test", "regression", "coverage", "lint", "build", "e2e"),
        14,
        frozenset({"read", "write", "execute"}),
    ),
    "debugger": RoleProfile(
        "debugger",
        ("qa", "software-engineering", "devops"),
        ("debug", "failure", "trace", "logs", "reproduce", "regression"),
        12,
        frozenset({"read", "write", "execute"}),
    ),
    "performance": RoleProfile(
        "performance",
        ("qa", "frontend", "backend", "devops", "data"),
        ("performance", "benchmark", "latency", "profil", "load", "optimization"),
        12,
        frozenset({"read", "execute"}),
    ),
    "research": RoleProfile(
        "research",
        ("research", "browser-automation", "documentation"),
        ("research", "search", "crawl", "extract", "source", "documentation"),
        16,
        frozenset({"read", "network"}),
    ),
    "ai-research": RoleProfile(
        "ai-research",
        ("ai-ml", "data", "research", "agent-management"),
        ("llm", "rag", "embedding", "fine-tune", "eval", "transformer", "inference"),
        16,
        frozenset({"read", "execute"}),
    ),
    "documentation": RoleProfile(
        "documentation",
        ("documentation", "research", "design"),
        ("docs", "readme", "diagram", "spec", "translation", "report"),
        10,
        frozenset({"read", "write"}),
    ),
    "mobile": RoleProfile(
        "mobile",
        ("mobile", "frontend", "design", "qa"),
        ("ios", "android", "react native", "flutter", "swiftui", "expo"),
        12,
        frozenset({"read", "write", "execute"}),
    ),
}


def classify(name: str, description: str, body: str = "") -> tuple[str, list[str], dict[str, int]]:
    """Deterministic keyword classification; returns category, tags and raw scores."""
    corpus = f"{name} {description} {body}".lower()
    scores: dict[str, int] = {}
    for category, keywords in CATEGORIES.items():
        score = 0
        for keyword, weight in keywords.items():
            occurrences = len(_keyword_pattern(keyword).findall(corpus))
            if occurrences:
                score += weight * min(occurrences, 4)
        if score:
            scores[category] = score
    if not scores:
        return "uncategorized", [], {}
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best, best_score = ranked[0]
    tags = [category for category, score in ranked if score >= max(2, best_score // 3)][:5]
    return best, tags, scores


def keyword_tags(text: str, limit: int = 8) -> list[str]:
    lowered = text.lower()
    scores: dict[str, int] = {}
    for keywords in CATEGORIES.values():
        for keyword, weight in keywords.items():
            if _keyword_pattern(keyword).search(lowered):
                scores[keyword] = scores.get(keyword, 0) + weight
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [keyword.strip() for keyword, _ in ranked][:limit]


def agents_for_category(category: str) -> list[str]:
    return list(CATEGORY_AGENTS.get(category, ()))


def profile_for(role: str) -> RoleProfile:
    normalized = role.strip().lower()
    if normalized in ROLE_PROFILES:
        return ROLE_PROFILES[normalized]
    raise KeyError(f"unknown agent role: {role}")


def keywords_for_role(role: str) -> list[str]:
    return list(profile_for(role).keywords)
