from fastapi import HTTPException

SYSTEM_MESSAGE_PREDECESSORS = {"user.custom_tool_result", "user.message", "user.tool_result"}


def validate_system_message_batch(event_types: list[str]) -> None:
    system_indexes = [index for index, event_type in enumerate(event_types) if event_type == "system.message"]
    if not system_indexes:
        return
    if len(system_indexes) > 1:
        raise HTTPException(status_code=422, detail="At most one system.message event is allowed per request")
    system_index = system_indexes[0]
    if system_index != len(event_types) - 1:
        raise HTTPException(status_code=422, detail="system.message must be the final event in the request")
    if system_index == 0 or event_types[system_index - 1] not in SYSTEM_MESSAGE_PREDECESSORS:
        raise HTTPException(
            status_code=422,
            detail="system.message must immediately follow user.message, user.tool_result, or user.custom_tool_result",
        )
