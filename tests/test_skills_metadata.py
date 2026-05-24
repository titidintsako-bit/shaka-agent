from pathlib import Path

from shaka.skills import SkillsRegistry


def test_core_fileops_and_codeexec_expose_mutating_approval_metadata():
    registry = SkillsRegistry()
    core_dir = Path(__file__).resolve().parents[1] / "shaka" / "skills_core"
    registry.load_core_skills(str(core_dir), verbose=False)

    skills = {item["name"]: item for item in registry.list_skills()}

    for name in ["fileops", "codeexec"]:
        assert skills[name]["mutating"] is True
        assert skills[name]["read_only"] is False
        assert skills[name]["approval_required"] is True
        assert skills[name]["risk_level"] == "risky_write"
        assert skills[name]["risk"]["mutating"] is True
        assert skills[name]["risk"]["approval_required"] is True
