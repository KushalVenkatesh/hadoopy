#!/usr/bin/env python
# (C) Copyright 2010 Brandyn A. White
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__author__ = 'Brandyn A. White <bwhite@cs.umd.edu>'
__license__ = 'GPL V3'

import subprocess
import re
import os
import hadoopy
from hadoopy._runner import _find_hstreaming


def _cleaned_hadoop_stderr(hdfs_stderr):
    for line in hdfs_stderr:
        parts = line.split()
        if parts[2] == 'INFO' or parts[2] == 'WARN':
            pass
        else:
            yield line
        

def _hadoop_fs_command(cmd, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, java_mem_mb=100):
    env = dict(os.environ)
    env['HADOOP_OPTS'] = "-Xmx%dm" % java_mem_mb
    p = subprocess.Popen(cmd, env=env, shell=True, close_fds=True,
                         stdin=stdin,
                         stdout=stdout,
                         stderr=stderr)
    return p


def _checked_hadoop_fs_command(cmd, *args, **kw):
    p = _hadoop_fs_command(cmd, *args, **kw)
    stdout, stderr = p.communicate()
    rcode = p.returncode
    if rcode is not 0:
        raise IOError('Ran[%s]: %s' % (cmd, stderr))
    return rcode, stdout, stderr


def exists(path):
    """Check if a file exists.
    
    Args:
        path: A string for the path.  This should not have any wildcards.
        
    Return:
        True if the path exists, False otherwise.
    """
    cmd = "hadoop fs -test -e %s"
    p = _hadoop_fs_command(cmd % (path))
    p.communicate()
    rcode = p.returncode
    return bool(int(rcode == 0))


def isdir(path):
    """Check if a path is a directory
    
    Args:
        path: A string for the path.  This should not have any wildcards.
        
    Return:
        True if the path is a directory, False otherwise.
    """
    cmd = "hadoop fs -test -d %s"
    p = _hadoop_fs_command(cmd % (path))
    p.communicate()
    rcode = p.returncode
    return bool(int(rcode == 0))


def isempty(path):
    """Check if a path has zero length (also true if it's a directory)
    
    Args:
        path: A string for the path.  This should not have any wildcards.
        
    Return:
        True if the path has zero length, False otherwise.
    """
    cmd = "hadoop fs -test -z %s"
    p = _hadoop_fs_command(cmd % (path))
    p.communicate()
    rcode = p.returncode
    return bool(int(rcode == 0))


_USER_HOME_DIR = None  # Cache for user's home directory


def abspath(path):
    """Return the absolute path to a file and canonicalize it

    Path is returned without a trailing slash and without redundant slashes.
    Caches the user's home directory.
    
    Args:
        path: A string for the path.  This should not have any wildcards.
        
    Return:
        Absolute path to the file

    Raises:
        IOError: If unsuccessful
    """
    global _USER_HOME_DIR
    # FIXME(brandyn): User's home directory must exist
    if path[0] == '/':
        return os.path.abspath(path)
    if _USER_HOME_DIR is None:
        try:
            _USER_HOME_DIR = hadoopy.ls('.')[0].rsplit('/', 1)[0]
        except IOError, e:
            if not exists('.'):
                raise IOError("Home directory doesn't exist")
            raise e
    return os.path.abspath(os.path.join(_USER_HOME_DIR, path))


def rmr(path):
    """Remove a file if it exists (recursive)
    
    Args:
        path: A string (potentially with wildcards).

    Raises:
        IOError: If unsuccessful
    """
    cmd = "hadoop fs -rmr %s" % (path)
    rcode, stdout, stderr = _checked_hadoop_fs_command(cmd)


def put(local_path, hdfs_path):
    """Put a file on hdfs
    
    Args:
        local_path: Source (str)
        hdfs_path: Destrination (str)

    Raises:
        IOError: If unsuccessful
    """
    cmd = "hadoop fs -put %s %s" % (local_path, hdfs_path)
    rcode, stdout, stderr = _checked_hadoop_fs_command(cmd)


def get(hdfs_path, local_path):
    """Get a file from hdfs
    
    Args:
        hdfs_path: Destrination (str)
        local_path: Source (str)

    Raises:
        IOError: If unsuccessful
    """
    cmd = "hadoop fs -get %s %s" % (hdfs_path, local_path)
    rcode, stdout, stderr = _checked_hadoop_fs_command(cmd)


def ls(path):
    """List files on HDFS.

    Args:
        path: A string (potentially with wildcards).

    Returns:
        A list of strings representing HDFS paths.

    Raises:
        IOError: An error occurred listing the directory (e.g., not available).
    """
    rcode, stdout, stderr = _checked_hadoop_fs_command('hadoop fs -ls %s' % path)
    found_line = lambda x: re.search('Found [0-9]+ items$', x)
    out = [x.split(' ')[-1] for x in stdout.split('\n')
           if x and not found_line(x)]
    return out


def writetb(path, kvs):
    """Write typedbytes sequence file on HDFS

    Args:
        path: HDFS path (str)
        kvs: Iterator of (key, value)
    
    Raises:
        IOError: An error occurred while saving the data.
    """
    read_fd, write_fd = os.pipe()
    read_fp = os.fdopen(read_fd, 'r')
    hstreaming = _find_hstreaming()
    cmd = 'hadoop jar %s loadtb %s' % (hstreaming, path)
    p = _hadoop_fs_command(cmd, stdin=read_fp)
    read_fp.close()
    with hadoopy.TypedBytesFile(write_fd=write_fd) as tb_fp:
        for kv in kvs:
            if p.poll() is not None:
                raise IOError('Child process quit while we were sending it data. STDOUT[%s] STDERR[%s]' % p.communicate())
            tb_fp.write(kv)
        tb_fp.flush()
    p.wait()


def readtb(paths, ignore_logs=True, num_procs=10):
    """Read typedbytes sequence files on HDFS (with optional compression).

    By default, ignores files who's names start with an underscore '_' as they
    are log files.  This allows you to cat a directory that may be a variety of
    outputs from hadoop (e.g., _SUCCESS, _logs).  This works on directories and
    files.

    Args:
        paths: HDFS path (str) or paths (iterator)
        ignore_logs: If True, ignore all files who's name starts with an
            underscore.  Defaults to True.
        num_procs: Number of reading procs to open (default 10)

    Returns:
        An iterator of key, value pairs.

    Raises:
        IOError: An error occurred listing the directory (e.g., not available).
    """
    import select
    hstreaming = _find_hstreaming()
    if isinstance(paths, str):
        paths = [paths]
    read_fds = set()
    procs = {}
    tb_fps = {}

    def _open_tb(cur_path):
        cmd = 'hadoop jar %s dumptb %s' % (hstreaming, cur_path)
        read_fd, write_fd = os.pipe()
        write_fp = os.fdopen(write_fd, 'w')
        p = _hadoop_fs_command(cmd, stdout=write_fp)
        write_fp.close()
        read_fds.add(read_fd)
        procs[read_fd] = p
        tb_fps[read_fd] = hadoopy.TypedBytesFile(read_fd=read_fd)

    def _path_gen():
        for root_path in paths:
            try:
                all_paths = ls(root_path)
            except IOError:
                raise IOError("No such file or directory: '%s'" % root_path)
            if ignore_logs:
                # Ignore any files that start with an underscore
                keep_file = lambda x: os.path.basename(x)[0] != '_'
                all_paths = filter(keep_file, all_paths)
            for cur_path in all_paths:
                yield _open_tb(cur_path)

    path_gen = _path_gen()
    for x in range(num_procs):
        try:
            path_gen.next()
        except (AttributeError, StopIteration):
            path_gen = None
    while read_fds:
        cur_fds = select.select(read_fds, [], [])[0]
        for read_fd in cur_fds:
            p = procs[read_fd]
            tp_fp = tb_fps[read_fd]
            try:
                yield tp_fp.next()
            except StopIteration:
                p.wait()
                del procs[read_fd]
                del tb_fps[read_fd]
                read_fds.remove(read_fd)
                try:
                    path_gen.next()
                except (AttributeError, StopIteration):
                    path_gen = None
