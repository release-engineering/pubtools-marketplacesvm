from typing import Any, Dict, List

from pushsource import AmiSecurityGroup

from .starmap import MappedVMIPushItem


def aws_security_groups_converter(value: List[Dict[str, Any]]) -> List[AmiSecurityGroup]:
    """
    Convert a list of data to a list of AmiSecurityGroup.

    Args:
        value
            List of security groups to convert.
    Returns:
        List of converted dicionaries to ``AmiSecurityGroup``.
    """
    return [AmiSecurityGroup._from_data(x) for x in value]


MappedVMIPushItem.register_converter("security_groups", aws_security_groups_converter)
