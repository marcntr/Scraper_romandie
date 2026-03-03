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
    matched_keywords: list[str] = field(default_factory=list)
    deducted_keywords: list[str] = field(default_factory=list)
