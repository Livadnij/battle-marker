"""Errors the service layer raises. Their message is meant for the user as is."""


class ServiceError(Exception):
    pass


class NoRecordingsError(ServiceError):
    pass


class ResolutionError(ServiceError):
    pass


class NoFramesError(ServiceError):
    pass


class NoScanError(ServiceError):
    pass


class SteamRunningError(ServiceError):
    pass
