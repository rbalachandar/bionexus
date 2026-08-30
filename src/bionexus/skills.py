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
