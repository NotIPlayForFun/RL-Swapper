# Based on work by https://github.com/CrunchyRL/RLUPKTools and https://github.com/bitsfdb/VelocityRL

#!/usr/bin/env python3
import argparse
import base64
import concurrent.futures
import ctypes
import hashlib
import io
import os
import struct
import sys
import threading
import traceback
import zlib
from dataclasses import dataclass, field
import re
import zipfile
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Tuple

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PACKAGE_FILE_TAG = 0x9E2A83C1
COMPRESS_NONE = 0x00
COMPRESS_ZLIB = 0x01
PKG_COOKED = 0x00000008
DEFAULT_KEY = bytes([
    0xC7, 0xDF, 0x6B, 0x13, 0x25, 0x2A, 0xCC, 0x71,
    0x47, 0xBB, 0x51, 0xC9, 0x8A, 0xD7, 0xE3, 0x4B,
    0x7F, 0xE5, 0x00, 0xB7, 0x7F, 0xA5, 0xFA, 0xB2,
    0x93, 0xE2, 0xF2, 0x4E, 0x6B, 0x17, 0xE7, 0x79,
])
HEX_PREVIEW_LIMIT = 65536
COMPACT_INDEX_DEPRECATED = 178
NUMBER_ADDED_TO_NAME = 343
ENUM_NAME_ADDED_TO_BYTE_PROPERTY_TAG = 633
BOOL_VALUE_TO_BYTE_FOR_BOOL_PROPERTY_TAG = 673


class BinaryReader:
    def __init__(self, fh: BinaryIO):
        self.fh = fh

    def tell(self) -> int:
        return self.fh.tell()

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self.fh.seek(offset, whence)

    def read_exact(self, size: int) -> bytes:
        data = self.fh.read(size)
        if len(data) != size:
            raise EOFError(f"Expected {size} bytes, got {len(data)}")
        return data

    def read_i32(self) -> int:
        return struct.unpack("<i", self.read_exact(4))[0]

    def read_u32(self) -> int:
        return struct.unpack("<I", self.read_exact(4))[0]

    def read_u64(self) -> int:
        return struct.unpack("<Q", self.read_exact(8))[0]

    def read_u16(self) -> int:
        return struct.unpack("<H", self.read_exact(2))[0]

    def read_i64(self) -> int:
        return struct.unpack("<q", self.read_exact(8))[0]

    def read_u8(self) -> int:
        return struct.unpack("<B", self.read_exact(1))[0]

    def read_i8(self) -> int:
        return struct.unpack("<b", self.read_exact(1))[0]

    def read_f32(self) -> float:
        return struct.unpack("<f", self.read_exact(4))[0]

    def remaining(self) -> int:
        cur = self.tell()
        self.seek(0, os.SEEK_END)
        end = self.tell()
        self.seek(cur)
        return end - cur

    def read_fstring(self) -> str:
        length = self.read_i32()
        if length == 0:
            return ""
        if length < 0:
            char_count = -length
            raw = self.read_exact(char_count * 2)
            return raw[:-2].decode("utf-16-le", errors="ignore")
        raw = self.read_exact(length - 1)
        self.read_exact(1)
        # UE3 positive length strings are ANSI/Windows-1252, not UTF-8
        return raw.decode("windows-1252", errors="ignore")


@dataclass
class FNameRef:
    name_index: int
    instance_number: int


@dataclass
class NameEntry:
    index: int
    name: str
    flags: int


@dataclass
class ImportEntry:
    table_index: int
    class_package: FNameRef
    class_name: FNameRef
    outer_index: int
    object_name: FNameRef


@dataclass
class ExportEntry:
    table_index: int
    class_index: int
    super_index: int
    outer_index: int
    object_name: FNameRef
    archetype_index: int
    object_flags: int
    serial_size: int
    serial_offset: int
    export_flags: int
    net_objects: List[int]
    package_guid: Tuple[int, int, int, int]
    package_flags: int


@dataclass
class FCompressedChunk:
    uncompressed_offset: int
    uncompressed_size: int
    compressed_offset: int
    compressed_size: int


@dataclass
class FileSummary:
    tag: int = 0
    file_version: int = 0
    licensee_version: int = 0
    total_header_size: int = 0
    folder_name: str = ""
    package_flags_flags_offset: int = 0
    package_flags: int = 0
    name_count: int = 0
    name_offset: int = 0
    export_count: int = 0
    export_offset: int = 0
    import_count: int = 0
    import_offset: int = 0
    depends_offset: int = 0
    import_export_guids_offset: int = 0
    import_guids_count: int = 0
    export_guids_count: int = 0
    thumbnail_table_offset: int = 0
    guid: Tuple[int, int, int, int] = (0, 0, 0, 0)
    generations: List[Tuple[int, int, int]] = field(default_factory=list)
    engine_version: int = 0
    cooker_version: int = 0
    compression_flags_offset: int = 0
    compression_flags: int = 0
    compressed_chunks: List[FCompressedChunk] = field(default_factory=list)


@dataclass
class FileCompressionMetaData:
    garbage_size: int
    compressed_chunks_offset: int
    last_block_size: int


@dataclass
class ParsedPackage:
    file_path: Path
    summary: FileSummary
    names: List[NameEntry]
    imports: List[ImportEntry]
    exports: List[ExportEntry]
    file_bytes: bytes

    def object_data(self, export: ExportEntry) -> bytes:
        start = export.serial_offset
        end = start + export.serial_size
        if start < 0 or end < start or end > len(self.file_bytes):
            return b""
        return self.file_bytes[start:end]

    def resolve_name(self, ref: FNameRef) -> str:
        if 0 <= ref.name_index < len(self.names):
            base = self.names[ref.name_index].name
        else:
            base = f"<Name#{ref.name_index}>"
        return f"{base}_{ref.instance_number}" if ref.instance_number > 0 else base

    def resolve_object_ref(self, index: int) -> str:
        if index == 0:
            return "None"
        if index > 0:
            export_index = index - 1
            if 0 <= export_index < len(self.exports):
                exp = self.exports[export_index]
                return f"Export[{export_index}] {self.resolve_name(exp.object_name)}"
            return f"Export[{export_index}] <invalid>"
        import_index = -index - 1
        if 0 <= import_index < len(self.imports):
            imp = self.imports[import_index]
            return f"Import[{import_index}] {self.resolve_name(imp.object_name)}"
        return f"Import[{import_index}] <invalid>"

    def resolve_object_path(self, index: int, seen: Optional[set] = None) -> str:
        if index == 0:
            return "None"
        if seen is None:
            seen = set()
        if index in seen:
            return "<cycle>"
        seen.add(index)
        if index > 0:
            exp = self.exports[index - 1]
            name = self.resolve_name(exp.object_name)
            if exp.outer_index == 0:
                return name
            return f"{self.resolve_object_path(exp.outer_index, seen)}.{name}"
        imp = self.imports[-index - 1]
        name = self.resolve_name(imp.object_name)
        if imp.outer_index == 0:
            return name
        return f"{self.resolve_object_path(imp.outer_index, seen)}.{name}"

    def export_class_name(self, export: ExportEntry) -> str:
        if export.class_index == 0:
            return "Class"
        if export.class_index > 0:
            target = self.exports[export.class_index - 1]
            return self.resolve_name(target.object_name)
        target = self.imports[-export.class_index - 1]
        return self.resolve_name(target.object_name)

    def is_placeholder_export(self, export: ExportEntry) -> bool:
        # An export is a placeholder/garbage slot if its class is the meta
        # 'Class' (class_index == 0), its name resolves to literal 'None'
        # (name table index 0 in UE3), it has no outer, no serial body, and
        # no flags set. UE Explorer filters these out of its class list using
        # essentially the same predicate (ClassIndex == 0 && Name == 'None').
        # We additionally require zero size/offset/flags to avoid false
        # positives on rare native objects whose class index is 0.
        if export.class_index != 0:
            return False
        name = self.resolve_name(export.object_name)
        if name.lower() != "none":
            return False
        if export.outer_index != 0:
            return False
        if export.serial_size != 0 or export.serial_offset != 0:
            return False
        if export.object_flags != 0 or export.export_flags != 0:
            return False
        return True

    def resolve_export_class_candidates(self, export: ExportEntry) -> List[str]:
        raw = self.export_class_name(export)
        candidates = [raw]
        for prefix in ("A", "U", "F"):
            candidates.append(f"{prefix}{raw}")
        return candidates


@dataclass
class SDKField:
    name: str
    type_name: str
    offset: int
    size: int
    owner: str


@dataclass
class SDKType:
    name: str
    kind: str
    super_name: Optional[str]
    fields: List[SDKField] = field(default_factory=list)


@dataclass
class ParsedProperty:
    index: int
    name: str
    tag_type: str
    size: int
    array_index: int
    tag_offset: int
    value_offset: int
    value: str
    declared_type: str = "?"
    owner_type: str = "?"
    struct_name: Optional[str] = None
    enum_name: Optional[str] = None
    bool_value: Optional[bool] = None
    raw_hex: str = ""


class RLSDKDatabase:
    def __init__(self):
        self.types: Dict[str, SDKType] = {}

    def get_type(self, name: str) -> Optional[SDKType]:
        if name in self.types:
            return self.types[name]
        for candidate in (name, f"A{name}", f"U{name}", f"F{name}"):
            if candidate in self.types:
                return self.types[candidate]
        return None

    def resolve_field(self, owner_name: str, field_name: str) -> Tuple[Optional[SDKField], Optional[str]]:
        seen = set()
        cur = self.get_type(owner_name)
        while cur and cur.name not in seen:
            seen.add(cur.name)
            for field in cur.fields:
                if field.name == field_name:
                    return field, cur.name
            cur = self.get_type(cur.super_name) if cur.super_name else None
        return None, None


def parse_rlsdk_database(zip_path: Path) -> RLSDKDatabase:
    db = RLSDKDatabase()
    class_re = re.compile(r"//\s+(?:Class|ScriptStruct)\s+[^\n]+\n//[^\n]*\n(?:class|struct)\s+(\w+)(?:\s*:\s*public\s+(\w+))?\s*\{(.*?)\n\};", re.S)
    field_re = re.compile(r"^\s*(.+?)\s+(\w+)(?:\[[^\]]+\])?;\s*//\s*0x([0-9A-Fa-f]+)\s*\(0x([0-9A-Fa-f]+)\)", re.M)
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.endswith(("_classes.hpp", "_structs.hpp")):
                continue
            text = zf.read(name).decode("utf-8", errors="ignore")
            kind = "class" if name.endswith("_classes.hpp") else "struct"
            for m in class_re.finditer(text):
                type_name, super_name, body = m.groups()
                sdk_type = db.types.get(type_name)
                if sdk_type is None:
                    sdk_type = SDKType(name=type_name, kind=kind, super_name=super_name)
                    db.types[type_name] = sdk_type
                else:
                    sdk_type.kind = kind
                    sdk_type.super_name = super_name
                fields: List[SDKField] = []
                for fm in field_re.finditer(body):
                    type_name_raw, field_name, offset_hex, size_hex = fm.groups()
                    fields.append(SDKField(
                        name=field_name,
                        type_name=" ".join(type_name_raw.split()),
                        offset=int(offset_hex, 16),
                        size=int(size_hex, 16),
                        owner=type_name,
                    ))
                sdk_type.fields = fields
    return db


COMMON_STRUCT_DECODERS = {
    "FVector": lambda r: f"({r.read_f32():.6g}, {r.read_f32():.6g}, {r.read_f32():.6g})",
    "FVector2D": lambda r: f"({r.read_f32():.6g}, {r.read_f32():.6g})",
    "FRotator": lambda r: f"({r.read_i32()}, {r.read_i32()}, {r.read_i32()})",
    "FColor": lambda r: f"RGBA({r.read_u8()}, {r.read_u8()}, {r.read_u8()}, {r.read_u8()})",
    "FLinearColor": lambda r: f"({r.read_f32():.6g}, {r.read_f32():.6g}, {r.read_f32():.6g}, {r.read_f32():.6g})",
    "FQuat": lambda r: f"({r.read_f32():.6g}, {r.read_f32():.6g}, {r.read_f32():.6g}, {r.read_f32():.6g})",
    "FGuid": lambda r: f"{r.read_u32():08X}-{r.read_u32():08X}-{r.read_u32():08X}-{r.read_u32():08X}",
}


def parse_tarray_inner_type(type_name: str) -> Optional[str]:
    m = re.search(r"TArray<(.+)>", type_name)
    if not m:
        return None
    return " ".join(m.group(1).split())


def clean_cpp_type_name(type_name: str) -> str:
    t = type_name.replace("class ", "").replace("struct ", "").strip()
    return t.rstrip("*").strip()


def decode_name_ref(raw: bytes, package: ParsedPackage) -> str:
    if not raw:
        return ""
    bio = io.BytesIO(raw)
    r = BinaryReader(bio)
    ref = read_fname_pkg(r, package)
    return package.resolve_name(ref)


def decode_object_ref(raw: bytes, package: ParsedPackage) -> str:
    if not raw:
        return ""
    bio = io.BytesIO(raw)
    r = BinaryReader(bio)
    index = read_index_pkg(r, package)
    return f"{index} ({package.resolve_object_ref(index)})"


def decode_array_preview(raw: bytes, inner_type: Optional[str], package: ParsedPackage) -> str:
    if len(raw) < 4:
        return raw.hex(" ").upper()
    bio = io.BytesIO(raw)
    r = BinaryReader(bio)
    count = read_index_pkg(r, package)
    if count < 0:
        return f"count={count} (invalid)"
    if count == 0:
        return "count=0"
    if not inner_type:
        return f"count={count}, data={raw[4:36].hex(' ').upper()}"
    inner_clean = clean_cpp_type_name(inner_type)
    preview = []
    try:
        for _ in range(min(count, 4)):
            if inner_clean in ("int32_t", "INT", "DWORD") and r.remaining() >= 4:
                preview.append(str(r.read_i32()))
            elif inner_clean == "float" and r.remaining() >= 4:
                preview.append(f"{r.read_f32():.6g}")
            elif inner_clean in ("FName", "class FName") and r.remaining() >= 8:
                preview.append(package.resolve_name(read_fname_pkg(r, package)))
            elif inner_clean.startswith("U") and r.remaining() >= 4:
                preview.append(package.resolve_object_ref(read_index_pkg(r, package)))
            elif inner_clean in COMMON_STRUCT_DECODERS:
                preview.append(COMMON_STRUCT_DECODERS[inner_clean](r))
            else:
                break
    except Exception:
        pass
    if preview:
        return f"count={count}, preview=[{', '.join(preview)}]"
    return f"count={count}, data={raw[4:36].hex(' ').upper()}"


def decode_property_value(tag_type: str, raw: bytes, package: ParsedPackage, declared_type: str = "", struct_name: Optional[str] = None, enum_name: Optional[str] = None, bool_value: Optional[bool] = None) -> str:
    try:
        if tag_type == "BoolProperty":
            if bool_value is not None:
                return "True" if bool_value else "False"
            if raw:
                return "True" if raw[0] else "False"
            return "False"
        if tag_type == "IntProperty" and len(raw) >= 4:
            return str(struct.unpack("<i", raw[:4])[0])
        if tag_type == "FloatProperty" and len(raw) >= 4:
            return f"{struct.unpack('<f', raw[:4])[0]:.6g}"
        if tag_type in ("ObjectProperty", "ClassProperty", "ComponentProperty", "InterfaceProperty"):
            return decode_object_ref(raw, package)
        if tag_type == "NameProperty":
            return decode_name_ref(raw, package)
        if tag_type == "StrProperty":
            return BinaryReader(io.BytesIO(raw)).read_fstring()
        if tag_type == "ByteProperty":
            if enum_name and len(raw) >= 8:
                return decode_name_ref(raw, package)
            if raw:
                return str(raw[0])
        if tag_type == "StructProperty":
            if struct_name in COMMON_STRUCT_DECODERS:
                return COMMON_STRUCT_DECODERS[struct_name](BinaryReader(io.BytesIO(raw)))
            return f"{struct_name or '?'} ({len(raw)} bytes)"
        if tag_type == "ArrayProperty":
            return decode_array_preview(raw, parse_tarray_inner_type(declared_type), package)
        if tag_type == "QWordProperty" and len(raw) >= 8:
            return str(struct.unpack("<Q", raw[:8])[0])
        if tag_type == "StringRefProperty" and len(raw) >= 4:
            return str(struct.unpack("<I", raw[:4])[0])
        if tag_type == "DelegateProperty":
            if raw:
                rr = BinaryReader(io.BytesIO(raw))
                obj = read_index_pkg(rr, package)
                func = package.resolve_name(read_fname_pkg(rr, package))
                return f"obj={package.resolve_object_ref(obj)}, func={func}"
        if raw:
            return raw[:32].hex(" ").upper()
        return ""
    except Exception as exc:
        return f"<decode error: {exc}>"


VALID_PROPERTY_TYPES = {
    "ByteProperty", "IntProperty", "BoolProperty", "FloatProperty", "ObjectProperty",
    "NameProperty", "DelegateProperty", "ClassProperty", "ArrayProperty", "StructProperty",
    "VectorProperty", "RotatorProperty", "StrProperty", "MapProperty", "FixedArrayProperty",
    "InterfaceProperty", "ComponentProperty", "QWordProperty", "PointerProperty",
    "StringRefProperty", "BioMask4Property", "GuidProperty"
}


def _valid_name_ref(ref: FNameRef, package: ParsedPackage) -> bool:
    return 0 <= ref.name_index < len(package.names) and ref.instance_number >= -1


def _parse_property_tag_at(package: ParsedPackage, raw: bytes, offset: int, index: int) -> Tuple[Optional[ParsedProperty], int, bool]:
    if offset < 0 or offset + 8 > len(raw):
        return None, offset, False
    r = BinaryReader(io.BytesIO(raw))
    r.seek(offset)
    try:
        tag_offset = offset
        name_ref = read_fname_pkg(r, package)
        if not _valid_name_ref(name_ref, package):
            return None, offset, False
        name = package.resolve_name(name_ref)
        if name == "None":
            return None, r.tell(), True

        type_ref = read_fname_pkg(r, package)
        if not _valid_name_ref(type_ref, package):
            return None, offset, False
        tag_type = package.resolve_name(type_ref)
        if tag_type not in VALID_PROPERTY_TYPES:
            return None, offset, False

        size = r.read_i32()
        array_index = r.read_i32()
        if size < 0 or array_index < 0:
            return None, offset, False

        struct_name = None
        enum_name = None
        bool_value = None
        declared_type = "?"

        if tag_type == "StructProperty":
            sref = read_fname_pkg(r, package)
            if not _valid_name_ref(sref, package):
                return None, offset, False
            struct_name = package.resolve_name(sref)
            declared_type = struct_name
        elif tag_type == "ByteProperty":
            if package.summary.file_version >= ENUM_NAME_ADDED_TO_BYTE_PROPERTY_TAG:
                eref = read_fname_pkg(r, package)
                if not _valid_name_ref(eref, package):
                    return None, offset, False
                enum_name = package.resolve_name(eref)
                declared_type = enum_name or "Byte"
            else:
                declared_type = "Byte"
        elif tag_type == "ArrayProperty":
            declared_type = "TArray"
        elif tag_type == "BoolProperty":
            if package.summary.file_version >= BOOL_VALUE_TO_BYTE_FOR_BOOL_PROPERTY_TAG:
                bool_value = bool(r.read_u8())
            declared_type = "bool"
        else:
            declared_type = {
                "IntProperty": "int",
                "FloatProperty": "float",
                "ObjectProperty": "UObject*",
                "ClassProperty": "UClass*",
                "ComponentProperty": "UObject*",
                "InterfaceProperty": "UObject*",
                "NameProperty": "FName",
                "StrProperty": "FString",
                "DelegateProperty": "FScriptDelegate",
                "QWordProperty": "uint64",
                "PointerProperty": "pointer",
                "StringRefProperty": "uint32",
                "MapProperty": "TMap",
                "FixedArrayProperty": "array",
                "GuidProperty": "FGuid",
                "BioMask4Property": "BioMask4",
            }.get(tag_type, tag_type)

        value_offset = r.tell()
        if value_offset + size > len(raw):
            return None, offset, False
        value_raw = raw[value_offset:value_offset + size]
        value = decode_property_value(tag_type, value_raw, package, declared_type, struct_name, enum_name, bool_value)
        prop = ParsedProperty(
            index=index,
            name=name,
            tag_type=tag_type,
            size=size,
            array_index=array_index,
            tag_offset=tag_offset,
            value_offset=value_offset,
            value=value,
            declared_type=declared_type,
            owner_type="SerializedTag",
            struct_name=struct_name,
            enum_name=enum_name,
            bool_value=bool_value,
            raw_hex=value_raw[:64].hex(" ").upper(),
        )
        return prop, value_offset + size, False
    except Exception:
        return None, offset, False


def _try_parse_property_stream(package: ParsedPackage, raw: bytes, start_offset: int) -> Tuple[int, List[ParsedProperty], bool]:
    props: List[ParsedProperty] = []
    offset = start_offset
    seen = set()
    ended = False
    for i in range(4096):
        if offset in seen:
            break
        seen.add(offset)
        prop, next_offset, hit_end = _parse_property_tag_at(package, raw, offset, i)
        if hit_end:
            ended = True
            offset = next_offset
            break
        if prop is None:
            break
        props.append(prop)
        offset = next_offset
    return offset, props, ended


def _find_best_property_stream_offset(package: ParsedPackage, raw: bytes, class_type: Optional[SDKType] = None, sdk_db: Optional[RLSDKDatabase] = None) -> Tuple[int, List[ParsedProperty]]:
    del class_type, sdk_db
    if len(raw) < 24:
        return 0, []

    best_offset = 0
    best_props: List[ParsedProperty] = []
    best_score = -1
    max_scan = max(0, len(raw) - 24)
    for start in range(max_scan + 1):
        name_index = struct.unpack_from('<i', raw, start)[0]
        if not (0 <= name_index < len(package.names)):
            continue
        end_off, props, ended = _try_parse_property_stream(package, raw, start)
        if not props:
            continue
        score = len(props) * 1000
        if ended:
            score += 250
        score += min(end_off - start, 512)
        score -= start
        if score > best_score:
            best_score = score
            best_offset = start
            best_props = props
    return best_offset, best_props


class DecryptionProvider:
    def __init__(self, key_file_path: Optional[str] = None):
        if key_file_path is None:
            self.decryption_keys = [DEFAULT_KEY]
        else:
            if not os.path.exists(key_file_path):
                raise FileNotFoundError(f"Failed to load the key file: {key_file_path}")
            with open(key_file_path, "r", encoding="utf-8") as fh:
                self.decryption_keys = [
                    base64.b64decode(line.strip())
                    for line in fh
                    if line.strip()
                ]

    @staticmethod
    def decrypt_ecb(key: bytes, data: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()
        return decryptor.update(data) + decryptor.finalize()

    @staticmethod
    def encrypt_ecb(key: bytes, data: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        encryptor = cipher.encryptor()
        return encryptor.update(data) + encryptor.finalize()


def find_valid_key(encrypted_path: Path, provider: DecryptionProvider) -> Tuple[FileSummary, FileCompressionMetaData, bytes, bytes]:
    with encrypted_path.open("rb") as src:
        summary = parse_file_summary(src)
        meta = parse_file_compression_metadata(src)
        encrypted_size = summary.total_header_size - meta.garbage_size - summary.name_offset
        if encrypted_size < 0:
            raise ValueError(
                f"Computed encrypted region size is negative ({encrypted_size}). "
                f"summary.total_header_size={summary.total_header_size}, "
                f"meta.garbage_size={meta.garbage_size}, "
                f"summary.name_offset={summary.name_offset}. "
                f"This usually indicates a corrupted or already-edited package header."
            )
        encrypted_size = (encrypted_size + 15) & ~15
        src.seek(summary.name_offset)
        encrypted_data = src.read(encrypted_size)
        if len(encrypted_data) != encrypted_size:
            raise ValueError(
                f"Failed to read encrypted region: expected {encrypted_size} bytes "
                f"at offset {summary.name_offset}, got {len(encrypted_data)} (file truncated?)"
            )
    for key in provider.decryption_keys:
        if verify_decryptor(summary, meta, key, encrypted_data):
            return summary, meta, encrypted_data, key
    raise ValueError("Unknown Decryption key")


def serialize_rl_chunk_table(chunks: List[FCompressedChunk]) -> bytes:
    out = bytearray()
    out += struct.pack("<i", len(chunks))
    for chunk in chunks:
        out += struct.pack("<q", chunk.uncompressed_offset)
        out += struct.pack("<i", chunk.uncompressed_size)
        out += struct.pack("<q", chunk.compressed_offset)
        out += struct.pack("<i", chunk.compressed_size)
    return bytes(out)


def compress_chunk_payload(uncompressed: bytes, block_size: int = 0x20000, level: int = 6) -> bytes:
    out = bytearray()
    out += struct.pack("<I", PACKAGE_FILE_TAG)
    out += struct.pack("<i", block_size)
    blocks = []
    total_compressed = 0
    for i in range(0, len(uncompressed), block_size):
        piece = uncompressed[i:i + block_size]
        comp = zlib.compress(piece, level)
        blocks.append((comp, len(piece)))
        total_compressed += len(comp)
    out += struct.pack("<ii", total_compressed, len(uncompressed))
    for comp, uncomp_size in blocks:
        out += struct.pack("<ii", len(comp), uncomp_size)
    for comp, _ in blocks:
        out += comp
    return bytes(out)


def _find_file_compression_metadata_offsets(stream: BinaryIO) -> Dict[str, int]:
    parse_file_summary(stream)
    meta_offset = stream.tell()
    r = BinaryReader(stream)
    garbage_size_offset = meta_offset
    r.read_i32()
    compressed_chunks_offset_offset = stream.tell()
    r.read_i32()
    last_block_size_offset = stream.tell()
    r.read_i32()
    return {
        "meta_offset": meta_offset,
        "garbage_size_offset": garbage_size_offset,
        "compressed_chunks_offset_offset": compressed_chunks_offset_offset,
        "last_block_size_offset": last_block_size_offset,
    }


def find_key_for_encrypted_upk(encrypted_path: Path, provider: DecryptionProvider) -> bytes:
    """Return the first key from *provider* that successfully decrypts *encrypted_path*.

    Raises ValueError if no key in the provider works.
    """
    _, _, _, key = find_valid_key(encrypted_path, provider)
    return key


def build_reencrypted_package(original_encrypted_path: Path, modified_decrypted_bytes: bytes, provider: DecryptionProvider, output_path: Path, *, override_key: Optional[bytes] = None) -> Path:
    summary, meta, original_encrypted_data, valid_key = find_valid_key(original_encrypted_path, provider)
    # If the caller wants to encrypt with a different key (e.g. sourced from a
    # donor encrypted UPK), use that key for the output instead of the key that
    # was used to decrypt the original package.
    if override_key is not None:
        valid_key = override_key
    modified_summary = parse_file_summary(io.BytesIO(modified_decrypted_bytes))
    original_plain = bytearray(DecryptionProvider.decrypt_ecb(valid_key, original_encrypted_data))
    original_chunks = parse_rl_compressed_chunks(bytes(original_plain), meta.compressed_chunks_offset)
    if not original_chunks:
        raise ValueError("No compressed chunks were found in original encrypted header")

    new_chunk_table_offset = modified_summary.depends_offset - modified_summary.name_offset
    patch_limit = max(0, new_chunk_table_offset)
    chunk_shift = modified_summary.depends_offset - original_chunks[0].uncompressed_offset

    rebuilt_chunks: List[FCompressedChunk] = []
    rebuilt_chunk_payloads: List[bytes] = []
    chunk_table_placeholder = serialize_rl_chunk_table([
        FCompressedChunk(0, 0, 0, 0) for _ in original_chunks
    ])
    required_plain_len = new_chunk_table_offset + len(chunk_table_placeholder)
    encrypted_plain_len = (required_plain_len + 15) & ~15
    header_plain = bytearray(encrypted_plain_len)
    copy_len = min(len(original_plain), encrypted_plain_len)
    header_plain[:copy_len] = original_plain[:copy_len]

    new_total_header_size = modified_summary.name_offset + encrypted_plain_len + meta.garbage_size
    current_compressed_offset = new_total_header_size
    for i, chunk in enumerate(original_chunks):
        start = chunk.uncompressed_offset + chunk_shift
        if i + 1 < len(original_chunks):
            end = original_chunks[i + 1].uncompressed_offset + chunk_shift
            if end > len(modified_decrypted_bytes):
                raise ValueError("Modified decrypted package changed size too early for the rebuilt chunk layout")
        else:
            end = len(modified_decrypted_bytes)
        if end < start:
            raise ValueError("Invalid rebuilt chunk bounds")
        payload = compress_chunk_payload(modified_decrypted_bytes[start:end])
        rebuilt_chunk_payloads.append(payload)
        rebuilt_chunks.append(FCompressedChunk(
            uncompressed_offset=start,
            uncompressed_size=end - start,
            compressed_offset=current_compressed_offset,
            compressed_size=len(payload),
        ))
        current_compressed_offset += len(payload)

    if patch_limit > len(header_plain):
        raise ValueError("Modified decrypted header exceeds encrypted header capacity")
    if patch_limit > 0:
        header_plain[:patch_limit] = modified_decrypted_bytes[summary.name_offset:modified_summary.depends_offset]

    chunk_table = serialize_rl_chunk_table(rebuilt_chunks)
    table_end = new_chunk_table_offset + len(chunk_table)
    if table_end > len(header_plain):
        raise ValueError("Rebuilt compressed chunk table does not fit inside encrypted header")
    header_plain[new_chunk_table_offset:table_end] = chunk_table
    encrypted_header = DecryptionProvider.encrypt_ecb(valid_key, bytes(header_plain))

    original_bytes = Path(original_encrypted_path).read_bytes()
    prefix = bytearray(original_bytes[:summary.name_offset])
    summary_offsets = _find_summary_offsets(modified_decrypted_bytes)
    patch_i32_le(prefix, summary_offsets["total_header_size_offset"], new_total_header_size)
    patch_i32_le(prefix, summary_offsets["name_count_offset"], modified_summary.name_count)
    patch_i32_le(prefix, summary_offsets["name_offset_offset"], modified_summary.name_offset)
    patch_i32_le(prefix, summary_offsets["export_count_offset"], modified_summary.export_count)
    patch_i32_le(prefix, summary_offsets["export_offset_offset"], modified_summary.export_offset)
    patch_i32_le(prefix, summary_offsets["import_count_offset"], modified_summary.import_count)
    patch_i32_le(prefix, summary_offsets["import_offset_offset"], modified_summary.import_offset)
    patch_i32_le(prefix, summary_offsets["depends_offset_offset"], modified_summary.depends_offset)
    patch_i32_le(prefix, summary_offsets["import_export_guids_offset_offset"], modified_summary.import_export_guids_offset)
    if "thumbnail_table_offset_offset" in summary_offsets:
        patch_i32_le(prefix, summary_offsets["thumbnail_table_offset_offset"], modified_summary.thumbnail_table_offset)
    _patch_generation_counts(prefix, summary_offsets, modified_summary.export_count, modified_summary.name_count)
    with original_encrypted_path.open("rb") as src:
        meta_offsets = _find_file_compression_metadata_offsets(src)
    patch_i32_le(prefix, meta_offsets["compressed_chunks_offset_offset"], new_chunk_table_offset)
    if rebuilt_chunks:
        patch_i32_le(prefix, meta_offsets["last_block_size_offset"], rebuilt_chunks[-1].uncompressed_size)

    output = bytearray()
    output += prefix
    output += encrypted_header
    gap_start = modified_summary.name_offset + len(encrypted_header)
    original_gap_start = summary.name_offset + len(original_encrypted_data)
    original_gap_end = original_chunks[0].compressed_offset
    gap_bytes = original_bytes[original_gap_start:original_gap_end]
    if len(gap_bytes) != meta.garbage_size:
        gap_bytes = original_bytes[original_gap_end - meta.garbage_size:original_gap_end]
    output += gap_bytes
    for payload in rebuilt_chunk_payloads:
        output += payload

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    return output_path


def _pack_fname_value(package: ParsedPackage, text: str) -> bytes:
    text = text.strip()
    # Allow either "#<index>" to pick a name table entry by raw index, or a
    # plain base/base_<N> string to match by name. Instance suffixes are
    # split off so users can write things like "Foo_3" and have it round-trip
    # through the version-aware serialize_fname adjustment.
    base_text, instance_number = _split_name_instance(text)
    match = None
    if base_text.startswith("#"):
        try:
            idx = int(base_text[1:])
            if 0 <= idx < len(package.names):
                match = package.names[idx]
        except Exception:
            pass
    if match is None:
        for entry in package.names:
            if entry.name == base_text:
                match = entry
                break
    if match is None:
        # Fall back to the original full string (for the legacy case where a
        # name literally contained '_<digits>').
        for entry in package.names:
            if entry.name == text:
                match = entry
                instance_number = 0
                break
    if match is None:
        raise ValueError(f"FName not found in package name table: {text}")
    # instance_number == 0 from _split_name_instance means "no suffix typed",
    # which corresponds to in-memory -1 for >= NUMBER_ADDED_TO_NAME packages
    # (so serialize_fname writes 0 on disk). Translate appropriately.
    if package.summary.file_version >= NUMBER_ADDED_TO_NAME and instance_number == 0:
        in_memory_instance = -1
    else:
        in_memory_instance = instance_number
    return serialize_fname(FNameRef(match.index, in_memory_instance), package.summary)


def _parse_struct_numbers(text: str) -> List[float]:
    parts = [p.strip() for p in text.replace("(", "").replace(")", "").split(",") if p.strip()]
    return [float(p) for p in parts]



def get_export_entry_offsets(package: ParsedPackage) -> List[int]:
    bio = io.BytesIO(package.file_bytes)
    bio.seek(package.summary.export_offset)
    r = BinaryReader(bio)
    offsets: List[int] = []
    generation_count = len(package.summary.generations)
    for _ in range(package.summary.export_count):
        offsets.append(bio.tell())
        parse_export_entry(r, len(offsets) - 1, generation_count, package.summary)
    return offsets


def patch_i32_le(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 4] = struct.pack("<i", value)


def patch_i64_le(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 8] = struct.pack("<q", value)


def encode_property_value(package: ParsedPackage, prop: ParsedProperty, text: str) -> Tuple[int, bytes]:
    text = text.strip()
    if text.lower().startswith("hex:"):
        raw = bytes.fromhex(text[4:].strip())
        target_offset = prop.value_offset - 1 if prop.tag_type == "BoolProperty" and prop.bool_value is not None else prop.value_offset
        expected = 1 if prop.tag_type == "BoolProperty" and prop.bool_value is not None else prop.size
        if len(raw) != expected:
            raise ValueError(f"hex payload must be exactly {expected} bytes")
        return target_offset, raw
    if prop.tag_type == "BoolProperty":
        v = text.lower()
        if v in ("1", "true", "yes", "on"):
            return prop.value_offset - 1, b""
        if v in ("0", "false", "no", "off"):
            return prop.value_offset - 1, b"\x00"
        raise ValueError("BoolProperty expects true/false")
    if prop.tag_type == "IntProperty":
        return prop.value_offset, struct.pack("<i", int(text, 0))
    if prop.tag_type == "FloatProperty":
        return prop.value_offset, struct.pack("<f", float(text))
    if prop.tag_type == "QWordProperty":
        return prop.value_offset, struct.pack("<Q", int(text, 0))
    if prop.tag_type == "StringRefProperty":
        return prop.value_offset, struct.pack("<I", int(text, 0))
    if prop.tag_type in ("ObjectProperty", "ClassProperty", "ComponentProperty", "InterfaceProperty"):
        resolved = resolve_object_index_by_text(package, text)
        if resolved is None:
            raise ValueError("Object reference not found in exports/imports; use an index like -12 or a full object path")
        return prop.value_offset, struct.pack("<i", resolved)
    if prop.tag_type == "NameProperty":
        return prop.value_offset, _pack_fname_value(package, text)
    if prop.tag_type == "ByteProperty":
        if prop.enum_name:
            return prop.value_offset, _pack_fname_value(package, text)
        return prop.value_offset, struct.pack("<B", int(text, 0) & 0xFF)
    if prop.tag_type == "StrProperty":
        encoded = write_fstring_bytes(text)
        return prop.value_offset, encoded
    if prop.tag_type == "StructProperty":
        if prop.struct_name == "FVector":
            vals = _parse_struct_numbers(text)
            if len(vals) != 3:
                raise ValueError("FVector expects x,y,z")
            return prop.value_offset, struct.pack("<fff", *vals)
        if prop.struct_name == "FVector2D":
            vals = _parse_struct_numbers(text)
            if len(vals) != 2:
                raise ValueError("FVector2D expects x,y")
            return prop.value_offset, struct.pack("<ff", *vals)
        if prop.struct_name == "FRotator":
            vals = [int(v) for v in _parse_struct_numbers(text)]
            if len(vals) != 3:
                raise ValueError("FRotator expects pitch,yaw,roll")
            return prop.value_offset, struct.pack("<iii", *vals)
        if prop.struct_name == "FColor":
            vals = [int(v) for v in _parse_struct_numbers(text)]
            if len(vals) != 4:
                raise ValueError("FColor expects r,g,b,a")
            return prop.value_offset, bytes(v & 0xFF for v in vals)
        if prop.struct_name == "FLinearColor":
            vals = _parse_struct_numbers(text)
            if len(vals) != 4:
                raise ValueError("FLinearColor expects r,g,b,a")
            return prop.value_offset, struct.pack("<ffff", *vals)
        if prop.struct_name == "FGuid":
            cleaned = text.replace('-', '').replace('{', '').replace('}', '').strip()
            if len(cleaned) != 32:
                raise ValueError("FGuid expects 32 hex digits or a dashed guid")
            vals = [int(cleaned[i:i+8], 16) for i in range(0, 32, 8)]
            return prop.value_offset, struct.pack("<IIII", *vals)
    raise ValueError(f"Editing is not implemented for {prop.tag_type}")

def write_fstring_bytes(text: str) -> bytes:
    if not text:
        return struct.pack('<i', 0)
    try:
        # If it's pure ASCII, serialize as 1-byte ANSI (positive length)
        encoded = text.encode('ascii') + b'\x00'
        return struct.pack('<i', len(encoded)) + encoded
    except UnicodeEncodeError:
        # If it contains non-ASCII characters, serialize as 2-byte UTF-16LE (negative length)
        encoded = text.encode('utf-16-le') + b'\x00\x00'
        char_count = len(text) + 1
        return struct.pack('<i', -char_count) + encoded

def serialize_fname(ref: FNameRef, summary: Optional["FileSummary"] = None) -> bytes:
    # Mirror the version-aware adjustment in read_fname: for >= NUMBER_ADDED_TO_NAME
    # the on-disk stored value is (instance_number + 1), so we add 1 here.
    # When summary is None (legacy callers), fall back to writing the raw
    # in-memory value, which preserves prior behaviour for any code path
    # that hasn't been threaded through.
    if summary is not None and summary.file_version >= NUMBER_ADDED_TO_NAME:
        stored_instance = ref.instance_number + 1
    else:
        stored_instance = ref.instance_number
    return struct.pack("<ii", ref.name_index, stored_instance)


def serialize_name_entry(entry: NameEntry) -> bytes:
    return write_fstring_bytes(entry.name) + struct.pack("<Q", entry.flags)


def serialize_import_entry(entry: ImportEntry, summary: Optional["FileSummary"] = None) -> bytes:
    return b"".join([
        serialize_fname(entry.class_package, summary),
        serialize_fname(entry.class_name, summary),
        struct.pack("<i", entry.outer_index),
        serialize_fname(entry.object_name, summary),
    ])


def serialize_export_entry(entry: ExportEntry, summary: Optional["FileSummary"] = None) -> bytes:
    out = bytearray()
    out += struct.pack("<i", entry.class_index)
    out += struct.pack("<i", entry.super_index)
    out += struct.pack("<i", entry.outer_index)
    out += serialize_fname(entry.object_name, summary)
    out += struct.pack("<i", entry.archetype_index)
    out += struct.pack("<Q", entry.object_flags)
    out += struct.pack("<i", entry.serial_size)
    out += struct.pack("<q", entry.serial_offset)
    out += struct.pack("<i", entry.export_flags)
    out += struct.pack("<i", len(entry.net_objects))
    for value in entry.net_objects:
        out += struct.pack("<i", value)
    out += struct.pack("<IIII", *entry.package_guid)
    out += struct.pack("<i", entry.package_flags)
    return bytes(out)


def _find_summary_offsets(data: bytes) -> Dict[str, int]:
    bio = io.BytesIO(data)
    r = BinaryReader(bio)
    if r.read_u32() != PACKAGE_FILE_TAG:
        raise ValueError("Not a valid Unreal Engine package")
    r.read_u16()
    r.read_u16()
    total_header_size_offset = bio.tell()
    r.read_i32()
    r.read_fstring()
    package_flags_offset = bio.tell()
    r.read_u32()
    name_count_offset = bio.tell()
    r.read_i32()
    name_offset_offset = bio.tell()
    r.read_i32()
    export_count_offset = bio.tell()
    r.read_i32()
    export_offset_offset = bio.tell()
    r.read_i32()
    import_count_offset = bio.tell()
    r.read_i32()
    import_offset_offset = bio.tell()
    r.read_i32()
    depends_offset_offset = bio.tell()
    r.read_i32()
    import_export_guids_offset_offset = bio.tell()
    r.read_i32()
    r.read_i32()
    r.read_i32()
    thumbnail_table_offset_offset = bio.tell()
    r.read_i32()
    read_guid(r)
    generations_count_offset = bio.tell()
    gen_count = r.read_i32()
    generation_entries_offset = bio.tell()
    return {
        "total_header_size_offset": total_header_size_offset,
        "package_flags_offset": package_flags_offset,
        "name_count_offset": name_count_offset,
        "name_offset_offset": name_offset_offset,
        "export_count_offset": export_count_offset,
        "export_offset_offset": export_offset_offset,
        "import_count_offset": import_count_offset,
        "import_offset_offset": import_offset_offset,
        "depends_offset_offset": depends_offset_offset,
        "import_export_guids_offset_offset": import_export_guids_offset_offset,
        "thumbnail_table_offset_offset": thumbnail_table_offset_offset,
        "generations_count_offset": generations_count_offset,
        "generation_entries_offset": generation_entries_offset,
        "generation_count": gen_count,
    }


def _patch_generation_counts(data: bytearray, offsets: Dict[str, int], export_count: int, name_count: int) -> None:
    gen_count = offsets.get("generation_count", 0)
    if gen_count <= 0:
        return
    base = offsets["generation_entries_offset"] + (gen_count - 1) * 12
    if base + 8 > len(data):
        return
    patch_i32_le(data, base, export_count)
    patch_i32_le(data, base + 4, name_count)


def _replace_header_tables(package: ParsedPackage, names: List[NameEntry], imports: List[ImportEntry]) -> bytes:
    summary = package.summary
    offsets = _find_summary_offsets(package.file_bytes)
    old_depends_offset = summary.depends_offset

    prefix = bytearray(package.file_bytes[:summary.name_offset])
    patched_exports: List[ExportEntry] = []
    for x in package.exports:
        patched_exports.append(ExportEntry(
            table_index=x.table_index,
            class_index=x.class_index,
            super_index=x.super_index,
            outer_index=x.outer_index,
            object_name=FNameRef(x.object_name.name_index, x.object_name.instance_number),
            archetype_index=x.archetype_index,
            object_flags=x.object_flags,
            serial_size=x.serial_size,
            serial_offset=x.serial_offset,
            export_flags=x.export_flags,
            net_objects=list(x.net_objects),
            package_guid=x.package_guid,
            package_flags=x.package_flags,
        ))

    names_blob = b"".join(serialize_name_entry(x) for x in names)
    imports_blob = b"".join(serialize_import_entry(x, summary) for x in imports)
    export_offset = summary.name_offset + len(names_blob) + len(imports_blob)
    depends_offset = export_offset + sum(len(serialize_export_entry(x, summary)) for x in patched_exports)
    delta = depends_offset - old_depends_offset

    if delta != 0:
        for exp in patched_exports:
            if exp.serial_offset >= old_depends_offset:
                exp.serial_offset += delta

    exports_blob = b"".join(serialize_export_entry(x, summary) for x in patched_exports)
    depends_offset = export_offset + len(exports_blob)
    delta = depends_offset - old_depends_offset

    header_blob = prefix + names_blob + imports_blob + exports_blob
    patch_i32_le(header_blob, offsets["name_count_offset"], len(names))
    patch_i32_le(header_blob, offsets["name_offset_offset"], summary.name_offset)
    patch_i32_le(header_blob, offsets["export_count_offset"], len(patched_exports))
    patch_i32_le(header_blob, offsets["export_offset_offset"], export_offset)
    patch_i32_le(header_blob, offsets["import_count_offset"], len(imports))
    patch_i32_le(header_blob, offsets["import_offset_offset"], summary.name_offset + len(names_blob))
    patch_i32_le(header_blob, offsets["depends_offset_offset"], depends_offset)

    import_export_guids_offset = summary.import_export_guids_offset
    if import_export_guids_offset >= old_depends_offset and import_export_guids_offset != 0:
        import_export_guids_offset += delta
    patch_i32_le(header_blob, offsets["import_export_guids_offset_offset"], import_export_guids_offset)

    thumbnail_table_offset = summary.thumbnail_table_offset
    if thumbnail_table_offset >= old_depends_offset and thumbnail_table_offset != 0:
        thumbnail_table_offset += delta
    if "thumbnail_table_offset_offset" in offsets:
        patch_i32_le(header_blob, offsets["thumbnail_table_offset_offset"], thumbnail_table_offset)

    # NOTE: total_header_size is intentionally written back UNCHANGED. In a
    # decrypted RL package this field carries over the value from the original
    # encrypted file (unpack_package copies the encrypted prefix verbatim into
    # the decrypted output and never adjusts this field). The encrypted-save
    # path (build_reencrypted_package) computes its own correct value from
    # name_offset + encrypted_plain_len + garbage_size and patches it
    # independently, so the value we write here only matters for
    # 'Save Decrypted UPK' where preserving the original-encrypted semantics
    # is the right behaviour. An earlier attempt to "fix" this by adding the
    # names+imports growth delta produced corrupt encrypted files because the
    # delta concept doesn't apply to the encrypted-layout meaning of this field.
    patch_i32_le(header_blob, offsets["total_header_size_offset"], summary.total_header_size)
    _patch_generation_counts(header_blob, offsets, len(patched_exports), len(names))

    new_data = bytearray()
    new_data += header_blob
    new_data += package.file_bytes[old_depends_offset:]
    return bytes(new_data)


def _split_name_instance(text: str) -> Tuple[str, int]:
    if '_' in text:
        base, suffix = text.rsplit('_', 1)
        if suffix.isdigit():
            return base, int(suffix)
    return text, 0


def _find_existing_name_ref(names: List[NameEntry], text: str) -> Optional[FNameRef]:
    base, instance = _split_name_instance(text)
    for entry in names:
        if entry.name == base:
            return FNameRef(entry.index, instance)
    return None


def _ensure_name_entry(names: List[NameEntry], text: str, flags: int = 0) -> FNameRef:
    found = _find_existing_name_ref(names, text)
    if found is not None:
        return found
    base, instance = _split_name_instance(text)
    names.append(NameEntry(index=len(names), name=base, flags=flags))
    return FNameRef(len(names) - 1, instance)


def import_donor_names(package: ParsedPackage, donor_package: ParsedPackage, selected_names: Optional[List[str]] = None) -> ParsedPackage:
    names = [NameEntry(index=n.index, name=n.name, flags=n.flags) for n in package.names]
    wanted = None if not selected_names else set(selected_names)
    added = 0
    for entry in donor_package.names:
        if wanted is not None and entry.name not in wanted:
            continue
        if _find_existing_name_ref(names, entry.name) is None:
            names.append(NameEntry(index=len(names), name=entry.name, flags=entry.flags))
            added += 1
    if added == 0:
        result = ParsedPackage(package.file_path, package.summary, names, package.imports, package.exports, package.file_bytes)
        setattr(result, '_merge_added_names', 0)
        return result
    patched = _replace_header_tables(package, names, package.imports)
    temp_path = package.file_path.with_name(package.file_path.stem + '_names_merged.upk')
    temp_path.write_bytes(patched)
    result = parse_decrypted_package(temp_path)
    setattr(result, '_merge_added_names', added)
    return result


def _collect_existing_import_paths(package: ParsedPackage) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i in range(len(package.imports)):
        out[package.resolve_object_path(-(i + 1))] = -(i + 1)
    return out


def _class_package_and_name_for_ref(package: ParsedPackage, class_index: int) -> Tuple[str, str]:
    if class_index == 0:
        return "Core", "Class"
    path = package.resolve_object_path(class_index)
    parts = [p for p in path.split('.') if p and p != 'None']
    if not parts:
        return "Core", "Class"
    if len(parts) == 1:
        return "Core", parts[-1]
    return parts[-2], parts[-1]


def _derive_donor_package_name(donor_package: ParsedPackage, override: Optional[str] = None) -> str:
    """Return the package name UE will use to LoadPackage the donor at runtime.

    Priority:
      1. Explicit override from the caller (e.g. user typed it in).
      2. The donor file's stem (e.g. 'MyDonorAssets.upk' -> 'MyDonorAssets').
         This is what the engine resolves through its package search paths,
         so it must match how the file is actually deployed in the game's
         cooked content directory.
      3. The donor's embedded summary.folder_name. Often empty in cooked
         RL packages but used as a last resort.

    Raises ValueError if no usable name can be derived.
    """
    if override and override.strip():
        return override.strip()
    stem = donor_package.file_path.stem
    # Strip our own '_decrypted' / '_decompressed' suffixes that resolve_input_package
    # appends when it produces a working copy - the file the game loads has the
    # original stem.
    for suffix in ("_decrypted", "_decompressed"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if stem:
        return stem
    folder = (donor_package.summary.folder_name or "").strip()
    if folder:
        return folder
    raise ValueError("Could not determine donor package name; pass it explicitly")


def merge_donor_exports_as_imports(target_package: ParsedPackage, donor_package: ParsedPackage, donor_package_name: Optional[str] = None) -> ParsedPackage:
    # The donor's package name is what the engine will look up at runtime to
    # locate and LoadPackage the donor .upk. Every donor export we re-import
    # MUST be rooted under a Core.Package import with this name, otherwise
    # the engine has no way to know which file to open to resolve the
    # reference. Previously donor root exports were imported with
    # outer_index=0 (i.e. as if they themselves were top-level packages),
    # which left the engine unable to resolve them.
    resolved_donor_name = _derive_donor_package_name(donor_package, donor_package_name)

    names = [NameEntry(index=n.index, name=n.name, flags=n.flags) for n in target_package.names]
    imports = [ImportEntry(table_index=i, class_package=FNameRef(x.class_package.name_index, x.class_package.instance_number), class_name=FNameRef(x.class_name.name_index, x.class_name.instance_number), outer_index=x.outer_index, object_name=FNameRef(x.object_name.name_index, x.object_name.instance_number)) for i, x in enumerate(target_package.imports)]
    existing_paths = _collect_existing_import_paths(target_package)
    donor_cache: Dict[int, int] = {}

    def ensure_package_root(package_name: str) -> int:
        existing = existing_paths.get(package_name)
        if existing is not None:
            return existing
        cp = _ensure_name_entry(names, 'Core')
        cn = _ensure_name_entry(names, 'Package')
        on = _ensure_name_entry(names, package_name)
        imports.append(ImportEntry(len(imports), cp, cn, 0, on))
        idx = -len(imports)
        existing_paths[package_name] = idx
        return idx

    # Pre-create the donor package import up front. Even if no donor exports
    # ended up needing it (e.g. all collisions with existing imports), having
    # this entry guarantees the engine will attempt to load the donor file
    # when the target is loaded, which is what users typically want when
    # they "import donor exports".
    donor_root_index = ensure_package_root(resolved_donor_name)

    def ensure_donor_object(index: int) -> int:
        if index == 0:
            return 0
        if index in donor_cache:
            return donor_cache[index]
        path = donor_package.resolve_object_path(index)
        # When matching against existing target imports, prepend the donor
        # package name so a donor export "Foo" doesn't collide with an
        # unrelated existing import literally named "Foo". For donor
        # imports we keep the original path because those refer to the same
        # external packages (Engine, Core, etc.) the target may also
        # reference, and we WANT to share those.
        scoped_path = f"{resolved_donor_name}.{path}" if index > 0 else path
        if scoped_path in existing_paths:
            donor_cache[index] = existing_paths[scoped_path]
            return existing_paths[scoped_path]
        if index > 0:
            obj = donor_package.exports[index - 1]
            obj_name = donor_package.resolve_name(obj.object_name)
            outer_index = ensure_donor_object(obj.outer_index) if obj.outer_index else 0
            if outer_index == 0:
                # Root donor export: parent it to the donor package import so
                # the engine knows to LoadPackage(donor_name) to resolve it.
                outer_index = donor_root_index
            class_pkg_name, class_name_name = _class_package_and_name_for_ref(donor_package, obj.class_index)
        else:
            obj = donor_package.imports[-index - 1]
            obj_name = donor_package.resolve_name(obj.object_name)
            outer_index = ensure_donor_object(obj.outer_index) if obj.outer_index else 0
            class_pkg_name = donor_package.resolve_name(obj.class_package)
            class_name_name = donor_package.resolve_name(obj.class_name)
        cp = _ensure_name_entry(names, class_pkg_name)
        cn = _ensure_name_entry(names, class_name_name)
        on = _ensure_name_entry(names, obj_name)
        imports.append(ImportEntry(len(imports), cp, cn, outer_index, on))
        new_index = -len(imports)
        donor_cache[index] = new_index
        existing_paths[scoped_path] = new_index
        return new_index

    imported = 0
    for i in range(1, len(donor_package.exports) + 1):
        before = len(imports)
        ensure_donor_object(i)
        if len(imports) != before:
            imported += 1

    patched = _replace_header_tables(target_package, names, imports)
    result = parse_decrypted_package_bytes(target_package.file_path, patched)
    setattr(result, '_merge_added_imports', len(imports) - len(target_package.imports))
    setattr(result, '_merge_added_names', len(names) - len(target_package.names))
    setattr(result, '_merge_donor_export_count', len(donor_package.exports))
    setattr(result, '_merge_donor_package_name', resolved_donor_name)
    return result



def replace_export_data(package: ParsedPackage, export: ExportEntry, new_data: bytes) -> ParsedPackage:
    """Replace the raw serial data of an export with new_data, adjusting all offsets."""
    size_delta = len(new_data) - export.serial_size
    file_bytes = bytearray(package.file_bytes)

    # Rebuild file bytes with new serial data
    new_file_bytes = bytearray()
    new_file_bytes += file_bytes[:export.serial_offset]
    new_file_bytes += new_data
    new_file_bytes += file_bytes[export.serial_offset + export.serial_size:]

    # Patch the export entry's serial_size
    export_entry_offsets = get_export_entry_offsets(package)
    entry_offset = export_entry_offsets[export.table_index]
    patch_i32_le(new_file_bytes, entry_offset + 32, len(new_data))

    # Shift all exports that come after the modified one
    for idx, other in enumerate(package.exports):
        if idx == export.table_index:
            continue
        if other.serial_offset > export.serial_offset:
            # We need to find the offset in the NEW file bytes, but the table order is preserved.
            # However, the table itself might have shifted if it was after the modified export.
            # BUT in UE3, the header (tables) is always BEFORE the export bodies.
            # So serial_offset of all exports are always > any table offset.
            other_entry_offset = export_entry_offsets[idx]
            patch_i64_le(new_file_bytes, other_entry_offset + 36, other.serial_offset + size_delta)

    return parse_decrypted_package_bytes(package.file_path, bytes(new_file_bytes))


def replace_export_with_donor_export(target_package: ParsedPackage, donor_package: ParsedPackage, target_export_path: str, donor_export_path: str) -> ParsedPackage:
    merged = import_donor_names(target_package, donor_package, None)
    merged = merge_donor_exports_as_imports(merged, donor_package)

    target_index = resolve_object_index_by_text(merged, target_export_path)
    donor_index = resolve_object_index_by_text(donor_package, donor_export_path)
    if target_index is None or target_index <= 0:
        raise ValueError(f"Target export not found: {target_export_path}")
    if donor_index is None or donor_index <= 0:
        raise ValueError(f"Donor export not found: {donor_export_path}")

    target_export = merged.exports[target_index - 1]
    donor_export = donor_package.exports[donor_index - 1]

    target_class = merged.export_class_name(target_export)
    donor_class = donor_package.export_class_name(donor_export)
    if target_class != donor_class:
        raise ValueError(f"Class mismatch: target is {target_class}, donor is {donor_class}")

    donor_bytes = donor_package.object_data(donor_export)
    if not donor_bytes:
        raise ValueError("Donor export has no serial data")

    result = replace_export_data(merged, target_export, donor_bytes)
    setattr(result, '_replace_target_export_path', target_export_path)
    setattr(result, '_replace_donor_export_path', donor_export_path)
    setattr(result, '_replace_note', 'Raw donor serial data copied into target export. Name/index remapping inside arbitrary native data is not performed.')
    return result


def rename_name_entry(package: ParsedPackage, name_index: int, new_text: str) -> ParsedPackage:
    """Rewrite the text of a single entry in the package's name table.

    The name's *index* stays the same, only the string changes. Because every
    FNameRef across the package (exports, imports, serialized property tags,
    object names, etc.) references names by index, all references continue to
    resolve correctly and now read the new text.

    The names blob length almost always changes (different string length, or
    ANSI vs UTF-16 encoding), so the entire header is rebuilt via
    _replace_header_tables. That helper recomputes name_offset-following
    offsets (import/export/depends/thumbnail/import-export-guids) and shifts
    every export.serial_offset by the resulting delta, so the package stays
    internally consistent. total_header_size is preserved by the rebuild
    helper's offset patching - the bytes after the header are taken verbatim
    from the original file at old_depends_offset.

    Args:
        package: The package to modify.
        name_index: Zero-based index into package.names of the entry to rename.
        new_text: New text for the name entry. Must be a bare base name (no
            "_<N>" instance suffix - instance numbers live on FNameRefs, not
            on name table entries).

    Raises:
        ValueError: If name_index is out of range, new_text is empty, new_text
            contains an instance suffix, or new_text already exists elsewhere
            in the name table (which would create a duplicate base name and
            ambiguous lookups).

    Returns:
        A re-parsed ParsedPackage with attributes:
            _name_rename_index: int  - index that was renamed
            _name_rename_old: str    - previous text
            _name_rename_new: str    - new text
            _name_size_delta: int    - bytes added (+) or removed (-) by the
                                       rename, useful for status reporting
    """
    new_text = (new_text or "").strip()
    if not new_text:
        raise ValueError("Empty name text")
    if name_index < 0 or name_index >= len(package.names):
        raise ValueError(f"Name index {name_index} out of range (0..{len(package.names) - 1})")

    # Reject instance suffixes - those belong on FNameRefs, not entries. A
    # name table entry is a pure base string; entries like "Foo_3" only happen
    # if the original asset really had a literal underscore-digit base name.
    base, instance = _split_name_instance(new_text)
    if instance != 0:
        raise ValueError(
            "Name entries cannot include an instance suffix like '_3'. "
            "Instance numbers live on each FName reference, not on the "
            "name table entry. Use the bare base name (e.g. 'MyName')."
        )

    old_entry = package.names[name_index]
    if old_entry.name == new_text:
        # No-op: re-parse so callers always get a fresh ParsedPackage with the
        # standard rename metadata attached.
        result = parse_decrypted_package_bytes(package.file_path, bytes(package.file_bytes))
        setattr(result, '_name_rename_index', name_index)
        setattr(result, '_name_rename_old', old_entry.name)
        setattr(result, '_name_rename_new', new_text)
        setattr(result, '_name_size_delta', 0)
        return result

    # Reject collisions with other entries. Merging duplicates would require
    # remapping every FNameRef across exports/imports/serialized properties to
    # the surviving index, which is a much larger operation than a rename.
    for entry in package.names:
        if entry.index == name_index:
            continue
        if entry.name == new_text:
            raise ValueError(
                f"Name '{new_text}' already exists at index {entry.index}. "
                "Renaming would create a duplicate base name. Choose a unique "
                "name, or rename the other entry first."
            )

    # Build the modified names list and let _replace_header_tables redo the
    # names blob, recompute downstream offsets, and shift export serial_offsets
    # by the size delta.
    old_blob_len = len(serialize_name_entry(old_entry))
    new_entry = NameEntry(index=name_index, name=new_text, flags=old_entry.flags)
    new_blob_len = len(serialize_name_entry(new_entry))
    size_delta = new_blob_len - old_blob_len

    names = [NameEntry(index=n.index, name=n.name, flags=n.flags) for n in package.names]
    names[name_index] = new_entry

    rebuilt_bytes = _replace_header_tables(package, names, package.imports)
    result = parse_decrypted_package_bytes(package.file_path, rebuilt_bytes)
    setattr(result, '_name_rename_index', name_index)
    setattr(result, '_name_rename_old', old_entry.name)
    setattr(result, '_name_rename_new', new_text)
    setattr(result, '_name_size_delta', size_delta)
    return result


def resolve_object_index_by_text(package: ParsedPackage, text: str) -> Optional[int]:
    text = text.strip()
    try:
        return int(text, 0)
    except Exception:
        pass
    if text.startswith('Import[') or text.startswith('Export['):
        m = re.match(r'^(Import|Export)\[(\d+)\]', text)
        if m:
            kind, num = m.groups()
            idx = int(num)
            return -(idx + 1) if kind == 'Import' else (idx + 1)
    for i in range(len(package.exports)):
        if package.resolve_object_path(i + 1) == text:
            return i + 1
    for i in range(len(package.imports)):
        if package.resolve_object_path(-(i + 1)) == text:
            return -(i + 1)
    return None


# ── DLLBind support ──────────────────────────────────────────────────────────
#
# In UE3 the compiler keyword `DLLBind(SomeDLL)` on a class declaration
# stores the DLL name as an FString field called DLLBindName inside the
# UClass serial body.  It is the LAST field serialized by UClass::Serialize,
# immediately after NativeClassName (also an FString).
#
# When the engine loads the package it reads this field and calls
# LoadLibrary on the named DLL before the class is fully initialised,
# making DLLBind a clean DLL-injection point for Rocket League mods.
#
# Binary layout at the tail of a cooked UClass serial body:
#   [... UClass-specific fields ...]
#   NativeClassName  : FString  (usually empty → 4 zero bytes)
#   DLLBindName      : FString  (empty = 4 zero bytes; or len+chars+NUL)
#
# FString encoding:  int32 length (including NUL) then ASCII bytes + NUL.
#                    Length == 0 means empty string (no NUL follows).

def is_uclass_export(package: ParsedPackage, export: ExportEntry) -> bool:
    """Return True when *export* is itself a class definition (class_index → Class)."""
    return package.export_class_name(export) == "Class"


def find_uclass_dllbind_fstring_offset(raw: bytes) -> Optional[Tuple[int, str]]:
    """Locate the DLLBindName FString at the tail of a UClass serial body.

    Strategy: DLLBindName is the last thing serialized by UClass::Serialize.
    We scan forward from the last 260 bytes of *raw* looking for the unique
    FString whose byte span ends exactly at len(raw).

    Returns (fstring_start_offset, dll_name) where fstring_start_offset is
    the offset (relative to the start of *raw*) of the 4-byte length field of
    DLLBindName, and dll_name is the current value (empty string if no bind).

    Returns None if no valid FString pattern ending at EOF is found.
    """
    L = len(raw)
    if L < 4:
        return None

    # Determine the search window.  DLLBind names are short (<260 chars),
    # so DLLBindName is at most 4+260 = 264 bytes.  We walk backwards.
    lo = max(0, L - 264 - 4)

    # Try every possible starting offset for an FString that ends at L.
    #   fstring_start = pos
    #   length field  = int32 at pos              (4 bytes)
    #   string data   = raw[pos+4 : pos+4+length] (length bytes)
    #   total size    = 4 + length
    #   must satisfy  = pos + 4 + length == L
    for pos in range(L - 4, lo - 1, -1):
        if pos < 0:
            break
        try:
            length = struct.unpack_from("<i", raw, pos)[0]
        except struct.error:
            break

        if length == 0:
            # Empty FString: occupies exactly 4 bytes.
            if pos + 4 == L:
                return pos, ""
            # Keep scanning — this zero might be padding before the real field.
            continue

        if length < 0 or length > 260:
            # Negative → UTF-16 (unusual for DLL names); too large → noise.
            continue

        # Non-empty ASCII FString: must end exactly at L.
        if pos + 4 + length != L:
            continue

        str_bytes = raw[pos + 4: L]
        if len(str_bytes) != length:
            continue
        # Null-terminated ASCII.
        if str_bytes[-1] != 0:
            continue
        try:
            dll_name = str_bytes[:-1].decode("ascii")
        except (UnicodeDecodeError, ValueError):
            continue
        if not dll_name.isprintable():
            continue
        return pos, dll_name

    return None

def read_tarray(reader: BinaryReader, read_item):
    count = reader.read_i32()
    return [read_item(reader) for _ in range(count)]


def read_guid(reader: BinaryReader) -> Tuple[int, int, int, int]:
    return (reader.read_u32(), reader.read_u32(), reader.read_u32(), reader.read_u32())


def read_generation(reader: BinaryReader) -> Tuple[int, int, int]:
    return (reader.read_i32(), reader.read_i32(), reader.read_i32())


def read_texture_allocation(reader: BinaryReader):
    reader.read_i32()
    reader.read_i32()
    reader.read_i32()
    reader.read_i32()
    reader.read_i32()
    read_tarray(reader, lambda r: r.read_i32())
    return None


def read_compact_index(reader: BinaryReader) -> int:
    index = 0
    b0 = reader.read_u8()
    if (b0 & 0x40) != 0:
        b1 = reader.read_u8()
        if (b1 & 0x80) != 0:
            b2 = reader.read_u8()
            if (b2 & 0x80) != 0:
                b3 = reader.read_u8()
                if (b3 & 0x80) != 0:
                    b4 = reader.read_u8()
                    index = b4
                index = (index << 7) | (b3 & 0x7F)
            index = (index << 7) | (b2 & 0x7F)
        index = (index << 7) | (b1 & 0x7F)
    index = (index << 6) | (b0 & 0x3F)
    if (b0 & 0x80) != 0:
        index *= -1
    return index


def read_index_pkg(reader: BinaryReader, package: ParsedPackage) -> int:
    if package.summary.file_version >= COMPACT_INDEX_DEPRECATED:
        return reader.read_i32()
    return read_compact_index(reader)


def read_fname_pkg(reader: BinaryReader, package: ParsedPackage) -> FNameRef:
    name_index = read_index_pkg(reader, package)
    if package.summary.file_version >= NUMBER_ADDED_TO_NAME:
        instance_number = reader.read_i32() - 1
    else:
        instance_number = -1
    return FNameRef(name_index, instance_number)


def read_fname(reader: BinaryReader, summary: Optional["FileSummary"] = None) -> FNameRef:
    # When called with a FileSummary, applies the same UE3 instance-number
    # convention as read_fname_pkg: the value stored on disk is (number + 1),
    # so we subtract 1 to recover the in-memory number where -1 means "no
    # suffix" and 0/1/2/... are real instance suffixes. UE Explorer's
    # ReadName/ReadNameReference does the same thing
    # (see UELib/src/UnrealStream.cs ReadName, line ~509-516). When called
    # without a summary we keep the legacy raw read for any caller that
    # genuinely wants two i32s with no adjustment - currently nothing in the
    # codebase relies on that, but the default keeps the signature backwards
    # compatible if external callers exist.
    name_index = reader.read_i32()
    raw_instance = reader.read_i32()
    if summary is not None and summary.file_version >= NUMBER_ADDED_TO_NAME:
        instance_number = raw_instance - 1
    else:
        instance_number = raw_instance
    return FNameRef(name_index, instance_number)


def read_name_entry(reader: BinaryReader, index: int) -> NameEntry:
    return NameEntry(index=index, name=reader.read_fstring(), flags=reader.read_u64())


def read_compressed_chunk_32(reader: BinaryReader) -> FCompressedChunk:
    return FCompressedChunk(
        uncompressed_offset=reader.read_i32(),
        uncompressed_size=reader.read_i32(),
        compressed_offset=reader.read_i32(),
        compressed_size=reader.read_i32(),
    )


def read_compressed_chunk_64(reader: BinaryReader) -> FCompressedChunk:
    return FCompressedChunk(
        uncompressed_offset=reader.read_i64(),
        uncompressed_size=reader.read_i32(),
        compressed_offset=reader.read_i64(),
        compressed_size=reader.read_i32(),
    )


def parse_file_summary(stream: BinaryIO) -> FileSummary:
    r = BinaryReader(stream)
    summary = FileSummary()
    summary.tag = r.read_u32()
    if summary.tag != PACKAGE_FILE_TAG:
        raise ValueError("Not a valid Unreal Engine package")
    summary.file_version = r.read_u16()
    summary.licensee_version = r.read_u16()
    summary.total_header_size = r.read_i32()
    summary.folder_name = r.read_fstring()
    summary.package_flags_flags_offset = r.tell()
    summary.package_flags = r.read_u32()
    summary.name_count = r.read_i32()
    summary.name_offset = r.read_i32()
    summary.export_count = r.read_i32()
    summary.export_offset = r.read_i32()
    summary.import_count = r.read_i32()
    summary.import_offset = r.read_i32()
    summary.depends_offset = r.read_i32()
    summary.import_export_guids_offset = r.read_i32()
    summary.import_guids_count = r.read_i32()
    summary.export_guids_count = r.read_i32()
    summary.thumbnail_table_offset = r.read_i32()
    summary.guid = read_guid(r)
    summary.generations = read_tarray(r, read_generation)
    summary.engine_version = r.read_u32()
    summary.cooker_version = r.read_u32()
    summary.compression_flags_offset = r.tell()
    summary.compression_flags = r.read_u32()
    summary.compressed_chunks = read_tarray(r, read_compressed_chunk_32)
    r.read_i32()
    read_tarray(r, lambda rr: rr.read_fstring())
    read_tarray(r, read_texture_allocation)
    return summary


def parse_file_compression_metadata(stream: BinaryIO) -> FileCompressionMetaData:
    r = BinaryReader(stream)
    return FileCompressionMetaData(
        garbage_size=r.read_i32(),
        compressed_chunks_offset=r.read_i32(),
        last_block_size=r.read_i32(),
    )


def verify_decryptor(summary: FileSummary, meta: FileCompressionMetaData, key: bytes, encrypted_data: bytes) -> bool:
    block_offset = meta.compressed_chunks_offset % 16
    block_start = meta.compressed_chunks_offset - block_offset
    probe = encrypted_data[block_start:block_start + 32]
    if len(probe) != 32:
        return False
    decrypted = DecryptionProvider.decrypt_ecb(key, probe)
    view = decrypted[block_offset:]
    if len(view) < 8:
        return False
    chunk_info_length, first_uncompressed_offset = struct.unpack("<ii", view[:8])
    return chunk_info_length >= 1 and first_uncompressed_offset == summary.depends_offset


def decrypt_data(stream: BinaryIO, summary: FileSummary, meta: FileCompressionMetaData, provider: DecryptionProvider) -> bytes:
    encrypted_size = summary.total_header_size - meta.garbage_size - summary.name_offset
    encrypted_size = (encrypted_size + 15) & ~15
    stream.seek(summary.name_offset)
    encrypted_data = stream.read(encrypted_size)
    if len(encrypted_data) != encrypted_size:
        raise ValueError("Failed to read the encrypted data from the stream")
    valid_key = None
    for key in provider.decryption_keys:
        if verify_decryptor(summary, meta, key, encrypted_data):
            valid_key = key
            break
    if valid_key is None:
        raise ValueError("Unknown Decryption key")
    return DecryptionProvider.decrypt_ecb(valid_key, encrypted_data)


def parse_rl_compressed_chunks(decrypted_data: bytes, offset: int) -> List[FCompressedChunk]:
    bio = io.BytesIO(decrypted_data)
    bio.seek(offset)
    r = BinaryReader(bio)
    return read_tarray(r, read_compressed_chunk_64)


def process_compressed_data(output: BinaryIO, package_stream: BinaryIO, summary: FileSummary) -> None:
    if not summary.compressed_chunks:
        raise ValueError("No compressed chunks were found in decrypted data")
    first_uncompressed_offset = summary.compressed_chunks[0].uncompressed_offset
    last_chunk = summary.compressed_chunks[-1]
    final_size = last_chunk.uncompressed_offset + last_chunk.uncompressed_size
    output.truncate(final_size)
    output.seek(first_uncompressed_offset)
    r = BinaryReader(package_stream)
    for chunk in summary.compressed_chunks:
        package_stream.seek(chunk.compressed_offset)
        r.read_i32()
        r.read_i32()
        r.read_i32()
        total_uncompressed_size = r.read_i32()
        sum_uncompressed_size = 0
        blocks: List[Tuple[int, int]] = []
        while sum_uncompressed_size < total_uncompressed_size:
            comp_size = r.read_i32()
            uncomp_size = r.read_i32()
            blocks.append((comp_size, uncomp_size))
            sum_uncompressed_size += uncomp_size
        for comp_size, uncomp_size in blocks:
            compressed_block = r.read_exact(comp_size)
            inflated = zlib.decompress(compressed_block)
            if len(inflated) != uncomp_size:
                raise ValueError(f"Unexpected uncompressed block size: expected {uncomp_size}, got {len(inflated)}")
            output.write(inflated)
    output.seek(summary.package_flags_flags_offset)
    output.write(struct.pack("<I", summary.package_flags & ~PKG_COOKED))
    output.seek(summary.compression_flags_offset)
    output.write(struct.pack("<I", COMPRESS_NONE))


def unpack_package(input_path: str, output_path: str, provider: DecryptionProvider) -> Path:
    with open(input_path, "rb") as src:
        summary = parse_file_summary(src)
        if (summary.compression_flags & COMPRESS_ZLIB) == 0:
            raise ValueError("Package compression type is unsupported")
        meta = parse_file_compression_metadata(src)
        src.seek(0)
        header_bytes = src.read(summary.name_offset)
        decrypted_data = decrypt_data(src, summary, meta, provider)
        summary.compressed_chunks = parse_rl_compressed_chunks(decrypted_data, meta.compressed_chunks_offset)
        if not summary.compressed_chunks or summary.compressed_chunks[0].uncompressed_offset != summary.depends_offset:
            raise ValueError("Failed to parse decrypted compressed chunk table")
        output_path = str(output_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb+") as dst:
            dst.write(header_bytes)
            dst.write(decrypted_data)
            process_compressed_data(dst, src, summary)
    return Path(output_path)


def unpack_plain_package(input_path: str, output_path: str) -> Path:
    with open(input_path, "rb") as src:
        summary = parse_file_summary(src)
        if (summary.compression_flags & COMPRESS_ZLIB) == 0:
            raise ValueError("Package compression type is unsupported")
        output_path = str(output_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        original_bytes = Path(input_path).read_bytes()
        with open(output_path, "wb+") as dst:
            dst.write(original_bytes)
            process_compressed_data(dst, src, summary)
    return Path(output_path)


def try_parse_plain_package(input_path: Path) -> Optional["ParsedPackage"]:
    try:
        return parse_decrypted_package(input_path)
    except Exception:
        return None


def resolve_input_package(input_path: Path, decrypted_dir: Path, script_dir: Path) -> Tuple[Path, "ParsedPackage", Optional[DecryptionProvider], Optional[Path], bool]:
    plain_package = try_parse_plain_package(input_path)
    if plain_package is not None:
        return input_path, plain_package, None, None, False

    with input_path.open("rb") as fh:
        summary = parse_file_summary(fh)

    if (summary.compression_flags & COMPRESS_ZLIB) != 0:
        plain_decompressed_path = decrypted_dir / f"{input_path.stem}_decompressed.upk"
        try:
            unpack_plain_package(str(input_path), str(plain_decompressed_path))
            return plain_decompressed_path, parse_decrypted_package(plain_decompressed_path), None, None, False
        except Exception:
            pass

    keys_path = find_keys_path(script_dir, input_path)
    if keys_path is None:
        raise FileNotFoundError("Could not find keys.txt next to the script, current directory, or selected file")
    provider = DecryptionProvider(str(keys_path))
    decrypted_path = decrypted_dir / f"{input_path.stem}_decrypted.upk"
    unpack_package(str(input_path), str(decrypted_path), provider)
    return decrypted_path, parse_decrypted_package(decrypted_path), provider, keys_path, True


def parse_import_entry(reader: BinaryReader, table_index: int, summary: "FileSummary") -> ImportEntry:
    return ImportEntry(
        table_index=table_index,
        class_package=read_fname(reader, summary),
        class_name=read_fname(reader, summary),
        outer_index=reader.read_i32(),
        object_name=read_fname(reader, summary),
    )


def parse_export_entry(reader: BinaryReader, table_index: int, generation_count: int, summary: "FileSummary") -> ExportEntry:
    # The export entry layout in this UE3 build is:
    #   class_index (i32) | super_index (i32) | outer_index (i32) |
    #   object_name (FName: i32 name_index + i32 instance_number) |
    #   archetype_index (i32) | object_flags (u64) |
    #   serial_size (i32) | serial_offset (i64) | export_flags (i32) |
    #   net_objects (TArray<i32>: i32 count + count * i32) |
    #   package_guid (4*u32) | package_flags (i32)
    #
    # net_objects IS length-prefixed in this package version - it was the
    # generation_count assumption that was wrong. The original "None / Class
    # / 0 / 0" tail in the GUI is most likely an artifact of the export count
    # in the summary being larger than the number of real entries on disk
    # (the table is followed by zero padding), not a parser desync. The
    # generation_count parameter is kept for signature stability with
    # callers, but is not used.
    del generation_count
    class_index = reader.read_i32()
    super_index = reader.read_i32()
    outer_index = reader.read_i32()
    object_name = read_fname(reader, summary)
    archetype_index = reader.read_i32()
    object_flags = reader.read_u64()
    serial_size = reader.read_i32()
    serial_offset = reader.read_i64()
    export_flags = reader.read_i32()
    net_objects = read_tarray(reader, lambda rr: rr.read_i32())
    package_guid = read_guid(reader)
    package_flags = reader.read_i32()
    return ExportEntry(
        table_index=table_index,
        class_index=class_index,
        super_index=super_index,
        outer_index=outer_index,
        object_name=object_name,
        archetype_index=archetype_index,
        object_flags=object_flags,
        serial_size=serial_size,
        serial_offset=serial_offset,
        export_flags=export_flags,
        net_objects=net_objects,
        package_guid=package_guid,
        package_flags=package_flags,
    )


def parse_decrypted_package(file_path: Path) -> ParsedPackage:
    data = file_path.read_bytes()
    bio = io.BytesIO(data)
    summary = parse_file_summary(bio)
    if summary.compression_flags != COMPRESS_NONE:
        raise ValueError("The decrypted package is still marked as compressed")
    r = BinaryReader(bio)
    bio.seek(summary.name_offset)
    names = [read_name_entry(r, i) for i in range(summary.name_count)]
    bio.seek(summary.import_offset)
    imports = [parse_import_entry(r, i, summary) for i in range(summary.import_count)]
    bio.seek(summary.export_offset)
    exports = [parse_export_entry(r, i, len(summary.generations), summary) for i in range(summary.export_count)]
    return ParsedPackage(file_path=file_path, summary=summary, names=names, imports=imports, exports=exports, file_bytes=data)


def parse_decrypted_package_bytes(file_path: Path, data: bytes) -> ParsedPackage:
    bio = io.BytesIO(data)
    summary = parse_file_summary(bio)
    if summary.compression_flags != COMPRESS_NONE:
        raise ValueError("The decrypted package is still marked as compressed")
    r = BinaryReader(bio)
    bio.seek(summary.name_offset)
    names = [read_name_entry(r, i) for i in range(summary.name_count)]
    bio.seek(summary.import_offset)
    imports = [parse_import_entry(r, i, summary) for i in range(summary.import_count)]
    bio.seek(summary.export_offset)
    exports = [parse_export_entry(r, i, len(summary.generations), summary) for i in range(summary.export_count)]
    return ParsedPackage(file_path=file_path, summary=summary, names=names, imports=imports, exports=exports, file_bytes=data)


def find_keys_path(script_dir: Path, selected_file: Path) -> Optional[Path]:
    candidates = [
        script_dir / "keys.txt",
        Path.cwd() / "keys.txt",
        selected_file.parent / "keys.txt",
    ]
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, Path(sys._MEIPASS) / "keys.txt")
        
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def format_hex_preview(data: bytes, base_offset: int = 0) -> str:
    if not data:
        return ""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base_offset + i:08X}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())