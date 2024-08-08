Credentials Format
------------------

Each credential file must be in the following format:

.. code-block:: json

  {
    "marketplace_account": "CLOUD_ALIAS",
    "auth":
    {
        "KEY": "VALUE", // ...
    }
  }


Being the *KEY*s and *VALUE*s for the ``auth`` object specific for each Cloud Provider implementation.

**Example for Azure NA:**

.. code-block:: json

  {
    "marketplace_account": "azure-na",
    "auth": {
        "AZURE_TENANT_ID": "******************",
        "AZURE_PUBLISHER_NAME": "*************",
        "AZURE_API_SECRET": "******************",
        "AZURE_CLIENT_ID": "*******************",
        "AZURE_STORAGE_CONNECTION_STRING": "******************"
    }
  }

**Example for AWS NA:**

.. code-block:: json

  {
    "marketplace_account": "aws-na",
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

