"""
Small helper copied from the official Spotware OpenApiPy client to map payload
type integers to protobuf message classes.
"""

from __future__ import annotations

import re
from typing import Dict, Type

from ctrader_open_api.messages import (
    OpenApiCommonMessages_pb2 as ocm,
    OpenApiMessages_pb2 as om,
)


class Protobuf:
    _protos: Dict[int, Type] = {}
    _names: Dict[str, int] = {}
    _abbr_names: Dict[str, int] = {}

    @classmethod
    def populate(cls) -> Dict[int, Type]:
        for name in dir(ocm) + dir(om):
            if not name.startswith("Proto"):
                continue

            module = ocm if hasattr(ocm, name) else om
            klass = getattr(module, name)
            cls._protos[klass().payloadType] = klass
            cls._names[klass.__name__] = klass().payloadType
            abbr_name = re.sub(r"^Proto(OA)?(.*)", r"\2", klass.__name__)
            cls._names[abbr_name] = klass().payloadType
        return cls._protos

    @classmethod
    def get(cls, payload, fail: bool = True, **params):
        if not cls._protos:
            cls.populate()

        if payload in cls._protos:
            return cls._protos[payload](**params)

        for dictionary in [cls._names, cls._abbr_names]:
            if payload in dictionary:
                payload = dictionary[payload]
                return cls._protos[payload](**params)

        if fail:  # pragma: nocover - defensive guard
            raise IndexError(f"Invalid payload: {payload}")
        return None

    @classmethod
    def extract(cls, message: ocm.ProtoMessage):
        payload = cls.get(message.payloadType)
        payload.ParseFromString(message.payload)
        return payload

