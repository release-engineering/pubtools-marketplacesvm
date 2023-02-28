from strenum import StrEnum


class State(StrEnum):
    """The possible states for the push items."""

    PENDING = "PENDING"
    """
    The image is waiting for one of these operations:

    - Upload to the cloud marketplace
    - Vulnerability scan result (AWS only)
    - Product listing go live
    """

    PUSHED = "PUSHED"
    """The image was successfully uploaded and associated with a product listing."""

    UPLOADFAILED = "UPLOADFAILED"
    """Failed to upload this content to the remote server."""

    NOTPUSHED = "NOTPUSHED"
    """An error occurred while publishing the push item to a product listing."""
