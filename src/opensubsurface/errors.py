class DomainError(Exception):
    def __init__(self, code: str, message: str, field: str = "", remediation: str = "", details=None):
        super().__init__(message)
        self.code, self.message, self.field, self.remediation = code, message, field, remediation
        self.details = details

    def __reduce__(self):
        # Process workers must preserve structured domain errors across spawn/IPC.
        return type(self), (self.code, self.message, self.field, self.remediation, self.details)

    def as_dict(self):
        result = {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "remediation": self.remediation,
        }
        if self.details is not None:
            result["details"] = self.details
        return result


def require(condition, code, message, field="", remediation="", details=None):
    if not condition:
        raise DomainError(code, message, field, remediation, details)


def json_path(loc):
    path = ""
    for part in loc:
        path += f"[{part}]" if isinstance(part, int) else ("." if path else "") + str(part)
    return path


def validation_error(error):
    """Name every offending field by JSON path; model validators prefix messages with the field."""
    import re

    fields = []
    for item in error.errors(include_url=False):
        loc = [part for part in item["loc"] if part not in ("function-after", "function-before")]
        message = item["msg"].removeprefix("Value error, ")
        named = re.match(r"^([a-z][a-z0-9_]*): (.+)$", message, re.S)
        if named and item["type"] == "value_error":
            loc, message = [*loc, named[1]], named[2]
        fields.append(dict(field=json_path(loc), message=message, type=item["type"]))
    return dict(
        code="INVALID_ARGUMENTS",
        message="; ".join(f"{f['field'] or 'request'}: {f['message']}" for f in fields),
        field=fields[0]["field"] if fields else "",
        fields=fields,
        remediation="Correct the listed fields; every field, unit and allowed value is described in this "
        "tool's inputSchema. Z is positive upward (depth 2692 m -> -2692).",
    )
