# Miscellaneous
import contextlib
import datetime
import functools
import os
import signal
import subprocess
import time
import traceback
# Multiprocessing
import multiprocessing
from queue import Empty as EmptyQueue
# Web server
import socket
import tornado.ioloop
import tornado.web
# URL parsing
import urllib.parse
import url_normalize
# Database
import sqlitedict



# The main HTML request handler, responsible for handling
# GET and POST requests to the root page.
class MainHandler(tornado.web.RequestHandler):
    # At initialization time, store a reference to the top-level
    # service object, from which everything else is reachable.
    def initialize(self, service):
        self.service = service

    # Method for printing a message at each request
    def verbose_message(self, status):
        date = datetime.datetime.now().strftime('%d/%b/%Y %H:%M:%S')
        print(
            f'[{self.request.remote_ip}'
            f' - {date}'
            f' - {self.request.method.ljust(4)}'
            f' - {self.request.version}'
            f' - {status}]'
        )

    # Method quite similar to the builtin send_error,
    # though with a custom message.
    async def send_error_emulate(self, status, message=''):
        self.clear()
        self.set_status(status)
        self.finish(f'<html><body><b>{status}</b><br>{message}</body></html>')

    # Method for generating HTML responses
    @functools.lru_cache(1024)
    def generate_html(self, url_long='', url_short=''):
        """Without arguments, this returns the HTML for the
        default root page. With arguments, additional HTML is added,
        showing the result of the query (url_short) as well as the
        query itself (url_long).
        You should never pass in only one of the URLs.
        """
        result = []
        if url_short:
            result = [
                f'Shortened URL:<br>'
                f'<a id="url_short" href="{url_short}">{url_short}</a><br>',
                f'<button onClick="copyToClipboard(\'url_short\')">Copy to clipboard</button>',
                f'<script>',
                f'function copyToClipboard(id) {{',
                f'  var from = document.getElementById(id);',
                f'  var range = document.createRange();',
                f'  window.getSelection().removeAllRanges();',
                f'  range.selectNode(from);',
                f'  window.getSelection().addRange(range);',
                f'  document.execCommand(\'copy\');',
                f'  window.getSelection().removeAllRanges();',
                f'}}',
                f'</script>',
            ]
        # Return HTML as single str
        html = '\n'.join([
            # Concatenate default HTML response with potential result
            f'<html>',
            f'<body>',
            f'  <h2>URL shortener!</h2>',
            f'  Long URL goes here:<br>'
            f'  <form method="POST">',
            f'    <input type="text" value="{url_long}" name="url_long" size="64" /><br>',
            f'    <input type="submit" value="Submit" />',
            f'  </form>',
            *result,
            f'</body>',
            f'</html>',
        ])
        return html

    # Method for handling GET requests,
    # i.e. sending back the default root page.
    async def get(self):
        if self.service.verbosity > 1:
            self.verbose_message(200)
        await self.finish(self.generate_html())

    # Method for handling POST requests,
    # i.e. accepting a long URL and sending back
    # the corresponding short URL.
    async def post(self):
        # Extract long URL
        url_long = self.get_body_argument('url_long')
        if not url_long:
            # Empty url_long. Send back default HTML.
            if self.service.verbosity > 1:
                self.verbose_message(200)
            self.finish(self.generate_html())
            return
        # Long URL received. Canonicalize it.
        try:
            url_long = url_normalize.url_normalize(url_long)
        except UnicodeError:
            await self.send_error_emulate(400, f'Failed to interpret URL "{url_long}"')
            return
        # Get short URL and send back response
        url_short = await self.service.lookup(url_long, tablename='long2short')
        # Assemble full version of short URL
        url_short = f'{self.service.get_host_url(self.request)}/{url_short}'
        if self.service.verbosity > 1:
            self.verbose_message(200)
        self.finish(self.generate_html(url_long, url_short))

# HTML request handler responsible for handling redirections,
# i.e. GET request to pages deeper than the root.
class RedirectHandler(MainHandler):
    async def get(self, path):
        # Browsers may ask for a favicon.ico. We do not have any.
        if path == 'favicon.ico':
            await self.send_error_emulate(404, 'No favicon available')
            return
        # The path should be a short URL. Look it up in the database.
        url_long = await self.service.lookup(path, tablename='short2long')
        if url_long:
            # Long URL retrieved from database. Redirect.
            status = 307
            if self.service.verbosity > 1:
                self.verbose_message(status)
            self.redirect(url_long, status=status)
            return
        # Database lookup failed
        await self.send_error_emulate(404, f'Destination not found: "{path}"')

# Class handling numeric encoding of numbers in any base
class Encoder:
    def __init__(self, alphabet):
        self.alphabet = alphabet
        self.base = len(self.alphabet)

    def encode(self, number):
        digits = []
        while number:
            number_new = number//self.base
            remainder = number - number_new*self.base
            number = number_new
            digits.append(remainder)
        if not digits:
            digits = [0]
        return ''.join(self.alphabet[digit] for digit in reversed(digits))

# Class representing the sqlite key-value database
class Database:
    def __init__(self, filename):
        # The database consists of two files, one for mapping long
        # URLs to short URLs, and one for the reverse mapping.
        if '.' in filename:
            left, dot, right = filename.rpartition('.')
        else:
            left, dot, right = filename, '', ''
        self.filenames = {
            'long2short': f'{left}_l2s{dot}{right}',
            'short2long': f'{left}_s2l{dot}{right}',
        }

    # Context manager for opening a table within the database
    @contextlib.contextmanager
    def open(self, mapping, *args, **kwargs):
        with sqlitedict.SqliteDict(self.filenames[mapping], *args, **kwargs) as table:
            # Yield control (and the table) back to the caller
            yield table
            # Commit changes to disk before closing file
            table.commit()

# Last recently used cache, used to cache the
# database lookups on the server processes.
class LruCache:
    def __init__(self, capacity=1024, data=None):
        self.capacity = capacity
        if data is None:
            data = {}
        self.data = dict(data)

    def get(self, key):
        try:
            val = self[key]
        except KeyError:
            return None
        return val

    def __getitem__(self, key):
        val = self.data[key]
        # If here, lookup was succesfull.
        # Reinsert the item, so that it appears at the top.
        self.data.pop(key)
        self.data[key] = val
        return val

    def __setitem__(self, key, val):
        # Pop if key already exists,
        # so that when inserted it appears at the end.
        try:
            self.data.pop(key)
        except KeyError:
            pass
        # Pop first used if full
        if len(self) == self.capacity:
            self.data.pop(next(iter(self.data)))
        self.data[key] = val

    def __len__(self):
        return len(self.data)

# Class representing the web service.
# It has the Tornado server and application as attributes.
class Service:
    def __init__(self, address=None, port=None, database=None, nprocs=None, verbosity=None):
        # Store the supplied specifications.
        # If not supplied, retrieve from environment.
        # If not in environment, use sensible defaults.
        if address is None:
            address = os.environ.get('address', 'localhost')
        if port is None:
            port = int(os.environ.get('port', 8000))
        if database is None:
            database = os.environ.get('database', 'db.sqlite')
        if nprocs is None:
            nprocs = int(os.environ.get('nprocs', 4))
        if verbosity is None:
            verbosity = int(os.environ.get('verbosity', 1))
        self.address = address
        self.port = port
        self.database_filename = database  # Note the name change
        self.nprocs = nprocs
        self.verbosity = verbosity
        if nprocs < 1:
            raise ValueError('You must have at least nprocs = 1 server processes')
        # The process ID of the process used to start the service.
        # This is used in the stop() method.
        self.master_pid = os.getpid()
        # Instantiate Encoder instance, mapping non-negative integers
        # to alphanumeric strs.
        self.encoder = Encoder(''.join(
              [chr(i) for i in range(48,  58)]  # 0-9
            + [chr(i) for i in range(65,  91)]  # A-Z
            + [chr(i) for i in range(97, 123)]  # a-z
        ))
        # Instantiate database and caches
        self.database = Database(self.database_filename)
        self.database_cache = {'long2short': LruCache(), 'short2long': LruCache()}
        # Tuples of multiprocessing queues, for communicating
        # back and forth between server processes and the
        # database process, one queue for each server process.
        # We can use either multiprocessing.Queue or
        # multiprocessing.Manager.Queue(). For some reason,
        # using a manager is faster. The manager creation itself
        # however forks off a process, which does not play nice
        # with the Tornado multiprocessing. Hence the ugly hack
        # in the stop() method.
        manager = multiprocessing.Manager()
        self.queues_server2db = tuple(manager.Queue() for _ in range(self.nprocs))
        self.queues_db2server = tuple(manager.Queue() for _ in range(self.nprocs))
        # Integer ID for the server process.
        # This attribute is local to each process.
        self.server_process_id = None

    # Method for starting the web server using multiprocessing.
    # This should be called from a single process.
    def start(self):
        if self.verbosity > 0:
            print(
                f'Starting URL shortener web service, using\n'
                f'  address   = {self.address}\n'
                f'  port      = {self.port}\n'
                f'  database  = {self.database_filename}\n'
                f'  nprocs    = {self.nprocs}\n'
                f'  verbosity = {self.verbosity}\n'
                ,
                end='',
                flush=True,
            )
        # Spin up Tornado server
        self.application = tornado.web.Application(
            [
                (r'^/$',   MainHandler,     dict(service=self)),
                (r'/(.+)', RedirectHandler, dict(service=self)),
            ],
            debug=False,
        )
        self.server = tornado.httpserver.HTTPServer(self.application)
        self.server.listen(self.port, self.address)
        # We want to let self.nprocs concurrent process work as
        # server processs, while 1 process takes care of the database.
        # In order for the multiprocessing module to play nicely with
        # the multiprocessing of Tornado, the database process should
        # be forked from a server process. We thus fork off
        # self.nprocs server processes, each of which is given an
        # integer ID. The one with an ID of zero will be responsible
        # for forking off and joining the database process.
        # Note that this zero ID process is different from the
        # master process; the original Python process.
        queue = multiprocessing.Queue()
        for i in range(self.nprocs):
            queue.put(i)
        self.server.start(self.nprocs)
        self.server_process_id = queue.get()
        if self.server_process_id == 0:
            self.database_process = multiprocessing.Process(target=self.handle_database)
            self.database_process.start()
        # Start of event loop
        tornado.ioloop.IOLoop.current().start()

    # Method for stopping the running service.
    # This should be called by all processes spawned by the server.
    def stop(self):
        # Let the master process do the printing
        if self.verbosity > 0 and os.getpid() == self.master_pid:
            print('\nStopping URL shortener web service', flush=True)
        # The zero ID process joins back the database process
        if self.server_process_id == 0:
            self.database_process.join()
            self.database_process.close()
        # Stop server and event loop
        self.server.stop()
        ioloop = tornado.ioloop.IOLoop.instance()
        ioloop.add_callback(ioloop.stop)
        # In a perfect world, all forked off subprocesses should now
        # be joined. However, our use of multiprocessing from both
        # Tornado and Python somehow leaves child processes still
        # running, which will be wrongly joined at Python exit,
        # leading to uncatchable exceptions. It is no big deal,
        # but the large tracebacks are annoying.
        # As a very hacky solution, we send all processes to sleep
        # except the master process, i.e. the one originally
        # responsible for launching the service, and thus a common
        # ancestor to all other running processes. This process then
        # gets the process ID of all its descendents (through a hacky
        # call to the system ps command), and then asks the system to
        # kill these.
        if os.getpid() != self.master_pid:
            time.sleep(1)
            return  # Ought to be killed before reaching here
        pids = sorted(
            int(line.strip())
            for line in subprocess.check_output(
                f'ps -o pid -g $(ps -o sid= -p {self.master_pid})', shell=True,
            ).decode().split('\n')
            if 'pid' not in line.lower() and line.strip()
        )
        for pid in pids:
            if pid > self.master_pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    # Method for getting the URL of the host.
    # This is really already known information,
    # except when 'localhost' is used for the address.
    def get_host_url(self, request, cache=[]):
        if cache:
            # One-element cache for performance
            return cache[0]
        # Construct URL including protocol
        hostname = urllib.parse.urlparse(
            f'{request.protocol}://{request.host}'
        ).hostname
        address = socket.gethostbyname(hostname)
        url = f'{request.protocol}://{address}'
        # Append port
        if ':' in request.host:
            url += ':' + request.host.split(':')[-1]
        cache.append(url)
        return self.get_host_url(request)

    # Method returning the short URL matching the integer n
    def short_url_from_int(self, n):
        return self.encoder.encode(n)

    # Method in which the database process is trapped while the service
    # is running. It communicates with the server processes using
    # multiprocessing queues.
    def handle_database(self):
        # Open both database files simultaneously.
        # These wll be held open until the service shuts down.
        with self.database.open('long2short') as long2short, \
             self.database.open('short2long') as short2long:
            # Commit changes to both files periodically
            t_between_commits = 1  # In seconds
            t_last_commit = time.time()
            # As this function is run through multiprocessing.Process,
            # exception handling in outer functions do not apply.
            try:
                while True:
                    for queue_server2db, queue_db2server in zip(
                        self.queues_server2db, self.queues_db2server,
                    ):
                        try:
                            tablename, url = queue_server2db.get(block=False)
                            # Database request received
                            if tablename == 'long2short':
                                # Get short URL from long URL. If not
                                # present in the database, add it.
                                url_result = long2short.get(url)
                                if url_result is None:
                                    url_result = long2short[url] = self.short_url_from_int(len(long2short))
                                    # Also add reverse mapping
                                    short2long[url_result] = url
                            elif tablename == 'short2long':
                                # Get long URL from short URL.
                                # Nevermind if not present in database.
                                url_result = short2long.get(url)
                            queue_db2server.put(url_result)
                        except EmptyQueue:
                            pass
                    # If it is time, do commit
                    t_now = time.time()
                    if t_now - t_last_commit > t_between_commits:
                        short2long.commit()
                        long2short.commit()
                        t_last_commit = t_now
            except KeyboardInterrupt:
                pass
            except Exception:
                traceback.print_exc()

    # Property methods for easily getting the queue
    # belonging to the running server process.
    @property
    def queue_server2db(self):
        return self.queues_server2db[self.server_process_id]
    @property
    def queue_db2server(self):
        return self.queues_db2server[self.server_process_id]

    # Method for looking up URLs in the database
    async def lookup(self, url, tablename):
        # Look for result in cache
        cache = self.database_cache[tablename]
        result = cache.get(url)
        if result is not None:
            return result
        # Not found in cache. Query the database process.
        item = (tablename, url)
        self.queue_server2db.put(item)
        result = self.queue_db2server.get()
        cache[url] = result
        return result



# The only top level function,
# used to run the web service.
def start_service(address=None, port=None, database=None, nprocs=None, verbosity=None,
    *, block=True):
    def start():
        service = Service(
            address=address,
            port=port,
            database=database,
            nprocs=nprocs,
            verbosity=verbosity,
        )
        # Encapsulate running service, ensuring proper shutdown
        try:
            service.start()
        except KeyboardInterrupt:
            pass
        except Exception:
            traceback.print_exc()
        finally:
            service.stop()
    if block:
        # Start the service directly.
        # This will block until the service is stopped.
        start()
    else:
        # Start the service in a new process.
        # A function is returned, which when called stops the service.
        process = multiprocessing.Process(target=start)
        process.start()
        return lambda sig=signal.SIGINT: os.kill(process.pid, sig)



# Run web service if invoked as a script,
# using environment or default specifications.
if __name__ == '__main__':
    # Ensure installation of signal handling for SIGINT (Ctrl+C)
    # (needed if launched from bash as a background process).
    signal.signal(signal.SIGINT, signal.default_int_handler)
    # Start service in default (blocking) mode
    start_service()
