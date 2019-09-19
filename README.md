URL shortener
=============
This Python project implements URL shortening as a web service,
using the [Tornado](https://www.tornadoweb.org/) framework.

In an effort to scale the service, it utilizes cuncurrency at both
the asyncio and multiprocessing level.

The service maps arbitrary URLs to short URLs, which are kept in
a sqlite3 database. The domain of the short URLs is that of the
server, so that it can handle the redirection as well.



Design
------
- **Web framework**: Tornado was chosen for the web framework and
  HTTP server, as it allows for easy utilization of asyncio. The
  still simpler built-in threaded HTTP server in Python was rejected
  due to bad performance at high load.
- **Concurrency**: The use of asyncio means that a single process
  can serve many requests concurrently. Furhtermore, any number of
  processes may be added to the pool of web servers, through the use
  of a multiprocessing feature of Tornado. On top of this, a separate
  process handles the database.
- **Database**: We are in need of a persistent mapping from long URLs
  to short URLs, as well as the reverse (for later redirection). For
  this, two key-value stores are ideal. For the database, this project
  uses the [sqlitedict](https://github.com/RaRe-Technologies/sqlitedict/)
  Python package, which builds on by SQLite.

A key problem is how to generate the short URLs. Instead of relying on
hashing (and dealing with collision), the program simply generates
every<sup id="a1">[1](#f1)</sup> possible alphanumeric string in order.

To bypass the problem of concurrent access to the database, a separate
process is dedicated to this purpose. It communicates with the server
processes using [queues](https://docs.python.org/3/library/multiprocessing.html#multiprocessing.managers.SyncManager.Queue).
The communication through these queues are rather slow, providing the
bottleneck of the program. On top of this, the database process does not
make use of asyncio or threads.



How to run locally
------------------
The program `url_shortener.py` can either be run as a script or imported
as a Python module. To run it as a script, do

    python url_shortener.py

with a Python version of at least<sup id="a2">[2](#f2)</sup> 3.6.
The following third-party Python packages are required:
[Tornado](https://www.tornadoweb.org/),
[sqlitedict](https://github.com/RaRe-Technologies/sqlitedict/),
[url-normalize](https://github.com/niksite/url-normalize).
The web service will start up on `localhost`, using `port=8000`,
as displayed. Now visit `http://localhost:8000/` in a browser and you
will be confronted with a self-evident interface.

To change the settings shown at start-up, set the corresponding
environment variables. Consider

    export port=8888
    nprocs=6 verbosity=2 python url_shortener.py

which starts `url_shortener.py` on port `8888`, using `6` server
processors and a verbosity level of `2`.



<b id="f1">¹</b> With the exception of left 0-padded strings. [↩](#a1)

<b id="f2">²</b> I have only tested it with Python 3.7. [↩](#a2)
