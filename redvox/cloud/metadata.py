"""
This module contains classes and enums for working with generic RedVox packet metadata through the cloud API.
"""
import requests
from dataclasses import dataclass
from typing import List, Optional

from dataclasses_json import dataclass_json

from redvox.cloud.api import ApiConfig
from redvox.cloud.routes import RoutesV1


@dataclass_json
@dataclass
class AudioMetadata:
    sensor_name: Optional[str] = None
    sample_rate: Optional[float] = None
    first_sample_ts: Optional[int] = None
    payload_cnt: Optional[int] = None
    payload_mean: Optional[float] = None
    payload_std: Optional[float] = None
    payload_median: Optional[float] = None


@dataclass_json
@dataclass
class SingleMetadata:
    sensor_name: Optional[str] = None
    timestamps_microseconds_utc_count: Optional[int] = None
    payload_count: Optional[int] = None
    sample_interval_mean: Optional[float] = None
    sample_interval_std: Optional[float] = None
    sample_interval_median: Optional[float] = None
    value_mean: Optional[float] = None
    value_std: Optional[float] = None
    value_median: Optional[float] = None
    metadata: Optional[List[str]] = None


@dataclass_json
@dataclass
class XyzMetadata:
    sensor_name: Optional[str] = None
    timestamps_microseconds_utc_count: Optional[int] = None
    payload_count: Optional[int] = None
    sample_interval_mean: Optional[float] = None
    sample_interval_std: Optional[float] = None
    sample_interval_median: Optional[float] = None
    x_mean: Optional[float] = None
    x_std: Optional[float] = None
    x_median: Optional[float] = None
    y_mean: Optional[float] = None
    y_std: Optional[float] = None
    y_median: Optional[float] = None
    z_mean: Optional[float] = None
    z_std: Optional[float] = None
    z_median: Optional[float] = None
    metadata: Optional[List[str]] = None


@dataclass_json
@dataclass
class LocationMetadata:
    sensor_name: Optional[str] = None
    timestamps_microseconds_utc_count: Optional[int] = None
    payload_count: Optional[int] = None
    sample_interval_mean: Optional[float] = None
    sample_interval_std: Optional[float] = None
    sample_interval_median: Optional[float] = None
    latitude_mean: Optional[float] = None
    latitude_std: Optional[float] = None
    latitude_median: Optional[float] = None
    longitude_mean: Optional[float] = None
    longitude_std: Optional[float] = None
    longitude_median: Optional[float] = None
    altitude_mean: Optional[float] = None
    altitude_std: Optional[float] = None
    altitude_median: Optional[float] = None
    speed_mean: Optional[float] = None
    speed_std: Optional[float] = None
    speed_median: Optional[float] = None
    accuracy_mean: Optional[float] = None
    accuracy_std: Optional[float] = None
    accuracy_median: Optional[float] = None
    metadata: Optional[List[str]] = None


@dataclass_json
@dataclass
class PacketMetadataResult:
    api: Optional[int] = None
    station_id: Optional[str] = None
    station_uuid: Optional[str] = None
    auth_email: Optional[str] = None
    is_backfilled: Optional[bool] = None
    is_private: Optional[bool] = None
    is_scrambled: Optional[bool] = None
    station_make: Optional[str] = None
    station_model: Optional[str] = None
    station_os: Optional[str] = None
    station_os_version: Optional[str] = None
    station_app_version: Optional[str] = None
    battery_level: Optional[float] = None
    station_temperature: Optional[float] = None
    acquisition_url: Optional[str] = None
    synch_url: Optional[str] = None
    auth_url: Optional[str] = None
    os_ts: Optional[int] = None
    mach_ts: Optional[int] = None
    server_ts: Optional[int] = None
    data_key: Optional[str] = None
    mach_time_zero: Optional[float] = None
    best_latency: Optional[float] = None
    best_offset: Optional[float] = None
    audio_sensor: Optional[AudioMetadata] = None
    barometer_sensor: Optional[SingleMetadata] = None
    location_sensor: Optional[LocationMetadata] = None
    time_synchronization_sensor: Optional[SingleMetadata] = None
    accelerometer_sensor: Optional[XyzMetadata] = None
    magnetometer_sensor: Optional[XyzMetadata] = None
    gyroscope_sensor: Optional[XyzMetadata] = None
    light_sensor: Optional[SingleMetadata] = None
    proximity_sensor: Optional[SingleMetadata] = None


@dataclass_json
@dataclass
class AvailableMetadata:
    Api: str = "Api"
    StationId: str = "StationId"
    StationUuid: str = "StationUuid"
    AuthEmail: str = "AuthEmail"
    IsBackfilled: str = "IsBackfilled"
    IsPrivate: str = "IsPrivate"
    IsScrambled: str = "IsScrambled"
    StationMake: str = "StationMake"
    StationModel: str = "StationModel"
    StationOs: str = "StationOs"
    StationOsVersion: str = "StationOsVersion"
    StationAppVersion: str = "StationAppVersion"
    BatteryLevel: str = "BatteryLevel"
    StationTemperature: str = "StationTemperature"
    AcquisitionUrl: str = "AcquisitionUrl"
    SynchUrl: str = "SynchUrl"
    AuthUrl: str = "AuthUrl"
    OsTs: str = "OsTs"
    MachTs: str = "MachTs"
    ServerTs: str = "ServerTs"
    DataKey: str = "DataKey"
    MachTimeZero: str = "MachTimeZero"
    BestLatency: str = "BestLatency"
    BestOffset: str = "BestOffset"
    AudioSensor: str = "AudioSensor"
    BarometerSensor: str = "BarometerSensor"
    AccelerometerSensor: str = "AccelerometerSensor"
    GyroscopeSensor: str = "GyroscopeSensor"
    TimeSynchronizationSensor: str = "TimeSynchronizationSensor"
    MagnetometerSensor: str = "MagnetometerSensor"
    LightSensor: str = "LightSensor"
    ProximitySensor: str = "ProximitySensor"
    LocationSensor: str = "LocationSensor"

    @staticmethod
    def all_available_metadata() -> List[str]:
        return [
            AvailableMetadata.Api,
            AvailableMetadata.StationId,
            AvailableMetadata.StationUuid,
            AvailableMetadata.AuthEmail,
            AvailableMetadata.IsBackfilled,
            AvailableMetadata.IsPrivate,
            AvailableMetadata.IsScrambled,
            AvailableMetadata.StationMake,
            AvailableMetadata.StationModel,
            AvailableMetadata.StationOs,
            AvailableMetadata.StationOsVersion,
            AvailableMetadata.StationAppVersion,
            AvailableMetadata.BatteryLevel,
            AvailableMetadata.StationTemperature,
            AvailableMetadata.AcquisitionUrl,
            AvailableMetadata.SynchUrl,
            AvailableMetadata.AuthUrl,
            AvailableMetadata.OsTs,
            AvailableMetadata.MachTs,
            AvailableMetadata.ServerTs,
            AvailableMetadata.DataKey,
            AvailableMetadata.MachTimeZero,
            AvailableMetadata.BestLatency,
            AvailableMetadata.BestOffset,
            AvailableMetadata.AudioSensor,
            AvailableMetadata.BarometerSensor,
            AvailableMetadata.AccelerometerSensor,
            AvailableMetadata.GyroscopeSensor,
            AvailableMetadata.TimeSynchronizationSensor,
            AvailableMetadata.MagnetometerSensor,
            AvailableMetadata.LightSensor,
            AvailableMetadata.ProximitySensor,
            AvailableMetadata.LocationSensor,
        ]


@dataclass_json
@dataclass
class MetadataReq:
    auth_token: str
    start_ts_s: int
    end_ts_s: int
    station_ids: List[str]
    fields: List[str]
    secret_token: Optional[str] = None


@dataclass_json
@dataclass
class MetadataResp:
    metadata: List[PacketMetadataResult]


@dataclass_json
@dataclass
class TimingMetaRequest:
    """
    Request for timing metadata.
    """
    auth_token: str
    start_ts_s: int
    end_ts_s: int
    station_ids: List[str]
    secret_token: Optional[str] = None


@dataclass_json
@dataclass
class TimingMeta:
    """
    Timing metadata extracted from an individual packet.
    """
    station_id: str
    start_ts_os: float
    start_ts_mach: float
    server_ts: float
    mach_time_zero: float
    best_latency: float
    best_offset: float


@dataclass_json
@dataclass
class TimingMetaResponse:
    """
    Response of obtaining timing metadta.
    """
    items: List[TimingMeta]


def request_timing_metadata(api_config: ApiConfig,
                            timing_req: TimingMetaRequest) -> TimingMetaResponse:
    """
    Retrieve timing metadata.
    :param api_config: An instance of the API configuration.
    :param timing_req: An instance of a timing request.
    :return: An instance of a timing response.
    """
    url: str = api_config.url(RoutesV1.TIMING_METADATA_REQ)
    # noinspection Mypy
    resp: requests.Response = requests.post(url, json=timing_req.to_dict())
    if resp.status_code == 200:
        return TimingMetaResponse(resp.json())
    else:
        return TimingMetaResponse(list())


def request_metadata(api_config: ApiConfig, packet_metadata_req: MetadataReq) -> Optional[MetadataResp]:
    """
    Requests generic metadata from the cloud API.
    :param api_config: An instance of the API config.
    :param packet_metadata_req: An instance of a metadata request.
    :return: A metadata response on successful call or None if there is an error.
    """
    url: str = api_config.url(RoutesV1.METADATA_REQ)
    # noinspection Mypy
    resp: requests.Response = requests.post(url, json=packet_metadata_req.to_dict())
    if resp.status_code == 200:
        # noinspection Mypy
        return MetadataResp.from_dict(resp.json())
    else:
        return None
