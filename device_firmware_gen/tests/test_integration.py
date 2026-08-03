import os
import subprocess

import pytest
from device_firmware_gen import FirmwareGenerator
from register_mapper import Register, RegisterMapGenerator, Group


# ---------------------------------------------------------------------------
# Parametrize cases
# ---------------------------------------------------------------------------

def _cases(word_width):
    cases = []
    for reg_type in ("unsigned", "signed"):
        for rw in ("r", "w", "rw"):
            for bank_size in (1, 4):
                for width in (8, 16, 32, 64):
                    cases.append((reg_type, rw, bank_size, width, word_width))
    for reg_type in ("bool", "float", "double"):
        for rw in ("r", "w", "rw"):
            for bank_size in (1, 4):
                cases.append((reg_type, rw, bank_size, None, word_width))
    return cases


ALL_CASES = _cases(32) + _cases(8) + _cases(16)


def _make_rm(reg_type, rw, bank_size, width, word_width):
    name = f"{reg_type}_bk{bank_size}_w{word_width}_mod"
    rm = RegisterMapGenerator(name, [], word_width=word_width)
    kwargs = {"rw": rw, "type": reg_type, "bank_size": bank_size}
    if width is not None and reg_type not in ("bool", "float", "double"):
        kwargs["width"] = width
    rm.add(Register("val", **kwargs))
    rm.generate()
    return rm


def _case_id(case):
    reg_type, rw, bank_size, width, word_width = case
    w = width if width is not None else "auto"
    return f"{reg_type}-{rw}-bs{bank_size}-w{w}-ww{word_width}"


# ---------------------------------------------------------------------------
# Basic file creation
# ---------------------------------------------------------------------------

class TestFileCreation:
    CORE_SUFFIXES = [
        "reg_types.hpp",
        "reg_storage.hpp",
        "reg_storage.cpp",
        "reg_device.hpp",
        "reg_comm.hpp",
        "reg_comm.cpp",
    ]
    SHELL_SUFFIXES = [
        "reg_verify.cpp",
        "reg_host.cpp",
        "reg_doc.hpp",
        "reg_doc.cpp",
        "reg_meta.hpp",
        "reg_meta.cpp",
    ]
    SHELL_STATIC_FILES = [
        "reg_shell.hpp",
        "reg_shell.cpp",
        "reg_doc_types.hpp",
    ]

    def test_six_core_files_created(self, simple_rm, out_dir):
        FirmwareGenerator(simple_rm).generate(out_dir)
        assert len(os.listdir(out_dir)) == 6

    def test_correct_core_filenames(self, simple_rm, out_dir):
        FirmwareGenerator(simple_rm).generate(out_dir)
        files = set(os.listdir(out_dir))
        for suffix in self.CORE_SUFFIXES:
            assert suffix in files

    def test_shell_creates_fifteen_files(self, simple_rm, out_dir):
        FirmwareGenerator(simple_rm, interfaces="shell").generate(out_dir)
        assert len(os.listdir(out_dir)) == 15

    def test_shell_filenames(self, simple_rm, out_dir):
        FirmwareGenerator(simple_rm, interfaces="shell").generate(out_dir)
        files = set(os.listdir(out_dir))
        for suffix in self.CORE_SUFFIXES + self.SHELL_SUFFIXES:
            assert suffix in files
        for fname in self.SHELL_STATIC_FILES:
            assert fname in files

    def test_output_dir_created_if_missing(self, tmp_path):
        rm = RegisterMapGenerator("x_mod", [], word_width=32)
        rm.add(Register("r", rw="r", type="unsigned", width=8))
        rm.generate()
        new_dir = str(tmp_path / "new" / "subdir")
        FirmwareGenerator(rm).generate(new_dir)
        assert os.path.isdir(new_dir)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrors:
    def test_init_raises_if_not_generated(self):
        rm = RegisterMapGenerator("x_mod", [], word_width=32)
        rm.add(Register("r", rw="r", type="unsigned", width=8))
        # generate() not called
        with pytest.raises(ValueError, match="generate\\(\\)"):
            FirmwareGenerator(rm)


# ---------------------------------------------------------------------------
# Correctness
# ---------------------------------------------------------------------------

class TestCorrectness:
    def test_namespace_in_types_header(self, simple_rm, out_dir):
        FirmwareGenerator(simple_rm).generate(out_dir)
        path = os.path.join(out_dir, "reg_types.hpp")
        content = open(path, encoding="utf-8").read()
        assert "regs" in content

    def test_generate_from_json_smoke(self, json_rm, out_dir):
        FirmwareGenerator(json_rm).generate(out_dir)
        assert len(os.listdir(out_dir)) == 6

    def test_generate_idempotent(self, simple_rm, tmp_path):
        out1 = str(tmp_path / "out1")
        out2 = str(tmp_path / "out2")
        os.makedirs(out1)
        os.makedirs(out2)
        FirmwareGenerator(simple_rm).generate(out1)
        FirmwareGenerator(simple_rm).generate(out2)
        for fname in os.listdir(out1):
            c1 = open(os.path.join(out1, fname), encoding="utf-8").read()
            c2 = open(os.path.join(out2, fname), encoding="utf-8").read()
            assert c1 == c2, f"Mismatch in {fname}"

    def test_complex_map_generates(self, tmp_path):
        rm = RegisterMapGenerator("complex_mod", [], word_width=32)
        rm.add(Register("status", rw="r", type="unsigned", width=8,
                        enum={"IDLE": 0, "BUSY": 1}))
        rm.add(Register("ctrl", rw="w", type="unsigned", width=8, bank_size=4))
        rm.add(Register("big", rw="r", type="unsigned", width=64))
        rm.add(Register("f32", rw="r", type="float"))
        en = Register("en", rw="r", type="bool")
        lvl = Register("lvl", rw="r", type="unsigned", width=4)
        rm.add(Register("bf", rw="r", type="unsigned", width=8, bit_field=[en, lvl]))
        g = Group("periph", count=3)
        g.add(Register("val", rw="w", type="unsigned", width=16))
        rm.add(g)
        rm.generate()
        out = str(tmp_path / "out")
        os.makedirs(out)
        FirmwareGenerator(rm).generate(out)
        assert len(os.listdir(out)) == 6


# ---------------------------------------------------------------------------
# C++ compilation
# ---------------------------------------------------------------------------

def _compile(compiler, out_dir, tmp_path):
    storage = os.path.join(out_dir, "reg_storage.cpp")
    comm = os.path.join(out_dir, "reg_comm.cpp")
    result = subprocess.run(
        [compiler, "-std=c++17", "-c", "-I", out_dir, storage, comm],
        capture_output=True, text=True, cwd=str(tmp_path)
    )
    return result


class TestCompilation:
    def test_simple_rm_compiles(self, simple_rm, out_dir, compiler, tmp_path):
        FirmwareGenerator(simple_rm).generate(out_dir)
        r = _compile(compiler, out_dir, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_banked_rm_compiles(self, banked_rm, out_dir, compiler, tmp_path):
        FirmwareGenerator(banked_rm).generate(out_dir)
        r = _compile(compiler, out_dir, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_grouped_rm_compiles(self, grouped_rm, out_dir, compiler, tmp_path):
        FirmwareGenerator(grouped_rm).generate(out_dir)
        r = _compile(compiler, out_dir, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_multiword_rm_compiles(self, multiword_rm, out_dir, compiler, tmp_path):
        FirmwareGenerator(multiword_rm).generate(out_dir)
        r = _compile(compiler, out_dir, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_enum_rm_compiles(self, enum_rm, out_dir, compiler, tmp_path):
        FirmwareGenerator(enum_rm).generate(out_dir)
        r = _compile(compiler, out_dir, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_bitfield_rm_compiles(self, bitfield_rm, out_dir, compiler, tmp_path):
        FirmwareGenerator(bitfield_rm).generate(out_dir)
        r = _compile(compiler, out_dir, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_json_rm_compiles(self, json_rm, out_dir, compiler, tmp_path):
        FirmwareGenerator(json_rm).generate(out_dir)
        r = _compile(compiler, out_dir, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_min_access_rm_compiles(self, min_access_rm, out_dir, compiler, tmp_path):
        FirmwareGenerator(min_access_rm).generate(out_dir)
        r = _compile(compiler, out_dir, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_grouped_instance_methods_compile(self, grouped_rm, out_dir, compiler, tmp_path):
        FirmwareGenerator(grouped_rm).generate(out_dir)

        smoke = os.path.join(str(tmp_path), "instanced_group_methods_smoke.cpp")
        with open(smoke, "w", encoding="utf-8") as f:
            f.write(
                """
#include <cstdint>
#include "reg_storage.hpp"

int main() {
    regs::regs.periph[0].set_enable(true);
    bool e0 = regs::regs.periph[0].get_enable();
    regs::regs.periph[1].set_value(static_cast<uint16_t>(123));
    uint16_t v1 = regs::regs.periph[1].get_value();

    const auto& periph_const = regs::regs.periph;
    uint16_t v_const = periph_const[1].get_value();

    (void)e0;
    (void)v1;
    (void)v_const;
    return 0;
}
"""
            )

        storage = os.path.join(out_dir, "reg_storage.cpp")
        comm = os.path.join(out_dir, "reg_comm.cpp")
        binary = os.path.join(str(tmp_path), "instanced_group_methods_smoke")
        if os.name == "nt":
            binary += ".exe"

        result = subprocess.run(
            [compiler, "-std=c++17", "-I", out_dir, storage, comm, smoke, "-o", binary],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Exhaustive: generate without error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_CASES, ids=[_case_id(c) for c in ALL_CASES])
def test_parametrized_generate_no_error(case, tmp_path):
    reg_type, rw, bank_size, width, word_width = case
    rm = _make_rm(reg_type, rw, bank_size, width, word_width)
    out = str(tmp_path / "out")
    os.makedirs(out)
    FirmwareGenerator(rm).generate(out)
    assert len(os.listdir(out)) == 6


# ---------------------------------------------------------------------------
# Exhaustive: generate + compile
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_CASES, ids=[_case_id(c) for c in ALL_CASES])
def test_parametrized_compiles(case, tmp_path, compiler):
    reg_type, rw, bank_size, width, word_width = case
    rm = _make_rm(reg_type, rw, bank_size, width, word_width)
    out = str(tmp_path / "out")
    os.makedirs(out)
    gen = FirmwareGenerator(rm)
    gen.generate(out)
    r = _compile(compiler, out, tmp_path)
    assert r.returncode == 0, (
        f"Compilation failed for {_case_id(case)}:\n{r.stderr}"
    )
