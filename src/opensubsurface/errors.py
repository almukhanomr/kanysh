class DomainError(Exception):
    def __init__(self, code: str, message: str, field: str = "", remediation: str = ""):
        super().__init__(message)
        self.code, self.message, self.field, self.remediation = code, message, field, remediation

    def as_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "remediation": self.remediation,
        }


def require(condition, code, message, field="", remediation=""):
    if not condition:
        raise DomainError(code, message, field, remediation)
