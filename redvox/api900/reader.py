# pylint: disable=too-many-lines
"""
This module provides functions and classes for working with RedVox API 900 data.
"""

import collections
import glob
import os
import os.path
import typing

import redvox.api900.lib.api900_pb2 as api900_pb2
import redvox.api900.concat as concat
import redvox.api900.date_time_utils as date_time_utils
import redvox.api900.reader_utils as reader_utils

# For backwards compatibility, we want to expose as much as we can from this file since everything used to live in this
# file. This will allow old code that referenced everything through this module to still function. Someday "soon" we
# should probably deprecate this.
from redvox.api900.wrapped_redvox_packet import WrappedRedvoxPacket
from redvox.api900.sensors.interleaved_channel import InterleavedChannel
from redvox.api900.sensors.unevenly_sampled_channel import UnevenlySampledChannel
from redvox.api900.sensors.evenly_sampled_channel import EvenlySampledChannel
from redvox.api900.sensors.evenly_sampled_sensor import EvenlySampledSensor
from redvox.api900.sensors.unevenly_sampled_sensor import UnevenlySampledSensor
from redvox.api900.sensors.xyz_unevenly_sampled_sensor import XyzUnevenlySampledSensor
from redvox.api900.sensors.microphone_sensor import MicrophoneSensor
from redvox.api900.sensors.barometer_sensor import BarometerSensor
from redvox.api900.sensors.location_sensor import LocationSensor
from redvox.api900.sensors.time_synchronization_sensor import TimeSynchronizationSensor
from redvox.api900.sensors.accelerometer_sensor import AccelerometerSensor
from redvox.api900.sensors.magnetometer_sensor import MagnetometerSensor
from redvox.api900.sensors.gyroscope_sensor import GyroscopeSensor
from redvox.api900.sensors.light_sensor import LightSensor
from redvox.api900.sensors.infrared_sensor import InfraredSensor
from redvox.api900.sensors.image_sensor import ImageSensor

WrappedRedvoxPackets = typing.List[WrappedRedvoxPacket]
RedvoxSensor = typing.Union[
    EvenlySampledSensor,
    UnevenlySampledSensor,
    MicrophoneSensor,
    BarometerSensor,
    LocationSensor,
    TimeSynchronizationSensor,
    AccelerometerSensor,
    GyroscopeSensor,
    MagnetometerSensor,
    LightSensor,
    InfraredSensor,
    ImageSensor
]
RedvoxSensors = typing.List[RedvoxSensor]


def wrap(redvox_packet: api900_pb2.RedvoxPacket) -> WrappedRedvoxPacket:
    """
    Wraps a protobuf packet in a WrappedRedocPacket.
    :param redvox_packet: Protobuf packet to wrap.
    :return: A WrappedRedvoxPacket.
    """
    return WrappedRedvoxPacket(redvox_packet)


def read_buffer(buf: bytes, is_compressed: bool = True) -> api900_pb2.RedvoxPacket:
    """
    Deserializes a serialized protobuf RedvoxPacket buffer.
    :param buf: Buffer to deserialize.
    :param is_compressed: Whether or not the buffer is compressed or decompressed.
    :return: Deserialized protobuf redvox packet.
    """
    buffer = reader_utils.lz4_decompress(buf) if is_compressed else buf
    redvox_packet = api900_pb2.RedvoxPacket()
    redvox_packet.ParseFromString(buffer)
    return redvox_packet


def read_file(file: str, is_compressed: bool = None) -> api900_pb2.RedvoxPacket:
    """
    Deserializes a serialized protobuf RedvoxPacket file.
    :param file: File to deserialize.
    :param is_compressed: Whether or not the file is compressed or decompressed.
    :return: Deserialized protobuf redvox packet.
    """
    file_ext = file.split(".")[-1]

    if is_compressed is None:
        _is_compressed = True if file_ext == "rdvxz" else False
    else:
        _is_compressed = is_compressed
    with open(file, "rb") as fin:
        return read_buffer(fin.read(), _is_compressed)


def read_rdvxz_file(path: str) -> WrappedRedvoxPacket:
    """
    Reads a .rdvxz file from the specified path and returns a WrappedRedvoxPacket.
    :param path: The path of the file.
    :return: A WrappedRedvoxPacket.
    """
    return wrap(read_file(path))


def _is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except ValueError:
        return False


def _is_valid_redvox_filename(filename: str) -> bool:
    return len(filename) == 30 \
            and _is_int(filename[0:10]) \
            and filename[10:11] == "_" \
            and _is_int(filename[11:24]) \
            and filename[24:len(filename)] == ".rdvxz"


def _is_path_in_set(path: str,
                    start_timestamp_utc_s: int,
                    end_timestamp_utc_s: int,
                    redvox_ids: typing.Set[str] = set()) -> bool:
    """
    Determines whether a given path is in a provided time range and set of redvox_ids.
    :param path: The path to
    :param start_timestamp_utc_s:
    :param end_timestamp_utc_s:
    :param redvox_ids:
    :return:
    """
    filename = path.split(os.sep)[-1]

    if not _is_valid_redvox_filename(filename):
        return False

    timestamp = int(date_time_utils.milliseconds_to_seconds(float(filename[11:24])))

    if not (start_timestamp_utc_s <= timestamp <= end_timestamp_utc_s):
        return False

    if len(redvox_ids)> 0:
        if len(redvox_ids) > 0:
            redvox_id = filename[0:10]
            if redvox_id not in redvox_ids:
                return False

    return True


def _get_structured_paths(directory: str,
                          start_timestamp_utc_s: int,
                          end_timestamp_utc_s: int,
                          redvox_ids: typing.Set[str] = set()) -> typing.List[str]:
    """
    Given a base directory (which should end with api900), find the paths of all structured .rdvxz files.
    :param directory: The base directory path (which should end with api900)
    :param start_timestamp_utc_s: Start timestamp as seconds since the epoch UTC.
    :param end_timestamp_utc_s: End timestamp as seconds since the epoch UTC.
    :param redvox_ids: An optional set of redvox_ids to filter against.
    :return: A list of paths in a structured layout of filtered .rdvxz files.
    """
    paths = []
    for (year, month, day) in date_time_utils.DateIterator(start_timestamp_utc_s, end_timestamp_utc_s):
        all_paths = glob.glob(os.path.join(directory, year, month, day, "*.rdvxz"))
        valid_paths = list(
            filter(lambda path: _is_path_in_set(path, start_timestamp_utc_s, end_timestamp_utc_s, redvox_ids),
                   all_paths))
        paths.extend(valid_paths)
    return paths


# These type vars are used for defining a generic group by function further down.
T = typing.TypeVar("T")
TT = typing.TypeVar("TT")


def _group_by(grouping_fn: typing.Callable[[T], TT],
              items: typing.Iterable[T]) -> typing.Dict[TT, typing.List[T]]:
    """
    Groups items by a grouping function.
    :param grouping_fn: A function that takes an item and returns a key that should be used to group the items.
    :param items: The items to group.
    :return: A dictionary where each key groups similar items into the value.
    """
    grouped = collections.defaultdict(list)

    for item in items:
        grouped[grouping_fn(item)].append(item)
    return grouped


def _id_uuid(wrapped_redvox_packet: WrappedRedvoxPacket) -> str:
    """
    Extracts and formats the redvox id and uuid from a WrappedRedvoxPacket.
    :param wrapped_redvox_packet: Packet to extract redvox id and uuid from.
    :return: Formatted redvox_id:uuid
    """
    return "%s:%s" % (wrapped_redvox_packet.redvox_id(),
                      wrapped_redvox_packet.uuid())


def read_rdvxz_file_range(directory: str,
                          start_timestamp_utc_s: int,
                          end_timestamp_utc_s: int,
                          redvox_ids: typing.List[str] = [],
                          structured_layout: bool = False,
                          concat_continuous_segments: bool = True) -> typing.Dict[
    str, typing.List[WrappedRedvoxPacket]]:
    """
    Reads a range of .rdvxz files from a given directory.

    Given start and end timestamps which represent UNIX time (the number of seconds from the epoch) UTC and an
    optional set of redvox ids, this function reads .rdvxz within the given time range with the given redvox ids. If
    not redvox ids are provided, all valid .rdvxz files within the given time range will be included.

    We also support a standardized structured layout. The structured layout organizes .rdvxz files by api, year, month,
    and day. The structured layout is as follows. api900/YYYY/MM/DD/*.rdvxz where YYYY is the year, MM is the month,
    and DD is the day. When using the structured layout option, be sure that the root directory path is api900.
    :param directory: The root directory of the data. If structured_layout is False, then this directory will contain
                      various unorganized .rdvxz files. If structured_layout is True, then this directory must be the
                      root api900 directory of the structured files.
    :param start_timestamp_utc_s: The start timestamp as seconds since the epoch UTC.
    :param end_timestamp_utc_s: The end timestamp as seconds since the epoch UTC.
    :param redvox_ids: An optional list of redvox_ids to filter against (default=[]).
    :param structured_layout: An optional value to define if this is loading structured data (default=False).
    :param concat_continuous_segments: An optional value to define if this function should concatenate rdvxz files into
                                       a multiple continuous rdvxz files seperated at gaps.
    :return: A dictionary where each key is a single redvox id and each value is a list of ordered WrappedRedvoxPackets.
    """

    # Remove trailing directory separators
    while directory.endswith("/") or directory.endswith("\\"):
        directory = directory[:-1]

    if structured_layout:
        paths = _get_structured_paths(directory,
                                      start_timestamp_utc_s,
                                      end_timestamp_utc_s,
                                      set(redvox_ids))
    else:
        all_paths = glob.glob(os.path.join(directory, "*.rdvxz"))
        paths = list(
            filter(lambda path: _is_path_in_set(path, start_timestamp_utc_s, end_timestamp_utc_s, set(redvox_ids)),
                   all_paths))

    # Convert to WrappedRedvoxPackets
    wrapped_redvox_packets = map(read_rdvxz_file, paths)

    # Group by redvox_id
    grouped = _group_by(_id_uuid, wrapped_redvox_packets)

    # Sort
    for packets in grouped.values():
        packets.sort(key=WrappedRedvoxPacket.app_file_start_timestamp_machine)

    # If not concatenating, return what we have
    if not concat_continuous_segments:
        return grouped

    # Otherwise, concatenate and return
    for id_uuid in grouped:
        grouped[id_uuid] = concat.concat_wrapped_redvox_packets(grouped[id_uuid])

    return grouped


def read_rdvxz_buffer(buf: bytes) -> WrappedRedvoxPacket:
    """
    Reads a .rdvxz file from the provided buffer and returns a WrappedRedvoxPacket.
    :param buf: The buffer of bytes consisting of a compressed .rdvxz file.
    :return: A WrappedRedvoxPacket.
    """
    return wrap(read_buffer(buf))


def read_json_file(path: str) -> WrappedRedvoxPacket:
    """
    Reads a RedVox compliant API 900 .json file from the provided path and returns a WrappedRedvoxPacket.
    :param path: Path to the RedVox compliant API 900 .json file.
    :return: A WrappedRedvoxPacket.
    """
    with open(path, "r") as json_in:
        return wrap(reader_utils.from_json(json_in.read()))


def read_json_string(json: str) -> WrappedRedvoxPacket:
    """
    Reads a RedVox compliant API 900 json string and returns a WrappedRedvoxPacket.
    :param json: RedVox API 900 compliant json string.
    :return: A WrappedRedvoxPacket.
    """
    return wrap(reader_utils.from_json(json))


def read_directory(directory_path: str) -> typing.Dict[str, typing.List[WrappedRedvoxPacket]]:
    """
    Reads .rdvxz files from a directory and returns a dictionary from redvox_id -> a list of sorted wrapped redvox
    packets that belong to that device.
    :param directory_path: The path to the directory containing .rdvxz files.
    :return: A dictionary representing a mapping from redvox_id to its packets.
    """

    # Make sure the directory ends with a trailing slash "/"
    if directory_path[-1] != "/":
        directory_path = directory_path + "/"

    file_paths = sorted(glob.glob(directory_path + "*.rdvxz"))
    protobuf_packets = map(read_file, file_paths)
    wrapped_packets = list(map(wrap, protobuf_packets))
    grouped = collections.defaultdict(list)

    for wrapped_packet in wrapped_packets:
        grouped[wrapped_packet.redvox_id()].append(wrapped_packet)

    return grouped
