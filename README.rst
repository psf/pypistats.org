PyPI Stats
==========

A simple analytics dashboard for aggregate data on PyPI downloads. PyPI Stats is built using Flask with plotly.js.

`PyPI Stats <https://pypistats.org/>`_

GitHub OAuth
------------

PyPI Stats has an integration with GitHub so you can track install data on the packages you maintain.

`User page <https://pypistats.org/user>`_

JSON API
--------

PyPI Stats provides a simple JSON API to retrieve aggregate download stats and time histories of pypi packages.

`JSON API <https://pypistats.org/api>`_

Development
-----------

Prerequisites:

- Docker
- Docker Compose, available as the ``docker-compose`` command used by the
  Makefile
- Make

1. Copy ``.env.example`` to ``.env`` and configure your environment variables:
   
   .. code-block:: bash
   
      cp .env.example .env
      # Edit .env with your configuration

2. Run ``make pypistats`` to launch a complete development environment. The
   target stops any existing containers, rebuilds the images, and starts the
   Docker Compose services for the app:

   .. code-block:: bash

      make pypistats
