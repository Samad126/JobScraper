""".NET Backend, Java Backend, React Frontend...: a developer role together with its main technology.

How the technology is chosen (all local, no AI):
  1. from the job title, if it names one ("Java Backend Developer", ".NET Developer", "React Native Developer");
  2. otherwise, only when the post advertises a single job, from the post text: the technology family that is
     mentioned most (a main language repeated through the description beats one listed as a nice-to-have);
  3. otherwise "(technology not stated)". A post listing several jobs mixes their technologies, so for those only the
     title counts.

Edit BACKEND / FRONTEND / MOBILE below to add or rename families. Each entry is label -> [(technology from
stack.py, weight)]. JavaScript and TypeScript weigh less than a framework, because they are mentioned in many jobs
that are really about something else.
"""
from .stack import _COMPILED

_RX = dict(_COMPILED)

BACKEND = {
    ".NET": [(".NET", 1), ("C#", 1), ("Entity Framework", 1)],
    "Java": [("Java", 1), ("Spring", 1)],
    "Python": [("Python", 1), ("Django", 1), ("Flask", 1), ("FastAPI", 1)],
    "Node.js / JS": [("Node.js", 1), ("NestJS", 1), ("JavaScript", 0.4), ("TypeScript", 0.4)],
    "PHP": [("PHP", 1), ("Laravel", 1), ("Symfony", 1)],
    "Go": [("Go", 1)],
    "C++": [("C++", 1)],
    "Ruby": [("Ruby", 1)],
}
FRONTEND = {
    "React": [("React", 1), ("Next.js", 1)],
    "Angular": [("Angular", 1)],
    "Vue": [("Vue", 1)],
    "JavaScript": [("JavaScript", 0.4), ("TypeScript", 0.4), ("HTML/CSS", 0.2)],
}
MOBILE = {
    "Flutter": [("Flutter", 1), ("Dart", 1)],
    "React Native": [("React Native", 1)],
}

# role -> (word in the label, technology families that make sense for it, label when no technology is found).
# A "Software Developer" who works in Java, .NET, Python... is counted as a backend job of that technology.
FAMILIES = {
    "Backend Developer": ("Backend", BACKEND, "Backend (technology not stated)"),
    "Frontend Developer": ("Frontend", FRONTEND, "Frontend (technology not stated)"),
    "Full-Stack Developer": ("Full-Stack", {**BACKEND, **FRONTEND}, "Full-Stack (technology not stated)"),
    "Software Developer": ("Backend", BACKEND, "Developer (technology not stated)"),
    "Mobile Developer": ("Mobile", MOBILE, "Mobile (technology not stated)"),
}
# roles that already name their technology
SELF_LABELLED = ("Android Developer", "iOS Developer")


def _pick(text, families):
    """The family with the highest score in `text` (ties: whichever is mentioned first), or None.
    Technologies with weight below 1 (JavaScript, TypeScript, HTML/CSS) are only a fallback: together they can
    never outweigh a single mention of a real language or framework."""
    if not text:
        return None
    best, best_key = None, None
    for label, techs in families.items():
        strong, weak, first = 0.0, 0.0, None
        for name, weight in techs:
            rx = _RX.get(name)
            if rx is None:
                continue
            hits = [m.start() for m in rx.finditer(text)]
            if hits:
                if weight >= 1:
                    strong += weight * len(hits)
                else:
                    weak += weight * len(hits)
                first = hits[0] if first is None else min(first, hits[0])
        score = strong + min(weak, 0.9)
        if score > 0:
            key = (-score, first)
            if best_key is None or key < best_key:
                best, best_key = label, key
    return best


def specialization(role, title, text, jobs_in_post):
    """'.NET Backend', 'React Frontend', 'Backend (technology not stated)'... or None for roles that are not
    developer roles."""
    if role in SELF_LABELLED:
        return role
    family = FAMILIES.get(role)
    if not family:
        return None
    word, families, unstated = family
    best = _pick(title, families)
    if best is None and jobs_in_post == 1:
        best = _pick(text, families)
    return f"{best} {word}" if best else unstated
