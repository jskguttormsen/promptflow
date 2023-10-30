# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

import base64
import collections
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, OrderedDict

from promptflow._internal import ToolProvider, tool
from promptflow._utils.dataclass_serializer import serialize
from promptflow._utils.tool_utils import get_inputs_for_prompt_template
from promptflow.contracts.run_info import RunInfo as NodeRunInfo

from .constants import PF_RECORDING_MODE

PROMOTFLOW_ROOT = Path(__file__).parent.parent.parent.parent


def is_recording() -> bool:
    return os.getenv(PF_RECORDING_MODE, "") == "record"


def is_replaying() -> bool:
    return os.getenv(PF_RECORDING_MODE, "") == "replay"


def recording_or_replaying() -> bool:
    return is_recording() or is_replaying()


class RecordItemMissingException(Exception):
    pass


class RecordFileMissingException(Exception):
    pass


class RecordStorage:
    """
    RecordStorage static class to manage recording file storage_record.json
    and cache the content in memory.
    Each change of runItems will trigger write_file to storage_record.json
    """

    runItems: Dict[str, Dict[str, str]] = {}

    @staticmethod
    def write_file(recording_file: Path) -> None:

        path_hash = hashlib.sha1(str(recording_file.parts[-4:]).encode("utf-8")).hexdigest()
        file_content = RecordStorage.runItems.get(path_hash, None)
        if file_content is not None:
            with open(recording_file, "w+") as fp:
                json.dump(RecordStorage.runItems[path_hash], fp, indent=4)

    @staticmethod
    def load_file(recording_file: Path) -> None:
        path_hash = hashlib.sha1(str(recording_file.parts[-4:]).encode("utf-8")).hexdigest()
        local_content = RecordStorage.runItems.get(path_hash, None)
        if not local_content:
            if not os.path.exists(recording_file):
                return
            with open(recording_file, "r", encoding="utf-8") as fp:
                RecordStorage.runItems[path_hash] = json.load(fp)

    @staticmethod
    def get_record(recording_file: Path, hashDict: OrderedDict) -> str:
        hash_value: str = hashlib.sha1(str(hashDict).encode("utf-8")).hexdigest()
        path_hash: str = hashlib.sha1(str(recording_file.parts[-4:]).encode("utf-8")).hexdigest()
        file_item: Dict[str, str] = RecordStorage.runItems.get(path_hash, None)
        if file_item is None:
            RecordStorage.load_file(recording_file)
            file_item = RecordStorage.runItems.get(path_hash, None)
        if file_item is not None:
            item = file_item.get(hash_value, None)
            if item is not None:
                real_item = base64.b64decode(bytes(item, "utf-8")).decode()
                return real_item
            else:
                raise RecordItemMissingException(
                    f"Record item not found in folder {recording_file}.\n"
                    f"Path hash {path_hash}\nHash value: {hash_value}\n"
                    f"Hash dict: {hashDict}\nHashed values: {json.dumps(hashDict)}\n"
                )
        else:
            raise RecordFileMissingException(f"Record file not found in folder {recording_file}.")

    @staticmethod
    def set_record(recording_file: Path, hashDict: OrderedDict, output: object) -> None:
        hash_value: str = hashlib.sha1(str(hashDict).encode("utf-8")).hexdigest()
        path_hash: str = hashlib.sha1(str(recording_file.parts[-4:]).encode("utf-8")).hexdigest()
        output_base64: str = base64.b64encode(bytes(output, "utf-8")).decode(encoding="utf-8")
        current_saved_record: Dict[str, str] = RecordStorage.runItems.get(path_hash, None)
        if current_saved_record is None:
            RecordStorage.load_file(recording_file)
            if RecordStorage.runItems is None:
                RecordStorage.runItems = {}
            if (RecordStorage.runItems.get(path_hash, None)) is None:
                RecordStorage.runItems[path_hash] = {}
            RecordStorage.runItems[path_hash][hash_value] = output_base64
            RecordStorage.write_file(recording_file)
        else:
            saved_output = current_saved_record.get(hash_value, None)
            if saved_output is not None and saved_output == output_base64:
                return
            else:
                current_saved_record[hash_value] = output_base64
                RecordStorage.write_file(recording_file)


class ToolRecordPlayer(ToolProvider):
    """
    ToolRecordPlayer Record inputs and outputs of llm tool, in replay mode,
    this tool will read the cached result from storage_record.json
    """

    @tool
    def completion(toolType: str, *args, **kwargs) -> str:
        # "AzureOpenAI" =  args[0], this is type indicator, there may be more than one indicators
        prompt_tmpl = args[1]
        prompt_tpl_inputs = args[2]
        recording_file = args[3]

        hashDict = {}
        for keyword in prompt_tpl_inputs:
            if keyword in kwargs:
                hashDict[keyword] = kwargs[keyword]
        hashDict["prompt"] = prompt_tmpl
        hashDict = collections.OrderedDict(sorted(hashDict.items()))

        real_item = RecordStorage.get_record(recording_file, hashDict)
        return real_item


@tool
def just_return(toolType: str, *args, **kwargs) -> str:
    # Replay: Promptflow internal test tool, get all input and return recorded output
    return ToolRecordPlayer().completion(toolType, *args, **kwargs)


def _record_node_run(run_info: NodeRunInfo, flow_folder: Path, api_call: Dict[str, Any]) -> None:
    hashDict = {}
    if "name" in api_call and api_call["name"].startswith("AzureOpenAI"):
        prompt_tpl = api_call["inputs"]["prompt"]
        prompt_tpl_inputs = get_inputs_for_prompt_template(prompt_tpl)

        for keyword in prompt_tpl_inputs:
            if keyword in api_call["inputs"]:
                hashDict[keyword] = api_call["inputs"][keyword]
        hashDict["prompt"] = prompt_tpl
        hashDict = collections.OrderedDict(sorted(hashDict.items()))
        item = serialize(run_info)
        RecordStorage.set_record(flow_folder, hashDict, str(item["output"]))


def record_node_run(run_info: Any, flow_folder: Path) -> None:
    """Recording: Persist node run record to local storage."""
    if isinstance(run_info, dict):
        for api_call in run_info["api_calls"]:
            _record_node_run(run_info, flow_folder, api_call)
    else:
        for api_call in run_info.api_calls:
            _record_node_run(run_info, flow_folder, api_call)
