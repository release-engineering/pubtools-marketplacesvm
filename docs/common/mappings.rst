Destination Mapping
-------------------

The destination mapping is given by an internal service named ``StArMap`` throught the `Starmap Client`_ library.

The tool expects a valid endpoint to the StArMap service and/or a JSON string containing the list of mappings
using the parameter ``--repo``.

The following sections will cover all the details about the destination mappings.

Mapping request modes
^^^^^^^^^^^^^^^^^^^^^

Online mode
"""""""""""

In this mode the tooling will use the `Starmap Client`_ library to connect into a StArMap server to provide
the mappings for each `VMIPushItem`_ into the proper marketplace destination.

To initiate the tooling into the "online mode" it's just a matter of providing a valid StArMap server URL

.. code-block::

    --starmap-url https://starmap.base.url

The workflow will be executed like this:

.. code-block::

   # For each incoming "VMIPushItem" get its destination data from StArMap
   # using the image name, version and the desired workflow
   curl -S https://starmap.base.url/api/v1/query?name=IMG_NAME&version=IMG_VERworkflow=community
   curl -S https://starmap.base.url/api/v1/query?name=IMG_NAME&version=IMG_VER&workflow=stratosphere

   # If mapping not defined => fail; else
   # Upload and publish the VMs into the proper destinations
   ...

Offline mode
""""""""""""

In this mode the tooling will use the `Starmap Client`_ library to load the mappings from the ``--repo`` argument
and use these mappings to upload and publish each `VMIPushItem`_ into the proper marketplace destination. In this mode
it will fail any `VMIPushItem`_ which doesn't have a mapping specified on ``--repo``.

Note that no network calls will be made to the StArMap server in this mode, so the ``--starmap-url`` can be
any fake url.

To initiate the tooling into the "offline mode" you must specify the ``--repo`` mappings as well as the flag ``--offline``:

.. code-block::

    --starmap-url https://some.fake.url \
    --repo "{...}" \
    --offline

The workflow will be executed like this:

.. code-block::

   # For each incoming "VMIPushItem" get its destination data from --repo
   # using the image name and the desired workflow
   # If mapping not defined => fail; else
   # Upload and publish the VMs into the proper destinations
   ...


Hybrid mode
"""""""""""

In this mode the tooling will use the `Starmap Client`_ library to load the mappings from the ``--repo`` argument
and use these mappings to upload and publish each `VMIPushItem`_ into the proper marketplace destination. Howevever,
if a certain mapping is not defined on repo it will request the data from the StArMap server.

Note that no network calls will be made to the StArMap server in this mode, so the ``--starmap-url`` can be
any fake url.

To initiate the tooling into the "offline mode" you must specify the ``--repo`` mappings as well as 
valid StArMap server URL for fallback:

.. code-block::

    --starmap-url https://starmap.base.url \
    --repo "{...}"

The workflow will be executed like this:

.. code-block::

   # For each incoming "VMIPushItem" get its destination data from --repo
   # using the image name and the desired workflow
   # If mapping not defined call the StArMap server
   curl -S https://starmap.base.url/api/v1/query?name=IMG_NAME&version=IMG_VERworkflow=community
   curl -S https://starmap.base.url/api/v1/query?name=IMG_NAME&version=IMG_VER&workflow=stratosphere
   # If mapping is still not defined => fail; else
   # Upload and publish the VMs into the proper destinations
   ...

Mapping Format
^^^^^^^^^^^^^^

The value for the ``--repo`` argument expects a JSON with either a single or multiple `QueryResponse`_ data.

With that, it supports either a JSON starting with a list (for multiple mappings) or a dictionary (single mapping).

The StArMap APIv1 `QueryResponse`_ has the following format:

.. code-block:: json

    {
      "name": "str",
      "workflow": "str",
      "mappings": {"obj"}
    }

- ``name``: The name from the image's NVR. It will be used to match the propre VM artifact.
- ``workflow``: Can be either ``community`` or ``stratosphere`` and it's used to match the tooling workflow.
- ``mappings``: The ``clouds`` object with the marketplace name and its destinations and metadata

The ``mappings`` object has the following format:

.. code-block:: json

    {
       "MARKETPLACE_NAME": [
          {
            "architecture": "str",
            "destination": "str",
            "meta": {"obj"},
            "overwrite": "bool",
            "provider": "str",
            "restrict_version": "bool",
            "restrict_major": "bool",
            "restrict_minor": "bool",
            "tags": {}
           },
           {"..."}
       ]
    }

- ``MARKETPLACE_NAME``: A string matching a single `marketplace_account`_ from credentials. E.g. ``aws-na``.
  It's used the retrieve the proper credentials to upload and publish into the given marketplace.
- ``LIST``: A list of destination objects, which are described below.

Destination objects format:

- ``architecture``: A string representing the VM image architecture to publish. E.g. ``x86_64``.
- ``destination``: A string representing a offer/plan destination for the image to be published. E.g. ``offer_1/plan_1``.
- ``meta``: An object with any key/values which may be threated as complementary metadata for publishing on marketplaces.
- ``overwrite``: A boolean indicating whenever the image should replace the existing version (true) in the marketplace.
- ``provider``: A string meant to be used only on community workflow. It indicates the provider name (``AWS``, ``AGOV``, ``ACN``).
- ``restrict_version``: A boolean for AWS marketplace only which indicates whether a previous version need to be restricted after publishing.
- ``restrict_major``: An optional boolean indicating whether to restrict a major version. Only applicable if ``restrict_version`` is set to ``true``.
- ``restrict_minor``: An optional boolean indicating whether to restrict a minor version. Only applicable if ``restrict_version`` is set to ``true``.
- ``tags``: An object with any key/values to be applied as tags once the VM images are uploaded.

Examples
""""""""

An **Azure** mapping for ``RHEL`` using the architecture ``x86_64`` to be published in the marketplace:

.. code-block:: bash

    curl -S 'https://starmap.base.url/api/v1/query?name=rhel-azure&version=8.0&workflow=stratosphere'


.. code-block:: json

    {
        "name": "rhel-azure",
        "workflow": "stratosphere",
        "mappings": {
            "azure-na": [
                {
                    "architecture": "x86_64",
                    "destination": "rh-rhel-test/rh-rhel8-internal",
                    "meta": { "generation": "V2", "support_legacy": true },
                    "overwrite": false,
                    "provider": null,
                    "restrict_major": null,
                    "restrict_minor": null,
                    "restrict_version": false,
                    "tags": {},
                },
            ],
        }
    }

An **AWS** mapping for ``RHEL`` using the architecture ``x86_64`` to be published in the marketplace:

.. code-block:: bash

    curl -S 'https://starmap.base.url/api/v1/query?name=rhel-ec2&workflow=stratosphere'

.. code-block:: json

    {
        "name": "rhel-ec2",
        "workflow": "stratosphere",
        "mappings": {
            "aws-na": [
                {
                    "architecture": "x86_64",
                    "destination": "d87bcebf-9cf4-47f5-9b5b-5470d4490f3d",
                    "meta": {
                        "description": "Provided by Red Hat, Inc.",
                        "ena_support": true,
                        "marketplace_entity_type": "AmiProduct",
                        "recommended_instance_type": "m5dn.2xlarge",
                        "release": {
                            "product": "Red Hat Enterprise Linux",
                            "type": "ga",
                            "variant": "Server"
                        },
                        "release_notes": "https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/{major_version}/html/{major_minor}_release_notes/index",
                        "root_device": "/dev/sda1",
                        "scanning_port": 22,
                        "security_groups": [
                            {
                            "from_port": 22,
                            "ip_protocol": "tcp",
                            "ip_ranges": [
                                "0.0.0.0/0"
                            ],
                            "to_port": 22
                            }
                        ],
                        "sriov_net_support": "simple",
                        "usage_instructions": "Access your instance via ssh using the default username \"ec2-user\" and the ssh key registered with AWS. This product provides access to multiple versions. When launching with 1-click launch, please pay attention to the version. You have the ability to select another version of the RHEL image (including RHEL 8 and newer) when launching from the full AWS Marketplace website.",
                        "user_name": "ec2-user",
                        "virtualization": "hvm",
                        "volume": "gp2"
                    },
                    "overwrite": false,
                    "provider": null,
                    "restrict_major": null,
                    "restrict_minor": null,
                    "restrict_version": true,
                    "tags": {}
                }
            ]
        }
    }

An **AWS** mapping for ``RHEL`` using the architecture ``x86_64`` to be published as a community image:

.. code-block:: bash

  curl -S 'https://starmap.base.url/api/v1/query?name=rhel-ec2&workflow=community'

.. code-block:: json

    {
        "name": "rhel-ec2",
        "workflow": "community",
        "mappings": {
            "aws-us-storage": [
            {
                "architecture": null,
                "destination": "us-east-1-access",
                "meta": {
                    "description": "Provided by Red Hat, Inc.",
                    "ena_support": true,
                    "release": {
                        "product": "RHEL",
                        "type": "ga",
                        "variant": "BaseOS"
                    },
                    "root_device": "/dev/sda1",
                    "sriov_net_support": "simple",
                    "virtualization": "hvm",
                    "volume": "gp3"
                },
                "overwrite": false,
                "provider": "AWS",
                "restrict_major": null,
                "restrict_minor": null,
                "restrict_version": false,
                "tags": {}
            },
            {
                "architecture": null,
                "destination": "us-east-2-access",
                "meta": {
                    "description": "Provided by Red Hat, Inc.",
                    "ena_support": true,
                    "release": {
                        "product": "RHEL",
                        "type": "ga",
                        "variant": "BaseOS"
                    },
                    "root_device": "/dev/sda1",
                    "sriov_net_support": "simple",
                    "virtualization": "hvm",
                    "volume": "gp3"
                },
                "overwrite": false,
                "provider": "AWS",
                "restrict_major": null,
                "restrict_minor": null,
                "restrict_version": false,
                "tags": {}
            },
            {
                "architecture": null,
                "destination": "us-west-1-access",
                "meta": {
                    "description": "Provided by Red Hat, Inc.",
                    "ena_support": true,
                    "release": {
                        "product": "RHEL",
                        "type": "ga",
                        "variant": "BaseOS"
                    },
                    "root_device": "/dev/sda1",
                    "sriov_net_support": "simple",
                    "virtualization": "hvm",
                    "volume": "gp3"
                },
                "overwrite": false,
                "provider": "AWS",
                "restrict_major": null,
                "restrict_minor": null,
                "restrict_version": false,
                "tags": {}
            },
            {
                "architecture": null,
                "destination": "us-west-2-access",
                "meta": {
                    "description": "Provided by Red Hat, Inc.",
                    "ena_support": true,
                    "release": {
                        "product": "RHEL",
                        "type": "ga",
                        "variant": "BaseOS"
                    },
                    "root_device": "/dev/sda1",
                    "sriov_net_support": "simple",
                    "virtualization": "hvm",
                    "volume": "gp3"
                },
                "overwrite": false,
                "provider": "AWS",
                "restrict_major": null,
                "restrict_minor": null,
                "restrict_version": false,
                "tags": {}
            }
            ]
        }
    }

.. _`marketplace_account`: credentials.html
.. _QueryResponse: https://release-engineering.github.io/starmap-client/model/models.html#starmap_client.models.QueryResponse
.. _Starmap Client: https://release-engineering.github.io/starmap-client/
.. _VMIPushItem: https://release-engineering.github.io/pushsource/model/vmi.html
