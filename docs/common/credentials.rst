Credentials
-----------

This section describes the supported values for the ``--credentials`` command line argument.

Expected format
^^^^^^^^^^^^^^^

Overall format
""""""""""""""
Each credential file must be in the following format:

.. code-block:: json

  {
    "marketplace_account": "CLOUD_ALIAS",
    "auth":
    {
        "KEY": "VALUE", // ...
    }
  }


The supported values for the key ``marketplace_account`` are described below:

Marketplace accounts (push)
"""""""""""""""""""""""""""
Required when using the "marketplace" or "combined" workflow

- ``aws-na``
- ``aws-emea``
- ``azure-na``
- ``azure-emea``

Storage accounts (community-push)
"""""""""""""""""""""""""""""""""
Required when using the "community" or "combined" workflow

- ``aws-us-storage``
- ``aws-us-gov-storage``
- ``aws-china-storage``

Auth format
"""""""""""

The *KEY*s and *VALUE*s for the ``auth`` object are specific for each Cloud Provider implementation.

**AWS Format**

The following properties are supported for AWS ``auth``:

- ``AWS_IMAGE_ACCESS_KEY``: The AWS access key for uploading the images and import them as AMIs
- ``AWS_IMAGE_SECRET_ACCESS``: The AWS secret key for uploading the images and import them as AMIs
- ``AWS_MARKETPLACE_ACCESS_KEY``: The AWS access key for publishing a new product version with its AMI into the marketplace
- ``AWS_MARKETPLACE_SECRET_ACCESS``: The AWS secret key for publishing a new product version with its AMI into the marketplace
- ``AWS_ACCESS_ROLE_ARN``: IAM role Amazon Resource Name (ARN) used by AWS Marketplace to access the provided AMI. For details about creating and using this ARN, see `Giving AWS Marketplace access to your AMI`_ in the AWS Marketplace Seller Guide.
- ``AWS_GROUPS``: The default sharing accounts for uploading and importing AMIs
- ``AWS_SNAPSHOT_ACCOUNTS``: The default sharing snapshot accounts for uploading and importing AMIs
- ``AWS_REGION``: The default region for uploading and importing AMIs
- ``AWS_S3_BUCKET``: The S3 bucket name to upload the raw VM images

Example:

.. code-block:: json

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


**Azure Format**

The following properties are supported for AWS ``auth``:

- ``AZURE_TENANT_ID``: The tenant ID for publishing a new product version
- ``AZURE_PUBLISHER_NAME``: The publisher name for publishing a new product version
- ``AZURE_CLIENT_ID``: The Azure's AD Client ID to communicate with Microsoft APIs
- ``AZURE_API_SECRET``: The Azure's AD Client Secret to communicate with Microsoft APIs
- ``AZURE_STORAGE_CONNECTION_STRING``: The Azure Storage Account connection string to upload VHD images

.. code-block:: json

  {
    "AZURE_TENANT_ID": "******************",
    "AZURE_PUBLISHER_NAME": "*************",
    "AZURE_API_SECRET": "******************",
    "AZURE_CLIENT_ID": "*******************",
    "AZURE_STORAGE_CONNECTION_STRING": "******************"
  }

Examples
""""""""

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


CLI parameter format
^^^^^^^^^^^^^^^^^^^^

Once the credentials are properly crafted, then can be passed to the tooling in one of the following ways:


Credentials as files
""""""""""""""""""""

It's possible to storage each credential into a single JSON file and passing the path for all files
using a comma delimited string for the parameter ``--credentials``:

.. code-block:: bash

  --credentials PATH_TO_CREDS_1.json,PATH_TO_CREDS_2.json,PATH_TO_CREDS3.json

The tooling will split the string by comma (``,``) and open/parse each credential file for loading its credentials.

Note that the parameter ``--credentials`` support only a single string argument. Avoid using space as ``bash`` may consider it two or more arguments.

Credentials as list of base64 string
""""""""""""""""""""""""""""""""""""

Another way to pass the credentials is to encode each credential JSON into a ``base64`` string and passing it
as a list of encoded strings separated by comma (``,``).

Since comma will never be used on ``base64`` encoding the tooling will first split the string into multiple
substrings of ``base64`` encoding, each one representing a single credentials.

.. code-block:: bash

  ## Convert each creds to a base64 encoded string
  for i in PATH_TO_CREDS_1.json PATH_TO_CREDS_2.json PATH_TO_CREDS3.json; do
    cat $i | base64
  done

  ## Join the output into a single line and then

  --credentials BASE64_STRING_1,BASE64_STRING_2,BASE64_STRING_3

Note that the parameter ``--credentials`` support only a single string argument. Avoid using space as ``bash`` may consider it two or more arguments.


Examples
""""""""

Using the path mode:

.. code-block:: bash

  pubtools-marketplacesvm-push \
  --credentials creds/aws-na.json,creds/aws-emea.json,creds/azure-na.json,creds/azure-emea.json \
  ...

Using the base64 mode:

.. code-block:: bash

  pubtools-marketplacesvm-push \
  --credentials ewogICAgIm1hcmtWNlX[...],ewogICAgIm1hcmtldH[...],ewogICAgIm1hcmtl[...],ewogICAgIm1hcmtldHBsYW[...] \
  ...


.. _`Giving AWS Marketplace access to your AMI`: https://docs.aws.amazon.com/marketplace-catalog/latest/api-reference/ami-products.html#working-with-single-AMI-products
