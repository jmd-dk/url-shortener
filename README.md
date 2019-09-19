URL shortener
=============
This Python project implements URL shortening as a web service,
using the [Tornado](https://www.tornadoweb.org/) framework.

In an effort to scale the service, it utilizes concurrency at both
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
  can serve many requests concurrently. Furthermore, any number of
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

```bash
    python url_shortener.py
```

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

```bash
export port=8888  # Or supply it as below
nprocs=6 verbosity=2 python url_shortener.py
```

which starts `url_shortener.py` on port `8888`, using `6` server
processors and a verbosity level of `2`.

To run the service from within another Python module, include code
like so:

```python
import url_shortener

# Non-blocking example
killer = url_shortener.start_service(block=False)
# Do computation
...
# When done, shut down the service like so
killer()

# Blocking example
url_shortener.start_service(port=8888, nprocs=6)
unreachable_statement  # Untill service is killed, e.g. via Ctrl+C
```

### Testing
A test suite consisting of correctness and stress tests is can be found
in the `test` bash script. As with the Python script, the various
settings may be set through environment variables. Importantly,
the `python` variable, storing the path to the python interpreter,
should also set (may also be done permanently in the `test` source).

If the service is already running on the matching `address` and `port`,
this will be used for the test. Otherwise, a new service will be
spun up. As some warnings are emitted by the service during the tests,
it is nicer to run it in terminal window separate from the tests.

Here is an example demonstrating the effectiveness of having multiple
server processes:

```bash
for nprocs in $(seq 4 -1 1); do
    rm -f db*.sqlite  # Remove database
    nprocs=${nprocs} ./test
done
```


<b id="f1">¹</b> With the exception of left 0-padded strings. [↩](#a1)

<b id="f2">²</b> Python 3.7+ needed to run without constant TypeError's. [↩](#a2)
