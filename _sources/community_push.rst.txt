community-push
==============

.. argparse::
   :module: pubtools._marketplacesvm.tasks.community_push
   :func: doc_parser
   :prog: pubtools-marketplacesvm-community-push

Example
.......

Push Example
------------

A typical invocation of push would look like this:

.. code-block::

  pubtools-marketplacesvm-community-push \
    --starmap-url https://starmap.example.com \
    --credentials PATH_TO_CREDS_1.json,PATH_TO_CREDS_2.json \
    koji:https://koji.example.com/kojihub?vmi_build=build-example1,build-example2


Credentials Format
------------------

Each credential file must be in the following format:

.. code-block:: json

  {
    "marketplace_account": "aws-XX",
    "auth":
    {
        "AWS_IMAGE_ACCESS_KEY": "******************",
        "AWS_IMAGE_SECRET_ACCESS": "***************",
        "AWS_MARKETPLACE_ACCESS_KEY": "******************",
        "AWS_MARKETPLACE_SECRET_ACCESS": "******************",
        "AWS_ACCESS_ROLE_ARN": "******************",
        "AWS_GROUPS": [],
        "AWS_SNAPSHOT_ACCOUNTS": [],
        "AWS_REGION": "us-east-1",
        "AWS_S3_BUCKET": "******************"
    }
  }


Being the *XX* ``NA`` or ``EMEA``.


Supported Sources
------------------

The tooling supports the `KojiSource`_ and `ErrataSource`_ from ``pushsource``.

All the VM images in the given source path will be uploaded
to the corresponding cloud provider and published to its marketplace.

The expected parameter for the VM images is ``vmi_build``:

**Example:**

  .. code-block::

    koji:https://koji.example.com/kojihub?vmi_build=build-example1,build-example2

Destination Mapping
...................

The destination mapping is given by `StArMap`_.

The tool expects a valid endpoint to the StArMap service.

.. _KojiSource: https://release-engineering.github.io/pushsource/sources/koji.html#accessing-virtual-machine-images
.. _ErrataSource: https://release-engineering.github.io/pushsource/sources/errata.html
.. _StArMap: https://gitlab.cee.redhat.com/stratosphere/starmap
