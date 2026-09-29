class NotFoundError(Exception):
    """A requested entity does not exist; mapped to HTTP 404."""


class FieldNotFoundError(NotFoundError):
    def __init__(self, field_id: object) -> None:
        super().__init__(f"field {field_id} not found")
