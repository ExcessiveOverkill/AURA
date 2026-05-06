import json
import pytest
from register_mapper import Register, Group, RegisterMapGenerator


# ---------------------------------------------------------------------------
# Init validation
# ---------------------------------------------------------------------------

class TestRMGInit:
    def test_word_width_zero_raises(self):
        with pytest.raises(ValueError, match="Invalid word_width"):
            RegisterMapGenerator("m", [], word_width=0)

    def test_word_width_negative_raises(self):
        with pytest.raises(ValueError, match="Invalid word_width"):
            RegisterMapGenerator("m", [], word_width=-8)

    def test_valid_construction(self):
        rm = RegisterMapGenerator("mod", ["drv1"], {"k": 1}, "desc", word_width=16)
        assert rm.name == "mod"
        assert rm.word_width == 16

    def test_min_access_words_default_is_one(self):
        rm = RegisterMapGenerator("m", [])
        assert rm.min_access_words == 1

    def test_min_access_words_stored(self):
        rm = RegisterMapGenerator("m", [], min_access_words=4)
        assert rm.min_access_words == 4

    def test_min_access_words_zero_raises(self):
        with pytest.raises(ValueError, match="Invalid min_access_words"):
            RegisterMapGenerator("m", [], min_access_words=0)

    def test_min_access_words_negative_raises(self):
        with pytest.raises(ValueError, match="Invalid min_access_words"):
            RegisterMapGenerator("m", [], min_access_words=-1)


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------

class TestRMGGenerate:
    def _make_simple_rm(self, word_width=32):
        rm = RegisterMapGenerator("mod", ["drv"], word_width=word_width)
        rm.add(Register("r1", "r", start_address=0x0))
        return rm

    def test_map_keys_present(self):
        rm = self._make_simple_rm()
        rm.generate()
        for key in ("name", "word_width", "min_access_words", "compatible_drivers", "driver_settings", "base_group"):
            assert key in rm.map, f"Missing key: {key}"

    def test_min_access_words_in_map(self):
        rm = RegisterMapGenerator("mod", [], min_access_words=4)
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        assert rm.map["min_access_words"] == 4

    def test_min_access_words_default_in_map(self):
        rm = self._make_simple_rm()
        rm.generate()
        assert rm.map["min_access_words"] == 1

    def test_word_width_in_map(self):
        rm = self._make_simple_rm(word_width=16)
        rm.generate()
        assert rm.map["word_width"] == 16

    def test_compatible_drivers_in_map(self):
        rm = RegisterMapGenerator("mod", ["drv1", "drv2"])
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        assert rm.map["compatible_drivers"] == ["drv1", "drv2"]

    def test_driver_settings_in_map(self):
        rm = RegisterMapGenerator("mod", [], {"baud": 9600})
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        assert rm.map["driver_settings"]["baud"] == 9600

    def test_double_generate_raises(self):
        rm = self._make_simple_rm()
        rm.generate()
        with pytest.raises(ValueError, match="already generated"):
            rm.generate()

    def test_add_after_generate_raises(self):
        rm = self._make_simple_rm()
        rm.generate()
        with pytest.raises(ValueError, match="already generated"):
            rm.add(Register("r2", "r"))

    def test_generated_flag(self):
        rm = self._make_simple_rm()
        rm.generate()
        assert rm.generated is True

    def test_registers_appear_in_base_group(self):
        rm = self._make_simple_rm()
        rm.generate()
        assert "r1" in rm.map["base_group"]["registers"]

    def test_groups_appear_in_base_group(self):
        rm = RegisterMapGenerator("mod", [])
        g = Group("grp", start_address=0x0, alignment=4)
        g.add(Register("r1", "r", start_address=0x0))
        rm.add(g)
        rm.generate()
        assert "grp" in rm.map["base_group"]["groups"]


# ---------------------------------------------------------------------------
# export()
# ---------------------------------------------------------------------------

class TestRMGExport:
    def test_export_returns_dict(self):
        rm = RegisterMapGenerator("mod", [])
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        result = rm.export()
        assert isinstance(result, dict)
        assert result is rm.map

    def test_export_before_generate_raises(self):
        rm = RegisterMapGenerator("mod", [])
        with pytest.raises(ValueError, match="generated"):
            rm.export()


# ---------------------------------------------------------------------------
# exportJSON()
# ---------------------------------------------------------------------------

class TestRMGExportJSON:
    def test_json_file_written(self, tmp_path):
        rm = RegisterMapGenerator("mod", [])
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        out = tmp_path / "out.json"
        rm.exportJSON(str(out))
        assert out.exists()

    def test_json_roundtrip(self, tmp_path):
        rm = RegisterMapGenerator("mod", ["d"], {"x": 42}, word_width=16)
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        out = tmp_path / "out.json"
        rm.exportJSON(str(out))
        with open(out) as f:
            loaded = json.load(f)
        assert loaded["name"] == "mod"
        assert loaded["word_width"] == 16
        assert loaded["driver_settings"]["x"] == 42
        assert "r1" in loaded["base_group"]["registers"]

    def test_export_json_before_generate_raises(self, tmp_path):
        rm = RegisterMapGenerator("mod", [])
        with pytest.raises(ValueError, match="generated"):
            rm.exportJSON(str(tmp_path / "out.json"))


# ---------------------------------------------------------------------------
# from_dict() / fromJSON()
# ---------------------------------------------------------------------------

class TestRMGImportJSON:
    def _make_complex_rm(self):
        rm = RegisterMapGenerator("mod", ["drv"], {"baud": 115200}, word_width=16)
        bit_fields = [
            Register("sub1", type="unsigned", width=4),
            Register("sub2", type="unsigned", width=4, start_address=4),
        ]
        rm.add(Register("r1", "r", width=16, start_address=0x0, bit_field=bit_fields, enum={"DISABLED": 0, "ENABLED": 1}, min_val=0, max_val=15, default_val=1, unit="state"))
        rm.add(Register("rf", "r", type="float", start_address=0x2, default_val=1.5, min_val=0.0, max_val=5.0, unit="V"))
        rm.add(Register("rd", "r", type="double", start_address=0x4, default_val=2.5, min_val=0.0, max_val=10.0, unit="A"))

        g = Group("g1", alignment=4)
        g.add(Register("gr1", "r", start_address=0x0))
        rm.add(g)

        rm.generate()
        return rm

    def test_from_json_roundtrip_restores_metadata(self, tmp_path):
        rm = self._make_complex_rm()
        out = tmp_path / "roundtrip.json"
        rm.exportJSON(str(out))

        loaded = RegisterMapGenerator.fromJSON(str(out))

        assert loaded.generated is True
        assert loaded.name == "mod"
        assert loaded.word_width == 16
        assert loaded.compatible_drivers == ["drv"]
        assert loaded.driver_settings["baud"] == 115200

    def test_from_json_register_attr_traversal(self, tmp_path):
        rm = self._make_complex_rm()
        out = tmp_path / "traversal.json"
        rm.exportJSON(str(out))

        loaded = RegisterMapGenerator.fromJSON(str(out))
        assert loaded.r1.width == 16

    def test_from_json_bit_field_attr_traversal(self, tmp_path):
        rm = self._make_complex_rm()
        out = tmp_path / "bitfield.json"
        rm.exportJSON(str(out))

        loaded = RegisterMapGenerator.fromJSON(str(out))
        assert loaded.r1.sub1.width == 4
        assert loaded.r1.sub2.starting_bit == 4

    def test_from_json_enum_attr_traversal(self, tmp_path):
        rm = self._make_complex_rm()
        out = tmp_path / "enum.json"
        rm.exportJSON(str(out))

        loaded = RegisterMapGenerator.fromJSON(str(out))
        assert loaded.r1.ENABLED == 1
        assert loaded.r1.DISABLED == 0

    def test_from_json_metadata_attr_traversal(self, tmp_path):
        rm = self._make_complex_rm()
        out = tmp_path / "meta.json"
        rm.exportJSON(str(out))

        loaded = RegisterMapGenerator.fromJSON(str(out))
        assert loaded.r1.min_val == 0
        assert loaded.r1.max_val == 15
        assert loaded.r1.default_val == 1
        assert loaded.r1.unit == "state"

    def test_from_json_float_double_types(self, tmp_path):
        rm = self._make_complex_rm()
        out = tmp_path / "float_double.json"
        rm.exportJSON(str(out))

        loaded = RegisterMapGenerator.fromJSON(str(out))
        assert loaded.rf.type == "float"
        assert loaded.rf.default_val == 1.5
        assert loaded.rd.type == "double"
        assert loaded.rd.default_val == 2.5

    def test_from_json_nested_group_attr_traversal(self, tmp_path):
        rm = self._make_complex_rm()
        out = tmp_path / "group.json"
        rm.exportJSON(str(out))

        loaded = RegisterMapGenerator.fromJSON(str(out))
        assert loaded.g1.gr1.width == rm.word_width

    def test_loaded_export_matches_original_map(self, tmp_path):
        rm = self._make_complex_rm()
        out = tmp_path / "match.json"
        rm.exportJSON(str(out))

        loaded = RegisterMapGenerator.fromJSON(str(out))
        assert loaded.export() == rm.export()

    def test_min_access_words_roundtrip(self, tmp_path):
        rm = RegisterMapGenerator("mod", [], min_access_words=4, word_width=8)
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        out = tmp_path / "maw.json"
        rm.exportJSON(str(out))

        loaded = RegisterMapGenerator.fromJSON(str(out))
        assert loaded.min_access_words == 4
        assert loaded.map["min_access_words"] == 4

    def test_min_access_words_defaults_to_one_when_missing(self):
        # JSON files created before this field was added should still load cleanly.
        rm = RegisterMapGenerator("mod", [], word_width=32)
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        map_data = rm.export().copy()
        del map_data["min_access_words"]

        loaded = RegisterMapGenerator.from_dict(map_data)
        assert loaded.min_access_words == 1

    def test_from_dict_missing_required_key_raises(self):
        with pytest.raises(ValueError, match="missing key 'base_group'"):
            RegisterMapGenerator.from_dict({
                "name": "mod",
                "word_width": 32,
                "compatible_drivers": [],
                "driver_settings": {},
            })

    def test_from_dict_invalid_word_width_raises(self):
        with pytest.raises(ValueError, match="Invalid word_width"):
            RegisterMapGenerator.from_dict({
                "name": "mod",
                "word_width": 0,
                "compatible_drivers": [],
                "driver_settings": {},
                "base_group": {},
            })

    def test_from_dict_invalid_register_words_per_register_raises(self):
        rm = self._make_complex_rm()
        map_data = json.loads(json.dumps(rm.export()))
        map_data["base_group"]["registers"]["r1"]["words_per_register"] = 3

        with pytest.raises(ValueError, match="words_per_register"):
            RegisterMapGenerator.from_dict(map_data)

    def test_from_dict_invalid_base_group_shape_raises(self):
        with pytest.raises(ValueError, match="missing key 'alignment'"):
            RegisterMapGenerator.from_dict({
                "name": "mod",
                "word_width": 32,
                "compatible_drivers": [],
                "driver_settings": {},
                "base_group": {
                    "name": "base_group",
                    "address_offset": 0,
                    "description": "",
                    "count": 1,
                    "groups": {},
                    "registers": {},
                },
            })


# ---------------------------------------------------------------------------
# __getattr__ traversal
# ---------------------------------------------------------------------------

class TestRMGGetattr:
    def test_access_register_by_name(self):
        rm = RegisterMapGenerator("mod", [])
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        # Should return the Register object, not raise
        assert rm.r1 is not None

    def test_access_sub_register_through_chain(self):
        field = Register("sub1", type="unsigned", width=4)
        r = Register("r1", "r", width=8, start_address=0x0, bit_field=[field])
        rm = RegisterMapGenerator("mod", [])
        rm.add(r)
        rm.generate()
        assert rm.r1.sub1.width == 4

    def test_unknown_attr_raises(self):
        rm = RegisterMapGenerator("mod", [])
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        with pytest.raises(AttributeError):
            _ = rm.nonexistent


# ---------------------------------------------------------------------------
# No compatible drivers warning
# ---------------------------------------------------------------------------

class TestRMGWarnings:
    def test_no_compatible_drivers_warns(self, capsys):
        rm = RegisterMapGenerator("mod", [])
        rm.add(Register("r1", "r", start_address=0x0))
        rm.generate()
        output = capsys.readouterr().out
        assert "No compatible drivers" in output
