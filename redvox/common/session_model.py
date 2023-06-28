import os.path
from typing import List, Dict, Optional, Tuple, Union, Callable
from pathlib import Path
from dataclasses_json import dataclass_json
from dataclasses import dataclass, field
from bisect import insort

import numpy as np

import redvox
import redvox.api1000.proto.redvox_api_m_pb2 as api_m
import redvox.common.session_io as s_io
import redvox.common.date_time_utils as dtu
from redvox.cloud import session_model_api as sm
from redvox.common.timesync import TimeSync
from redvox.common.errors import RedVoxExceptions, RedVoxError
from redvox.common.date_time_utils import datetime_from_epoch_microseconds_utc
from redvox.api1000.wrapped_redvox_packet.sensors.location import LocationProvider
from redvox.common.session_model_utils import TimeSyncModel, SensorModel, MetricsSessionModel


SESSION_VERSION = "2023-06-26"  # Version of the SessionModel
CLIENT_NAME = "redvox-sdk/session_model"  # Name of the client used to create the SessionModel
CLIENT_VERSION = SESSION_VERSION  # Version of the client used to create the SessionModel
APP_NAME = "RedVox"  # Default name of the app
DAILY_SESSION_NAME = "Day"  # Identifier for day-long dynamic sessions
HOURLY_SESSION_NAME = "Hour"  # Identifier for hour-long dynamic sessions
GPS_TRAVEL_MICROS = 60000.  # Assumed GPS latency in microseconds
GPS_VALIDITY_BUFFER = 2000.  # microseconds before GPS offset is considered valid
DEGREES_TO_METERS = 0.00001  # About 1 meter in degrees
NUM_BUFFER_POINTS = 3  # number of data points to keep in a buffer
MOVEMENT_METERS = 5.  # number of meters before station is considered moved

COLUMN_TO_ENUM_FN = {"location_provider": lambda l: LocationProvider(l).name}

# These are used for checking if a field is present or not
_ACCELEROMETER_FIELD_NAME: str = "accelerometer"
_AMBIENT_TEMPERATURE_FIELD_NAME: str = "ambient_temperature"
_AUDIO_FIELD_NAME: str = "audio"
_COMPRESSED_AUDIO_FIELD_NAME: str = "compressed_audio"
_GRAVITY_FIELD_NAME: str = "gravity"
_GYROSCOPE_FIELD_NAME: str = "gyroscope"
_IMAGE_FIELD_NAME: str = "image"
_LIGHT_FIELD_NAME: str = "light"
_LINEAR_ACCELERATION_FIELD_NAME: str = "linear_acceleration"
_LOCATION_FIELD_NAME: str = "location"
_MAGNETOMETER_FIELD_NAME: str = "magnetometer"
_ORIENTATION_FIELD_NAME: str = "orientation"
_PRESSURE_FIELD_NAME: str = "pressure"
_PROXIMITY_FIELD_NAME: str = "proximity"
_RELATIVE_HUMIDITY_FIELD_NAME: str = "relative_humidity"
_ROTATION_VECTOR_FIELD_NAME: str = "rotation_vector"
_VELOCITY_FIELD_NAME: str = "velocity"
_HEALTH_FIELD_NAME: str = "health"


Sensor = Union[
    api_m.RedvoxPacketM.Sensors.Xyz,
    api_m.RedvoxPacketM.Sensors.Single,
    api_m.RedvoxPacketM.Sensors.Audio,
    api_m.RedvoxPacketM.Sensors.Image,
    api_m.RedvoxPacketM.Sensors.Location,
    api_m.RedvoxPacketM.Sensors.CompressedAudio,
    api_m.RedvoxPacketM.StationInformation.StationMetrics
]

__SENSOR_NAME_TO_SENSOR_FN: Dict[
    str,
    Optional[
        Callable[
            [api_m.RedvoxPacketM],
            Union[Sensor],
        ]
    ],
] = {
    "unknown": None,
    _HEALTH_FIELD_NAME: lambda packet: packet.station_information.station_metrics,
    _ACCELEROMETER_FIELD_NAME: lambda packet: packet.sensors.accelerometer,
    _AMBIENT_TEMPERATURE_FIELD_NAME: lambda packet: packet.sensors.ambient_temperature,
    _AUDIO_FIELD_NAME: lambda packet: packet.sensors.audio,
    _COMPRESSED_AUDIO_FIELD_NAME: lambda packet: packet.sensors.compressed_audio,
    _GRAVITY_FIELD_NAME: lambda packet: packet.sensors.gravity,
    _GYROSCOPE_FIELD_NAME: lambda packet: packet.sensors.gyroscope,
    _IMAGE_FIELD_NAME: lambda packet: packet.sensors.image,
    _LIGHT_FIELD_NAME: lambda packet: packet.sensors.light,
    _LINEAR_ACCELERATION_FIELD_NAME: lambda packet: packet.sensors.linear_acceleration,
    _LOCATION_FIELD_NAME: lambda packet: packet.sensors.location,
    _MAGNETOMETER_FIELD_NAME: lambda packet: packet.sensors.magnetometer,
    _ORIENTATION_FIELD_NAME: lambda packet: packet.sensors.orientation,
    _PRESSURE_FIELD_NAME: lambda packet: packet.sensors.pressure,
    _PROXIMITY_FIELD_NAME: lambda packet: packet.sensors.proximity,
    _RELATIVE_HUMIDITY_FIELD_NAME: lambda packet: packet.sensors.relative_humidity,
    _ROTATION_VECTOR_FIELD_NAME: lambda packet: packet.sensors.rotation_vector,
    _VELOCITY_FIELD_NAME: lambda packet: packet.sensors.velocity,
}


def _get_sensor_for_data_extraction(sensor_name: str, packet: api_m.RedvoxPacketM) -> Optional[Sensor]:
    """
    :param sensor_name: name of sensor to return
    :param packet: the data packet to get the sensor from
    :return: Sensor that matches the sensor_name or None if that Sensor doesn't exist
    """
    sensor_fn: Optional[
        Callable[[api_m.RedvoxPacketM], Sensor]
    ] = __SENSOR_NAME_TO_SENSOR_FN[sensor_name]
    if (sensor_name == _HEALTH_FIELD_NAME or _has_sensor(packet, sensor_name)) and sensor_fn is not None:
        return sensor_fn(packet)


def _get_mean_sample_rate_from_sensor(sensor: Sensor) -> float:
    """
    :param sensor: Sensor to get data from
    :return: number of samples and mean sample rate of the sensor; returns np.nan if sample rate doesn't exist
    """
    num_pts = int(sensor.timestamps.timestamp_statistics.count)
    if num_pts > 1:
        return sensor.timestamps.mean_sample_rate
    return np.nan


def _has_sensor(
        data: Union[api_m.RedvoxPacketM, api_m.RedvoxPacketM.Sensors], field_name: str
) -> bool:
    """
    Returns true if the given packet or sensors instance contains the valid sensor.

    :param data: Either a packet or a packet's sensors message.
    :param field_name: The name of the sensor being checked.
    :return: True if the sensor exists, False otherwise.
    """
    if isinstance(data, api_m.RedvoxPacketM):
        # noinspection Mypy,PyTypeChecker
        return data.sensors.HasField(field_name)

    if isinstance(data, api_m.RedvoxPacketM.Sensors):
        # noinspection Mypy,PyTypeChecker
        return data.HasField(field_name)

    return False


def get_all_sensors_in_packet(packet: api_m.RedvoxPacketM) -> List[Tuple[str, str, float]]:
    """
    :param packet: packet to check
    :return: list of all sensors as tuple of name, description, and mean sample rate in the packet
    """
    result: List[Tuple] = []
    for s in [_AUDIO_FIELD_NAME, _COMPRESSED_AUDIO_FIELD_NAME]:
        if _has_sensor(packet, s):
            sensor = _get_sensor_for_data_extraction(s, packet)
            result.append((s, sensor.sensor_description, sensor.sample_rate))
    for s in [_PRESSURE_FIELD_NAME, _LOCATION_FIELD_NAME,
              _ACCELEROMETER_FIELD_NAME, _AMBIENT_TEMPERATURE_FIELD_NAME, _GRAVITY_FIELD_NAME,
              _GYROSCOPE_FIELD_NAME, _IMAGE_FIELD_NAME, _LIGHT_FIELD_NAME, _LINEAR_ACCELERATION_FIELD_NAME,
              _MAGNETOMETER_FIELD_NAME, _ORIENTATION_FIELD_NAME, _PROXIMITY_FIELD_NAME,
              _RELATIVE_HUMIDITY_FIELD_NAME, _ROTATION_VECTOR_FIELD_NAME, _VELOCITY_FIELD_NAME]:
        if _has_sensor(packet, s):
            sensor = _get_sensor_for_data_extraction(s, packet)
            result.append((s, sensor.sensor_description, sensor.timestamps.mean_sample_rate))
    if packet.station_information.HasField("station_metrics"):
        result.insert(2, (_HEALTH_FIELD_NAME, "station_metrics",
                          packet.station_information.station_metrics.timestamps.mean_sample_rate))
    return result


def __ordered_insert(buffer: List, value: Tuple):
    """
    inserts the value into the buffer using the timestamp as the key

    :param value: value to add.  Must include a timestamp and the same data type as the other buffer elements
    """
    if len(buffer) < 1:
        buffer.append(value)
    else:
        insort(buffer, value)


def add_to_fst_buffer(buffer: List, buf_max_size: int, timestamp: float, value):
    """
    * add a value into the first buffer.
    * If the buffer is not full, the value is added automatically
    * If the buffer is full, the value is only added if it comes before the last element.

    :param buffer: the buffer to add the value to
    :param buf_max_size: the maximum size of the buffer
    :param timestamp: timestamp in microseconds since epoch UTC to add.
    :param value: value to add.  Must be the same type of data as the other elements in the queue.
    """
    if len(buffer) < buf_max_size or timestamp < buffer[-1][0]:
        __ordered_insert(buffer, (timestamp, value))
        while len(buffer) > buf_max_size:
            buffer.pop()


def add_to_lst_buffer(buffer: List, buf_max_size: int, timestamp: float, value):
    """
    * add a value into the last buffer.
    * If the buffer is not full, the value is added automatically
    * If the buffer is full, the value is only added if it comes after the first element.

    :param buffer: the buffer to add the value to
    :param buf_max_size: the maximum size of the buffer
    :param timestamp: timestamp in microseconds since epoch UTC to add.
    :param value: value to add.  Must be the same type of data as the other elements in the queue.
    """
    if len(buffer) < buf_max_size or timestamp > buffer[0][0]:
        __ordered_insert(buffer, (timestamp, value))
        while len(buffer) > buf_max_size:
            buffer.pop(0)


def get_local_timesync(packet: api_m.RedvoxPacketM) -> Optional[Tuple]:
    """
    if the data exists, the returning tuple looks like:

    (start_timestamp, end_timestamp, num_exchanges, best_latency, best_offset, list of TimeSyncData)

    :param packet: packet to get timesync data from
    :return: Timing object using data from packet
    """
    ts = TimeSync().from_raw_packets([packet])
    if ts.num_tri_messages() > 0:
        _ts_latencies = ts.latencies().flatten()
        _ts_offsets = ts.offsets().flatten()
        _ts_timestamps = ts.get_device_exchanges_timestamps()
        # add data to the buffers
        _ts_data = [sm.TimeSyncData(_ts_timestamps[i], _ts_latencies[i], _ts_offsets[i])
                    for i in range(len(_ts_timestamps))]
        return ts.data_start_timestamp(), ts.data_end_timestamp(), ts.num_tri_messages(), \
            ts.best_latency(), ts.best_offset(), _ts_data
    return None


def add_to_welford(value: float, welford: Optional[sm.WelfordAggregator] = None) -> sm.WelfordAggregator:
    """
    adds the value to the welford, then returns the updated object.

    If welford is None, creates a new WelfordAggregator object and returns it.

    :param value: the value to add
    :param welford: optional WelfordAggregator object to update.  if not given, will make a new one.  Default None
    :return: updated or new WelfordAggregator object
    """
    if welford is None:
        return sm.WelfordAggregator(0., value, 1)
    welford.cnt += 1
    delta = value - welford.mean
    welford.mean += delta / float(welford.cnt)
    delta2 = value - welford.mean
    welford.m2 += delta * delta2
    return welford


def add_to_stats(value: float, stats: Optional[sm.Stats] = None) -> sm.Stats:
    """
    adds the value to the stats, then returns the updated object.

    If stats is None, creates a new Stats object and returns it.

    :param value: the value to add
    :param stats: optional Stats object to update.  if not given, will make a new one.  Default None
    :return: updated or new Stats object
    """
    if stats is None:
        return sm.Stats(value, value, add_to_welford(value))
    if value < stats.min:
        stats.min = value
    if value > stats.max:
        stats.max = value
    add_to_welford(value, stats.welford)
    return stats


def add_to_location(lat: float, lon: float, alt: float, timestamp: float,
                    loc_stat: Optional[sm.LocationStat] = None) -> sm.LocationStat:
    """
    update a LocationStat object with the location, or make a new one

    :param lat: latitude in degrees
    :param lon: longitude in degrees
    :param alt: altitude in meters
    :param timestamp: timestamp in microseconds from epoch UTC
    :param loc_stat: optional LocationStat object to update.  if not given, will make a new one.  Default None
    :return: updated or new LocationStat object
    """
    if loc_stat is None:
        fst_lst = sm.FirstLastBufLocation([], NUM_BUFFER_POINTS, [], NUM_BUFFER_POINTS)
        add_to_fst_buffer(fst_lst.fst, fst_lst.fst_max_size, timestamp, sm.Location(lat, lon, alt))
        add_to_lst_buffer(fst_lst.lst, fst_lst.lst_max_size, timestamp, sm.Location(lat, lon, alt))
        return sm.LocationStat(fst_lst, add_to_stats(lat), add_to_stats(lon), add_to_stats(alt))
    add_to_fst_buffer(loc_stat.fst_lst.fst, loc_stat.fst_lst.fst_max_size, timestamp, sm.Location(lat, lon, alt))
    add_to_lst_buffer(loc_stat.fst_lst.lst, loc_stat.fst_lst.lst_max_size, timestamp, sm.Location(lat, lon, alt))
    loc_stat.lat = add_to_stats(lat, loc_stat.lat)
    loc_stat.lng = add_to_stats(lon, loc_stat.lng)
    loc_stat.alt = add_to_stats(alt, loc_stat.alt)
    return loc_stat


def get_location_data(packet: api_m.RedvoxPacketM) -> List[Tuple[str, float, float, float, float]]:
    """
    :param packet: packet to get location data from
    :return: List of location data as a tuples from the packet
    """
    locations = []
    loc = packet.sensors.location
    lat = lon = alt = ts = 0.
    source = "UNKNOWN"
    num_pts = int(loc.timestamps.timestamp_statistics.count)
    # check for actual location values
    if len(loc.location_providers) < 1:
        lat = loc.latitude_samples.value_statistics.mean
        lon = loc.longitude_samples.value_statistics.mean
        alt = loc.altitude_samples.value_statistics.mean
        ts = loc.timestamps.timestamp_statistics.mean
    elif num_pts > 0 and loc.latitude_samples.value_statistics.count > 0 \
            and loc.longitude_samples.value_statistics.count > 0 \
            and loc.altitude_samples.value_statistics.count > 0 \
            and num_pts == loc.latitude_samples.value_statistics.count \
            and num_pts == loc.altitude_samples.value_statistics.count \
            and num_pts == loc.longitude_samples.value_statistics.count:
        lats = loc.latitude_samples.values
        lons = loc.longitude_samples.values
        alts = loc.altitude_samples.values
        tstp = loc.timestamps.timestamps
        # we add each of the location values
        for i in range(num_pts):
            lat = lats[i]
            lon = lons[i]
            alt = alts[i]
            ts = tstp[i]
            source = "UNKNOWN" if len(loc.location_providers) != num_pts \
                else COLUMN_TO_ENUM_FN["location_provider"](loc.location_providers[i])
            locations.append((source, lat, lon, alt, ts))
        # set a special flag for later, so we don't add an extra location value
        source = None
    elif loc.last_best_location is not None:
        ts = loc.last_best_location.latitude_longitude_timestamp.mach
        source = loc.last_best_location.location_provider
        lat = loc.last_best_location.latitude
        lon = loc.last_best_location.longitude
        alt = loc.last_best_location.altitude
    elif loc.overall_best_location is not None:
        ts = loc.overall_best_location.latitude_longitude_timestamp.mach
        source = loc.overall_best_location.location_provider
        lat = loc.overall_best_location.latitude
        lon = loc.overall_best_location.longitude
        alt = loc.overall_best_location.altitude
    # source is not None if we got only one location through non-usual methods
    if source is not None:
        locations.append((source, lat, lon, alt, ts))
    return locations


def get_dynamic_data(packet: api_m.RedvoxPacketM) -> Dict:
    """
    :param packet: packet to get data from
    :return: Dictionary of all dynamic session data from the packet
    """
    location = get_location_data(packet)
    battery = packet.station_information.station_metrics.battery.value_statistics.mean
    temperature = packet.station_information.station_metrics.temperature.value_statistics.mean
    return {"location": location, "battery": battery, "temperature": temperature}


def add_location_data(data: List[Tuple[str, float, float, float, float]],
                      loc_dict: Optional[Dict[str, sm.LocationStat]] = None) -> Dict[str, sm.LocationStat]:
    """
    update a dictionary of LocationStat or make a new dictionary

    :param data: the data to add
    :param loc_dict: the location dictionary to update
    :return: the updated or new location dictionary
    """
    if loc_dict is None:
        loc_dict = {}
    for s in data:
        loc_dict[s[0]] = add_to_location(s[1], s[2], s[3], s[4], loc_dict[s[0]] if s[0] in loc_dict.keys() else None)
    return loc_dict


class LocalSessionModels:
    """
    SDK version of SessionModelsResp from the cloud API
    """
    def __init__(self):
        self._errors: RedVoxExceptions = RedVoxExceptions("LocalSessionModel")
        self.sessions: List[SessionModel] = []


class SessionModel:
    """
    SDK version of Session from the cloud API
    """
    def __init__(self, session: Optional[sm.Session] = None, dynamic: Optional[Dict[str, sm.DynamicSession]] = None):
        self.cloud_session: Optional[sm.Session] = session
        self.dynamic_sessions: Dict[str, sm.DynamicSession] = {} if dynamic is None else dynamic
        self._errors: RedVoxExceptions = RedVoxExceptions("SessionModel")

    def as_dict(self) -> dict:
        """
        :return: SessionModel as dictionary
        """
        return {
            "cloud_session": self.cloud_session.to_dict(),
            "dynamic_sessions": {n: m.to_dict() for n, m in self.dynamic_sessions.items()}
        }

    @staticmethod
    def from_dict(dictionary: Dict) -> "SessionModel":
        """
        :param dictionary: dictionary to read from
        :return: SessionModel from the dict
        """
        return SessionModel(sm.Session.from_dict(dictionary["cloud_session"]),
                            {n: sm.DynamicSession.from_dict(m) for n, m in dictionary["dynamic_sessions"].items()})

    def compress(self, out_dir: str = ".") -> Path:
        """
        Compresses this SessionModel to a file at out_dir.
        Uses the id and start_ts to name the file.

        :param out_dir: Directory to save file to.  Default "." (current directory)
        :return: The path to the written file.
        """
        return s_io.compress_session_model(self, out_dir)

    def save(self, out_type: str = "json", out_dir: str = ".") -> Path:
        """
        Save the SessionModel to disk.  Options for out_type are "json" for JSON file and "pkl" for .pkl file.
        Defaults to "json".  File will be named after id and start_ts of the SessionModel

        :param out_type: "json" for JSON file and "pkl" for .pkl file
        :param out_dir: Directory to save file to.  Default "." (current directory)
        :return: path to saved file
        """
        if out_type == "pkl":
            return self.compress(out_dir)
        return s_io.session_model_to_json_file(self, out_dir)

    @staticmethod
    def load(file_path: str) -> "SessionModel":
        """
        Load the SessionModel from a JSON or .pkl file.

        :param file_path: full name and path to the SessionModel file
        :return: SessionModel from file
        """
        ext = os.path.splitext(file_path)[1]
        if ext == ".json":
            return SessionModel.from_dict(s_io.session_model_dict_from_json_file(file_path))
        elif ext == ".pkl":
            return s_io.decompress_session_model(file_path)
        else:
            raise ValueError(f"{file_path} has unknown file extension; this function only accepts json and pkl files.")

    def default_file_name(self) -> str:
        """
        :return: Default file name as [id]_[start_ts]_model, with start_ts as integer of microseconds
                    since epoch UTC.  File extension NOT included.
        """
        return f"{self.cloud_session.id}_" \
               f"{0 if np.isnan(self.cloud_session.start_ts) else self.cloud_session.start_ts}_model"

    @staticmethod
    def create_from_packet(packet: api_m.RedvoxPacketM) -> "SessionModel":
        """
        create a SessionModel from a single packet

        :param packet: API M packet of data to read
        :return: Session using the data from the packet
        """
        try:
            duration = packet.timing_information.packet_end_mach_timestamp \
                       - packet.timing_information.packet_start_mach_timestamp
            all_sensors = get_all_sensors_in_packet(packet)
            sensors = [sm.Sensor(s[0], s[1], add_to_stats(s[2])) for s in all_sensors]
            local_ts = get_local_timesync(packet)
            if local_ts is None:
                raise RedVoxError(f"Unable to find timing data for station {packet.station_information.id}.\n"
                                  f"Timing is required to complete SessionModel.\nNow Quitting.")
            fst_lst = sm.FirstLastBufTimeSync([], NUM_BUFFER_POINTS, [], NUM_BUFFER_POINTS)
            for f in local_ts[5]:
                add_to_fst_buffer(fst_lst.fst, fst_lst.fst_max_size, f.ts, f)
                add_to_lst_buffer(fst_lst.lst, fst_lst.lst_max_size, f.ts, f)
            timing = sm.Timing(local_ts[0], local_ts[1], local_ts[2], local_ts[3], local_ts[4], fst_lst)
            result = SessionModel(sm.Session(id=packet.station_information.id, uuid=packet.station_information.uuid,
                                             desc=packet.station_information.description,
                                             start_ts=int(packet.timing_information.app_start_mach_timestamp),
                                             client=CLIENT_NAME, client_ver=CLIENT_VERSION,
                                             session_ver=SESSION_VERSION, app=APP_NAME, api=int(packet.api),
                                             sub_api=int(packet.sub_api), make=packet.station_information.make,
                                             model=packet.station_information.model,
                                             app_ver=packet.station_information.app_version,
                                             owner=packet.station_information.auth_id,
                                             private=packet.station_information.is_private, packet_dur=duration,
                                             sensors=sensors, n_pkts=1, timing=timing, sub=[])
                                  )
            result.sub = [result.add_dynamic_day(packet)]
        except Exception as e:
            # result = SessionModel(station_description=f"FAILED: {e}")
            raise e
        return result

    @staticmethod
    def create_from_stream(data_stream: List[api_m.RedvoxPacketM]) -> "SessionModel":
        """
        create a SessionModel from a stream of data packets

        :param data_stream: list of API M packets from a single station to read
        :return: SessionModel using the data from the stream
        """
        p1 = data_stream.pop(0)
        model = SessionModel.create_from_packet(p1)
        for p in data_stream:
            model.add_data_from_packet(p)
        data_stream.insert(0, p1)
        return model

    def add_data_from_packet(self, packet: api_m.RedvoxPacketM):
        """
        Adds the data from the packet to the SessionModel

        :param packet: packet to add
        """
        local_ts = get_local_timesync(packet)
        if local_ts is None:
            self._errors.append(f"Timesync doesn't exist in packet starting at "
                                f"{packet.timing_information.packet_start_mach_timestamp}.")
        else:
            timing = self.cloud_session.timing
            for f in local_ts[5]:
                add_to_fst_buffer(timing.fst_lst.fst, timing.fst_lst.fst_max_size, f.ts, f)
                add_to_lst_buffer(timing.fst_lst.lst, timing.fst_lst.lst_max_size, f.ts, f)
            timing.n_ex += local_ts[2]
            timing.mean_lat = \
                (timing.mean_lat * self.cloud_session.n_pkts + local_ts[3]) / (self.cloud_session.n_pkts + 1)
            timing.mean_off = \
                (timing.mean_off * self.cloud_session.n_pkts + local_ts[4]) / (self.cloud_session.n_pkts + 1)
            if local_ts[0] < timing.first_data_ts:
                timing.first_data_ts = local_ts[0]
            if local_ts[1] > timing.last_data_ts:
                timing.last_data_ts = local_ts[1]
        all_sensors = get_all_sensors_in_packet(packet)
        for s in all_sensors:
            sensor = self.get_sensor(s[0], s[1])
            if sensor is not None:
                sensor.sample_rate_stats = add_to_stats(s[2], sensor.sample_rate_stats)
            else:
                self.cloud_session.sensors.append(sm.Sensor(s[0], s[1], add_to_stats(s[2])))
        self.add_dynamic_day(packet)
        self.cloud_session.n_pkts += 1

    def add_dynamic_hour(self, data: dict, packet_start: float, session_key: str) -> str:
        """
        Add a dynamic session with length of 1 hour using a single packet or update an existing one if the
        key matches

        :param data: dictionary of data to add
        :param packet_start: starting timestamp of the packet in microseconds since epoch UTC
        :param session_key: the session key of the parent Session
        :return: the key to the new dynamic session
        """
        start_dt = dtu.datetime_from_epoch_microseconds_utc(packet_start)
        hour_start_dt = dtu.datetime(start_dt.year, start_dt.month, start_dt.day, start_dt.hour)
        hour_end_ts = int(dtu.datetime_to_epoch_microseconds_utc(hour_start_dt + dtu.timedelta(hours=1)))
        hour_start_ts = int(dtu.datetime_to_epoch_microseconds_utc(hour_start_dt))
        key = f"{session_key}:{hour_start_ts}:{hour_end_ts}"
        if key in self.dynamic_sessions.keys():
            self.update_dynamic_session(key, data, [f"{packet_start}"])
        else:
            self.dynamic_sessions[key] = sm.DynamicSession(1, add_location_data(data["location"]),
                                                           add_to_stats(data["battery"]),
                                                           add_to_stats(data["temperature"]), session_key,
                                                           hour_start_ts, hour_end_ts, HOURLY_SESSION_NAME,
                                                           [f"{packet_start}"])
        return key

    def add_dynamic_day(self, packet: api_m.RedvoxPacketM) -> str:
        """
        Add data to an existing or create a new dynamic session with length of 1 day using a single packet

        :param packet: packet to read data from
        :return: the key to the new or updated dynamic session
        """
        data = get_dynamic_data(packet)
        start_dt = dtu.datetime_from_epoch_microseconds_utc(packet.timing_information.packet_start_mach_timestamp)
        day_start_dt = dtu.datetime(start_dt.year, start_dt.month, start_dt.day)
        day_end_ts = int(dtu.datetime_to_epoch_microseconds_utc(day_start_dt + dtu.timedelta(days=1)))
        day_start_ts = int(dtu.datetime_to_epoch_microseconds_utc(day_start_dt))
        session_key = f"{packet.station_information.id}:{packet.station_information.uuid}:" \
                      f"{packet.timing_information.app_start_mach_timestamp}"
        key = f"{session_key}:{day_start_ts}:{day_end_ts}"
        hourly_key = self.add_dynamic_hour(data, packet.timing_information.packet_start_mach_timestamp, session_key)
        if key in self.dynamic_sessions.keys():
            self.update_dynamic_session(key, data, [hourly_key])
        else:
            self.dynamic_sessions[key] = sm.DynamicSession(1, add_location_data(data["location"]),
                                                           add_to_stats(data["battery"]),
                                                           add_to_stats(data["temperature"]), session_key,
                                                           day_start_ts, day_end_ts, DAILY_SESSION_NAME, [hourly_key])
        return key

    def update_dynamic_session(self, key: str, data: Dict, sub: List[str]):
        """
        update a dynamic session with a given key.

        :param key: key to the dynamic session
        :param data: dictionary of data to add
        :param sub: the list of keys that the dynamic session is linked to
        """
        if key not in self.dynamic_sessions.keys():
            self._errors.append(f"Attempted to update non-existent key: {key}.")
        else:
            dyn_sess = self.dynamic_sessions[key]
            dyn_sess.location = add_location_data(data["location"], dyn_sess.location)
            dyn_sess.battery = add_to_stats(data["battery"], dyn_sess.battery)
            dyn_sess.temperature = add_to_stats(data["temperature"], dyn_sess.temperature)
            for s in sub:
                if s in self.dynamic_sessions.keys():
                    self.update_dynamic_session(s, data, self.dynamic_sessions[s].sub)

    def num_sensors(self) -> int:
        """
        :return: number of sensors in the Session
        """
        return len(self.cloud_session.sensors)

    def get_sensor_names(self) -> List[str]:
        """
        :return: number of sensors in the Session
        """
        return [n.name for n in self.cloud_session.sensors]

    def get_sensor(self, name: str, desc: Optional[str] = None) -> Optional[sm.Sensor]:
        """
        :param name: name of the sensor to get
        :param desc: Optional description of the sensor to get.  If None, will get the first sensor that
                        matches the name given.  Default None.
        :return: the first sensor that matches the name and description given or None if sensor was not found
        """
        for s in self.cloud_session.sensors:
            if s.name == name:
                if desc is None or s.description == desc:
                    return s
        return None

    def audio_sample_rate_nominal_hz(self) -> float:
        """
        :return: number of sensors in the Session
        """
        for n in self.cloud_session.sensors:
            if n.name == "audio":
                return n.sample_rate_stats.welford.mean

    def get_daily_dynamic_sessions(self) -> List[sm.DynamicSession]:
        """
        :return: all day-long dynamic sessions in the Session
        """
        return [n for n in self.dynamic_sessions.values() if n.dur == DAILY_SESSION_NAME]

    def get_hourly_dynamic_sessions(self) -> List[sm.DynamicSession]:
        """
        :return: all hour-long dynamic sessions in the Session
        """
        return [n for n in self.dynamic_sessions.values() if n.dur == HOURLY_SESSION_NAME]
