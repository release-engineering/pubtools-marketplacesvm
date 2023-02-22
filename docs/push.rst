push
====

.. argparse::
   :module: pubtools._marketplacesvm.tasks.push
   :func: doc_parser
   :prog: pubtools-marketplacesvm-push

Example
.......

A typical invocation of push would look like this:

.. code-block::

  pubtools-marketplacesvm-push \
    --starmap-url https://starmap.example.com \
    --credentials PATH_TO_CREDS_1.json,PATH_TO_CREDS_2.json \
    koji:https://koji.example.com/kojihub?vmi_build=build-example1,build-example2

All the VM images in the given source path will be uploaded
to the corresponding cloud provider and published to its marketplace.

The destination mapping is given by `StArMap`_.

.. _StArMap: https://gitlab.cee.redhat.com/stratosphere/starmap
