import enum
import uuid
import typing
import reprlib
import construct
import itertools
import dataclasses
from PIL import Image
import datetime as dt
from msband.sugar import IntEnumAdapter, EnumBase, csfield
from construct_typed import DataclassMixin, DataclassStruct, TEnum
from msband.static.i18n import (
    LocaleId,
    LocaleIdAdapter,
    Language,
    LanguageAdapter,
    DisplayTimeFormat,
    DisplayTimeFormatAdapter,
    DisplayDateFormat,
    DisplayDateFormatAdapter,
    UnitType,
    UnitTypeAdapter,
)
from construct import (
    this,
    Hex,
    Int8ul,
    Int16ul,
    Int32ul,
    Int64ul,
    Flag,
    Adapter,
    PaddedString,
    If,
    Padded,
    Default,
    Bytes,
    FlagsEnum,
)


# Needed for a weird recursion error
dataclasses.Field.__repr__ = reprlib.recursive_repr()(dataclasses.Field.__repr__)


PUSH_SERVICE = uuid.UUID(hex="d8895bfd-0461-400d-bd52-dbe2a3c33021")
BAND_APP_IOS = uuid.UUID(hex="090fa552-5e0c-a24d-803b-af536cf97da3")


EPOCH = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)


class BandTime(Adapter):
    def _decode(self, obj: int, context, path) -> dt.datetime:
        return EPOCH + dt.timedelta(microseconds=obj // 10)

    def _encode(self, date: dt.datetime, context, path) -> int:
        if date > dt.datetime.max.replace(tzinfo=dt.timezone.utc):
            raise ValueError(f"Date {date} too far in the future to be encoded")

        if date < EPOCH:
            raise ValueError(f"Date {date} too far in the past to be encoded")

        return int((date - EPOCH).total_seconds() * 10000000)


class BoolAdapter(Adapter):
    def _encode(self, obj, context, path):
        return obj

    def _decode(self, obj, context, path):
        return bool(obj)


class GUIDAdapter(Adapter):
    def _encode(self, guid: uuid.UUID, context, path):
        return guid.bytes_le

    def _decode(self, guid: bytes, context, path):
        return uuid.UUID(bytes_le=guid)


class GUIDStringAdapter(Adapter):
    def _encode(self, guid: uuid.UUID, context, path):
        return guid.hex

    def _decode(self, guid: str, context, path):
        return uuid.UUID(hex=guid)


class MeTileAdapter(Adapter):
    width: int
    height: int

    def __init__(self, subcon, width: int, height: int):
        super().__init__(subcon)
        self.width = width
        self.height = height

    def _encode(self, image: Image, context, path):
        # No packer found from RGB to BGR;16
        # return image.tobytes("raw", "BGR;16")

        rgb = image.tobytes("raw", "RGB")
        r = itertools.islice(rgb, 0, None, 3)
        g = itertools.islice(rgb, 1, None, 3)
        b = itertools.islice(rgb, 2, None, 3)

        bgr = bytearray(
            byte
            for r_value, g_value, b_value in zip(r, g, b)
            for byte in (
                ((g_value << 3) & 0b11100000) | (b_value >> 3 & 0b00011111),
                (r_value & 0b11111000) | ((g_value >> 2) >> 3 & 0b00000111),
            )
        )

        return b"" + bgr

    def _decode(self, image: bytes, context, path):
        return Image.frombytes("RGB", (self.width, self.height), image, "raw", "BGR;16")


class FirmwareApp(EnumBase):
    OneBL = 1
    TwoUp = 2
    App = 3
    UpApp = 4
    Invalid = 0xFF


FirmwareAppAdapter = IntEnumAdapter(FirmwareApp)


class FirmwareSdkCheckPlatform(EnumBase):
    WindowsPhone = 1
    Windows = 2
    Desktop = 3


FirmwareSdkCheckPlatformAdapter = IntEnumAdapter(FirmwareSdkCheckPlatform)


class SensorType(EnumBase):
    HRDebug = 0x18
    BatteryGauge = 0x26
    AccelGyro_2_4_MS_16G = 0x5E
    LogEntry = 0x7C


SensorTypeAdapter = IntEnumAdapter(SensorType)


class Gender(EnumBase):
    Male = 0
    Female = 1


GenderAdapter = IntEnumAdapter(Gender)


@dataclasses.dataclass
class RGB:
    # TODO: remake as DataclassStruct

    red: int
    green: int
    blue: int

    struct: typing.ClassVar = construct.Struct(
        "red" / Hex(Int8ul),
        "green" / Hex(Int8ul),
        "blue" / Hex(Int8ul),
    )

    def __repr__(self):
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


@dataclasses.dataclass
class ARGB(RGB):
    alpha: int = 255

    struct: typing.ClassVar = construct.Struct(
        "alpha" / Hex(Int8ul),
        "red" / Hex(Int8ul),
        "green" / Hex(Int8ul),
        "blue" / Hex(Int8ul),
    )

    def __repr__(self):
        return f"{super().__repr__()} ({self.alpha/255:.0f}%)"


class ArgbAdapter(Adapter):
    def _encode(self, obj: ARGB, context, path) -> bytes:
        return ARGB.struct.build(vars(ARGB), **context)

    def _decode(self, obj: bytes, context, path) -> ARGB:
        parsed = ARGB.struct.parse(obj)
        return ARGB(alpha=parsed.alpha, red=parsed.red, green=parsed.green, blue=parsed.blue)


ArgbStruct = ArgbAdapter(Bytes(4))


class TileSettings(enum.IntFlag):
    Null = 0
    EnableNotification = 1
    EnableBadging = 2
    UseCustomColorForTile = 4
    EnableAutoUpdate = 8
    ScreenTimeout30Seconds = 16
    ScreenTimeoutDisabled = 32

    @typing.overload
    def __or__(self, other: "TileSettings") -> "TileSettings":
        ...


TileData = Padded(
    16 + 4 + 4 + 2 + 2 + 60,
    construct.Struct(
        "GUID" / GUIDAdapter(Bytes(16)),
        "Order" / Int32ul,
        "ThemeColor" / ArgbStruct,
        "_NameLength" / Default(Int16ul, construct.len_(this.TileName)),
        "SettingsMask" / FlagsEnum(Int16ul, TileSettings),
        "TileName" / PaddedString(this._NameLength * 2, "utf_16_le"),
        "OwnerGUID" / GUIDAdapter(Bytes(16)),
    ),
)


@dataclasses.dataclass(kw_only=True)
class BandSystemTime(DataclassMixin):

    Year: int = csfield(Default(Int16ul, 0))
    Month: int = csfield(Default(Int16ul, 0))
    DayOfWeek: int = csfield(Default(Int16ul, 0))
    Day: int = csfield(Default(Int16ul, 0))
    Hour: int = csfield(Default(Int16ul, 0))
    Minute: int = csfield(Default(Int16ul, 0))
    Second: int = csfield(Default(Int16ul, 0))
    Milliseconds: int = csfield(Default(Int16ul, 0))


BandSystemTimeStruct = DataclassStruct(BandSystemTime)


class BandSystemDateTimeAdapter(Adapter):
    def _decode(self, obj: BandSystemTime, context, path) -> dt.datetime:
        return dt.datetime(
            year=obj.Year,
            month=obj.Month,
            day=obj.Day,
            hour=obj.Hour,
            minute=obj.Minute,
            second=obj.Second,
            microsecond=obj.Milliseconds * 1000,
        )

    def _encode(self, date: dt.datetime, context, path) -> BandSystemTime:
        return BandSystemTime(
            Year=date.year,
            Month=date.month,
            DayOfWeek=date.weekday(),  # TODO: verify
            Day=date.day,
            Hour=date.hour,
            Minute=date.minute,
            Second=date.second,
            Milliseconds=date.microsecond // 1000,
        )


Version = construct.Struct(
    "Major" / Int16ul,
    "Minor" / Int16ul,
    "Revision" / Int32ul,
    "Build" / Int32ul,
    "Debug" / Flag,
)


@dataclasses.dataclass(kw_only=True)
class Profile(DataclassMixin):

    Version: int = csfield(Int16ul)
    LastSync: dt.datetime = csfield(BandTime(Int64ul))
    UserGUID: uuid.UUID = csfield(GUIDAdapter(Bytes(16)))
    Birthday: dt.datetime = csfield(BandTime(Int64ul))
    Weight_g: int = csfield(Int32ul)
    Height_mm: int = csfield(Int16ul)
    Gender: Gender = csfield(TEnum(Int8ul, Gender))
    DeviceName: str = csfield(PaddedString(16 * 2, "utf_16_le"))
    LocaleName: str = csfield(PaddedString(6 * 2, "utf_16_le"))
    LocaleId: LocaleId = csfield(LocaleIdAdapter(Int16ul))
    Language: Language = csfield(LanguageAdapter(Int16ul))
    DateSeparator: str = csfield(PaddedString(1 * 2, "utf_16_le"))
    NumberSeparator: str = csfield(PaddedString(1 * 2, "utf_16_le"))
    DecimalSeparator: str = csfield(PaddedString(1 * 2, "utf_16_le"))
    TimeFormat: DisplayTimeFormat = csfield(DisplayTimeFormatAdapter(Int8ul))
    DateFormat: DisplayDateFormat = csfield(DisplayDateFormatAdapter(Int8ul))
    DistanceShortUnits: UnitType = csfield(UnitTypeAdapter(Int8ul))
    DistanceLongUnits: UnitType = csfield(UnitTypeAdapter(Int8ul))
    MassUnits: UnitType = csfield(UnitTypeAdapter(Int8ul))
    VolumeUnits: UnitType = csfield(UnitTypeAdapter(Int8ul))
    EnergyUnits: UnitType = csfield(UnitTypeAdapter(Int8ul))
    TemperatureUnits: UnitType = csfield(UnitTypeAdapter(Int8ul))
    RunDisplayUnits: UnitType = csfield(UnitTypeAdapter(Int8ul))
    Telemetry: bool = csfield(Default(Flag, False))

    HwagChangeTime: typing.Optional[dt.datetime] = csfield(If(this.Version >= 2, BandTime(Int64ul)))
    HwagChangeAgent: typing.Optional[int] = csfield(If(this.Version >= 2, Int8ul))
    DeviceNameChangeTime: typing.Optional[dt.datetime] = csfield(
        If(this.Version >= 2, BandTime(Int64ul))
    )
    DeviceNameChangeAgent: typing.Optional[int] = csfield(If(this.Version >= 2, Int8ul))
    LocaleSettingsChangeTime: typing.Optional[dt.datetime] = csfield(
        If(this.Version >= 2, BandTime(Int64ul))
    )
    LocaleSettingsChangeAgent: typing.Optional[int] = csfield(If(this.Version >= 2, Int8ul))
    LanguageChangeTime: typing.Optional[dt.datetime] = csfield(
        If(this.Version >= 2, BandTime(Int64ul))
    )
    LanguageChangeAgent: typing.Optional[int] = csfield(If(this.Version >= 2, Int8ul))
    MaxHR: typing.Optional[int] = csfield(If(this.Version >= 2, Int8ul))

    ReservedData: bytes = csfield(construct.GreedyBytes)


PROFILE_SIZE = 397  # is it???
ProfileStruct = Padded(PROFILE_SIZE, DataclassStruct(Profile))


@dataclasses.dataclass(kw_only=True)
class UserProfile(DataclassMixin):

    Version: int = csfield(Int16ul)
    LastSync: dt.datetime = csfield(BandTime(Int64ul))
    UserGUID: uuid.UUID = csfield(GUIDAdapter(Bytes(16)))

    ReservedData: bytes = csfield(Bytes(256))


UserProfileStruct = DataclassStruct(UserProfile)
