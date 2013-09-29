#!/usr/bin/env python2
"""Command to build a DXR instance"""

from argparse import ArgumentParser
import os.path

from dxr.build import build_instance


def main():
    parser = ArgumentParser()
    parser.add_argument('-s', '--srcdir', dest='source_folder', default='build')
    parser.add_argument('-t', '--tmpdir', dest='temp_folder', default='tmp')
    parser.add_argument('-b', '--objdir', dest='object_folder', default='.')
    parser.add_argument('-j', '--jobs', dest='nb_jobs',
                      default='1',
                      help='Number of parallel processes to use, (Default: 1)')
    parser.add_argument('-i', '--incremental',
                      action='store_true',
                      default=False,
                      help='This is an incremental build (the object folder '
                           'and temp folders will not be removed before '
                           'running the build command')
    parser.add_argument('build_command', nargs='+')
    config = parser.parse_args()
    config.ignore_patterns=[]
    config.ignore_paths=[]
    config.build_command = ' '.join(config.build_command)

    config.source_folder = os.path.abspath(config.source_folder)
    config.temp_folder = os.path.abspath(config.temp_folder)
    config.object_folder = os.path.abspath(config.object_folder)
    config.enabled_plugins = ['clang']
    config.log_folder = os.path.join(config.temp_folder, "logs")

    build_instance(config)

if __name__ == '__main__':
    main()
