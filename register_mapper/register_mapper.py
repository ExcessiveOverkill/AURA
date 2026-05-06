from typing import Union
import traceback
import math

"""
Things to support:

- Configurable word size (8, 16, 32 bits. etc)
    - this will be the smallest addressable unit, all registers must be a multiple of this size
    - all addresses will be in terms of this word size, so if the word size is 32 bits, address 0x1 will actually be 0x4 in terms of bytes

- Register read/write:
    - Read & write
    - Read only
    - Write only

- Variable types and sizes:
    - unsigned integers: 1-n bits
    - signed integers: 1-n bits
    - bool: 1 bit
    - float: 32 bit (IEEE 754)
    - double: 64 bit (IEEE 754)
    - enum: 1-n bits, with a list of possible values and their meanings
    - min/max values for numeric types
    - default value for all types
    - units for numeric types (e.g. "mV", "°C", etc.)

- Single value registers:
    - fixed/auto start address
    - starting bit is always 0 (no bit offsets)
    - always takes up the entire word size (or multiple words for larger widths and banks)

- Bit field registers:
    - up to the register size in bits
    - fixed/auto start bit offset (inside the parent register)
    - same type options as single value registers
    - read/write permissions are inherited from the parent register
    - bit fields cannot be nested
    - bit fields cannot be banks or groups

- Register banks:
    Many registers with the same configuration, like an array. used to store many values of the same type
    - 1-65536 registers
    - consecutive addresses (unless register is multiple words, then they will be aligned to the next word boundary)
    - fixed/auto start address
    - single value or bit fields supported
    - compressed to a single entry in the register map
    - meant to be accessed with an index, like name[0], name[1], etc.

- Register groups:
    - multiple registers with different configurations
    - fixed/auto start address
    - fixed/auto address alignment
    - all packing types supported (single value, bit field, register banks, and register groups) (group nesting is allowed)

- Register map:
    - should contain an entry for every register, bit field, register bank, and register group specified

"""




"""
example functions:

a single register:
Register("name", type="unsigned", width=8, rw="r", start_address=0x0, desc="description")

bit field registers:
Register("name", rw="r", start_address=0x0, desc="description", bit_field=[     # type and width are not set in the main register
    Register("sub1", "unsigned", width=4),  # rw is inherited from the parent register
    Register("sub2", "unsigned", width=4, start_address=0x4),  # start_address is relative to the parent register and becomes the bit offset
])

register bank:
any register can be turned into a bank by specifying the bank size
Register("name", rw="r", start_address=0x0, desc="description", bank_size=4)
Register("name", rw="r", start_address=0x0, desc="description", bank_size=4, bit_field=[
    Register("sub1", "unsigned", width=4),
    Register("sub2", "unsigned", width=4, start_address=0x4),
])

register group:
g = Group("name", start_address=0x0, desc="description", alignment=4, count=4)  # group needs created before anything can be added to it

g.add(Register("name", "unsigned", width=8, rw="r", desc="description"), start_address=0x0)    # any of the above register types can be added to a group, start_address is relative to the group instance
g.add(Register("name", rw="r", desc="description", bit_field=[
    Register("sub1", "unsigned", width=4),
    Register("sub2", "unsigned", width=4, start_address=0x4),
]), start_address=0x4)
g.add(Register("name", rw="r", desc="description", bank_size=4))    # ommitted start_address will be auto-assigned

g.add(Group("name", desc="description", alignment=4, count=4), start_address=0x80)  # groups can be nested

groups without an allignment will have the smallest alignment automatically set (power of 2 for effecient address decoding)
if allignment is specified, the group will be padded to the specified alignment
allignment must be a power of 2


"""

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class Register:
    def __init__(self, name: str, rw: str="", type: str="unsigned", width: int=-1, start_address: int=-1, desc:str="", bank_size:int=1, bit_field:list=[], enum:dict={}, min_val=None, max_val=None, default_val=None, unit:str=""):
        """
        Initialize a Register object.
        Args:
            name (str): The name of the register.
            rw (str): Read/Write access type for the Host (device always has rw access), 'r' for read, 'w' for write, or 'rw' for read/write.
            type (str, optional): The data type of the register. Must be one of "unsigned", "signed", "float", "double", or "bool". Defaults to "unsigned".
            width (int, optional): The bit width of the register. -1 which will auto assign word size or size of the type. Defaults to -1.
            start_address (int, optional): The starting address of the register. Must be between -1 and 0xFFFF. -1 means auto-assign. Defaults to -1.
            desc (str, optional): A description of the register.
            bank_size (int, optional): The size of the register bank (contiguous array of registers). Must be between 1 and 65536. Defaults to 1.
            bit_field (list, optional): A list of registers (will turn into bit_fields/sub_registers).
        Raises:
            ValueError: If any of the provided arguments are invalid.
        """

        if type not in ["unsigned", "signed", "bool", "float", "double"]:
            raise ValueError("Invalid type")
        
        if width == -1:
            # set default widths for float, double, and bool types
            if type == "float":
                width = 32
            elif type == "double":
                width = 64
            elif type == "bool":
                width = 1
            else:
                width = -1  # will be set to the word size during generation if not specified
        else:
            if type == "float" and width != 32:
                raise ValueError("Float type must have width 32")
            elif type == "double" and width != 64:
                raise ValueError("Double type must have width 64")
            elif type == "bool" and width != 1:
                raise ValueError("Bool type must have width 1")
        
        if width < 1 and width != -1:
            raise ValueError("Invalid width")
        
        if (start_address < -1 or start_address > 0xFFFF):
            raise ValueError("Invalid start_address")
        
        if bank_size is not None and bank_size not in range(1, 0xFFFF+1):
            raise ValueError("Invalid bank_size")

        if rw != "" and rw not in ["r", "w", "rw"]:
            raise ValueError("Invalid rw")

        if not isinstance(unit, str):
            raise ValueError("Invalid unit")

        if not isinstance(enum, dict):
            raise ValueError("Invalid enum")

        if type != "unsigned" and enum:
            raise ValueError("Enum type must be unsigned")

        max_enum_value = 0
        for enum_name, enum_value in enum.items():
            if not isinstance(enum_name, str):
                raise ValueError("Invalid enum name")
            if not isinstance(enum_value, int) or enum_value < 0:
                raise ValueError("Invalid enum value")
            if enum_value > max_enum_value:
                max_enum_value = enum_value
            if enum_value < 0:
                raise ValueError("Enum values must be non-negative integers")

        if len(enum) > 0:
            if width != -1:
                if max_enum_value >= 2 ** width:    # user specified a width too small to hold the enum values
                    raise ValueError("Enum value exceeds register width")
            else:   # automatically set width to the minimum needed to hold the enum values
                width = max(1, math.ceil(math.log2(max_enum_value + 1)))
            
            # handle string enum values in min/max/default by converting them to their corresponding integer values
            if isinstance(min_val, str) and min_val in enum:
                min_val = enum[min_val]
            if isinstance(max_val, str) and max_val in enum:
                max_val = enum[max_val]
            if isinstance(default_val, str) and default_val in enum:
                default_val = enum[default_val]

        if min_val is not None and not self.__is_valid_type_value(type, min_val):
            raise ValueError("Invalid min value")

        if max_val is not None and not self.__is_valid_type_value(type, max_val):
            raise ValueError("Invalid max value")

        if default_val is not None and not self.__is_valid_type_value(type, default_val):
            raise ValueError("Invalid default value")

        if width != -1 and type in ["unsigned", "signed", "bool"]:  # will check again during generation when width is finalized, but if the width is already specified we can check the min/max/default values now
            min_allowed, max_allowed = self.__int_limits(type, width)

            if min_val is not None and (min_val < min_allowed or min_val > max_allowed):
                raise ValueError("min value out of range for register width")

            if max_val is not None and (max_val < min_allowed or max_val > max_allowed):
                raise ValueError("max value out of range for register width")

            if default_val is not None and (default_val < min_allowed or default_val > max_allowed):
                raise ValueError("default value out of range for register width")

        if min_val is not None and max_val is not None and min_val > max_val:
            raise ValueError("min value must be <= max value")

        if default_val is not None:
            if min_val is not None and default_val < min_val:
                raise ValueError("default value must be >= min value")
            if max_val is not None and default_val > max_val:
                raise ValueError("default value must be <= max value")
        
        for sub_register in bit_field:
            if not isinstance(sub_register, Register):
                raise ValueError("Invalid sub_register")
        
        self.name = name
        self.type = type
        self.width = width
        self.rw = rw
        self.start_address = start_address
        self.desc = desc
        self.bank_size = bank_size
        self.enum = enum
        self.min_val = min_val
        self.max_val = max_val
        self.default_val = default_val
        self.unit = unit

        self.map = {}

        # convert bit_field list to a dictionary for easy access
        self.bit_field = {}
        for sub_register in bit_field:
            self.bit_field[sub_register.name] = sub_register


        self.used_bits = []
        self.unassigned_regs = []

        self.used_addresses = []

        self.is_sub_register = False
        self.generated = False

    @staticmethod
    def __is_valid_type_value(type_name, value):
        if type_name in ["unsigned", "signed", "bool"]:
            return isinstance(value, int)
        if type_name in ["float", "double"]:
            return isinstance(value, (int, float))
        return False

    @staticmethod
    def __int_limits(type_name, width):
        if type_name == "unsigned":
            return 0, (2 ** width) - 1
        if type_name == "signed":
            return -(2 ** (width - 1)), (2 ** (width - 1)) - 1
        if type_name == "bool":
            return 0, 1
        return None, None


    def __gen(self, sub_register: 'Register', starting_bit: int):
        """
        INTERNAL\n
        Generate the register map for a sub-register.
        Args:
            sub_register (Register): The sub-register to generate the map for.
            starting_bit (int): The starting bit of the sub-register.
        """
            
        sub_register.rw = self.rw   # inherit rw from parent register
        sub_register.generate(self.word_width)
        sub_register.map["address_offset"] = self.map["address_offset"]  # inherit address_offset from parent register
        sub_register.map["starting_bit"] = starting_bit  # set starting_bit to the start_address of the sub-register

        #self.used_addresses = range(self.map["address_offset"], self.map["address_offset"] + self.bank_size)

        if not self.__bits_available(starting_bit, sub_register.width):
            raise ValueError("Invalid sub_register, bits are already in use")

        self.map["bit_field"][sub_register.name] = sub_register.map
        self.__use_bits(starting_bit, sub_register.width)

        print(f"{bcolors.OKGREEN}Register gen: Register '{sub_register.name}' has been placed at bits {starting_bit}:{starting_bit+sub_register.width-1} in Register '{self.name}'{bcolors.ENDC}")

    def generate(self, word_width: int = 8):
        """
        INTERNAL\n
        Generate the register map for the register.
        Args:
            word_width (int): The word width in bits. Registers spanning multiple words are padded so that words_per_register is a power of 2.
        """

        self.word_width = word_width

        if self.width == -1:
            self.width = word_width # default to word width if never specified

        if self.type in ["unsigned", "signed", "bool"]:
            min_allowed, max_allowed = self.__int_limits(self.type, self.width)

            if self.min_val is not None and (self.min_val < min_allowed or self.min_val > max_allowed):
                raise ValueError("min value out of range for register width")

            if self.max_val is not None and (self.max_val < min_allowed or self.max_val > max_allowed):
                raise ValueError("max value out of range for register width")

            if self.default_val is not None and (self.default_val < min_allowed or self.default_val > max_allowed):
                raise ValueError("default value out of range for register width")

        self.generated = False
        self.used_bits = []
        self.unassigned_regs = []

        # these values are not dependent on the sub-registers, so they can be set here
        # compute how many address words this register occupies, always a power of 2
        words_needed = math.ceil(self.width / word_width)
        if words_needed <= 1:
            self.words_per_register = 1
        else:
            self.words_per_register = 2 ** math.ceil(math.log2(words_needed))

        padded_bits = self.words_per_register * word_width
        if padded_bits > self.width and not self.is_sub_register:
            print(f"{bcolors.WARNING}Register gen: Register '{self.name}' width {self.width} padded to {padded_bits} bits ({self.words_per_register} words) to maintain power-of-2 alignment{bcolors.ENDC}")

        self.map["name"] = self.name
        self.map["address_offset"] = self.start_address
        self.map["type"] = self.type
        self.map["bank_size"] = self.bank_size
        self.map["description"] = self.desc
        self.map["width"] = self.width
        self.map["word_width"] = word_width
        self.map["words_per_register"] = self.words_per_register
        self.map["starting_bit"] = 0

        if self.start_address == -1:
            self.used_addresses = range(self.bank_size * self.words_per_register)
        else:
            self.used_addresses = range(self.start_address, self.start_address + self.bank_size * self.words_per_register)

        # empty bit_field dict to start
        self.map["bit_field"] = {}
        self.map["enum"] = self.enum
        self.map["min"] = self.min_val
        self.map["max"] = self.max_val
        self.map["default"] = self.default_val
        self.map["unit"] = self.unit

        if self.rw == "":
            raise ValueError("rw must be set for non-sub-registers")
        self.map["rw"] = self.rw

        if not self.bit_field:
            self.generated = True
            return
        

        # place sub-registers
        for sub_register in self.bit_field.values():

            sub_register.is_sub_register = True

            if len(sub_register.bit_field) > 0:
                raise ValueError("Sub-registers cannot have their own sub-registers")

            if sub_register.rw != "" and self.rw != "rw" and sub_register.rw != self.rw:
                raise ValueError("Sub-register rw must match parent register rw")
            
            if sub_register.bank_size != 1:
                raise ValueError("Sub-registers cannot be banks")

            if sub_register.start_address == -1:   # if start_address is not set, add to unassigned_regs list, it will be auto-assigned later
                self.unassigned_regs.append(sub_register)
                continue

            self.__gen(sub_register, sub_register.start_address)
            
        # auto-assign start_address for sub-registers
        for sub_register in self.unassigned_regs:
            success = False
            for starting_bit in range(0, self.words_per_register * word_width - sub_register.width + 1):
                if self.__bits_available(starting_bit, sub_register.width):
                    self.__gen(sub_register, starting_bit)
                    success = True
                    break

            if not success:
                raise ValueError(f"Unable to auto-assign start_address for sub-register: {sub_register}, space not available")
            

        # make sure parent width is large enough to hold all sub-registers
        if self.width < max(self.used_bits) + 1:
            #print(f"{bcolors.WARNING}Register gen: Parent register '{self.name}' width {self.width} is too small to hold all sub-registers, width will be increased to {max(self.used_bits) + 1}{bcolors.ENDC}")
            raise ValueError(f"Parent register '{self.name}' width {self.width} is too small to hold all sub-registers, increase the width to at least {max(self.used_bits) + 1} bits")
        self.generated = True


    def __bits_available(self, starting_bit, width):
        """
        INTERNAL\n
        Check if a range of bits is available.
        Args:
            starting_bit (int): The starting bit of the range.
            width (int): The width of the range.
            used_bits (list): A list of used bits.
        Returns:
            bool: True if the range is available, False otherwise.
        """

        for i in range(starting_bit, starting_bit + width):
            if i in self.used_bits:
                return False
        
        return True
    
    def __use_bits(self, starting_bit, width):
        """
        INTERNAL\n
        Mark a range of bits as used.
        Args:
            starting_bit (int): The starting bit of the range.
            width (int): The width of the range. 
             used_bits (list): A list of used bits.
        """

        self.used_bits.extend(range(starting_bit, starting_bit + width))

    def post_assign_address_offset(self, address_offset):
        """
        INTERNAL\n
        Assign a base address to the register and all sub-registers.
        Args:
            address_offset (int): The base address to assign.
        """

        if not self.generated:
            raise ValueError("Register map must be generated before assigning a base address")
        
        self.map["address_offset"] = address_offset
        for sub_register in self.bit_field.values():
            sub_register.map["address_offset"] = address_offset


        self.used_addresses = range(self.map["address_offset"], self.map["address_offset"] + self.bank_size * self.words_per_register)


    def __getattr__(self, name):

        # handle internal attributes
        if name == "address_offset":
            if not self.is_sub_register:
                return self.map["address_offset"]
            else:
                print(f"{bcolors.WARNING}Register gen: Register '{self.name}' is a sub-register, its address_offset will always be zero, use starting_bit if you want the bit offset\nTraceback:{traceback.walk_stack()[-2]}{bcolors.ENDC}")
                return 0
        
        if name == "starting_bit":
            if not self.is_sub_register:
                print(f"{bcolors.WARNING}Register gen: Register '{self.name}' is not a sub-register, its starting_bit will always be zero\nTraceback: {traceback.format_stack()[-2]}{bcolors.ENDC}")
                return 0
            else:
                return self.map["starting_bit"]
        elif name == "width":
            return self.map["width"]
        elif name == "bank_size":
            return self.map["bank_size"]
        elif name == "description":
            return self.map["description"]
        elif name == "min":
            return self.map["min"]
        elif name == "max":
            return self.map["max"]
        elif name == "default":
            return self.map["default"]
        elif name == "unit":
            return self.map["unit"]

        if name in self.bit_field:
            return self.bit_field[name]

        if name in self.map["enum"]:
            return self.map["enum"][name]
            
        raise AttributeError(f"Register gen: '{self.name}' map has no item '{name}', did you reference it from the correct containing object?\nTraceback: {traceback.format_stack()[-2]}")

    def __repr__(self) -> str:
        return f"Register(Name: {self.name}, rw: {self.rw}, type: {self.type}, width: {self.width}, address_offset: {self.start_address}, desc: {self.desc}, bank_size: {self.bank_size}, bit_field: {self.bit_field}, enum: {self.enum}, min: {self.min_val}, max: {self.max_val}, default: {self.default_val}, unit: {self.unit})"

    @classmethod
    def from_map(cls, map_data: dict, is_bit_field: bool = False):
        """
        Reconstruct a Register instance from an exported register-map dictionary.
        """

        required_keys = [
            "name", "address_offset", "type", "bank_size", "description", "width",
            "word_width", "words_per_register", "starting_bit", "rw", "bit_field"
        ]
        for key in required_keys:
            if key not in map_data:
                raise ValueError(f"Invalid register map, missing key '{key}'")

        if map_data["type"] not in ["unsigned", "signed", "bool", "float", "double"]:
            raise ValueError("Invalid register type")

        if map_data["rw"] not in ["", "r", "w", "rw"]:
            raise ValueError("Invalid register rw")

        if not isinstance(map_data["width"], int) or map_data["width"] < 1:
            raise ValueError("Invalid register width")

        if not isinstance(map_data["word_width"], int) or map_data["word_width"] < 1:
            raise ValueError("Invalid register word_width")

        if not isinstance(map_data["words_per_register"], int) or map_data["words_per_register"] < 1:
            raise ValueError("Invalid register words_per_register")

        if map_data["words_per_register"] & (map_data["words_per_register"] - 1) != 0:
            raise ValueError("Invalid register words_per_register, must be a power of 2")

        if not isinstance(map_data["bank_size"], int) or map_data["bank_size"] < 1:
            raise ValueError("Invalid register bank_size")

        if not isinstance(map_data["bit_field"], dict):
            raise ValueError("Invalid register bit_field")

        enum_data = map_data.get("enum", {})
        min_data = map_data.get("min", None)
        max_data = map_data.get("max", None)
        default_data = map_data.get("default", None)
        unit_data = map_data.get("unit", "")

        if not isinstance(enum_data, dict):
            raise ValueError("Invalid register enum")

        register = cls(
            map_data["name"],
            map_data["rw"],
            map_data["type"],
            map_data["width"],
            map_data["address_offset"],
            map_data["description"],
            map_data["bank_size"],
            [],
            enum_data,
            min_data,
            max_data,
            default_data,
            unit_data
        )

        register.map = {}
        register.map["name"] = map_data["name"]
        register.map["address_offset"] = map_data["address_offset"]
        register.map["type"] = map_data["type"]
        register.map["bank_size"] = map_data["bank_size"]
        register.map["description"] = map_data["description"]
        register.map["width"] = map_data["width"]
        register.map["word_width"] = map_data["word_width"]
        register.map["words_per_register"] = map_data["words_per_register"]
        register.map["starting_bit"] = map_data["starting_bit"]
        register.map["rw"] = map_data["rw"]
        register.map["bit_field"] = {}
        register.map["enum"] = enum_data
        register.map["min"] = min_data
        register.map["max"] = max_data
        register.map["default"] = default_data
        register.map["unit"] = unit_data

        register.word_width = map_data["word_width"]
        register.words_per_register = map_data["words_per_register"]
        register.is_sub_register = is_bit_field
        register.generated = True

        if register.start_address == -1:
            register.used_addresses = range(register.bank_size * register.words_per_register)
        else:
            register.used_addresses = range(register.start_address, register.start_address + register.bank_size * register.words_per_register)

        register.bit_field = {}
        for bit_field_name, bit_field_map in map_data["bit_field"].items():
            bit_field_reg = cls.from_map(bit_field_map, is_bit_field=True)
            register.bit_field[bit_field_name] = bit_field_reg
            register.map["bit_field"][bit_field_name] = bit_field_reg.map

        return register







class Group:
    def __init__(self, name: str, count:int=1, start_address: int=-1, desc:str="", alignment:int=-1):
        """
        Initialize a Group object.
        Args:
            name (str): The name of the group.
            count (int, optional): The number of instances of the group. Must be between 1 and 0xFFFF. Defaults to 1.
            start_address (int, optional): The starting address of the group. Must be between -1 and 0xFFFF. -1 means auto-assign. Defaults to -1.
            desc (str, optional): A description of the group.
            alignment (int, optional): The alignment of the group. Must be a power of 2. If not specified (default -1), the smallest alignment will be used automatically.
        Raises:
            ValueError: If any of the provided arguments are invalid
        """

        if (start_address < -1 or start_address > 0xFFFF):
            raise ValueError("Invalid start_address")
        
        if alignment != -1 and alignment & (alignment - 1) != 0:  # check if alignment is a power of 2
            raise ValueError("Invalid alignment")
        
        if count is not None and (count < 1 or count > 0xFFFF):
            raise ValueError("Invalid count")

        self.name = name
        self.start_address = start_address
        self.desc = desc
        self.alignment = alignment
        self.count = count

        self.contents = {}

        self.map = {}

        self.unassigned_items = []
        self.used_addresses = []

        self.generated = False


    def add(self, item: Union[Register, 'Group']):
        """
        Add a Register or Group to the Group.
        Args:
            item (Register or Group): The Register or Group to add.
        Raises:
            ValueError: If the provided item is invalid.
        """

        if self.generated:
            raise ValueError("Map is already generated, you may not add more items")

        if not isinstance(item, Register) and not isinstance(item, Group):
            raise ValueError("Invalid item")

        if item.name in self.contents:
            raise ValueError(f"Item name '{item.name}' already exists in the group '{self.name}'")
        
        self.contents[item.name] = item

    def get_address_offset(self):
        """
        Get the address offset of the group.
        Returns:
            int: The address offset of the group.
        """

        return self.map["address_offset"]
    
    def get_address_alignment(self):
        """
        Get the address alignment of the group.
        Returns:
            int: The address alignment of the group.
        """

        return self.alignment

    def generate(self, word_width: int = 32):
        """
        INTERNAL\n
        Generate the register map for the group.
        Args:
            word_width (int): The word width in bits, forwarded to all contained registers.
        """

        self.generated = False

        self.map = {}
        self.map["name"] = self.name
        self.map["address_offset"] = self.start_address
        self.map["description"] = self.desc
        self.map["alignment"] = self.alignment
        self.map["count"] = self.count
        self.map["groups"] = {}
        self.map["registers"] = {}

        # place items
        for name, item in self.contents.items():

            item.generate(word_width)

            if item.map["address_offset"] == -1:    # skip items without a fixed base address for now, they will be auto-assigned later
                self.unassigned_items.append(item)
                continue

            if not self.__addresses_available(item.used_addresses):
                raise ValueError(f"Invalid item '{item}', addresses are already in use")
            
            if isinstance(item, Register):
                self.map["registers"][name] = item.map
                print(f"{bcolors.OKGREEN}Register gen: Register '{item.name}' has been placed at offset 0x{item.map['address_offset']:X} in group '{self.name}'{bcolors.ENDC}")
            else:
                if self.alignment != -1 and item.start_address % self.alignment != 0:
                    raise ValueError(f"Invalid group address '{item}', start_address must be aligned to the group's alignment ({item.alignment})")
                self.map["groups"][name] = item.map

            

            self.__use_addresses(item.used_addresses)


        # auto-assign base addresses for items
        success = False
        for item in self.unassigned_items:
            if isinstance(item, Register):
                alignment = item.words_per_register
            else:
                alignment = item.alignment

            for starting_address in range(0, 0xFFFF - len(item.used_addresses) + 1, alignment):
                if self.__addresses_available(item.used_addresses, starting_address):
                    item.post_assign_address_offset(starting_address)
                    if isinstance(item, Register):
                        self.map["registers"][item.name] = item.map
                        print(f"{bcolors.OKGREEN}Register gen: Register '{item.name}' has been placed at offset 0x{item.map['address_offset']:X} in group '{self.name}'{bcolors.ENDC}")
                    else:
                        self.map["groups"][item.name] = item.map

                    self.__use_addresses(item.used_addresses)
                    
                    success = True
                    break

            if not success:
                raise ValueError(f"Unable to auto-assign base address for item: {item}")
            

        if self.alignment != -1 and len(self.used_addresses) > self.alignment:
            raise ValueError(f"Group '{self}' alignment is too small to hold requested items ({self.alignment} < {len(self.used_addresses)})")
        
        if self.alignment == -1:
            # find a power of 2 alignment that is large enough to hold the item
            self.alignment = 1

            while self.alignment < max(len(self.used_addresses), max(self.used_addresses)+1):                                                                                               
                self.alignment *= 2
            print(f"{bcolors.OKGREEN}Register gen: Group '{self.name}' alignment has been automatically set to 0x{self.alignment:X}{bcolors.ENDC}")
            self.map["alignment"] = self.alignment
            
        # groups use up their entire address space, regardless of what is inside
        if self.start_address == -1:
            self.used_addresses = list(range(0, self.alignment*self.count))
        else:
            self.used_addresses = list(range(self.start_address, self.start_address + self.alignment*self.count))


        self.generated = True

    def __use_addresses(self, addresses):
        """
        INTERNAL
        Mark a range of addresses as used.
        Args:
            addresses (list): A list of addresses to mark as used.
        """

        self.used_addresses.extend(addresses)

    def __addresses_available(self, addresses, offset=0):
        """
        INTERNAL
        Check if all addresses in a list are available.
        Args:
            addresses (list): A list of addresses to check.
        Returns:
            bool: True if the range is available, False otherwise.
        """

        for address in addresses:
            if address+offset in self.used_addresses:
                return False
        
        return True
    
    def post_assign_address_offset(self, address_offset):

        self.map["address_offset"] = address_offset
        for i in range(len(self.used_addresses)):
            self.used_addresses[i] = i + address_offset

    def __getattr__(self, name):

        # handle internal attributes
        if name == "offset":
            return self.map["address_offset"]
        elif name == "alignment":
            return self.map["alignment"]
        elif name == "count":
            return self.map["count"]
        elif name == "description":
            return self.map["description"]

        if name in self.contents:
            return self.contents[name]
            
        raise AttributeError(f"Register gen: '{self.name}' map has no item '{name}', did you reference it from the correct containing object?\nTraceback: {traceback.format_stack()[-2]}")
    
    def __repr__(self) -> str:
        return f"Group(Name: {self.name}, count: {self.count}, address_offset: {self.start_address}, desc: {self.desc}, alignment: {self.alignment}, contents: {self.contents})"

    @classmethod
    def from_map(cls, map_data: dict):
        """
        Reconstruct a Group instance from an exported group-map dictionary.
        """

        required_keys = ["name", "address_offset", "description", "alignment", "count", "groups", "registers"]
        for key in required_keys:
            if key not in map_data:
                raise ValueError(f"Invalid group map, missing key '{key}'")

        if map_data["alignment"] == -1 or not isinstance(map_data["alignment"], int) or map_data["alignment"] < 1:
            raise ValueError("Invalid group alignment")

        if map_data["alignment"] & (map_data["alignment"] - 1) != 0:
            raise ValueError("Invalid group alignment")

        if not isinstance(map_data["count"], int) or map_data["count"] < 1:
            raise ValueError("Invalid group count")

        if not isinstance(map_data["groups"], dict):
            raise ValueError("Invalid group groups")

        if not isinstance(map_data["registers"], dict):
            raise ValueError("Invalid group registers")

        group = cls(
            map_data["name"],
            map_data["count"],
            map_data["address_offset"],
            map_data["description"],
            map_data["alignment"]
        )

        group.contents = {}
        group.map = {}
        group.map["name"] = map_data["name"]
        group.map["address_offset"] = map_data["address_offset"]
        group.map["description"] = map_data["description"]
        group.map["alignment"] = map_data["alignment"]
        group.map["count"] = map_data["count"]
        group.map["groups"] = {}
        group.map["registers"] = {}

        for name, sub_group_map in map_data["groups"].items():
            sub_group = cls.from_map(sub_group_map)
            group.contents[name] = sub_group
            group.map["groups"][name] = sub_group.map

        for name, register_map in map_data["registers"].items():
            register = Register.from_map(register_map)
            group.contents[name] = register
            group.map["registers"][name] = register.map

        if group.start_address == -1:
            group.used_addresses = list(range(0, group.alignment * group.count))
        else:
            group.used_addresses = list(range(group.start_address, group.start_address + group.alignment * group.count))

        group.generated = True
        return group





class RegisterMapGenerator:
    def __init__(self, name: str, compatible_drivers: list, driver_settings: dict={}, desc: str="", word_width: int=8, min_access_words: int=1):
        """
        Handle all registers and information about a module
        Args:
            name (str): The name of the module.
            compatible_drivers (list): A list of compatible drivers.
            driver_settings (dict): A dictionary of driver settings.
            desc (str, optional): A description of the module.
            word_width (int, optional): The word width in bits — the smallest addressable unit. All addresses are in terms of this word size. Defaults to 32.
            min_access_words (int, optional): The minimum number of words the hardware can atomically read/write in one operation. Registers with words_per_register <= this value do not need atomic read/write buffers. Defaults to 1.
        """
        if word_width < 1:
            raise ValueError("Invalid word_width")
        if min_access_words < 1:
            raise ValueError("Invalid min_access_words")

        self.name = name
        self.compatible_drivers = compatible_drivers
        self.driver_settings = driver_settings
        self.desc = desc
        self.word_width = word_width
        self.min_access_words = min_access_words

        self.base_group = Group("base_group", 1, 0, "Base group for all registers", 0x10000)

        self.generated = False

        self.map = {}

    def add(self, item: Union[Register, Group]):
        """
        Add a Register or Group to the base group.
        Args:
            item (Register or Group): The Register or Group to add.
        Raises:
            ValueError: If the provided item is invalid.
        """

        if self.generated:
            raise ValueError("Map is already generated, you may not add more items")

        self.base_group.add(item)


    def generate(self):
        """
        Generate the register map
        the module may not be modified after this is called
        """

        

        if self.generated:
            raise ValueError("Map is already generated")
        
        self.map["name"] = self.name
        self.map["word_width"] = self.word_width
        self.map["min_access_words"] = self.min_access_words
        print(f"{bcolors.OKBLUE}Register gen: Creating register map for module '{self.name}' (word_width={self.word_width}, min_access_words={self.min_access_words}){bcolors.ENDC}")
        
        if self.compatible_drivers:
            print(f"{bcolors.OKGREEN}Register gen: Compatible drivers set to {self.compatible_drivers}{bcolors.ENDC}")
        else:
            print(f"{bcolors.WARNING}Register gen: No compatible drivers set, controller will not be able to automatically use this module!{bcolors.ENDC}")
        self.map["compatible_drivers"] = self.compatible_drivers

        for setting, value in self.driver_settings.items():
            print(f"{bcolors.OKGREEN}Register gen: Driver setting '{setting}' = {value} added to '{self.name}'{bcolors.ENDC}")
        self.map["driver_settings"] = self.driver_settings

        self.base_group.generate(self.word_width)

        self.map["base_group"] = self.base_group.map

        self.generated = True

        print(f"{bcolors.OKBLUE}Register gen: Done creating register map for module '{self.name}'{bcolors.ENDC}")

    def exportJSON(self, filename):
        """
        Export the register map to a JSON file.
        Args:
            filename (str): The name of the file to export to.
        """

        if not self.generated:
            raise ValueError("Map must be generated before exporting")

        import json

        with open(filename, 'w') as f:
            json.dump(self.map, f, indent=4)

    def export(self) -> dict:
        """
        Export the register map as a dictionary.
        Returns:
            dict: The register map.
        """

        if not self.generated:
            raise ValueError("Map must be generated before exporting")

        return self.map

    @classmethod
    def from_dict(cls, map_data: dict):
        """
        Reconstruct a RegisterMapGenerator instance from an exported map dictionary.
        """

        required_keys = ["name", "word_width", "compatible_drivers", "driver_settings", "base_group"]
        for key in required_keys:
            if key not in map_data:
                raise ValueError(f"Invalid register map, missing key '{key}'")

        if not isinstance(map_data["word_width"], int) or map_data["word_width"] < 1:
            raise ValueError("Invalid word_width")

        if not isinstance(map_data["compatible_drivers"], list):
            raise ValueError("Invalid compatible_drivers")

        if not isinstance(map_data["driver_settings"], dict):
            raise ValueError("Invalid driver_settings")

        if not isinstance(map_data["base_group"], dict):
            raise ValueError("Invalid base_group")

        min_access_words = map_data.get("min_access_words", 1)

        register_map = cls(
            map_data["name"],
            map_data["compatible_drivers"],
            map_data["driver_settings"],
            "",
            map_data["word_width"],
            min_access_words,
        )

        register_map.base_group = Group.from_map(map_data["base_group"])
        register_map.map = {}
        register_map.map["name"] = map_data["name"]
        register_map.map["word_width"] = map_data["word_width"]
        register_map.map["min_access_words"] = min_access_words
        register_map.map["compatible_drivers"] = map_data["compatible_drivers"]
        register_map.map["driver_settings"] = map_data["driver_settings"]
        register_map.map["base_group"] = register_map.base_group.map
        register_map.generated = True

        return register_map

    @classmethod
    def fromJSON(cls, filename):
        """
        Load a register map from a JSON file and reconstruct a RegisterMapGenerator instance.
        """

        import json

        with open(filename, 'r') as f:
            map_data = json.load(f)

        return cls.from_dict(map_data)

    def __getattr__(self, name):
        if name in self.base_group.contents:
            return self.base_group.contents[name]
            
        raise AttributeError(f"Register gen: '{self.name}' map has no item '{name}', did you reference it from the correct containing object?")


if __name__ == "__main__":
    

    field = Register("sub", type="unsigned", width=8, start_address=4)
    r = Register("reg", "r", width=8, bit_field=[field])
    r.generate()

    # word_width=32: each address slot is 32 bits wide
    rm = RegisterMapGenerator("module", ["driver1", "driver2"], {"setting1": 1, "setting2": 2}, "Module description", word_width=32)

    # --- existing 32-bit registers (unchanged behaviour) ---
    bit_fields = [
        Register("sub1", type="unsigned", width=4),
        Register("sub2", type="unsigned", width=4,)
    ]
    r = Register("name1", "r", "unsigned", 8, 0x0, "description", bit_field=bit_fields)
    rm.add(r)

    rm.add(Register("name2", "r", "unsigned"))
    rm.add(Register("name3", "r", "unsigned"))
    rm.add(Register("name4", "r", "unsigned", bank_size=4))
    rm.add(Register("name5", "r", "unsigned"))

    g = Group("group1", 4)
    g.add(Register("name6", "r", "unsigned"))
    g.add(Register("name7", "r", "unsigned", start_address=0x4))
    g.add(Register("name8", "r", "unsigned", bank_size=2))
    rm.add(g)

    # --- multi-word register examples ---
    # 64-bit register: needs 2 words (2 is a power of 2, no padding)
    rm.add(Register("wide64", "r", "unsigned", width=64))

    # 96-bit register: needs 3 words -> rounded up to 4 (power of 2), padded to 128 bits
    rm.add(Register("wide96", "r", "unsigned", width=96))

    # bank of 4 x 64-bit registers: each entry occupies 2 addresses, 8 total
    rm.add(Register("bank64", "r", "unsigned", width=64, bank_size=4))

    # 64-bit register with bit fields spanning the word boundary
    wide_bit_fields = [
        Register("lo", type="unsigned", width=20),   # bits 0-19
        Register("hi", type="unsigned", width=20),   # bits 20-39 (crosses 32-bit word boundary)
    ]
    rm.add(Register("wide_bf", "r", "unsigned", width=64, bit_field=wide_bit_fields))

    rm.generate()
    rm.exportJSON("test.json")

    print(f"name1.sub1.width = {rm.name1.sub1.width}")
    print(f"wide64 words_per_register = {rm.map['base_group']['registers']['wide64']['words_per_register']}")
    print(f"wide96 words_per_register = {rm.map['base_group']['registers']['wide96']['words_per_register']}")

