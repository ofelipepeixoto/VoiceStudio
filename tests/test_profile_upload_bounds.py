"""Profile upload size boundaries without importing the app or model engines.

Execute the actual router function ASTs with synthetic uploads and tiny byte
limits. This covers the pre-decode/pre-database boundary, not the full HTTP API,
multipart parser, consent persistence, audio decoding or inference.
"""

import ast
import asyncio
import contextlib
import os
import uuid
from pathlib import Path
from typing import Optional

import pytest
from fastapi import HTTPException, UploadFile

SOURCE = Path(__file__).resolve().parents[1] / "backend/api/routers/profiles.py"


class Recording:
    filename = "fixture.wav"

    def __init__(self, data: bytes):
        self.data = data
        self.reads = []

    async def read(self, size=-1):
        self.reads.append(size)
        if size < 0:
            part, self.data = self.data, b""
        else:
            part, self.data = self.data[:size], self.data[size:]
        return part


def functions(tmp_path):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {"create_profile", "record_consent", "_save_upload"}
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in names
    ]
    assert {node.name for node in nodes} == names
    for node in nodes:
        # Router decorators and FastAPI parameter defaults are outside this
        # focused boundary; pass every parameter explicitly below.
        node.decorator_list = []
        node.args.defaults = []
    namespace = {
        "Optional": Optional,
        "UploadFile": UploadFile,
        "HTTPException": HTTPException,
        "os": os,
        "uuid": uuid,
        "asyncio": asyncio,
        "contextlib": contextlib,
        "VOICES_DIR": str(tmp_path / "voices"),
        "sanitize_instruct": lambda value: value,
        "StarletteUploadFile": UploadFile,
        "media_upload_suffix": lambda filename: ".wav",
        "_MAX_REF_AUDIO_BYTES": 8,
        "_UPLOAD_CHUNK": 4,
        "_MIN_CONSENT_AUDIO_BYTES": 2,
    }
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


def test_create_refuses_oversize_and_removes_partial_file(tmp_path):
    namespace = functions(tmp_path)
    upload = Recording(b"0123456789")
    with pytest.raises(HTTPException) as error:
        asyncio.run(namespace["create_profile"](
            name="fixture", ref_audio=upload, ref_text="", instruct="",
            language="Auto", seed=None, personality="", kind="clone",
            vd_states=None, image=None,
        ))
    assert error.value.status_code == 413
    assert list((tmp_path / "voices").iterdir()) == []
    assert upload.reads == [4, 4, 4]


def test_consent_refuses_oversize_before_any_database_access(tmp_path):
    namespace = functions(tmp_path)
    upload = Recording(b"0123456789")
    with pytest.raises(HTTPException) as error:
        asyncio.run(namespace["record_consent"](
            profile_id="fixture", consent_audio=upload,
            consent_text="synthetic consent",
        ))
    assert error.value.status_code == 413
    # db_conn is intentionally absent: any database access would fail here.
    assert upload.reads == [9]


def test_existing_stream_writer_preserves_bytes_at_limit(tmp_path):
    namespace = functions(tmp_path)
    upload = Recording(b"12345678")
    destination = tmp_path / "ok.wav"
    assert asyncio.run(namespace["_save_upload"](
        upload, str(destination),
    )) == 8
    assert destination.read_bytes() == b"12345678"
    assert upload.reads == [4, 4, 4]
