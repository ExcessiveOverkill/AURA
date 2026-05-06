import pytest
from cpp_writer import CppWriter


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Core primitives
# ---------------------------------------------------------------------------

class TestPrimitives:
    def test_line_writes_text(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.line("hello;")
        assert _read(f) == "hello;\n"

    def test_blank_writes_empty_line(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.blank()
        assert _read(f) == "\n"

    def test_line_no_arg_writes_blank(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.line()
        assert _read(f) == "\n"

    def test_raw_writes_verbatim_no_newline(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.raw("xyz")
        assert _read(f) == "xyz"

    def test_context_manager_creates_file(self, tmp_path):
        target = tmp_path / "new_file.hpp"
        assert not target.exists()
        with CppWriter(str(target)) as w:
            w.line("// ok")
        assert target.exists()


# ---------------------------------------------------------------------------
# Indentation
# ---------------------------------------------------------------------------

class TestIndent:
    def test_indent_adds_four_spaces(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.indent()
            w.line("a;")
        assert _read(f) == "    a;\n"

    def test_double_indent(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.indent()
            w.indent()
            w.line("deep;")
        assert _read(f) == "        deep;\n"

    def test_indented_context_manager_indents(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            with w.indented():
                w.line("inner;")
        assert _read(f) == "    inner;\n"

    def test_indented_context_manager_restores(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            with w.indented():
                w.line("inner;")
            w.line("outer;")
        lines = _read(f).splitlines()
        assert lines[0] == "    inner;"
        assert lines[1] == "outer;"

    def test_dedent_clamps_at_zero(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.dedent()
            w.dedent()
            w.line("x;")
        assert _read(f) == "x;\n"


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

class TestComments:
    def test_comment(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.comment("hello world")
        assert _read(f) == "// hello world\n"

    def test_block_comment_opens(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.block_comment(["line one", "line two"])
        content = _read(f)
        assert "/*\n" in content

    def test_block_comment_lines(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.block_comment(["line one", "line two"])
        content = _read(f)
        assert " * line one\n" in content
        assert " * line two\n" in content

    def test_block_comment_closes(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.block_comment(["x"])
        assert " */\n" in _read(f)

    def test_separator_with_title_length(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.separator("Section")
        line = _read(f).rstrip("\n")
        assert len(line) == 64  # "// --- " + title + " " + padding = 7+7+1+49

    def test_separator_no_title_is_dashes(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.separator()
        line = _read(f).rstrip("\n")
        assert line.startswith("// ")
        assert "-" * 10 in line

    def test_separator_no_title_length(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.separator()
        line = _read(f).rstrip("\n")
        assert len(line) == 68  # "// " + 65 dashes


# ---------------------------------------------------------------------------
# Boilerplate
# ---------------------------------------------------------------------------

class TestBoilerplate:
    def test_pragma_once(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.pragma_once()
        assert "#pragma once\n" in _read(f)

    def test_include_system(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.include("cstdint", system=True)
        assert "#include <cstdint>\n" in _read(f)

    def test_include_local(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.include("foo.hpp")
        assert '#include "foo.hpp"\n' in _read(f)

    def test_generated_header_do_not_edit(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.generated_header()
        assert "do not edit by hand" in _read(f)

    def test_generated_header_aura(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.generated_header()
        assert "AURA" in _read(f)

    def test_generated_header_with_description(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.generated_header("my description")
        assert "my description" in _read(f)


# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------

class TestNamespace:
    def test_namespace_open(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_namespace("my_ns")
            w.close_namespace("my_ns")
        assert "namespace my_ns {" in _read(f)

    def test_namespace_close_comment(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_namespace("my_ns")
            w.close_namespace("my_ns")
        assert "} // namespace my_ns" in _read(f)

    def test_namespace_indents_body(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_namespace("ns")
            w.line("int x;")
            w.close_namespace("ns")
        assert "    int x;\n" in _read(f)


# ---------------------------------------------------------------------------
# Structs
# ---------------------------------------------------------------------------

class TestStruct:
    def test_struct_open(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_struct("Foo_t")
            w.close_struct()
        assert "struct Foo_t {" in _read(f)

    def test_struct_close(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_struct("Foo_t")
            w.close_struct()
        assert "};" in _read(f)

    def test_struct_with_trailing(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_struct("Foo_t")
            w.close_struct(" instance")
        assert "} instance;" in _read(f)

    def test_struct_with_inherits(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_struct("Foo_t", inherits="Base_t")
            w.close_struct()
        assert "struct Foo_t : Base_t {" in _read(f)

    def test_struct_indents_body(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_struct("Foo_t")
            w.line("int x;")
            w.close_struct()
        assert "    int x;\n" in _read(f)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestEnum:
    def test_enum_class_default_underlying(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_enum_class("MyEnum")
            w.close_enum_class()
        assert "enum class MyEnum : uint8_t {" in _read(f)

    def test_enum_class_custom_underlying(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_enum_class("MyEnum", "uint32_t")
            w.close_enum_class()
        assert "enum class MyEnum : uint32_t {" in _read(f)

    def test_enum_value_has_comma(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_enum_class("E")
            w.enum_value("A", 0)
            w.close_enum_class()
        assert "A = 0," in _read(f)

    def test_enum_value_no_comma_on_last(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_enum_class("E")
            w.enum_value("A", 0, last=True)
            w.close_enum_class()
        content = _read(f)
        assert "A = 0," not in content
        assert "A = 0" in content

    def test_enum_value_with_comment(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_enum_class("E")
            w.enum_value("A", 1, comment="the value")
            w.close_enum_class()
        assert "// the value" in _read(f)

    def test_enum_close(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_enum_class("E")
            w.close_enum_class()
        assert "};" in _read(f)


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

class TestFunctions:
    def test_inline_function(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.inline_function("int get_x()", "return 42;")
        assert "inline int get_x() { return 42; }" in _read(f)

    def test_open_function_signature(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_function("void foo()")
            w.close_function()
        assert "void foo() {" in _read(f)

    def test_open_function_indents_body(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_function("void foo()")
            w.line("return;")
            w.close_function()
        assert "    return;\n" in _read(f)

    def test_close_function(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_function("void foo()")
            w.close_function()
        content = _read(f)
        assert content.endswith("}\n")


# ---------------------------------------------------------------------------
# Preprocessor
# ---------------------------------------------------------------------------

class TestPreprocessor:
    def test_open_ifdef(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_ifdef("MY_MACRO")
        assert "#ifdef MY_MACRO\n" in _read(f)

    def test_open_ifndef(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_ifndef("MY_MACRO")
        assert "#ifndef MY_MACRO\n" in _read(f)

    def test_pp_else(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.pp_else()
        assert "#else\n" in _read(f)

    def test_close_ifdef_with_name(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.close_ifdef("MY_MACRO")
        assert "#endif // MY_MACRO\n" in _read(f)

    def test_close_ifdef_no_name(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.close_ifdef()
        assert "#endif\n" in _read(f)

    def test_define_no_value(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.define("MY_FLAG")
        assert "#define MY_FLAG\n" in _read(f)

    def test_define_with_value(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.define("VERSION", "42")
        assert "#define VERSION 42\n" in _read(f)


# ---------------------------------------------------------------------------
# Generic braced blocks
# ---------------------------------------------------------------------------

class TestBrace:
    def test_open_brace_with_header(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_brace("if (x)")
            w.close_brace()
        assert "if (x) {" in _read(f)

    def test_open_brace_no_header(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_brace()
            w.close_brace()
        assert "{\n" in _read(f)

    def test_close_brace_with_suffix(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_brace()
            w.close_brace(" else {")
        assert "} else {\n" in _read(f)

    def test_brace_indents_body(self, tmp_path):
        f = str(tmp_path / "t.hpp")
        with CppWriter(f) as w:
            w.open_brace("if (x)")
            w.line("return;")
            w.close_brace()
        assert "    return;\n" in _read(f)
