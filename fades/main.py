# Copyright 2014-2015 Facundo Batista, Nicolás Demarchi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General
# Public License version 3, as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.
# If not, see <http://www.gnu.org/licenses/>.
#
# For further info, check  https://github.com/PyAr/fades

"""Main 'fades' modules."""

import argparse
import os
import signal
import sys
import logging
import subprocess

from fades import parsing, logger, cache, helpers, envbuilder

# the signals to redirect to the child process (note: only these are
# allowed in Windows, see 'signal' doc).
REDIRECTED_SIGNALS = [
    signal.SIGABRT,
    signal.SIGFPE,
    signal.SIGILL,
    signal.SIGINT,
    signal.SIGSEGV,
    signal.SIGTERM,
]

help_epilog = """
The "child program" is the script that fades will execute. It's an
optional parameter, it will be the first thing received by fades that
is not a parameter.  If no child program is indicated, a Python
interactive interpreter will be opened.

The "child options" (everything after the child program) are
parameters passed as is to the child program.
"""


def go(version, argv):
    """Make the magic happen."""
    parser = argparse.ArgumentParser(prog='PROG', epilog=help_epilog,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-V', '--version', action='store_true',
                        help="show version and info about the system, and exit")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="send all internal debugging lines to stderr, which may be very "
                             "useful to debug any problem that may arise.")
    parser.add_argument('-q', '--quiet', action='store_true',
                        help="don't show anything (unless it has a real problem), so the "
                             "original script stderr is not polluted at all.")
    parser.add_argument('-d', '--dependency', action='append',
                        help="specify dependencies through command line (this option can be "
                             "used multiple times)")
    parser.add_argument('child_program', nargs='?', default=None)
    parser.add_argument('child_options', nargs=argparse.REMAINDER)
    args = parser.parse_args()

    # validate input, parameters, and support some special options
    if args.version:
        print("Running 'fades' version", version)
        print("    Python:", sys.version_info)
        print("    System:", sys.platform)
        sys.exit()

    if args.verbose:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO

    # set up logger and dump basic version info
    l = logger.set_up(log_level)
    l.debug("Running Python %s on %r", sys.version_info, sys.platform)
    l.debug("Starting fades v. %s", version)
    l.debug("Arguments: %s", args)

    if args.verbose and args.quiet:
        l.warning("Overriding 'quiet' option ('verbose' also requested)")

    # parse file and get deps
    requested_deps = parsing.parse_file(args.child_program)
    l.debug("Dependencies from file: %s", requested_deps)
    manual_deps = parsing.parse_manual(args.dependency)
    l.debug("Dependencies from parameters: %s", manual_deps)
    # update previous dict, so manually specified dependencies are more
    # important and overwrite the ones in the file
    requested_deps.update(manual_deps)

    # start the virtualenvs manager
    venvscache = cache.VEnvsCache(os.path.join(helpers.get_basedir(), 'venvs.idx'))
    venv_data = venvscache.get_venv(requested_deps)
    if venv_data is None:
        venv_data, installed = envbuilder.create_venv(requested_deps)
        # store this new venv in the cache
        venvscache.store(installed, venv_data)

    # run forest run!!
    python_exe = os.path.join(venv_data['env_bin_path'], "python3")
    if args.child_program is None:
        l.debug("Calling the interactive Python interpreter")
        p = subprocess.Popen([python_exe])

    else:
        l.debug("Calling the child Python program %r with options %s",
                args.child_program, args.child_options)
        p = subprocess.Popen([python_exe, args.child_program] + args.child_options)

        def _signal_handler(signum, _):
            """Handle signals received by parent process, send them to child."""
            l.debug("Redirecting signal %s to child", signum)
            os.kill(p.pid, signum)

        # redirect these signals
        for s in REDIRECTED_SIGNALS:
            signal.signal(s, _signal_handler)

    # wait child to finish, end
    rc = p.wait()
    if rc:
        l.debug("Child process not finished correctly: returncode=%d", rc)
