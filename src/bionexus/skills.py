"""Agent-skills integration (K-Dense scientific-agent-skills).

BioNexus agents are LLM + tools inside sandboxes. The Agent Skills standard
(agentskills.io) gives those agents domain knowledge — e.g. `opentrons-integration`
for protocol authoring, `rdkit` for cheminformatics, `database-lookup` for
ChEMBL/PubChem queries. This module pre-loads curated skills into an agent's
skill directory (local dir, sandbox rootfs template, etc.).

Division of labor: skills teach the agent *how*; BioNexus core decides
*whether* (SafetyEngine) and records *what happened* (provenance).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = "https://github.com/K-Dense-AI/scientific-agent-skills"

# Curated for BioNexus agent roles (name = skill dir in that repo)
RECOMMENDED_SKILLS: dict[str, list[str]] = {
    "design-agent": ["rdkit", "datamol", "medchem", "molfeat"],
    "target-agent": ["database-lookup", "paper-lookup", "biopython"],
    "assay-planning-agent": ["opentrons-integration", "pylabrobot",
                             "database-lookup"],
    "analysis-agent": ["scientific-visualization", "statsmodels", "scikit-learn"],
    "trial-agent": ["database-lookup", "paper-lookup"],
}


def install_skills(skills: list[str], dest: str | Path,
                   repo: str = REPO, ref: str = "main",
                   repo_path: str | Path | None = None) -> list[Path]:
    """Install selected skills from the scientific-agent-skills repo into `dest`.

    Copies from a local checkout when `repo_path` is given (offline/CI),
    otherwise performs a sparse clone. Returns installed skill dirs.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    if repo_path:
        src_root = Path(repo_path) / "skills"
        for name in skills:
            src = src_root / name
            if not src.is_dir():
                continue
            target = dest / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
            installed.append(target)
        return installed
    tmp = dest / f".clone-{abs(hash(repo)) % 10**8}"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, "--",
             repo, str(tmp)],
            check=True, capture_output=True)
        for name in skills:
            src = tmp / "skills" / name
            if src.is_dir():
                target = dest / name
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(src, target)
                installed.append(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return installed


def load_skill_instructions(skill_dir: str | Path) -> str:
    """Read a SKILL.md's body (frontmatter stripped) as agent instructions.
    Accepts either the skill directory or the SKILL.md file itself."""
    p = Path(skill_dir)
    if p.is_file() and p.name == "SKILL.md":
        p = p.parent
    text = (p / "SKILL.md").read_text()
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].strip()
    return text.strip()


# ------------------------------------------------------------- discovery

DEFAULT_SKILL_PATHS = [
    "~/.agents/skills",      # `npx skills add` convention (user-level)
    ".agents/skills",        # project-level
    "~/.claude/skills",      # Claude Code
    "skills",                # this repo / sandbox rootfs
]


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    try:
        import yaml
        return yaml.safe_load(text[3:end]) or {}
    except Exception:
        return {}


def discover_skills(paths: list[str | Path] | None = None,
                    include_repo: str = REPO) -> dict[str, dict[str, Any]]:
    """Discover installed Agent Skills across standard directories.

    Returns {name: {path, description, version, source}} — the index an agent
    (or the sandbox builder) consults to load guidance. BioNexus's own skills
    are always included; K-Dense scientific skills appear once installed via
    `npx skills add`, `gh skill install`, or `install_skills()`.
    """
    import os

    if paths is None:
        paths = DEFAULT_SKILL_PATHS
    index: dict[str, dict[str, Any]] = {}
    for base in paths:
        base = Path(os.path.expanduser(str(base)))
        if not base.is_dir():
            continue
        for skill_md in base.glob("*/SKILL.md"):
            fm = _parse_frontmatter(skill_md.read_text(errors="replace"))
            name = fm.get("name") or skill_md.parent.name
            index[name] = {
                "path": str(skill_md.parent),
                "description": fm.get("description", ""),
                "version": (fm.get("metadata") or {}).get("version", ""),
                "source": str(base),
            }
    # skills bundled with this package/repo
    own = Path(__file__).resolve().parent.parent / "skills"
    if own.is_dir():
        for skill_md in own.glob("*/SKILL.md"):
            fm = _parse_frontmatter(skill_md.read_text(errors="replace"))
            index.setdefault(fm.get("name") or skill_md.parent.name, {
                "path": str(skill_md.parent),
                "description": fm.get("description", ""),
                "version": (fm.get("metadata") or {}).get("version", ""),
                "source": "bionexus",
            })
    return index


def guidance_for(skill_name: str, paths: list[str | Path] | None = None) -> str:
    """Convenience: discovered skill -> instruction text for a prompt."""
    found = discover_skills(paths)
    if skill_name not in found:
        raise KeyError(f"skill '{skill_name}' not installed; "
                       f"available: {sorted(found)}")
    return load_skill_instructions(found[skill_name]["path"])


def recommend_for_role(role: str, paths: list[str | Path] | None = None,
                       auto_install: bool = False, dest: str | Path = ".agents/skills") -> list[dict[str, Any]]:
    """Skills RECOMMENDED_SKILLS says this role needs, that are actually
    discoverable. With auto_install, missing ones are pulled from the repo."""
    wanted = RECOMMENDED_SKILLS.get(role, [])
    if auto_install:
        missing = [w for w in wanted if w not in discover_skills(paths)]
        if missing:
            install_skills(missing, dest)
    found = discover_skills(paths)
    return [found[w] for w in wanted if w in found]
