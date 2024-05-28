import logging
from typing import Any, Dict, List

from pushsource import AmiAccessEndpointUrl, AmiSecurityGroup

from .starmap import MappedVMIPushItem

log = logging.getLogger(__name__)


def aws_security_groups_converter(value: List[Dict[str, Any]]) -> List[AmiSecurityGroup]:
    """
    Convert a list of data to a list of AmiSecurityGroup.

    Args:
        value
            List of security groups to convert.
    Returns:
        List of converted dicionaries to ``AmiSecurityGroup``.
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


MappedVMIPushItem.register_converter("security_groups", aws_security_groups_converter)
MappedVMIPushItem.register_converter("access_endpoint_url", aws_access_endpoint_url_converter)
