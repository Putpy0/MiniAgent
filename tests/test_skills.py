"""Tests for skills installer, loader, and registry."""

import pytest

from miniagent.skills.installer import SkillInstaller
from miniagent.skills.loader import SkillInfo, SkillLoader
from miniagent.skills.registry import SkillRegistry


@pytest.fixture()
def installer(tmp_path):
    return SkillInstaller(skills_dir=str(tmp_path / "skills"))


class TestValidateBranch:
    @pytest.mark.parametrize("br", ["main", "feature/xyz-123", "a/b", "v1.0.2", "release_1"])
    def test_valid(self, installer, br):
        assert installer._validate_branch(br) is True

    @pytest.mark.parametrize(
        "br",
        [
            "-evil",       # option injection
            "", "   ",
            "..", ".",     # dot segments
            "a..b",        # range operator
            "./x", "x/./y",  # leading-dot components
            "end.",
            "name.lock",
            "x@{y",
            "HEAD:x",
            "a b", "x;y", "`x`",
        ],
    )
    def test_invalid(self, installer, br):
        assert installer._validate_branch(br) is False

    def test_branch_injection_rejected_before_subprocess(self, installer):
        ok, msg = installer.install(
            "https://github.com/example/repo.git", branch="--upload-pack=touch /tmp/pwned"
        )
        assert ok is False
        assert msg.startswith("Invalid branch name")


class TestCreateTemplateSkill:
    @pytest.fixture()
    def loader(self, tmp_path):
        ld = SkillLoader(str(tmp_path))
        tpl = tmp_path / "_template"
        tpl.mkdir()
        (tpl / "SKILL.md").write_text("---\nname: tpl\ndescription: t\n---\nbody")
        return ld

    @pytest.mark.parametrize("bad", ["../escapetest", "..\\evil", ".hidden", "sub/dir", "a..b", "x.lock", "end.", ""])
    def test_invalid_names_rejected(self, tmp_path, loader, bad):
        with pytest.raises(ValueError):
            loader.create_template_skill(bad)
        # nothing written outside the skills dir
        assert not list((tmp_path.parent).glob("escapetest"))

    def test_valid_name_creates_inside_skills_dir(self, loader, tmp_path):
        p = loader.create_template_skill("my_skill-1.0")
        assert (p / "SKILL.md").exists()
        assert p.resolve().relative_to(tmp_path.resolve())


class TestLoaderFrontmatter:
    def test_name_required(self, tmp_path):
        skill = tmp_path / "noskill"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\ndescription: x\n---\nbody")
        assert SkillLoader(str(tmp_path)).load_skill("noskill") is None

    def test_description_fallback(self, tmp_path):
        skill = tmp_path / "ok"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: ok\n---\nbody")
        info = SkillLoader(str(tmp_path)).load_skill("ok")
        assert info.name == "ok"
        assert info.description == "No description provided"


class TestRegistryScoring:
    def _registry_with(self, tmp_path, name, description, triggers):
        reg = SkillRegistry(skills_dir=str(tmp_path), auto_load=False)
        reg._skills[name] = SkillInfo(
            name=name, description=description, folder_path=str(tmp_path), triggers=triggers
        )
        return reg

    def test_word_overlap_finds_without_verbatim(self, tmp_path):
        reg = self._registry_with(
            tmp_path, "data-analisis", "membantu analisis data CSV dan Excel", ["analisis data"]
        )
        names = [s.name for s in reg.find_relevant_skills("tolong bantu analisis file excel saya")]
        assert names[0] == "data-analisis"

    def test_irrelevant_skill_hidden(self, tmp_path):
        reg = self._registry_with(tmp_path, "web-search", "mencari informasi di internet", ["cari web"])
        assert reg.find_relevant_skills("analisis file excel saya") == []

    def test_description_cap_vs_trigger_precision(self, tmp_path):
        """Documented behavior of the approved scoring design:

        A fully-overlapping description reaches the cap (3), which DOES
        outrank a single trigger hit (2). Only multiple trigger hits (>= 4)
        are guaranteed to outrank description-only matches.
        """
        reg = SkillRegistry(skills_dir=str(tmp_path), auto_load=False)
        reg._skills["desc-heavy"] = SkillInfo(
            name="desc-heavy",
            description="alpha beta gamma delta epsilon zeta",
            folder_path=str(tmp_path),
            triggers=[],
        )
        reg._skills["trigger-hit"] = SkillInfo(
            name="trigger-hit", description="unrelated words entirely", folder_path=str(tmp_path),
            triggers=["gamma"],
        )
        reg._skills["multi-trigger"] = SkillInfo(
            name="multi-trigger", description="unrelated words entirely", folder_path=str(tmp_path),
            triggers=["gamma", "zeta"],
        )

        # single trigger (2) loses to capped description overlap (3)
        ranked = reg.find_relevant_skills("alpha beta gamma delta epsilon")
        assert ranked[0].name == "desc-heavy"

        # two trigger hits (4) outrank any description-only skill (max 3)
        ranked2 = reg.find_relevant_skills("gamma zeta")
        assert ranked2[0].name == "multi-trigger"
