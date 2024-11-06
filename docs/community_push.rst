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


using a staged sourced

.. code-block::

  pubtools-marketplacesvm-community-push \
    --starmap-url https://starmap.example.com \
    --credentials PATH_TO_CREDS_1.json,PATH_TO_CREDS_2.json \
    staged:/direct/path/to/folder


.. include:: common/credentials.rst
.. include:: common/sources.rst
.. include:: common/mappings.rst
