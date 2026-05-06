# register_mapper

Defines the register map data model. Consumed by `device_firmware_gen` — no C++ generation here.

---

## Key classes (`register_mapper.py`)

| Class | Purpose |
|-------|---------|
| `Register` | Single register. Params: `name`, `rw` (`"r"/"w"/"rw"`), `type` (`"unsigned"/"signed"/"bool"/"float"/"double"`), `width` (bits), `bank_size`, `bit_field`, `enum` |
| `Group` | Named group of registers. Params: `name`, `count` (instances), optional `alignment` |
| `RegisterMapGenerator` | Root container. `RegisterMapGenerator(name, [], word_width=32)`. Call `.add()` then `.generate()` before use. |

## Important behaviors

- `word_width` must be 8, 16, or 32. All addresses are units of words.
- `bank_size > 1` creates an array of identical registers at consecutive addresses.
- `bit_field=[reg, ...]` packs sub-registers into one parent register's bits. Sub-register `rw` is validated against the parent's `rw`.
- `.generate()` must be called before passing the map to `FirmwareGenerator`.
- `RegisterMapGenerator.fromJSON(path)` loads from a JSON file.

## Test structure

| File | What it tests |
|------|--------------|
| `test_register.py` | `Register` validation, type/width/rw constraints |
| `test_group.py` | `Group` construction, alignment |
| `test_multiword.py` | Wide registers spanning multiple words |
| `test_register_map_generator.py` | Address assignment, `.generate()`, JSON round-trip |
