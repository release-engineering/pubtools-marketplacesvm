marketplace-push
================

.. argparse::
   :module: pubtools._marketplacesvm.tasks.push
   :func: doc_parser
   :prog: pubtools-marketplacesvm-marketplace-push

Example
.......

Push Example
------------

A typical invocation of push would look like this:

.. code-block::

  pubtools-marketplacesvm-marketplace-push \
    --starmap-url https://starmap.example.com \
    --credentials PATH_TO_CREDS_1.json,PATH_TO_CREDS_2.json \
    koji:https://koji.example.com/kojihub?vmi_build=build-example1,build-example2


.. include:: common/credentials.rst
.. include:: common/sources.rst
.. include:: common/mappings.rst
