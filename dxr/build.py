from codecs import getdecoder
import cgi
from datetime import datetime
from fnmatch import fnmatchcase
from itertools import chain, izip
import json
import os
from os import stat
from os.path import dirname
from pkg_resources import require
import shutil
import subprocess
import sys

from dxr.plugins.clang import indexer
import dxr.languages
from dxr.utils import connect_database, update_max, open_log


def build_instance(config):
    """Build a DXR instance.

    :arg config: configuration.

    """
    # Create config.target_folder (if not exists)
    print "Generating target folder"; sys.stdout.flush()
    ensure_folder(config.temp_folder, not config.incremental)
    ensure_folder(config.log_folder, True)
    config.bin_folder = os.path.join(config.temp_folder, 'bin')
    ensure_folder(config.bin_folder, True)

    ensure_folder(config.object_folder,       # Object folder (user defined!)
                  config.source_folder != config.object_folder # Only clean if not the srcdir
                  and not config.incremental                     # and not an incremental build
                  and config.object_folder != os.path.abspath('.'))
    ensure_folder(os.path.join(config.temp_folder, 'clang'), not config.incremental)

    # Connect to database (exits on failure: sqlite_version, tokenizer, etc)
    conn = connect_database(config)

    if not config.incremental:
        # Create database tables
        create_tables(config, conn)

    # Build tree
    build_tree(config, conn)

    # Close connection
    update_max(conn)
    conn.commit()
    conn.close()

def build_fixup(conn):
    # Note starting time
    start_time = datetime.now()

    indexer.db_fixup(conn)

    # Optimize and run integrity check on database
    finalize_database(conn)

    # Commit database
    conn.commit()

    # Save the tree finish time
    delta = datetime.now() - start_time
    print "(finished building in %s)" % delta; sys.stdout.flush()

    # Print a neat summary


def ensure_folder(folder, clean=False):
    """Ensure the existence of a folder.

    :arg clean: Whether to ensure that the folder is empty

    """
    if clean and os.path.isdir(folder):
        shutil.rmtree(folder, False)
    if not os.path.isdir(folder):
        os.makedirs(folder)


def create_tables(tree, conn):
    print "Creating tables"; sys.stdout.flush()
    # conn.execute("CREATE VIRTUAL TABLE trg_index USING trilite")
    conn.executescript(dxr.languages.language_schema.get_create_sql())

import codecs

def _unignored_folders(folders, source_path, ignore_patterns, ignore_paths):
    """Yield the folders from ``folders`` which are not ignored by the given
    patterns and paths.

    :arg source_path: Relative path to the source directory
    :arg ignore_patterns: Non-path-based globs to be ignored
    :arg ignore_paths: Path-based globs to be ignored

    """
    for folder in folders:
        if not any(fnmatchcase(folder, p) for p in ignore_patterns):
            folder_path = '/' + os.path.join(source_path, folder).replace(os.sep, '/') + '/'
            if not any(fnmatchcase(folder_path, p) for p in ignore_paths):
                yield folder


def build_tree(config, conn):
    """Build the tree, pre_process, build and post_process."""
    # Get system environment variables
    environ = {}
    for key, val in os.environ.items():
        environ[key] = val

    indexer.pre_process(config, environ)

    # Add source and build directories to the command
    environ["source_folder"] = config.source_folder
    environ["build_folder"] = config.object_folder

    # Open log file
    with open_log(config, "build.log") as log:
        # Call the make command
        print "Building"; sys.stdout.flush()
        r = subprocess.call(
            config.build_command.replace("$jobs", config.nb_jobs),
            shell   = True,
            stdout  = log,
            stderr  = log,
            env     = environ,
            cwd     = config.object_folder
        )

    # Abort if build failed!
    if r != 0:
        msg = "Build command for '%s' failed, exited non-zero! Log follows:"
        with open(log.name) as log_file:
            print >> sys.stderr, '    | %s ' % '    | '.join(log_file)
        sys.exit(1)

    indexer.post_process(config, conn)
    finalize_database(conn)


def finalize_database(conn):
    """Finalize the database."""
    print "Finalize database:"; sys.stdout.flush()

    print " - Build database statistics for query optimization"; sys.stdout.flush()
    conn.execute("VACUUM ANALYZE");

    print " - Running integrity check"; sys.stdout.flush()
    isOkay = None
    for row in conn.execute("PRAGMA integrity_check"):
        if row[0] == "ok" and isOkay is None:
            isOkay = True
        else:
            if isOkay is not False:
                print >> sys.stderr, "Database, integerity-check failed"
            isOkay = False
            print >> sys.stderr, "  | %s" % row[0]
    if not isOkay:
        sys.exit(1)

    conn.commit()
