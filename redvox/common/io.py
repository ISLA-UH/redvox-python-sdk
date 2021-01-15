"""
This module provides IO primitives for working with cross-API RedVox data.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from glob import glob
import os.path
from pathlib import Path, PurePath
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Optional,
    Set,
    Union,
    TYPE_CHECKING, Callable
)

from redvox.api900.reader import read_rdvxz_file
from redvox.api1000.common.common import check_type
from redvox.api1000.wrapped_redvox_packet.wrapped_packet import WrappedRedvoxPacketM
from redvox.common.versioning import check_version, ApiVersion
from redvox.common.date_time_utils import (
    datetime_from_epoch_microseconds_utc as dt_us,
    datetime_from_epoch_milliseconds_utc as dt_ms,
    truncate_dt_ymd,
    truncate_dt_ymdh
)

if TYPE_CHECKING:
    from redvox.api900.wrapped_redvox_packet import WrappedRedvoxPacket


def _is_int(value: str) -> Optional[int]:
    """
    Tests if a given str is a valid integer. If it is, the integer is returned, if it is not, None is returned.
    :param value: The string to test.
    :return: The integer value if it is valid, or None if it is not valid.
    """
    try:
        return int(value)
    except ValueError:
        return None


def _not_none(value: Any) -> bool:
    """
    Tests that the given value is not None.
    :param value: The value to test.
    :return: True if the value is not None, False if it is None.
    """
    return value is not None


@dataclass
class IndexEntry:
    """
    This class represents a single index entry. It extracts and encapsulated API agnostic fields that represent the
    information stored in standard RedVox file names.
    """
    full_path: str
    station_id: str
    date_time: datetime
    extension: str
    api_version: ApiVersion

    @staticmethod
    def from_path(path_str: str,
                  strict: bool = True) -> Optional['IndexEntry']:
        """
        Attempts to parse a file path into an IndexEntry. If a given path is not recognized as a valid RedVox file, None
        will be returned instead.
        :param path_str: The file system path to attempt to parse.
        :param strict: When set, None is returned if the referenced file DNE.
        :return: Either an IndexEntry or successful parse or None.
        """
        api_version: ApiVersion = check_version(path_str)
        path: Path = Path(path_str)
        name: str = path.stem
        ext: str = path.suffix

        # Attempt to parse file name parts
        split_name = name.split("_")
        if len(split_name) != 2:
            return None

        station_id: str = split_name[0]
        ts_str: str = split_name[1]

        # If you have a filename with a dot, but not an extension, i.e. "0000000001_0.", we need to remove the dot
        # from the end and make in the extension
        if len(ts_str) > 0 and ts_str[-1] == ".":
            ts_str = ts_str[:-1]
            ext = "."

        timestamp: Optional[int] = _is_int(ts_str)

        # Ensure that both the station ID and timestamp can be represented as ints
        if _is_int(station_id) is None or timestamp is None:
            return None

        # Parse the datetime per the specified API version
        date_time: datetime
        if api_version == ApiVersion.API_1000:
            date_time = dt_us(timestamp)
        else:
            date_time = dt_ms(timestamp)

        full_path: str
        try:
            full_path = str(path.resolve(strict=True))
        except FileNotFoundError:
            if strict:
                return None
            full_path = path_str

        return IndexEntry(full_path,
                          station_id,
                          date_time,
                          ext,
                          api_version)

    def read(self) -> Optional[Union[WrappedRedvoxPacketM, 'WrappedRedvoxPacket']]:
        """
        Reads, decompresses, deserializes, and wraps the RedVox file pointed to by this entry.
        :return: One of WrappedRedvoxPacket, WrappedRedvoxPacketM, or None.
        """
        if self.api_version == ApiVersion.API_900:
            return read_rdvxz_file(self.full_path)
        elif self.api_version == ApiVersion.API_1000:
            return WrappedRedvoxPacketM.from_compressed_path(self.full_path)
        else:
            return None

    # def __lt__(self, other: 'IndexEntry') -> bool:
    #     """
    #     Tests if this value is less than another value.
    #
    #     This along with __eq__ are used to fulfill the total ordering contract. Compares this entry's full path to
    #     another entries full path.
    #     :param other: Other IndexEntry to compare against.
    #     :return: True if this full path is less than the other full path.
    #     """
    #     return self.full_path.__lt__(other.full_path)

    def __eq__(self, other: object) -> bool:
        """
        Tests if this value is equal to another value.

        This along with __lt__ are used to fulfill the total ordering contract. Compares this entry's full path to
        another entries full path.
        :param other: Other IndexEntry to compare against.
        :return: True if this full path is less than the other full path.
        """
        if isinstance(other, IndexEntry):
            return self.full_path == other.full_path

        return False


# noinspection DuplicatedCode
@dataclass
class ReadFilter:
    """
    Filter RedVox files from the file system.
    """
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None
    station_ids: Optional[Set[str]] = None
    extensions: Optional[Set[str]] = field(default_factory=lambda: {".rdvxm", ".rdvxz"})
    start_dt_buf: Optional[timedelta] = timedelta(minutes=2.0)
    end_dt_buf: Optional[timedelta] = timedelta(minutes=2.0)
    api_versions: Optional[Set[ApiVersion]] = field(default_factory=lambda: {ApiVersion.API_900, ApiVersion.API_1000})

    @staticmethod
    def empty() -> 'ReadFilter':
        """
        :return: A ReadFilter with ALL filters set to None. This is opposed to the default
                 which sets sane defaults for extensions, APIs, and window buffers.
        """
        return ReadFilter(None, None, None, None, None, None, None)

    def with_start_dt(self, start_dt: Optional[datetime]) -> 'ReadFilter':
        """
        Adds a start datetime filter.
        :param start_dt: Start datetime that files should come after.
        :return: A modified instance of this filter
        """
        check_type(start_dt, [datetime, None])
        self.start_dt = start_dt
        return self

    def with_start_ts(self, start_ts: Optional[float]) -> 'ReadFilter':
        """
        Adds a start time filter.
        :param start_ts: Start timestamp (microseconds)
        :return: A modified instance of this filter
        """
        check_type(start_ts, [int, float, None])
        if start_ts is None:
            return self.with_start_dt(None)

        return self.with_start_dt(dt_us(start_ts))

    def with_end_dt(self, end_dt: Optional[datetime]) -> 'ReadFilter':
        """
        Adds an end datetime filter.
        :param end_dt: Filter for which packets should come before.
        :return: A modified instance of this filter
        """
        check_type(end_dt, [datetime, None])
        self.end_dt = end_dt
        return self

    def with_end_ts(self, end_ts: Optional[float]) -> 'ReadFilter':
        """
        Like with_end_dt, but uses a microsecond timestamp.
        :param end_ts: Timestamp microseconds.
        :return: A modified instance of this filter
        """
        check_type(end_ts, [int, float, None])
        if end_ts is None:
            return self.with_end_dt(None)

        return self.with_end_dt(dt_us(end_ts))

    def with_station_ids(self, station_ids: Optional[Set[str]]) -> 'ReadFilter':
        """
        Add a station id filter. Filters against provided station ids.
        :param station_ids: Station ids to filter against.
        :return: A modified instance of this filter
        """
        check_type(station_ids, [set, None])
        self.station_ids = station_ids
        return self

    def with_extensions(self, extensions: Optional[Set[str]]) -> 'ReadFilter':
        """
        Filters against known file extensions.
        :param extensions: One or more extensions to filter against
        :return: A modified instance of this filter
        """
        check_type(extensions, [set, None])
        self.extensions = extensions
        return self

    def with_start_dt_buf(self, start_dt_buf: Optional[timedelta]) -> 'ReadFilter':
        """
        Modifies the time buffer prepended to the start time.
        :param start_dt_buf: Amount of time to buffer before start time.
        :return: A modified instance of self.
        """
        check_type(start_dt_buf, [timedelta, None])
        self.start_dt_buf = start_dt_buf
        return self

    def with_end_dt_buf(self, end_dt_buf: Optional[timedelta]) -> 'ReadFilter':
        """
        Modifies the time buffer appended to the end time.
        :param end_dt_buf: Amount of time to buffer after end time.
        :return: A modified instance of self.
        """
        check_type(end_dt_buf, [timedelta, None])
        self.end_dt_buf = end_dt_buf
        return self

    def with_api_versions(self, api_versions: Optional[Set[ApiVersion]]) -> 'ReadFilter':
        """
        Filters for specified API versions.
        :param api_versions: A set containing valid ApiVersion enums that should be included.
        :return: A modified instance of self.
        """
        check_type(api_versions, [set, None])
        self.api_versions = api_versions
        return self

    def apply_dt(self, date_time: datetime,
                 dt_fn: Callable[[datetime], datetime] = lambda dt: dt) -> bool:
        """
        Tests if a given datetime passes this filter.
        :param date_time: Datetime to test
        :param dt_fn: An (optional) function that will transform one datetime into another.
        :return: True if the datetime is included, False otherwise
        """
        check_type(date_time, [datetime])
        start_buf: timedelta = timedelta(seconds=0) if self.start_dt_buf is None else self.start_dt_buf
        if self.start_dt is not None and date_time < (dt_fn(self.start_dt) - start_buf):
            return False

        end_buf: timedelta = timedelta(seconds=0) if self.end_dt_buf is None else self.end_dt_buf
        if self.end_dt is not None and date_time > (dt_fn(self.end_dt) + end_buf):
            return False

        return True

    def apply(self, entry: IndexEntry) -> bool:
        """
        Applies this filter to the given IndexEntry.
        :param entry: The entry to test.
        :return: True if the entry is accepted by the filter, False otherwise.
        """
        check_type(entry, [IndexEntry])

        if not self.apply_dt(entry.date_time):
            return False

        if self.station_ids is not None and entry.station_id not in self.station_ids:
            return False

        if self.extensions is not None and entry.extension not in self.extensions:
            return False

        if self.api_versions is not None and entry.api_version not in self.api_versions:
            return False

        return True


@dataclass
class IndexStationSummary:
    """
    Summary of a single station in the index.
    """
    station_id: str
    api_version: ApiVersion
    total_packets: int
    first_packet: datetime
    last_packet: datetime

    @staticmethod
    def from_entry(entry: IndexEntry) -> 'IndexStationSummary':
        """
        Instantiates a new summary from a given IndexEntry.
        :param entry: Entry to copy information from.
        :return: An instance of IndexStationSummary.
        """
        return IndexStationSummary(
            entry.station_id,
            entry.api_version,
            1,
            first_packet=entry.date_time,
            last_packet=entry.date_time)

    def update(self, entry: IndexEntry) -> None:
        """
        Updates this summary given a new index entry.
        :param entry: Entry to update this summary from.
        """
        self.total_packets += 1
        if entry.date_time < self.first_packet:
            self.first_packet = entry.date_time

        if entry.date_time > self.last_packet:
            self.last_packet = entry.date_time


@dataclass
class IndexSummary:
    """
    Summarizes the contents of the index.
    """
    station_summaries: Dict[ApiVersion, Dict[str, IndexStationSummary]]

    def station_ids(self, api_version: ApiVersion = None) -> List[str]:
        """
        Returns the station IDs referenced by this index.
        :param api_version: An (optional) filter to only return packets for a specified RedVox API version.
                            None will collect station IDs from all API versions.
        :return: The station IDs referenced by this index.
        """
        if api_version is not None:
            return list(set(map(lambda summary: summary.station_id, self.station_summaries[api_version].values())))
        else:
            # noinspection PyTypeChecker
            return list(set(map(lambda summary: summary.station_id,
                                self.station_summaries[ApiVersion.API_900].values()))) + \
                   list(set(map(lambda summary: summary.station_id,
                                self.station_summaries[ApiVersion.API_1000].values())))

    def total_packets(self, api_version: ApiVersion = None) -> int:
        """
        Returns the total number of packets referenced by this index.
        :param api_version: An (optional) filter to only return packets for a specified RedVox API version.
                            None will count packets from all API versions.
        :return: The total number of packets referenced by this index.
        """
        if api_version is not None:
            return sum(map(lambda summary: summary.total_packets, self.station_summaries[api_version].values()))
        else:
            # noinspection PyTypeChecker
            return sum(map(lambda summary: summary.total_packets,
                           self.station_summaries[ApiVersion.API_900].values())) + \
                   sum(map(lambda summary: summary.total_packets,
                           self.station_summaries[ApiVersion.API_1000].values()))

    @staticmethod
    def from_index(index: 'Index') -> 'IndexSummary':
        """
        Builds an IndexSummary from a given index.
        :param index: Index to build summary from.
        :return: An instance of IndexSummary.
        """
        station_summaries: Dict[ApiVersion, Dict[str, IndexStationSummary]] = defaultdict(dict)

        entry: IndexEntry
        for entry in index.entries:
            sub_entry: Dict[str, IndexStationSummary] = station_summaries[entry.api_version]
            if entry.station_id in sub_entry:
                # Update existing station summary
                sub_entry[entry.station_id].update(entry)
            else:
                # Create new station summary
                sub_entry[entry.station_id] = IndexStationSummary.from_entry(entry)

        return IndexSummary(station_summaries)


@dataclass
class Index:
    """
    An index of available RedVox files from the file system.
    """
    entries: List[IndexEntry] = field(default_factory=lambda: [])

    def sort(self) -> None:
        """
        Sorts the entries stored in this index.
        """
        self.entries = sorted(self.entries,
                              key=lambda entry: (entry.api_version, entry.station_id, entry.date_time))

    def append(self, entries: Iterator[IndexEntry]) -> None:
        """
        Appends new entries to this index.
        :param entries: Entries to append.
        """
        self.entries.extend(entries)

    def summarize(self) -> IndexSummary:
        """
        :return: A summary of the contents of this index.
        """
        return IndexSummary.from_index(self)

    def stream(self, read_filter: ReadFilter = ReadFilter()) -> Iterator[
            Union['WrappedRedvoxPacket', WrappedRedvoxPacketM]]:
        """
        Read, decompress, deserialize, wrap, and then stream RedVox data pointed to by this index.
        :param read_filter: Additional filtering to specify which data should be streamed.
        :return: An iterator over WrappedRedvoxPacket and WrappedRedvoxPacketM instances.
        """
        filtered: Iterator[IndexEntry] = filter(lambda entry: read_filter.apply(entry), self.entries)
        # noinspection Mypy
        return map(IndexEntry.read, filtered)

    def read(self, read_filter: ReadFilter = ReadFilter()) -> List[Union['WrappedRedvoxPacket', WrappedRedvoxPacketM]]:
        return list(self.stream(read_filter))


# The following constants are used for identifying valid RedVox API 900 and API 1000 structured directory layouts.
__VALID_YEARS: Set[str] = {f"{i:04}" for i in range(2015, 2031)}
__VALID_MONTHS: Set[str] = {f"{i:02}" for i in range(1, 13)}
__VALID_DATES: Set[str] = {f"{i:02}" for i in range(1, 32)}
__VALID_HOURS: Set[str] = {f"{i:02}" for i in range(0, 24)}


def _list_subdirs(base_dir: str, valid_choices: Set[str]) -> List[str]:
    """
    Lists sub-directors in a given base directory that match the provided choices.
    :param base_dir: Base dir to find sub dirs in.
    :param valid_choices: A list of valid directory names.
    :return: A list of valid subdirs.
    """
    subdirs: Iterator[str] = map(lambda p: PurePath(p).name, glob(os.path.join(base_dir, "*", "")))
    return sorted(list(filter(valid_choices.__contains__, subdirs)))


def index_unstructured(base_dir: str, read_filter: ReadFilter = ReadFilter()) -> Index:
    """
    Returns the list of file paths that match the given filter for unstructured data.
    :param base_dir: Directory containing unstructured data.
    :param read_filter: An (optional) ReadFilter for specifying station IDs and time windows.
    :return: An iterator of valid paths.
    """
    check_type(base_dir, [str])
    check_type(read_filter, [ReadFilter])

    index: Index = Index()

    extensions: Set[str] = read_filter.extensions if read_filter.extensions is not None else {""}

    extension: str
    for extension in extensions:
        pattern: str = str(PurePath(base_dir).joinpath(f"*{extension}"))
        paths: List[str] = glob(os.path.join(base_dir, pattern))
        # noinspection Mypy
        entries: Iterator[IndexEntry] = filter(read_filter.apply, filter(_not_none, map(IndexEntry.from_path, paths)))
        index.append(entries)

    index.sort()
    return index


def index_structured_api_900(base_dir: str, read_filter: ReadFilter = ReadFilter()) -> Index:
    """
    This parses a structured API 900 directory structure and identifies files that match the provided filter.
    :param base_dir: Base directory (should be named api900)
    :param read_filter: Filter to filter files with
    :return: A list of wrapped packets on an empty list if none match the filter or none are found
    """
    index: Index = Index()

    for year in _list_subdirs(base_dir, __VALID_YEARS):
        for month in _list_subdirs(os.path.join(base_dir, year), __VALID_MONTHS):
            for day in _list_subdirs(os.path.join(base_dir, year, month), __VALID_DATES):
                # Before scanning for *.rdvxm files, let's see if the current year, month, day, are in the
                # filter's range. If not, we can short circuit and skip getting the *.rdvxz files.
                if not read_filter.apply_dt(datetime(int(year),
                                                     int(month),
                                                     int(day)),
                                            dt_fn=truncate_dt_ymd):
                    continue

                data_dir: str = os.path.join(base_dir, year, month, day)
                entries: Iterator[IndexEntry] = iter(index_unstructured(data_dir, read_filter).entries)
                index.append(entries)

    index.sort()
    return index


def index_structured_api_1000(base_dir: str, read_filter: ReadFilter = ReadFilter()) -> Index:
    """
    This parses a structured API M directory structure and identifies files that match the provided filter.
    :param base_dir: Base directory (should be named api1000)
    :param read_filter: Filter to filter files with
    :return: A list of wrapped packets on an empty list if none match the filter or none are found
    """
    index: Index = Index()

    for year in _list_subdirs(base_dir, __VALID_YEARS):
        for month in _list_subdirs(os.path.join(base_dir, year), __VALID_MONTHS):
            for day in _list_subdirs(os.path.join(base_dir, year, month), __VALID_DATES):
                for hour in _list_subdirs(os.path.join(base_dir, year, month, day), __VALID_HOURS):
                    # Before scanning for *.rdvxm files, let's see if the current year, month, day, hour are in the
                    # filter's range. If not, we can short circuit and skip getting the *.rdvxm files.
                    if not read_filter.apply_dt(datetime(int(year),
                                                         int(month),
                                                         int(day),
                                                         int(hour)),
                                                dt_fn=truncate_dt_ymdh):
                        continue

                    data_dir: str = os.path.join(base_dir, year, month, day, hour)
                    entries: Iterator[IndexEntry] = iter(index_unstructured(data_dir, read_filter).entries)
                    index.append(entries)

    index.sort()
    return index


def index_structured(base_dir: str, read_filter: ReadFilter = ReadFilter()) -> Index:
    """
    "Indexes both API 900 and API 1000 structured directory layouts.
    :param base_dir: The base_dir may either end with api900, api1000, or be a parent directory to one or both of
                     API 900 and API 1000.
    :param read_filter: Filter to further filter results.
    :return: An Index of RedVox files.
    """
    base_path: PurePath = PurePath(base_dir)

    # API 900
    if base_path.name == "api900":
        return index_structured_api_900(base_dir, read_filter)
    # API 1000
    elif base_path.name == "api1000":
        return index_structured_api_1000(base_dir, read_filter)
    # Maybe parent to one or both?
    else:
        index: Index = Index()
        subdirs: List[str] = _list_subdirs(base_dir, {"api900", "api1000"})
        if "api900" in subdirs:
            index.append(iter(index_structured_api_900(str(base_path.joinpath("api900")), read_filter).entries))

        if "api1000" in subdirs:
            index.append(iter(index_structured_api_1000(str(base_path.joinpath("api1000")), read_filter).entries))

        index.sort()
        return index
