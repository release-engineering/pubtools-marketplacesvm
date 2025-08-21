import logging
from typing import Any, Dict, List

from pushsource import AmiAccessEndpointUrl, AmiSecurityGroup, BootMode

from .starmap import MappedVMIPushItemV2

log = logging.getLogger(__name__)


def aws_security_groups_converter(value: List[Dict[str, Any]]) -> List[AmiSecurityGroup]:
    """
    Convert a list of data to a list of AmiSecurityGroup.

    Args:
        value
            List of security groups to convert.
    Returns:
        List of converted dictionaries to ``AmiSecurityGroup``.
    """
    log.debug("Converting data to AmiSecurityGroup: %s", value)
    return [AmiSecurityGroup._from_data(x) for x in value]


def aws_access_endpoint_url_converter(value: Dict[str, Any]) -> AmiAccessEndpointUrl:
    """
    Convert data to AmiAccessEndpointUrl.

    Args:
        value (Dict[str, Any]): Access endpoint URL to convert.

    Returns:
        AmiAccessEndpointUrl: The converted AmiAccessEndpointUrl.
    """
    log.debug("Converting data to AmiAccessEndpointUrl: %s", value)
    return AmiAccessEndpointUrl._from_data(value)


def aws_boot_mode_converter(value: str) -> BootMode:
    """
    Convert boot_mode string value to BootMode enum.

    Args:
        value (str): boot_mode as string

    Returns:
        BootMode: The corresponding Enum for the received value
    """
    return BootMode(value)


MappedVMIPushItemV2.register_converter("security_groups", aws_security_groups_converter)
MappedVMIPushItemV2.register_converter("access_endpoint_url", aws_access_endpoint_url_converter)
MappedVMIPushItemV2.register_converter("boot_mode", aws_boot_mode_converter)
