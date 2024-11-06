Supported Sources
------------------

The tooling supports the `KojiSource`_ , `ErrataSource`_ , and `StagedSource`_ from ``pushsource``.

All the VM images in the given source path will be uploaded
to the corresponding cloud provider and published to its marketplace.

The expected parameter for the VM images is ``vmi_build``:

**Example:**

  .. code-block::

    koji:https://koji.example.com/kojihub?vmi_build=build-example1,build-example2

  .. code-block::

    staged:/direct/path/to/folder


.. _KojiSource: https://release-engineering.github.io/pushsource/sources/koji.html#accessing-virtual-machine-images
.. _ErrataSource: https://release-engineering.github.io/pushsource/sources/errata.html
.. _StagedSource: https://release-engineering.github.io/pushsource/sources/staged.html
