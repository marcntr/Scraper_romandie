from dataclasses import dataclass, field


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    shortcode: str = ""
    department: str = ""
    posted_date: str = ""
    score: int = 0
    status: str = "matched"
    matched_keywords: set[str] = field(default_factory=set)
    deducted_keywords: set[str] = field(default_factory=set)
