delete
==============

.. argparse::
   :module: pubtools._marketplacesvm.tasks.delete
   :func: doc_parser
   :prog: pubtools-marketplacesvm-delete

Example
.......

Delete Example
------------

A typical invocation of delete would look like this:

.. code-block::

  pubtools-marketplacesvm-delete \
    --credentials PATH_TO_CREDS_1.json,PATH_TO_CREDS_2.json \
    --builds build1,build2 \
    --keep-snapshots \
    --dry-run \
    pub:https://pub.example.com/pub/task/555555/


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

The tooling supports the `PubSource`_ from ``pushsource``.

All VM images only support pub source. The data from pub
gives the task information on the corresponding cloud provider 
and published to its marketplace.

End url is the task id that information will be used to delete the image:

**Example:**

  .. code-block::

    pub:https://pub.example.com/pub/task/555555/


.. _PubSource: https://release-engineering.github.io/pushsource/sources/pub.html
